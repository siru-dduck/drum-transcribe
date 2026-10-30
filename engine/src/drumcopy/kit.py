"""From model classes to kit pieces: crash vs ride, high/mid/floor toms, stem/mix ensemble,
cross-sticks, ghost notes and open hi-hats.

Thresholds were measured on the MDB Drums subclass labels (docs/phase3-improvements.md).
A mark is written by default only if at least 3 of 4 written marks were right and it
does not break repeats; open hi-hats fail the second test and are opt-in.
"""
from __future__ import annotations

import numpy as np

from .engines import pick_peaks
from .instruments import CLASS_DEFAULT

# Columns of the ADTOF activations: kick, snare, toms, hi-hat, cymbals.
# Measured on MDB Drums: kick/snare/hi-hat are best on the separated stem; toms and
# cymbals improve when stem and full-mix activations are averaged (toms .503 -> .585).
# Averaging the hi-hat too recovers quiet ballad off-beats (video reference .752 -> .783)
# but costs MDB score F1 (.847 -> .843) and repeats, so it was rejected.
AVERAGED_COLUMNS = [2, 4]


def combine(stem_activations, mix_activations):
    activations = stem_activations.copy()
    activations[:, AVERAGED_COLUMNS] = (stem_activations[:, AVERAGED_COLUMNS] + mix_activations[:, AVERAGED_COLUMNS]) / 2
    return activations


def detect(stem_activations, mix_activations, thresholds=None):
    kwargs = {"thresholds": thresholds} if thresholds else {}
    return pick_peaks(combine(stem_activations, mix_activations), **kwargs)


GHOST_DB = -10.0         # snare this much quieter than the song's on-beat snares: ghost
GHOST_PATTERN_DB = -6.0  # ... or this much, where the snares at that place in the bar are ghosts (precision .79 on MDB)
OPEN_HIHAT_CYMBAL = 0.10  # cymbal activation on a hi-hat hit (precision ~.78: off by default)
OPEN_HIHAT_CONTRAST = 0.04


def drop_cymbal_retriggers(events, beats, below=0.5):
    """Inside a running cymbal stream, a weak hit on an off sixteenth is the cymbal ringing,
    not a stroke (video reference: cymbals .905 -> .928; MDB unchanged)."""
    from .rhythm import beat_position

    beats = np.asarray(beats)
    cymbals = np.array([e["time"] for e in events if e["instrument"] in ("CR", "RD")])
    kept = []
    for e in events:
        if e["instrument"] in ("CR", "RD") and e.get("confidence", 1.0) < below:
            position = beat_position(beats, e["time"])
            index = int(np.clip(np.floor(position + 1 / 8), 0, len(beats) - 2))
            fraction = (position - index) % 1
            if min(abs(fraction - 0.25), abs(fraction - 0.75)) < 0.08:
                period = beats[index + 1] - beats[index]
                neighbours = np.sum((np.abs(cymbals - e["time"]) > 0) & (np.abs(cymbals - e["time"]) < 0.75 * period))
                if neighbours >= 2:
                    continue
        kept.append(e)
    return kept


def assign_instruments(events, drums_wav=None, stem_activations=None, open_hihat=False):
    events = [dict(e, instrument=CLASS_DEFAULT[e["class"]]) for e in events]
    _split_cymbals(events)
    if drums_wav is not None:
        _split_toms(events, drums_wav)
    if open_hihat and stem_activations is not None:
        mark_open_hihats(events, stem_activations)
    return events


def _load_mono(drums_wav):
    import soundfile as sf

    audio, sr = sf.read(str(drums_wav), always_2d=True)
    return audio.mean(axis=1), sr


def mark_ghosts(events, drums_wav, grid, threshold_db=GHOST_DB, margin_db=GHOST_PATTERN_DB):
    """Ghost notes: snares clearly quieter than the backbeat snares of the same song.

    Loudness is the 30 ms RMS after the onset on the drum stem, relative to the median
    snare on the beat (fallback: all snares). A snare is a ghost below threshold_db, or
    below margin_db when the snares at the same place in the bar are ghosts on the whole:
    a groove's ghost notes are then marked consistently instead of flipping at the threshold.
    Returns the number of ghost notes.
    """
    snares = [e for e in events if e["instrument"] == "SD"]
    if len(snares) < 8:
        return 0
    mono, sr = _load_mono(drums_wav)
    width = int(0.03 * sr)
    level = np.array([10 * np.log10(np.mean(mono[int(e["time"] * sr):int(e["time"] * sr) + width] ** 2) + 1e-12)
                      for e in snares])
    position = np.interp([e["time"] for e in snares], grid.beats, np.arange(len(grid.beats)))
    beat = np.floor(position + 1 / 24)
    on_beat = np.abs(position - beat) < 0.06
    level -= np.median(level[on_beat]) if on_beat.sum() >= 4 else np.median(level)
    # Place in the bar: beat of the bar and position inside the beat (twelfths).
    place = [(grid.beat_in_bar(int(b)), int(round((p - b) * 12)))
             for b, p in zip(beat, position)]
    groups = {key: [v for k, v in zip(place, level) if k == key] for key in set(place)}
    ghostly = {key for key, values in groups.items() if len(values) >= 4 and np.median(values) < threshold_db + 2}
    count = 0
    for e, value, key in zip(snares, level, place):
        e["level_db"] = round(float(value), 1)
        if value < threshold_db or (value < margin_db and key in ghostly):
            e["mark"] = "ghost"
            count += 1
    return count


CROSS_STICK_PEAK = 0.12    # snare + tom activation: the detector splits a cross-stick between the two
CROSS_STICK_REPEATS = 3    # a song uses cross-sticks only if they recur at one place in the bar
CROSS_STICK_CLICK = 0.05   # stick on the rim: 2-8 kHz share above 300 Hz (MDB side sticks: 94% above, congas .01)
TIMEKEEPING_BARS = 4       # stretch over which hi-hat detections are judged together


def _strike_features(mono, high, sr, t):
    """Sound of one stroke on the drum stem: level and low share (full band), and above
    300 Hz the share of the woody 300-2000 Hz band and the 30-100 ms decay."""
    start, head, end = int(t * sr), int(0.03 * sr), int(t * sr) + int(0.1 * sr)
    if end > len(mono):
        return None
    energy = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)
    window = np.hanning(2048)
    freqs = np.fft.rfftfreq(2048, 1 / sr)
    full = np.abs(np.fft.rfft(mono[start:start + 2048] * window)) ** 2
    upper = np.abs(np.fft.rfft(high[start:start + 2048] * window)) ** 2
    return {"level": energy(mono[start:start + head]),
            "low": full[freqs < 300].sum() / (full.sum() + 1e-12),
            "mid": upper[(freqs >= 300) & (freqs < 2000)].sum() / (upper[freqs >= 300].sum() + 1e-12),
            "decay": energy(high[start + head:end]) - energy(high[start:start + head])}


def _timbre(mono, sr, t):
    """At the attack (steepest rise within 30 ms of t), the shares of the sound above 300 Hz
    in the woody (300 Hz-2 kHz), click (2-8 kHz) and metallic (8 kHz and up) bands, and the
    30-100 ms decay. Sharing out only what is above 300 Hz keeps a kick underneath from
    hiding the stroke on top of it."""
    start = int((t - 0.03) * sr)
    if start < 0 or start + int(0.2 * sr) > len(mono):
        return None
    rise = np.convolve(np.abs(np.diff(mono[start:start + int(0.06 * sr)])), np.ones(32), "same")
    onset = start + int(np.argmax(rise))
    spectrum = np.abs(np.fft.rfft(mono[onset:onset + 1024] * np.hanning(1024), n=2048)) ** 2
    freqs = np.fft.rfftfreq(2048, 1 / sr)
    upper = spectrum[freqs >= 300].sum() + 1e-12
    share = lambda lo, hi: float(spectrum[(freqs >= lo) & (freqs < hi)].sum() / upper)
    energy = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)
    head = int(0.03 * sr)
    return {"wood": share(300, 2000), "click": share(2000, 8000), "air": share(8000, sr),
            "decay": energy(mono[onset + head:onset + int(0.1 * sr)]) - energy(mono[onset:onset + head])}


def mark_cross_sticks(events, stem_activations, drums_wav, grid, fps=100, wireless=False):
    """Cross-sticks (side stick): the stick laid across the rim gives a short, woody click
    with almost nothing below 300 Hz, where a snare stroke has its body (MDB side-stick
    hits: low-band share .02 against .77 for snares, 30-100 ms decay -13 dB against -5 dB).

    The detector has no class for it. It reports a snare, splits the click between snare
    and toms so that neither passes its threshold, or - when cross-sticks keep time - hears
    them as a hi-hat. Two searches:
      - Peaks of snare + tom activation. One is a cross-stick when it has the stick's click
        (2-8 kHz; a conga, struck by hand, has none) and either its spectrum is a side
        stick's on its own (low share < .2, woody band > .8 above 300 Hz, decay < -10 dB;
        MDB: 24 of 30, 3 wrong in 23 songs), or it was heard as a confident snare but sounds
        unlike the song's own snares: 6-20 dB quieter, low share .4 below theirs, not the
        pure high band of a hi-hat foot chick (video reference "서쪽하늘": all 3). Weaker
        peaks are not taken this way (MDB Gospel: hand claps). These count
        only if they recur at one place in the bar (3 times or more).
      - Hi-hat detections, judged 4 bars at a time (see _timekeeping_cross_sticks). When
        these keep time, the stream of all cross-sticks found is completed (_fill_stream).
      - Only when asked (wireless=True): snare detections and snare + tom peaks whose snare
        wires do not ring, as a pattern (see _wireless_cross_sticks).
    Snare/tom/hi-hat events at a cross-stick become XS; a missed one is added. Returns the
    number of cross-sticks. A cross-stick together with a kick is found only by the second
    search.
    """
    from scipy.signal import butter, find_peaks, sosfilt

    mono, sr = _load_mono(drums_wav)
    stream = _timekeeping_cross_sticks(events, mono, sr, grid)
    activation = stem_activations[:, 1] + stem_activations[:, 2]
    frames, _ = find_peaks(activation, height=CROSS_STICK_PEAK, distance=8)
    high = sosfilt(butter(4, 300, "highpass", fs=sr, output="sos"), mono)
    peaks = []
    for frame in frames:
        features, timbre = _strike_features(mono, high, sr, frame / fps), _timbre(mono, sr, frame / fps)
        if features and timbre:
            window = slice(max(0, frame - 3), frame + 4)
            features.update(time=frame / fps, snare=float(stem_activations[window, 1].max()), click=timbre["click"],
                            evidence=float(min(1.0, activation[window].max())))
            peaks.append(features)
    snares = [p for p in peaks if p["snare"] >= 0.5]
    reference = (np.median([p["low"] for p in snares]), np.median([p["level"] for p in snares])) \
        if len(snares) >= 4 else None

    def is_cross_stick(p):
        if (reference and p["level"] < reference[1] - 20) or p["click"] < CROSS_STICK_CLICK:
            return False  # too faint to write, or no stick
        if p["low"] < 0.2 and p["mid"] > 0.8 and p["decay"] < -10:
            return True
        return bool(reference) and p["snare"] >= 0.5 and p["low"] < min(0.45, reference[0] - 0.4) \
            and p["level"] < reference[1] - 6 and p["decay"] < -8 and p["mid"] >= 0.25

    found = [p for p in peaks if is_cross_stick(p)]
    position = np.interp([p["time"] for p in found], grid.beats, np.arange(len(grid.beats)))
    beat = np.floor(position + 1 / 24)
    places = [(grid.beat_in_bar(int(b)), int(round((x - b) * 12))) for b, x in zip(beat, position)]
    if not places or max(places.count(p) for p in set(places)) < CROSS_STICK_REPEATS:
        found = []
    for p in found:
        near = [e for e in events if e["class"] in ("snare", "toms") and abs(e["time"] - p["time"]) < 0.03]
        for e in near:
            e.update(instrument="XS", **{"class": "snare"})
            e.pop("mark", None)
        if not near:
            events.append({"time": round(p["time"], 4), "class": "snare", "confidence": round(p["evidence"], 3),
                           "instrument": "XS"})
    events.sort(key=lambda e: (e["time"], e["class"]))
    if wireless:
        _wireless_cross_sticks(events, peaks, mono, sr, grid)
    if stream:  # the stream is judged on every cross-stick found, by any search
        _fill_stream(events, [e for e in events if e["instrument"] == "XS"], mono, sr, grid)
    _drop_doubled(events, mono, high, sr, reference)
    return sum(e["instrument"] == "XS" for e in events)


WIRELESS = -14.0       # 3-8 kHz left 40-120 ms after the attack (dB): MDB side sticks 89% below, snares 2.5%
WIRELESS_LOOSE = -10.0  # inside a wireless pattern; a hi-hat on top leaves a little high band
WIRELESS_SHARE = 0.6    # share of the strokes at one place, within PATTERN_BARS, that must be wireless
PATTERN_BARS = 4
WIRED_SONG = 0.25       # share of the song's snare detections that must ring (> -8 dB) for the contrast to count


def _wire_sustain(band, sr, t):
    """How much of the 3-8 kHz band is left 40-120 ms after the attack (dB). Snare wires keep
    it ringing (MDB snares median -3.8 dB); a cross-stick does not touch the wires (MDB side
    sticks -18.9 dB, "서쪽하늘" -15.1)."""
    start = int((t - 0.02) * sr)
    if start < 0 or start + int(0.2 * sr) > len(band):
        return None
    envelope = np.convolve(np.abs(band[start:start + int(0.06 * sr)]), np.ones(64) / 64, "same")
    peak = start + int(np.argmax(envelope))
    energy = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)
    return energy(band[peak + int(0.04 * sr):peak + int(0.12 * sr)]) - energy(band[peak:peak + int(0.02 * sr)])


def _wireless_cross_sticks(events, peaks, mono, sr, grid):
    """Cross-sticks heard as snares, or split between snare and toms, whose recording has
    the snare's body below 300 Hz (Joel Raney "Love is Born" from bar 60: low share .88,
    like its snares) but not the ringing of the snare wires. A stroke is wireless below
    -14 dB of wire sustain, with the stick's click and no cymbal ring. Judged as a pattern:
    at one place in the bar, among the strokes within 4 bars, 60% or more must be wireless
    (a single dry snare stays a snare: 2.5% of MDB snares are below -14 dB); a wireless
    stroke may also open or close a pattern, and inside a pattern a stroke below -10 dB
    also counts. Only in a recording where the snare wires are heard (25% of its snare
    detections ring above -8 dB). Strokes on a kick are not judged: the beater's click
    also dies at once (Love is Born: kicks on 1 and 3 read as cross-sticks).

    Off by default, an option for songs known to have cross-stick sections: jazz ghost
    notes and hi-hat chicks also leave the wires silent and repeat in patterns (on MDB it
    wrote 228 cross-sticks at precision .11), and the quiet cross-sticks of "Love is Born"
    bars 95-96 (10-24 dB under its snares, little woody band) cannot be told from them by
    sound. Rules that tried (woody band, level floor) failed the gate's sensitivity check.
    Returns the number."""
    from scipy.signal import butter, sosfilt

    band = sosfilt(butter(4, [3000, 8000], "bandpass", fs=sr, output="sos"), mono)
    kicks = np.array([e["time"] for e in events if e["class"] == "kick"] or [-1.0])
    candidates = [{"time": e["time"], "event": e} for e in events if e["instrument"] == "SD"]
    for p in peaks:
        if not any(abs(c["time"] - p["time"]) < 0.03 for c in candidates):
            candidates.append({"time": p["time"], "event": None, "evidence": p["evidence"]})
    # Under a kick the beater's click fills the band and dies as fast as a stick's: no reading.
    candidates = [c for c in candidates if np.min(np.abs(kicks - c["time"])) >= 0.03]
    for c in candidates:
        timbre = _timbre(mono, sr, c["time"]) or {"click": 0.0, "air": 1.0}
        c.update(sustain=_wire_sustain(band, sr, c["time"]), click=timbre["click"], air=timbre["air"])
    candidates = [c for c in candidates if c["sustain"] is not None]
    rung = [c["sustain"] for c in candidates if c["event"] is not None]
    if len(rung) < 8 or np.mean(np.array(rung) > -8) < WIRED_SONG:
        return 0  # the snare wires are not heard in this recording: no contrast to judge by
    lines = [b for b in grid.bar_lines() if b < len(grid.beats) - 1]
    for c in candidates:
        position = float(np.interp(c["time"], grid.beats, np.arange(len(grid.beats))))
        beat = int(np.floor(position + 1 / 24))
        c["bar"] = max([i for i, b in enumerate(lines) if b <= beat] or [0])
        c["place"] = (beat - lines[c["bar"]], int(round((position - beat) * 12)) % 12)
    stick = lambda c: c["click"] >= CROSS_STICK_CLICK and c["air"] < 0.3  # the stick's click, no cymbal ring
    wireless = lambda c: c["sustain"] < WIRELESS and stick(c)

    def pattern(c, before, after):
        group = [d for d in candidates if d["place"] == c["place"] and -before <= d["bar"] - c["bar"] <= after]
        return len(group) >= 3 and np.mean([wireless(d) for d in group]) >= WIRELESS_SHARE

    sticks = []
    for c in candidates:
        if c["sustain"] >= WIRELESS_LOOSE or not stick(c):
            continue
        # A wireless stroke may open or close a pattern (the bars on one side are another
        # section); a stroke that only nearly qualifies must sit inside one.
        windows = [(PATTERN_BARS, PATTERN_BARS)] + ([(0, PATTERN_BARS), (PATTERN_BARS, 0)] if wireless(c) else [])
        if any(pattern(c, before, after) for before, after in windows):
            sticks.append(c)
    for c in sticks:
        near = [e for e in events if e["class"] in ("snare", "toms") and abs(e["time"] - c["time"]) < 0.03]
        for e in near:
            e.update(instrument="XS", **{"class": "snare"})
            e.pop("mark", None)
        if not near:
            events.append({"time": round(c["time"], 4), "class": "snare", "confidence": round(c["evidence"], 3),
                           "instrument": "XS"})
    events.sort(key=lambda e: (e["time"], e["class"]))
    return len(sticks)


def _drop_doubled(events, mono, high, sr, reference):
    """A cross-stick is played on the snare drum, so a snare stroke never sounds at the same
    moment (MDB: 0 of 38 side sticks have a snare within 30 ms). A snare detection on top of
    a cross-stick is the same stroke heard twice, or another sound (a low conga under the
    stick), and is dropped - unless it is a confident snare with the snare's body, which
    then wins over the cross-stick."""
    sticks = [e for e in events if e["instrument"] == "XS"]
    if not sticks:
        return
    times = np.array([e["time"] for e in sticks])
    dropped = set()
    for e in events:
        if e["instrument"] != "SD" or np.min(np.abs(times - e["time"])) >= 0.03:
            continue
        features = _strike_features(mono, high, sr, e["time"])
        body = bool(reference and features and features["low"] >= min(0.45, reference[0] - 0.4))
        if body and e.get("confidence", 0) >= 0.5:
            dropped.update(id(x) for x in sticks if abs(x["time"] - e["time"]) < 0.03)
        else:
            dropped.add(id(e))
    events[:] = [e for e in events if id(e) not in dropped]


def _timekeeping_cross_sticks(events, mono, sr, grid):
    """Cross-sticks keeping time, heard by the detector as a hi-hat: a stretch of 4 bars
    whose hi-hat detections, taken together, have no metallic ring (8 kHz+ share under .15
    and under a quarter of the song's real hi-hat), a woody body (.4) and a short decay
    (-8 dB). Taken together because one hi-hat stroke under a snare also loses its ring;
    against the song's own hi-hat because some recordings have a dark hi-hat throughout.
    At least 8 such strokes in the song (MDB: one stretch of tambourine, slow decay, kept
    out; no other stretch). Returns the hi-hat events turned into XS (empty if none)."""
    hats = [e for e in events if e["instrument"] == "HH"]
    timbre = {id(e): _timbre(mono, sr, e["time"]) for e in hats}
    lines = [grid.beats[b] for b in grid.bar_lines()[::TIMEKEEPING_BARS] if b < len(grid.beats)]
    windows = []
    for a, b in zip(lines, lines[1:] + [float("inf")]):
        inside = [e for e in hats if a <= e["time"] < b and timbre[id(e)]]
        if len(inside) >= 4:
            windows.append((inside, {k: float(np.median([timbre[id(e)][k] for e in inside])) for k in ("air", "wood", "decay")}))
    if not windows:
        return []
    metal = np.percentile([m["air"] for _, m in windows], 80)
    hits = [e for inside, m in windows
            if m["air"] < 0.15 and m["air"] < 0.25 * metal and m["wood"] >= 0.4 and m["decay"] <= -8
            for e in inside if timbre[id(e)]["air"] < 0.3]
    if len(hits) < 8:
        return []
    for e in hits:
        e.update(instrument="XS", **{"class": "snare"})
    return hits


STREAM_SHARE = 0.4   # a place in the bar belongs to the cross-stick stream if it is played in 40% of its bars
STREAM_CLICK = 20.0  # dB rise of the 2-8 kHz band at a missing stroke of the stream


def _fill_stream(events, hits, mono, sr, grid):
    """Cross-sticks keeping time are a steady stream, but the detector hears only some of
    them (Joel Raney "Lift Up Your Eyes": every beat has a 2-8 kHz click of +24 to +45 dB,
    the hi-hat activation is often near 0). Between the first and the last bar with two or
    more cross-sticks, a place of the stream with no cross-stick gets one if the stick's
    click is there (+20 dB) without a cymbal's ring. Returns the number added."""
    from scipy.signal import butter, sosfilt

    lines = [b for b in grid.bar_lines() if b < len(grid.beats) - 1]

    def where(t):
        position = float(np.interp(t, grid.beats, np.arange(len(grid.beats))))
        beat = int(np.floor(position + 1 / 24))
        bar = max([i for i, b in enumerate(lines) if b <= beat] or [0])
        return bar, (beat - lines[bar], int(round((position - beat) * 12)) % 12)

    placed = [where(e["time"]) for e in hits]
    per_bar = {}
    for bar, place in placed:
        per_bar.setdefault(bar, set()).add(place)
    busy = sorted(bar for bar, places in per_bar.items() if len(places) >= 2)
    if not busy:
        return 0
    span = range(busy[0], busy[-1] + 1)
    stream = [place for place in {p for _, p in placed}
              if sum(place in per_bar.get(bar, ()) for bar in span) >= STREAM_SHARE * len(span)]
    band = sosfilt(butter(4, [2000, 8000], "bandpass", fs=sr, output="sos"), mono)
    energy = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)

    def click(t):
        rises = []
        for shift in np.arange(-0.03, 0.031, 0.005):
            s = int((t + shift) * sr)
            if s - int(0.05 * sr) >= 0 and s + int(0.015 * sr) <= len(band):
                rises.append(energy(band[s:s + int(0.015 * sr)]) - energy(band[s - int(0.05 * sr):s - int(0.01 * sr)]))
        return max(rises, default=-99.0)

    added = 0
    for bar in span:
        for beat, twelfth in stream:
            if bar >= len(lines) or beat in (None,) or (beat, twelfth) in per_bar.get(bar, ()):
                continue
            k = lines[bar] + beat
            if k + 1 >= len(grid.beats) or (bar + 1 < len(lines) and k >= lines[bar + 1]):
                continue  # a short bar has no such beat
            t = float(grid.beats[k] + twelfth / 12 * (grid.beats[k + 1] - grid.beats[k]))
            timbre = _timbre(mono, sr, t)
            if timbre and timbre["air"] < 0.3 and click(t) >= STREAM_CLICK:
                events.append({"time": round(t, 4), "class": "snare", "confidence": 0.3, "instrument": "XS"})
                added += 1
    events.sort(key=lambda e: (e["time"], e["class"]))
    return added


UNCONFIRMED_KICK = 0.3      # kick confidence on the drum stem below which the full mix must confirm it
KICK_IN_MIX = 0.1           # kick activation on the full mix that confirms a weak stem kick


def drop_unconfirmed_kicks(events, mix_activations, fps=100):
    """A weak kick on the drum stem that the same model does not hear at all on the full mix
    is a leak into the stem (a hi-hat, a bass note), not a kick. MDB: of 6 such kicks
    (stem < .3, mix < .1), 5 were false; the looser .35 / .4 took 4 / 13 real (soft jazz)
    kicks and were not used. Returns the number removed."""
    drop = set()
    for e in events:
        if e["class"] == "kick" and e.get("confidence", 1.0) < UNCONFIRMED_KICK:
            frame = int(round(e["time"] * fps))
            if mix_activations[max(0, frame - 3):frame + 4, 0].max() < KICK_IN_MIX:
                drop.add(id(e))
    events[:] = [e for e in events if id(e) not in drop]
    return len(drop)


PITCHED = 0.6  # share of the sound (300 Hz-6 kHz) within 3% of its strongest frequency


def _tonal_share(mono, sr, t):
    """How much of the attack's sound (300 Hz-6 kHz) sits within 3% of its strongest frequency."""
    start = int((t - 0.02) * sr)
    if start < 0 or start + 4096 > len(mono):
        return 0.0
    rise = np.convolve(np.abs(np.diff(mono[start:start + int(0.05 * sr)])), np.ones(32), "same")
    onset = start + int(np.argmax(rise))
    freqs = np.fft.rfftfreq(4096, 1 / sr)
    spectrum = np.abs(np.fft.rfft(mono[onset:onset + 2048] * np.hanning(2048), n=4096)) ** 2
    band = (freqs >= 300) & (freqs < 6000)
    peak = freqs[np.argmax(spectrum * band)]
    return float(spectrum[np.abs(freqs - peak) <= peak * 0.03].sum() / (spectrum[band].sum() + 1e-12))


def drop_pitched_percussion(events, drums_wav):
    """Snare or cross-stick detections that are a pitched stick percussion (claves, woodblock):
    most of the sound at one frequency. 60% or more within 3% of the peak; no MDB side stick
    (max .44), snare (max .52) or tom (max .40) gets there, the claves of Joel Raney "Love
    is Born" do (.80-.94, near 2.3 kHz). They are removed. Returns the number removed."""
    strokes = [e for e in events if e["instrument"] in ("SD", "XS")]
    if not strokes:
        return 0
    mono, sr = _load_mono(drums_wav)
    drop = {id(e) for e in strokes if _tonal_share(mono, sr, e["time"]) >= PITCHED}
    events[:] = [e for e in events if id(e) not in drop]
    return len(drop)


HAND_DRUM_WOOD = 0.8  # a hand drum (conga) is all woody band above 300 Hz, with no stick click


def drop_hand_drums(events, drums_wav):
    """Snare detections that are a hand drum: no snare body (low share .4 under the song's
    snares, 6 dB quieter), almost all of the sound above 300 Hz in the woody band and no
    stick click (Joel Raney: congas wood .95-.99, click .01-.05; MDB side sticks click
    .10, snares have the body). They are removed. Returns the number removed."""
    from scipy.signal import butter, sosfilt

    snares = [e for e in events if e["instrument"] == "SD"]
    if len(snares) < 8:
        return 0
    mono, sr = _load_mono(drums_wav)
    high = sosfilt(butter(4, 300, "highpass", fs=sr, output="sos"), mono)
    features = [(_strike_features(mono, high, sr, e["time"]), _timbre(mono, sr, e["time"])) for e in snares]
    sure = [f for (f, t), e in zip(features, snares) if f and e.get("confidence", 0) >= 0.5]
    if len(sure) < 4:
        return 0
    low, level = np.median([f["low"] for f in sure]), np.median([f["level"] for f in sure])
    drop = {id(e) for (f, t), e in zip(features, snares)
            if f and t and f["low"] < min(0.45, low - 0.4) and f["level"] < level - 6
            and t["wood"] >= HAND_DRUM_WOOD and t["click"] < CROSS_STICK_CLICK}
    events[:] = [e for e in events if id(e) not in drop]
    return len(drop)


def mark_open_hihats(events, stem_activations, fps=100):
    """Open hi-hat: the detector also hears a cymbal on a hi-hat hit (the open hat's wash),
    clearly more than on the neighbouring hi-hat hits (a ringing ride or crash raises all of them)."""
    hats = [e for e in events if e["class"] == "hi-hat"]
    if not hats:
        return 0
    times = np.array([e["time"] for e in hats])
    frames = np.rint(times * fps).astype(int)
    cymbal = np.array([stem_activations[max(0, f - 2):f + 3, 4].max() for f in frames])
    count = 0
    for i, e in enumerate(hats):
        nearby = np.abs(times - times[i]) < 2.0
        if cymbal[i] >= OPEN_HIHAT_CYMBAL and cymbal[i] - np.median(cymbal[nearby]) >= OPEN_HIHAT_CONTRAST:
            e["instrument"] = "HO"
            count += 1
    return count


def _split_cymbals(events):
    """A cymbal played as a steady time-keeping stream is a ride; isolated hits are crashes."""
    cymbals = [e for e in events if e["class"] == "cymbals"]
    times = np.array([e["time"] for e in cymbals])
    for i, e in enumerate(cymbals):
        window = times[(times > e["time"] - 1.2) & (times < e["time"] + 1.2)]
        if len(window) >= 4:
            gaps = np.diff(window)
            if np.median(gaps) < 0.6 and np.std(gaps) < 0.6 * np.median(gaps) + 0.05:
                e["instrument"] = "RD"


def _split_toms(events, drums_wav):
    toms = [e for e in events if e["class"] == "toms"]
    if len(toms) < 2:
        return
    mono, sr = _load_mono(drums_wav)
    pitches = []
    for e in toms:
        start = int(e["time"] * sr)
        frame = mono[start:start + int(0.08 * sr)]
        if len(frame) < 256:
            pitches.append(np.nan)
            continue
        spectrum = np.abs(np.fft.rfft(frame * np.hanning(len(frame)), n=8192))
        freqs = np.fft.rfftfreq(8192, 1 / sr)
        band = (freqs > 60) & (freqs < 400)   # tom fundamentals
        pitches.append(freqs[band][np.argmax(spectrum[band])])
    pitches = np.array(pitches)
    valid = pitches[~np.isnan(pitches)]
    if len(valid) < 2 or valid.max() / valid.min() < 1.25:
        return  # one tom, or no clear pitch spread: keep the default mid tom
    # Split points from the largest gaps in log pitch, up to three toms.
    order = np.sort(np.log2(valid))
    gaps = np.diff(order)
    cuts = sorted(order[np.argsort(gaps)[-2:]][::-1] if len(order) > 2 else order[:1])
    cuts = [c for c, g in zip(order[:-1], gaps) if g >= 0.25 and c in cuts]
    names = {0: ["T2"], 1: ["FT", "T1"], 2: ["FT", "T2", "T1"]}[len(cuts)]
    for e, pitch in zip(toms, pitches):
        if np.isnan(pitch):
            continue
        group = sum(np.log2(pitch) > c for c in cuts)
        e["instrument"] = names[group]

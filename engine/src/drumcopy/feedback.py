"""Song-adaptive corrections: what the user heard, kept with the song and applied every time.

One transcription is a draft; the user listens and says what is wrong ("bars 60-74 beats 2
and 4 are cross-sticks", "bar 53 has one kick on beat 1"). The agent writes that into
<out>/feedback.json; every later notate/renotate applies it last, so a fixed bar stays
fixed. Entries are keyed by recording time (bar lines move when the beat grid changes);
the bar and beat the user named are kept for reference.

    {"time": 143.93, "instrument": "XS", "action": "present" | "absent",
     "bar": 60, "beat": "2", "note": "...", "source": "user", "added": "..."}

The song's structure, where the beat tracker miscounted (rubato, long legato notes) or
there is no score to check against. The user gives it by tapping or picking in `drumcopy
tune` (or the agent from a published score); bar numbers follow (bar 1 = start of music):

    {"kind": "span", "time": 0.5, "end": 21.5, "bars": 4, "beats": 6, "signature": "6/4"}
        this stretch is 4 bars of 6/4: its beats are re-counted (spread along the tracked
        beats' own tempo curve), a bar line at both ends; "bars": null keeps the beats and
        only groups them (a "12/8" signature: dotted beats, eighth triplets)
    {"kind": "meter", "time": 0.56, "bars": 4, "beats": 6}    the same, from a time on
    {"kind": "beats", "time": 3.1, "end": 20.9, "times": [...], "downbeats": [...]}
        tapped beats replace the tracked ones there; downbeats are the bars' first beats
        ("downbeats": null: the same beats moved by some milliseconds, bar lines kept)
    {"kind": "downbeat", "time": 47.2, "from": 46.6}   a bar starts on this beat (its bar
        line moved here from "from", if given)
    {"kind": "move", "time": 47.2, "to": 47.23}        this beat sits at "to" (bar lines kept)
    {"kind": "shift", "time": 40.0, "end": 52.0, "ms": -20}   the beats there, 20 ms earlier
    {"kind": "tempo", "time": 18.4, "mark": "rit." | "accel." | "a tempo" | 96 | "-"}
        the tempo mark of the bar starting there ("-": none), instead of the measured one

After a bar line the user gave, bars go on at the bar length until a tracked bar line
falls in step (or the next thing the user decided).

`suggest` (song adaptation) learns this song's sounds from the confirmed entries and lists
the strokes elsewhere in the song that sound like them, for the user to confirm.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

from .instruments import INSTRUMENTS

FILE = "feedback.json"
SUBDIVISIONS = {"": 0.0, "e": 0.25, "&": 0.5, "+": 0.5, "a": 0.75}


def load(out_dir):
    path = Path(out_dir) / FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def save(out_dir, entries):
    path = Path(out_dir) / FILE
    path.write_text(json.dumps(sorted(entries, key=lambda e: (e["time"], e.get("kind", ""), e.get("instrument", ""))),
                               indent=1, ensure_ascii=False), encoding="utf-8")


def position_time(score, bar, beat):
    """Recording time of bar (1-based, as printed) and beat ("2", "1&", "3e", "4a", "2.5")."""
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?([e&+a]?)", str(beat).strip())
    if not match:
        raise ValueError(f"beat {beat!r}: use 2, 1&, 3e, 4a or 2.5")
    first = 0 if score.measures and score.measures[0].pickup else 1
    measure = score.measures[bar - first]
    whole = int(match.group(1))
    fraction = float("0." + match.group(2)) if match.group(2) else SUBDIVISIONS[match.group(3)]
    if not 1 <= whole <= len(measure.beats):
        raise ValueError(f"bar {bar} has {len(measure.beats)} beats")
    k = measure.start_beat + whole - 1
    times = score.beat_times
    return float(times[k] + fraction * (times[k + 1] - times[k]))


def expand(score, bars, beats):
    """Positions for a bar range "60-74" or "95,96" and beats "2,4" or "all"."""
    numbers = []
    for part in str(bars).split(","):
        low, _, high = part.strip().partition("-")
        numbers += list(range(int(low), int(high or low) + 1))
    first = 0 if score.measures and score.measures[0].pickup else 1
    out = []
    for bar in numbers:
        count = len(score.measures[bar - first].beats)
        for beat in ([str(b) for b in range(1, count + 1)] if str(beats) == "all" else str(beats).split(",")):
            out.append((bar, beat.strip()))
    return out


def entries_for(score, positions, instrument, action, note=""):
    if instrument not in INSTRUMENTS:
        raise ValueError(f"unknown instrument {instrument!r}")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    for bar, beat in positions:
        when = round(position_time(score, bar, beat), 3)
        out.append({"time": when, "instrument": instrument, "action": action, "bar": bar, "beat": beat,
                    "note": note, "source": "user", "added": stamp})
        if action == "present" and instrument in ("XS", "SD"):
            # One drum: a cross-stick there is not also a snare stroke, and the other way round.
            other = "SD" if instrument == "XS" else "XS"
            out.append({"time": when, "instrument": other, "action": "absent", "bar": bar, "beat": beat,
                        "note": f"replaced by {instrument}" + (f": {note}" if note else ""), "source": "user", "added": stamp})
    return out


def meter_entry(score, bars, beats, note=""):
    """Bars a-b (as printed) have this many beats each, e.g. the first 4 bars are 6/4."""
    low, _, high = str(bars).partition("-")
    first_bar, last_bar = int(low), int(high or low)
    return {"kind": "meter", "time": round(position_time(score, first_bar, "1"), 3), "bars": last_bar - first_bar + 1,
            "beats": int(beats), "bar": first_bar, "note": note, "source": "user",
            "added": time.strftime("%Y-%m-%dT%H:%M:%S")}


def parse_signature(text):
    """"6/4" -> (6, False); "12/8" -> (4, True): beats per bar and dotted (compound) beats."""
    numerator, _, denominator = str(text).strip().partition("/")
    numerator, denominator = int(numerator), int(denominator or 4)
    if denominator == 8 and numerator % 3 == 0 and numerator >= 6:
        return numerator // 3, True
    if denominator == 4 and 1 <= numerator <= 7:
        return numerator, False
    raise ValueError(f"signature {text!r}: use 2/4 ... 7/4, 6/8, 9/8 or 12/8")


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def bar_time(score, bar, end=False):
    """Recording time of the first beat of a printed bar (end=True: of the bar after it)."""
    first = 0 if score.measures and score.measures[0].pickup else 1
    measure = score.measures[bar - first]
    k = measure.start_beat + (len(measure.beats) if end else 0)
    return float(score.beat_times[min(k, len(score.beat_times) - 1)])


def span_entry(start, end, bars, signature, note="", bar=None):
    """start-end is `bars` bars of `signature` (beats re-counted); bars None: the beats there are
    only grouped; end None: `bars` bars of the tracked beats from start."""
    beats, _ = parse_signature(signature)
    if end is None and not bars:
        raise ValueError("a span needs an end or a number of bars")
    if end is not None and not end > start:
        raise ValueError("a span ends after it starts")
    return {"kind": "span", "time": round(float(start), 3), "end": None if end is None else round(float(end), 3),
            "bars": int(bars) if bars else None, "beats": beats, "signature": str(signature), "bar": bar,
            "note": note, "source": "user", "added": _stamp()}


def downbeat_entry(when, note="", moved_from=None):
    entry = {"kind": "downbeat", "time": round(float(when), 3), "note": note, "source": "user", "added": _stamp()}
    if moved_from is not None:
        entry["from"] = round(float(moved_from), 3)
    return entry


def move_entry(when, to, note=""):
    return {"kind": "move", "time": round(float(when), 3), "to": round(float(to), 3), "note": note, "source": "user",
            "added": _stamp()}


def shift_entry(start, end, ms, note=""):
    if not end > start:
        raise ValueError("a shift ends after it starts")
    return {"kind": "shift", "time": round(float(start), 3), "end": round(float(end), 3), "ms": round(float(ms), 1),
            "note": note, "source": "user", "added": _stamp()}


def tempo_entry(when, mark, note=""):
    mark = str(mark).strip()
    if mark.lstrip("♩=").isdigit():
        mark = int(mark.lstrip("♩="))
    elif mark not in TEMPO_WORDS:
        raise ValueError(f"tempo mark {mark!r}: a number or one of {', '.join(TEMPO_WORDS)}")
    return {"kind": "tempo", "time": round(float(when), 3), "mark": mark, "note": note, "source": "user",
            "added": _stamp()}


TEMPO_WORDS = ("rit.", "accel.", "a tempo", "poco rit.", "poco accel.", "poco a poco accel.", "rall.", "rubato", "-")


def beats_entry(times, downbeats=(), note=""):
    times = sorted(round(float(t), 3) for t in times)
    if len(times) < 2:
        raise ValueError("tapped beats: at least two")
    return {"kind": "beats", "time": times[0], "end": times[-1], "times": times,
            "downbeats": None if downbeats is None else sorted(round(float(t), 3) for t in downbeats),
            "note": note, "source": "user", "added": _stamp()}


def _key(e):
    """Same time and kind (or instrument): the newer entry replaces the older one. Stretches
    (beats, span) are told apart by their end too: two stretches from one beat are two edits."""
    key = (round(e["time"], 2), e.get("kind") or e["instrument"])
    if e.get("kind") in ("beats", "span"):
        key += (round(e.get("end") or 0, 2),)
    return key


def merge(existing, new):
    """Newer entries win at the same time and instrument (or kind)."""
    keep = {_key(e): e for e in existing}
    for e in new:
        keep[_key(e)] = e
    return list(keep.values())


def drop(entries, when, kind=None):
    """Entries without the ones at this time (of this kind or instrument, if given)."""
    return [e for e in entries if not (abs(e["time"] - float(when)) < 0.0105
                                       and kind in (None, e.get("kind"), e.get("instrument")))]


def notes(entries):
    return [e for e in entries if e.get("kind", "note") == "note"]


STRUCTURE = ("meter", "span", "beats", "downbeat", "move", "shift")
TIMING_ONLY = ("move", "shift")


def structure(entries):
    """The structure entries in the order the user made them: each was made on the grid the
    ones before it had left (a beat dragged twice ends where it was dragged last)."""
    return sorted((e for e in entries if e.get("kind") in STRUCTURE), key=lambda e: (e.get("added") or "", e["time"]))


def apply_structure(grid, entries, events=()):
    """The user's beats, bar lines and meters replace the tracked ones where given; the tracked
    ones go on around them (the drums' own downbeats). Changes grid in place; returns the
    number of entries applied."""
    from .rhythm import STRAIGHT16, TRIPLET, choose_feel

    items = structure(entries)
    if not items:
        return 0
    old = {round(float(t), 4): template for t, template in zip(grid.beats, grid.templates)}
    b = {"t": [float(t) for t in grid.beats], "line": [False] * len(grid.beats), "compound": [None] * len(grid.beats)}
    for k in grid.bar_lines():
        if k < len(b["t"]):
            b["line"][k] = True
    applied, skipped = 0, []
    # Where the bars the user set stop running on: the next entry that sets bar lines itself
    # (a nudge of a few beats by milliseconds does not).
    sets_bars = sorted(e["time"] for e in items
                       if e["kind"] not in TIMING_ONLY and not (e["kind"] == "beats" and e.get("downbeats") is None))
    for e in items:
        stop = next((t for t in sets_bars if t > e["time"] + 1e-6), float("inf"))
        kind = e["kind"]
        if kind in ("span", "meter"):
            beats, compound = parse_signature(e["signature"]) if e.get("signature") else (int(e["beats"]), None)
            k0 = _anchor(b, e["time"])
            if e.get("end") is not None:
                k1 = _anchor(b, e["end"])
            else:  # meter: so many bars of the tracked beats from here
                k1 = min(k0 + int(e["bars"]) * beats, len(b["t"]) - 1)
            if k1 <= k0:
                continue
            if e.get("end") is not None and e.get("bars"):
                count = int(e["bars"]) * beats
                warp = np.interp(k0 + np.arange(count) * (k1 - k0) / count, np.arange(len(b["t"])), b["t"])
                b["t"][k0:k1] = [float(t) for t in warp]
                b["line"][k0:k1] = [False] * count
                b["compound"][k0:k1] = [None] * count
                k1 = k0 + count
            for k in range(k0, k1):
                b["line"][k] = (k - k0) % beats == 0
                b["compound"][k] = compound
            if k1 < len(b["t"]):
                # Ending on a bar line that was there, the bars after it stand (merging two 3/4
                # bars inside a 3/4 passage must not regroup what follows); elsewhere the song's
                # bars go on from the new line.
                ends_on_a_bar = b["line"][k1]
                b["line"][k1] = True
                if not ends_on_a_bar:
                    _rephase(b, k1, grid.beats_per_bar, stop)
        elif kind == "beats" and e.get("downbeats") is None:
            if not _move(b, e["times"]):  # timing only: the bar lines stay where they are
                skipped.append(e)
                continue
        elif kind == "beats":
            k0, k1 = _splice(b, e["times"])
            downbeats = [round(t, 3) for t in e.get("downbeats") or []]
            for k in range(k0, k1):
                b["line"][k] = round(b["t"][k], 3) in downbeats
            if downbeats and e.get("rephase", True):
                last = max(k for k in range(k0, k1) if b["line"][k])
                _rephase(b, last, _bar_length(b, last, grid.beats_per_bar), stop)
            else:
                before = max((k for k in range(k0) if b["line"][k]), default=None)
                if before is not None:
                    _rephase(b, before, _bar_length(b, before, grid.beats_per_bar), stop)
        elif kind == "move":
            k = _nearest(b["t"], e["time"])
            trial = list(b["t"])
            if k is not None:
                trial[k] = float(e["to"])
            if k is None or not np.all(np.diff(trial) > 0):
                skipped.append(e)  # the beat it moved is not there any more (the grid under it changed)
                continue
            b["t"][k] = float(e["to"])
        elif kind == "shift":
            trial = [t + e["ms"] / 1000 if e["time"] - 1e-3 <= t <= e["end"] + 1e-3 else t for t in b["t"]]
            if np.all(np.diff(trial) > 0):
                b["t"][:] = trial
        elif kind == "downbeat":
            if e.get("from") is not None:  # the bar line the user dragged away from here
                left = _nearest(b["t"], e["from"])
                if left is not None and left > 0:
                    b["line"][left] = False
            k = _anchor(b, e["time"])
            before = max((j for j in range(k) if b["line"][j]), default=None)
            length = _bar_length(b, before, grid.beats_per_bar) if before is not None else grid.beats_per_bar
            b["line"][k] = True
            _rephase(b, k, length, stop)
        applied += 1
    grid.beats = np.asarray(b["t"])
    starts = [k for k, line in enumerate(b["line"]) if line]
    grid.bar_starts = starts
    grid.first_downbeat = starts[0] if starts else 0
    grid.bar_compound = {k: b["compound"][k] for k in starts if b["compound"][k] is not None}
    # A beat the user moved or added is quantized on its own fresh template; the others keep theirs.
    fresh = choose_feel(grid.beats, list(events), force=grid.feel)[2] if events else [STRAIGHT16] * len(grid.beats)
    templates = [old.get(round(t, 4), fresh[k]) for k, t in enumerate(b["t"])]
    for k, compound in enumerate(b["compound"]):
        if compound:
            templates[k] = TRIPLET
        elif compound is False and grid.feel == "compound":
            templates[k] = STRAIGHT16
    grid.templates = templates
    grid.evidence["user_structure"] = grid.evidence.get("user_structure", 0) + applied
    grid.evidence["user_structure_skipped"] = grid.evidence.get("user_structure_skipped", []) + \
        [{"time": e["time"], "kind": e["kind"], "added": e.get("added")} for e in skipped]
    return applied


def apply_meter(grid, entries):
    return apply_structure(grid, entries)


def _period(times, k):
    lo, hi = max(0, k - 2), min(len(times) - 1, k + 2)
    return float(np.median(np.diff(times[lo:hi + 1]))) if hi > lo else 0.5


def _nearest(times, when):
    """Index of the beat at `when` (within a third of a beat), else None."""
    k = int(np.argmin(np.abs(np.asarray(times) - when)))
    return k if abs(times[k] - when) <= _period(times, k) / 3 else None


def _anchor(b, when):
    """Index of the beat at `when`: the nearest beat, moved there, or a new beat."""
    times = b["t"]
    k = int(np.argmin(np.abs(np.asarray(times) - when)))
    if abs(times[k] - when) <= 0.35 * _period(times, k):
        times[k] = float(when)
        return k
    k = int(np.searchsorted(times, when))
    b["t"].insert(k, float(when))
    b["line"].insert(k, False)
    b["compound"].insert(k, None)
    return k


def _splice(b, tapped):
    """Tapped beats in place of the tracked beats within half a beat of them: (first, end) index."""
    tapped = sorted(float(t) for t in tapped)
    gap = float(np.median(np.diff(tapped))) / 2
    keep = [k for k, t in enumerate(b["t"]) if not tapped[0] - gap < t < tapped[-1] + gap]
    gone = [(b["t"][k], b["compound"][k]) for k in range(len(b["t"])) if k not in set(keep)]
    # Tapping moves beats, not the kind of meter: each new beat keeps the dotted (12/8) or plain
    # beat of the beat it replaces.
    compound = [min(gone, key=lambda g: abs(g[0] - t))[1] if gone else None for t in tapped]
    k0 = sum(1 for k in keep if b["t"][k] <= tapped[0] - gap)
    for key, fill in (("t", tapped), ("line", [False] * len(tapped)), ("compound", compound)):
        kept = [b[key][k] for k in keep]
        b[key][:] = kept[:k0] + list(fill) + kept[k0:]
    return k0, k0 + len(tapped)


def _move(b, moved):
    """The beats nearest to these times (as many, in order) take these times; their bar-line
    flags stay. Nothing moves if the counts differ or the beats would change order."""
    moved = sorted(float(t) for t in moved)
    gap = float(np.median(np.diff(moved))) / 2
    inside = [k for k, t in enumerate(b["t"]) if moved[0] - gap < t < moved[-1] + gap]
    if len(inside) != len(moved):
        return False
    trial = list(b["t"])
    for k, t in zip(inside, moved):
        trial[k] = t
    if np.all(np.diff(trial) > 0):
        b["t"][:] = trial
        return True
    return False


def _bar_length(b, k, default):
    nxt = next((j for j in range(k + 1, len(b["line"])) if b["line"][j]), None)
    return nxt - k if nxt is not None and 2 <= nxt - k <= 7 else default


def _rephase(b, k, length, stop):
    """Bars of `length` beats from a bar line the user gave at k: tracked bar lines out of step
    go, until a tracked one falls in step or the next decision of the user (time `stop`)."""
    for j in range(k + 1, len(b["t"])):
        if b["t"][j] >= stop - 1e-6:
            return
        if (j - k) % length == 0:
            if b["line"][j]:
                return
            b["line"][j] = True
        else:
            b["line"][j] = False


def apply_tempo(score, entries):
    """The user's tempo marks into the bars starting at their times (Measure.tempo)."""
    times = score.beat_times
    count = 0
    for e in sorted((e for e in entries if e.get("kind") == "tempo"), key=lambda e: e["time"]):
        starts = [times[m.start_beat] if m.start_beat < len(times) else float("inf") for m in score.measures]
        index = int(np.argmin(np.abs(np.asarray(starts) - e["time"]))) if starts else None
        if index is None or abs(starts[index] - e["time"]) > 0.5 * _period(times, score.measures[index].start_beat) \
                * len(score.measures[index].beats):
            continue
        measure = score.measures[index]
        if measure.tempo is None or e["mark"] == "-":
            measure.tempo = []
        if e["mark"] != "-":
            measure.tempo.append(e["mark"])
        count += 1
    return count


def apply(score, entries):
    """Write the corrections into the score (in place). Returns (applied, skipped)."""
    times = np.asarray(score.beat_times)
    applied, skipped = 0, []
    for entry in notes(entries):
        located = _locate(score, times, entry["time"])
        if located is None:
            skipped.append(entry)
            continue
        slot = located
        if entry["action"] == "present":
            slot[entry["instrument"]] = slot.get(entry["instrument"], "")
        else:
            slot.pop(entry["instrument"], None)
        applied += 1
    return applied, skipped


def _locate(score, times, when):
    """The slot nearest to a time; a time just before a beat (rounded) belongs to that beat,
    also across a bar line."""
    if len(times) < 2:
        return None
    from .engrave import beat_span
    k = int(np.searchsorted(times, when + 1e-6)) - 1
    if k < 0:
        return None
    start, length = beat_span(times, k)
    fraction = (when - start) / length
    while fraction >= 1.0 - 1e-9 and k + 1 >= len(times):  # past the last tracked beat: count on with its length
        k += 1
        fraction -= 1.0
    beats = {measure.start_beat + b: beat for measure in score.measures for b, beat in enumerate(measure.beats)}
    if k not in beats:
        return None
    slot = int(round(fraction * beats[k].division))
    if slot < beats[k].division:
        return beats[k].slots[slot]
    return beats[k + 1].slots[0] if k + 1 in beats else None


# ---------------------------------------------------------------- song adaptation

def stroke_features(mono, band, sr, t):
    """The sound of one snare-family stroke, for comparing strokes within one song."""
    from . import kit
    timbre = kit._timbre(mono, sr, t)
    wire = kit._wire_sustain(band, sr, t)
    if timbre is None or wire is None:
        return None
    start = int(t * sr)
    energy = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)
    spectrum = np.abs(np.fft.rfft(mono[start:start + 2048] * np.hanning(2048))) ** 2
    freqs = np.fft.rfftfreq(2048, 1 / sr)
    return {"wire": wire, "tonal": kit._tonal_share(mono, sr, t), "click": timbre["click"], "wood": timbre["wood"],
            "air": timbre["air"], "decay": timbre["decay"],
            "low": float(spectrum[freqs < 300].sum() / (spectrum.sum() + 1e-12)),
            "level": energy(mono[start:start + int(0.03 * sr)])}


FEATURES = ("wire", "tonal", "click", "wood", "air", "decay", "low", "level")
NEAR = 0.06  # seconds: a written note, a detection and a feedback entry for the same stroke


def suggest(out_dir, limit=40):
    """Strokes of this song that sound like the user's confirmed cross-sticks (or snares) but
    are written otherwise. The confirmed entries teach the song's own sounds: each stroke's
    features, z-scored over the song's snare-family strokes, go to the nearer class centroid,
    each feature weighted by how well it separates the labelled strokes of this song.
    The snare class is the user's confirmed snares, or, if there are none, the written snares
    the user has not touched. Returns suggestions (bar, beat, written, suggested, margin 0-1:
    how much nearer the suggested class is), most certain first."""
    from scipy.signal import butter, sosfilt

    from . import kit
    from .score import from_text

    out = Path(out_dir)
    entries = notes(load(out))
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    times = json.loads((out / "beat_times.json").read_text(encoding="utf-8"))
    score = from_text((out / "score.txt").read_text(encoding="utf-8"), times)
    events = json.loads((out / "events.json").read_text(encoding="utf-8"))["events"]
    mono, sr = kit._load_mono(report["drums"])
    band = sosfilt(butter(4, [3000, 8000], "bandpass", fs=sr, output="sos"), mono)
    written = _written(score, times)
    near = lambda pairs, when: next((v for t, v in pairs if abs(t - when) < NEAR), None)
    candidates = sorted({e["time"] for e in events if e["class"] in ("snare", "toms")}
                        | {e["time"] for e in entries if e["action"] == "present" and e["instrument"] in ("XS", "SD")})
    strokes = []
    for when in candidates:
        if strokes and when - strokes[-1][0] < NEAR:
            continue  # one stroke, detected twice
        features = stroke_features(mono, band, sr, when)
        if features:
            strokes.append((when, features))
    confirmed = [(e["time"], e["instrument"]) for e in entries if e["action"] == "present" and e["instrument"] in ("XS", "SD")]
    touched = [(e["time"], True) for e in entries]
    label = {}
    for i, (when, _) in enumerate(strokes):
        label[i] = near(confirmed, when) or (None if near(touched, when) else ("SD?" if near(written, when) == "SD" else None))
    if not any(v == "SD" for v in label.values()):
        label = {i: ("SD" if v == "SD?" else v) for i, v in label.items()}  # no confirmed snare: the written ones
    if not strokes or "XS" not in label.values() or "SD" not in label.values():
        return {"suggestions": [], "note": "needs confirmed cross-sticks in feedback, and snares (confirmed or written)"}
    matrix = np.array([[f[k] for k in FEATURES] for _, f in strokes], dtype=float)
    z = (matrix - matrix.mean(axis=0)) / (matrix.std(axis=0) + 1e-9)
    groups = {n: z[[i for i, v in label.items() if v == n]] for n in ("XS", "SD")}
    centroids = {n: g.mean(axis=0) for n, g in groups.items()}
    # What tells this song's two sounds apart, learned from its labelled strokes (Fisher score):
    # in "Love is Born" the snare wires, not the low band that separates them on MDB.
    spread = groups["XS"].var(axis=0) + groups["SD"].var(axis=0) + 1e-6
    weight = (centroids["XS"] - centroids["SD"]) ** 2 / spread
    weight = weight / weight.sum()
    first = 0 if score.measures and score.measures[0].pickup else 1
    suggestions = []
    for i, (when, features) in enumerate(strokes):
        if near(touched, when):
            continue  # the user already decided
        d_xs, d_sd = (float(np.sqrt(np.sum(weight * (z[i] - centroids[n]) ** 2))) for n in ("XS", "SD"))
        guess, now = ("XS" if d_xs < d_sd else "SD"), near(written, when) or "-"
        if guess != now and not (now == "-" and guess == "SD"):  # snare <-> cross-stick, or a missed cross-stick
            bar, beat = _bar_beat(score, times, when, first)
            suggestions.append({"time": round(when, 3), "bar": bar, "beat": beat, "written": now, "suggested": guess,
                                "margin": round(abs(d_sd - d_xs) / (d_sd + d_xs), 2),
                                "wire": round(features["wire"], 1), "tonal": round(features["tonal"], 2)})
    suggestions.sort(key=lambda s: -s["margin"])
    return {"suggestions": suggestions[:limit], "total": len(suggestions),
            "learned_from": {n: sum(v == n for v in label.values()) for n in ("XS", "SD")},
            "weights": {k: round(float(w), 2) for k, w in zip(FEATURES, weight)}}


def _written(score, times):
    """[(time, "XS" | "SD")] of the score's snare-family hits."""
    from .engrave import _fraction, beat_span
    out = []
    for measure in score.measures:
        for b, beat in enumerate(measure.beats):
            span = beat_span(times, measure.start_beat + b)
            if span is None:
                continue
            for s, slot in enumerate(beat.slots):
                when = span[0] + _fraction(score, beat.division, s, measure) * span[1]
                out.extend((when, key) for key in ("XS", "SD") if key in slot)
    return out


def _bar_beat(score, times, when, first):
    k = int(np.searchsorted(times, when + 1e-6)) - 1
    if 0 <= k < len(times) - 1 and (when - times[k]) / (times[k + 1] - times[k]) > 0.97:
        k += 1  # a time rounded to just before a beat is that beat
    for index, measure in enumerate(score.measures):
        if measure.start_beat <= k < measure.start_beat + len(measure.beats):
            fraction = max(0.0, (when - times[k]) / (times[k + 1] - times[k]))
            sub = min(SUBDIVISIONS, key=lambda s: abs(SUBDIVISIONS[s] - fraction) if s != "+" else 9)
            return index + first, f"{k - measure.start_beat + 1}{sub}"
    return None, None

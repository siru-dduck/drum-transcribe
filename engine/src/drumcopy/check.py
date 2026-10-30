"""Self-check of a finished transcription: bars worth asking the user about, with evidence.

What a careful reviewer does by eye and ear, from the files of the output folder: the drum
strokes the detector found (events.json) against the beat grid the score is written on
(beat_times.json, score.txt). Nothing is changed; each finding is a question for the user,
and what the user confirms goes into feedback.json (or, if it recurs across songs, becomes
a gated rule). Findings, most telling first:

  pulse     the drums keep a slower pulse, 2:3 of the written beat (the tracker followed
            another instrument; written strokes land on dotted positions)
  offbeat   kick and snare sit off the beat bar after bar (beat grid half a beat out)
  unsteady  the beat grid jumps where the drums play (tracker slipped; fills misread)
  shortbar  a 2/4 or 3/4 bar inside a steady groove
  wireless  written snares whose wires do not ring, bar after bar (cross-stick section?)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

TIMEKEEPING = ("kick", "snare", "hi-hat", "cymbals")
WINDOW = 8               # beats judged at once
PULSE_MARGIN = 0.10      # looser than the automatic repair (rhythm.follow_drum_pulse): a question, not a fix
PULSE_FIT = 0.7         # weaker fits were noise on Lift Up Your Eyes and the fixed Christmas Joy (.65-.68)
OFFBEAT_SHARE = 0.7      # share of kick/snare strokes on the "&" for a window to count
UNSTEADY = 0.2           # a beat this much longer or shorter than its neighbours
WIRELESS = -14.0         # see kit.WIRELESS
LIMIT = 8


def run(out_dir, limit=LIMIT):
    from . import kit
    from .rhythm import _grid_fit
    from .score import from_text

    out = Path(out_dir)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    times = np.asarray(json.loads((out / "beat_times.json").read_text(encoding="utf-8")))
    score = from_text((out / "score.txt").read_text(encoding="utf-8"), list(times))
    events = json.loads((out / "events.json").read_text(encoding="utf-8"))["events"]
    if not score.measures:
        return {"issues": [], "note": "empty score: no kick or snare in this recording"}
    first = 0 if score.measures[0].pickup else 1
    starts = np.array([m.start_beat for m in score.measures])

    def bar(k):
        return int(np.searchsorted(starts, k, side="right") - 1) + first

    def bars(k0, k1):
        a, b = bar(k0), bar(max(k0, k1 - 1))
        return f"{a}" if a == b else f"{a}-{b}"

    stroke = np.asarray(sorted(e["time"] for e in events if e["class"] in TIMEKEEPING))
    strong = np.asarray(sorted(e["time"] for e in events if e["class"] in ("kick", "snare")))
    lo, hi = starts[0], min(starts[-1] + len(score.measures[-1].beats), len(times) - 1)
    issues = []

    # pulse and offbeat, window by window
    pulse, offbeat = [], []
    for k in range(lo, hi - WINDOW, WINDOW // 2):
        start, end = times[k], times[k + WINDOW]
        period = float(np.median(np.diff(times[k:k + WINDOW + 1])))
        inside = stroke[(stroke >= start) & (stroke < end)]
        if len(inside) >= WINDOW // 2:
            own, _ = _grid_fit(inside, period, start, end)
            # Only a slower drum pulse: a finer grid also "fits" dense strokes and swung triplets
            # (MDB SpeedMetal and BebopJazz: alarms at 330 bpm against a written 220).
            other, _ = _grid_fit(inside, 1.5 * period, start, end)
            if other >= PULSE_FIT and other > own + PULSE_MARGIN:
                pulse.append((k, 1.5, own, other, period))
        hits = strong[(strong >= start) & (strong < end)]
        if len(hits) >= 6:
            position = np.interp(hits, times, np.arange(len(times)))
            fraction = position - np.floor(position)
            on = np.mean((fraction < 0.12) | (fraction > 0.88))
            off = np.mean(np.abs(fraction - 0.5) < 0.12)
            if off >= OFFBEAT_SHARE and off > on:
                offbeat.append((k, off))
    for run_ in _runs([p[0] for p in pulse], WINDOW // 2):
        rows = [p for p in pulse if run_[0] <= p[0] <= run_[-1]]
        ratio = rows[0][1]
        bpm = 60 / float(np.median([p[4] for p in rows]))
        issues.append({"kind": "pulse", "bars": bars(run_[0], run_[-1] + WINDOW), "weight": 3 + len(rows),
                       "evidence": f"drum strokes fit a beat of {bpm * (1 / ratio):.0f} bpm "
                                   f"(fit {np.median([p[3] for p in rows]):.2f}) better than the written {bpm:.0f} "
                                   f"({np.median([p[2] for p in rows]):.2f})",
                       "question": f"Do the drums here keep about {bpm / ratio:.0f} bpm rather than {bpm:.0f}?"})
    for run_ in _runs([o[0] for o in offbeat], WINDOW // 2):
        if len(run_) < 2:
            continue
        rows = [o for o in offbeat if run_[0] <= o[0] <= run_[-1]]
        issues.append({"kind": "offbeat", "bars": bars(run_[0], run_[-1] + WINDOW), "weight": 2 + len(rows),
                       "evidence": f"{np.median([o[1] for o in rows]):.0%} of kicks and snares on the '&'",
                       "question": "Are kick and snare really off the beat here, or is the beat grid half a beat out?"})

    # unsteady beats where the drums play
    ibi = np.diff(times)
    jumps = []
    for k in range(max(lo, 4), min(hi, len(ibi) - 4)):
        around = np.concatenate([ibi[k - 4:k], ibi[k + 1:k + 5]])
        if abs(ibi[k] / np.median(around) - 1) > UNSTEADY and np.any((strong > times[k] - 0.5) & (strong < times[k + 1] + 0.5)):
            jumps.append(k)
    for run_ in _runs(jumps, 3):
        issues.append({"kind": "unsteady", "bars": bars(run_[0], run_[-1] + 1), "weight": 1.5 + 0.5 * len(run_),
                       "evidence": "beat lengths " + ", ".join(f"{ibi[k]:.2f}" for k in run_[:6]) + " s around "
                                   f"{np.median(ibi[max(lo, run_[0] - 4):run_[-1] + 5]):.2f} s",
                       "question": "Is the rhythm of this passage (often a fill or a tempo change) written right?"})

    # short bars inside a groove
    for i, measure in enumerate(score.measures):
        if measure.pickup or len(measure.beats) == score.beats_per_bar or not 0 < i < len(score.measures) - 1:
            continue
        if not (score.measures[i - 1].is_empty() or score.measures[i + 1].is_empty()):
            issues.append({"kind": "shortbar", "bars": f"{i + first}", "weight": 1.0,
                           "evidence": f"{len(measure.beats)}/{4 if score.feel != 'compound' else 8} bar between "
                                       "bars with drums",
                           "question": "Is this short bar real, or should the bar lines fall elsewhere?"})

    # snares without ringing wires, bar after bar
    written = [(t, i) for t, key, i in _written(score, times) if key == "SD"]
    if len(written) >= 8 and Path(report.get("drums", "")).is_file():
        from scipy.signal import butter, sosfilt
        mono, sr = kit._load_mono(report["drums"])
        band = sosfilt(butter(4, [3000, 8000], "bandpass", fs=sr, output="sos"), mono)
        wire = [(i, kit._wire_sustain(band, sr, t)) for t, i in written]
        wire = [(i, w) for i, w in wire if w is not None]
        if wire and np.mean([w > -8 for _, w in wire]) >= 0.25:  # the snare wires are heard in this recording
            per_bar = {}
            for i, w in wire:
                per_bar.setdefault(i, []).append(w)
            dry = sorted(i for i, ws in per_bar.items() if np.median(ws) < WIRELESS)
            for run_ in _runs(dry, 1):
                if len(run_) >= 3:
                    a, b = run_[0] + first, run_[-1] + first
                    issues.append({"kind": "wireless", "bars": f"{a}-{b}", "weight": 1.5 + 0.2 * len(run_),
                                   "evidence": f"snare wires silent (median {np.median([w for i in run_ for w in per_bar[i]]):.0f} dB)",
                                   "question": "Are these snares cross-sticks? (if so: feedback, or --wireless-cross-sticks)"})
    issues.sort(key=lambda x: -x["weight"])
    return {"issues": issues[:limit], "total": len(issues),
            "note": "questions for the user, not corrections; confirmed answers go into feedback.json"}


def _runs(values, step):
    """Consecutive runs (gaps of at most step) of sorted integers."""
    runs = []
    for v in sorted(values):
        if runs and v - runs[-1][-1] <= step:
            runs[-1].append(v)
        else:
            runs.append([v])
    return runs


def _written(score, times):
    """(time, instrument, measure index) of every written hit."""
    from .engrave import _fraction, beat_span
    out = []
    for index, measure in enumerate(score.measures):
        for b, beat in enumerate(measure.beats):
            span = beat_span(times, measure.start_beat + b)
            if span is None:
                continue
            for s, slot in enumerate(beat.slots):
                when = span[0] + _fraction(score, beat.division, s, measure) * span[1]
                out.extend((when, key, index) for key in slot)
    return out

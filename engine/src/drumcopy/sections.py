"""Rehearsal marks at section boundaries.

A boundary is where the groove changes: the bars after it are unlike the bars before it
(novelty between two 4-bar windows), the time is kept on another cymbal (hi-hat to
ride, the usual verse/chorus change), or a crash on the downbeat follows a fill. Sections
are at least four bars long. Labels stay neutral: A, B, C ..., a section that grooves
like an earlier one gets the same letter (A B A). Labels an agent or a person wrote are kept.
"""
from __future__ import annotations

import numpy as np

WINDOW = 4
MIN_BARS = 4
NOVELTY = 0.5      # 1 - cross-window similarity, relative to the windows' own consistency
CRASH_BONUS = 0.25
TIMEKEEPER_BONUS = 0.3
TIMEKEEPERS = ("HH", "HO", "RD")


def _groove(measure):
    """Hits without crash cymbals and marks: what the hands and feet keep playing."""
    return frozenset((b, s, k) for b, beat in enumerate(measure.beats) for s, slot in enumerate(beat.slots)
                     for k in slot if k != "CR")


def _similarity(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def _mean_similarity(left, right):
    pairs = [_similarity(a, b) for a in left for b in right if a is not b]
    return float(np.mean(pairs)) if pairs else 1.0


def _timekeeper(measures):
    """The cymbal most hits of these bars are played on (None if no cymbal keeps time)."""
    counts = {k: sum(k in slot for m in measures for beat in m.beats for slot in beat.slots) for k in TIMEKEEPERS}
    best = max(counts, key=counts.get)
    return best if counts[best] else None


def _crash_on_one(measure):
    return bool(measure.beats) and "CR" in measure.beats[0].slots[0]


def boundaries(measures):
    grooves = [_groove(m) for m in measures]
    bars = [i for i, m in enumerate(measures) if not m.pickup]
    scores = {}
    for n, i in enumerate(bars):
        before = [grooves[j] for j in bars[max(0, n - WINDOW):n]]
        after = [grooves[j] for j in bars[n:n + WINDOW]]
        if len(before) < 2 or len(after) < 2:
            continue
        within = (_mean_similarity(before, before) + _mean_similarity(after, after)) / 2
        novelty = within - _mean_similarity(before, after)
        left = _timekeeper([measures[j] for j in bars[max(0, n - WINDOW):n]])
        right = _timekeeper([measures[j] for j in bars[n:n + WINDOW]])
        if left and right and left != right:
            novelty += TIMEKEEPER_BONUS
        previous = measures[bars[n - 1]]
        fill = _similarity(grooves[bars[n - 1]], grooves[bars[n - 2]]) < 0.6
        if _crash_on_one(measures[i]) and fill and not _crash_on_one(previous):
            novelty += CRASH_BONUS
        scores[n] = novelty
    chosen = []
    for n in sorted(scores, key=scores.get, reverse=True):
        if scores[n] < NOVELTY:
            break
        if n >= MIN_BARS and len(bars) - n >= MIN_BARS and all(abs(n - c) >= MIN_BARS for c in chosen):
            chosen.append(n)
    return [bars[n] for n in sorted(chosen)], scores


def label(score):
    """Set Measure.section at boundaries; returns [(measure index, label)]."""
    measures = score.measures
    if any(m.section for m in measures):
        return []  # labels from an agent or a person win
    cuts, _ = boundaries(measures)
    if not cuts:
        return []
    first = next(i for i, m in enumerate(measures) if not m.pickup)
    starts = [first] + cuts
    ends = cuts + [len(measures)]
    letters, labels = [], []
    for start, end in zip(starts, ends):
        if not labels and all(m.is_empty() for m in measures[start:end]):
            continue  # bars before the drums come in are not a section of the drum part
        grooves = [_groove(m) for m in measures[start:end]]
        name = None
        for earlier, earlier_grooves in letters:
            if _mean_similarity(grooves, earlier_grooves) >= 0.7 * max(_mean_similarity(grooves, grooves), 1e-9):
                name = earlier
                break
        if name is None:
            name = chr(ord("A") + len({n for n, _ in letters}))
        letters.append((name, grooves))
        if not labels or labels[-1][1] != name:  # A followed by A is one section
            labels.append((start, name))
    if len(labels) < 2:
        return []
    for start, name in labels:
        measures[start].section = name
    return labels

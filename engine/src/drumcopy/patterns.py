"""Evidence-based pattern normalization.

A bar that differs from a frequent bar of the song by one or two hits is a
candidate for normalization. It is rewritten only when the model's own evidence
agrees: the extra hits are low-confidence, and the missing hits have some
activation at their time. Bars that genuinely vary (fills, accents) stay as played.
Marks (ghost notes) do not make a bar different: they come from a loudness threshold
that flips at the margin, so a normalized bar takes the prototype's marks too.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .instruments import INSTRUMENT_CLASS

COLUMN = {"kick": 0, "snare": 1, "toms": 2, "hi-hat": 3, "cymbals": 4}


def _hits(measure):
    return {(b, s, k) for b, beat in enumerate(measure.beats) for s, slot in enumerate(beat.slots) for k in slot}


def _plain_key(measure):
    return _layout(measure), frozenset(_hits(measure))


def _layout(measure):
    return tuple(beat.division for beat in measure.beats)


def normalize(score, grid, placed, activations, fps=100, max_diff=2, drop_below=0.45, restore_above=0.08):
    """Returns a list of changes (for the report); the score is edited in place."""
    confidence = {(h["beat"], h["slot"], h["instrument"]): h.get("confidence", 1.0) for h in placed}
    keys = [_plain_key(m) for m in score.measures]  # marks do not make a different groove
    counts = Counter(keys)
    changes = []
    for index, measure in enumerate(score.measures):
        if measure.pickup or counts[keys[index]] >= 3:
            continue
        mine = _hits(measure)
        best = None
        for key, count in counts.most_common():
            if count < 3 or count <= counts[keys[index]]:
                break
            prototype = score.measures[keys.index(key)]
            if _layout(prototype) != _layout(measure):
                continue
            theirs = _hits(prototype)
            diff = len(mine ^ theirs)
            if 0 < diff <= max_diff and (best is None or diff < best[0]):
                best = (diff, prototype, theirs)
        if best is None:
            continue
        _, prototype, theirs = best
        extra, missing = mine - theirs, theirs - mine
        start = measure.start_beat
        ok = all(confidence.get((start + b, s, k), 1.0) < drop_below for b, s, k in extra)
        for b, s, k in missing:
            time = _slot_time(grid, start + b, s, measure.beats[b].division)
            if time is None or _activation(activations, fps, time, _columns(k)) < restore_above:
                ok = False
        if not ok:
            continue
        for b, s, k in extra:
            measure.beats[b].slots[s].pop(k, None)
        for b, s, k in missing:
            measure.beats[b].slots[s][k] = prototype.beats[b].slots[s][k]
        remarked = 0
        for b, s, k in mine & theirs:
            if measure.beats[b].slots[s][k] != prototype.beats[b].slots[s][k]:
                measure.beats[b].slots[s][k] = prototype.beats[b].slots[s][k]
                remarked += 1
        keys[index] = _plain_key(measure)
        changes.append({"measure": index, "removed": sorted(extra), "restored": sorted(missing), "remarked": remarked})
    return changes


def _slot_time(grid, beat, slot, division):
    if beat + 1 >= len(grid.beats):
        return None
    template = grid.templates[beat]
    fraction = template[slot] if len(template) == division else slot / division
    return grid.beats[beat] + fraction * (grid.beats[beat + 1] - grid.beats[beat])


def _columns(key):
    # The detector splits a cross-stick between snare and toms (see kit.mark_cross_sticks).
    return [COLUMN["snare"], COLUMN["toms"]] if key == "XS" else COLUMN[INSTRUMENT_CLASS[key]]


def _activation(activations, fps, time, column):
    frame = int(round(time * fps))
    window = activations[max(0, frame - 3):frame + 4, column]
    return float(window.max()) if len(window) else 0.0


def crash_over_hihat(score):
    """Drop a closed hi-hat written together with a crash: the right hand plays the crash."""
    dropped = 0
    for measure in score.measures:
        for beat in measure.beats:
            for slot in beat.slots:
                if "CR" in slot and "HH" in slot:
                    slot.pop("HH")
                    dropped += 1
    return dropped


def unify_marks(score):
    """Bars with the same hits get the same marks: the majority per note over those bars.

    Ghost marks come from a loudness threshold; a groove played again and again is one
    pattern, and a mark flipping at the margin should not cancel a repeat sign.
    """
    groups = {}
    for measure in score.measures:
        if not measure.pickup:
            groups.setdefault(_plain_key(measure), []).append(measure)
    changed = 0
    for (_, hits), bars in groups.items():
        if len(bars) < 2:
            continue
        for b, s, k in hits:
            marks = [m.beats[b].slots[s][k] for m in bars]
            majority = max(dict.fromkeys(marks), key=marks.count)  # ties: the earliest
            for m in bars:
                if m.beats[b].slots[s][k] != majority:
                    m.beats[b].slots[s][k] = majority
                    changed += 1
    return changed

"""Measure-level drum score IR and its text form.

The text form is the contract with agents: it is compact, diffable, and can be
edited by hand or by an LLM and read back without loss.

    title: Back In Black
    tempo: 94
    time: 4/4
    feel: straight
    m1
      HH x-x-|x-x-|x-x-|x-x-
      SD ----|x---|----|x---
      BD x---|----|x-x-|----

A beat is one group between bars; its length is the subdivision
(4 = sixteenths, 3 = triplets, 2 = eighths; with a swing header the
written eighths/sixteenths are played long-short). XS is a cross-stick (side stick)
on the snare space. 'x' is a hit, 'X' an accent,
'g' a ghost note, '-' nothing. Rows that are all '-' may be omitted.

A bar in another kind of meter than the song's carries its signature in the header
("m25 12/8": beats are dotted quarters split in three eighths; "m30 4/4" inside a 12/8
song). A tempo line fixes the bar's tempo marks (the user's, from feedback): "tempo rit.",
"tempo 96", "tempo a tempo", "tempo -" (no mark); without one the marks are measured.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .instruments import INSTRUMENTS, ORDER

HIT_MARKS = {"x": "", "X": "accent", "g": "ghost"}


@dataclass
class Beat:
    division: int
    slots: list  # per slot: dict instrument -> mark ("" | "accent" | "ghost")

    @classmethod
    def empty(cls, division):
        return cls(division, [dict() for _ in range(division)])

    def is_empty(self):
        return not any(self.slots)

    def key(self):
        return (self.division, tuple(tuple(sorted(s.items())) for s in self.slots))


@dataclass
class Measure:
    beats: list
    pickup: bool = False
    start_beat: int = 0          # index into Score.beat_times of the first beat
    section: str = ""            # rehearsal label, e.g. "Verse"
    notes: list = field(default_factory=list)  # free-form comments from agents
    compound: bool = None        # this bar's beats are dotted (12/8); None = the song's feel
    tempo: list = None           # tempo marks fixed by the user ([] = none); None = measured

    def key(self):
        return tuple(b.key() for b in self.beats)

    def is_empty(self):
        return all(b.is_empty() for b in self.beats)


@dataclass
class Score:
    title: str
    bpm: int
    beats_per_bar: int
    feel: str
    measures: list
    beat_times: list = field(default_factory=list)  # audio seconds of every beat (sync)
    swing: tuple = None                              # (first, second, "eighth"|"16th")
    parts: list = None                               # e.g. ["kick", "snare"]; None = full kit

    @property
    def time_signature(self):
        if self.feel == "compound":
            return f"{self.beats_per_bar * 3}/8"
        return f"{self.beats_per_bar}/4"

    def is_compound(self, measure=None):
        """Dotted beats (12/8, 6/8) in this bar: its own signature, else the song's feel."""
        if measure is not None and measure.compound is not None:
            return measure.compound
        return self.feel == "compound"


def signature_text(beats, compound):
    return f"{beats * 3}/8" if compound else f"{beats}/4"


def from_grid(title, grid, placed):
    """Group quantized hits into measures, from the start of the music."""
    n = grid.beats_per_bar
    beats = [Beat.empty(len(template)) for template in grid.templates]
    for hit in placed:
        beats[hit["beat"]].slots[hit["slot"]][hit["instrument"]] = hit.get("mark", "")
    measures = []
    if grid.first_downbeat:
        measures.append(Measure(beats[:grid.first_downbeat], pickup=True, start_beat=0))
    # Bar lines from the bar tracker (short bars allowed), else regular bars from the downbeat.
    starts = list(grid.bar_starts or range(grid.first_downbeat, len(beats), n))
    starts = [b for b in starts if b < len(beats)]
    meters = getattr(grid, "bar_compound", None) or {}
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else start + n
        chunk = beats[start:end]
        while len(chunk) < end - start:
            chunk.append(Beat.empty(len(grid.templates[0])))
        compound = meters.get(start)
        measures.append(Measure(chunk, start_beat=start,
                                compound=None if compound is None or compound == (grid.feel == "compound") else compound))
    # Bar 1 is where the music starts (the first tracked beat), not where the drums come in:
    # bar numbers then match the song's own score. An empty pickup is dropped; silent bars
    # at the end are trimmed.
    if measures and measures[0].pickup and measures[0].is_empty():
        measures.pop(0)
    while measures and measures[-1].is_empty():
        measures.pop()
    return Score(title=title, bpm=int(round(grid.bpm)), beats_per_bar=n, feel=grid.feel, measures=measures,
                 beat_times=[float(t) for t in grid.beats], swing=grid.swing)


# ---------------------------------------------------------------- text form

def to_text(score):
    lines = [f"title: {score.title}", f"tempo: {score.bpm}", f"time: {score.time_signature}", f"feel: {score.feel}",
             f"first_beat: {score.measures[0].start_beat if score.measures else 0}"]
    if score.swing:
        lines.append(f"swing: {score.swing[0]}:{score.swing[1]} {score.swing[2]}")
    if score.parts:
        lines.append(f"parts: {','.join(score.parts)}")
    for number, measure in enumerate(score.measures, start=0 if score.measures and score.measures[0].pickup else 1):
        header = f"m{number}" + (" pickup" if measure.pickup else "") \
            + (f" {signature_text(len(measure.beats), measure.compound)}" if measure.compound is not None else "") \
            + (f" [{measure.section}]" if measure.section else "")
        lines.append(header)
        if measure.tempo is not None:
            lines.append("  tempo " + (", ".join(str(m) for m in measure.tempo) or "-"))
        used = [k for k in ORDER if any(k in slot for beat in measure.beats for slot in beat.slots)]
        if not used:
            lines.append("  rest " + "|".join("-" * b.division for b in measure.beats))
        for key in used:
            cells = []
            for beat in measure.beats:
                cells.append("".join(_mark_char(slot.get(key)) for slot in beat.slots))
            lines.append(f"  {key} " + "|".join(cells))
        for note in measure.notes:
            lines.append(f"  # {note}")
    return "\n".join(lines) + "\n"


def _mark_char(mark):
    if mark is None:
        return "-"
    return {"": "x", "accent": "X", "ghost": "g"}[mark]


def from_text(text, beat_times=None):
    header, measures, current = {}, [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("  #"):
            current.notes.append(line.strip()[1:].strip())
            continue
        match = re.match(r"^m(\d+)( pickup)?(?: (\d+)/(4|8))?(?: \[(.*)\])?$", line.strip())
        if match and not line.startswith("  "):
            current = Measure([], pickup=bool(match.group(2)), section=match.group(5) or "",
                              compound=None if not match.group(4) else match.group(4) == "8")
            measures.append(current)
            continue
        if line.startswith("  tempo "):
            value = line.strip()[len("tempo "):].strip()
            current.tempo = [] if value == "-" else [int(v) if v.isdigit() else v for v in
                                                     (x.strip() for x in value.split(","))]
            continue
        if not line.startswith("  ") and ":" in line:
            key, value = line.split(":", 1)
            header[key.strip()] = value.strip()
            continue
        name, cells = line.split(None, 1)
        groups = cells.split("|")
        if not current.beats:
            current.beats = [Beat.empty(len(g)) for g in groups]
        if [len(g) for g in groups] != [b.division for b in current.beats]:
            raise ValueError(f"beat lengths differ inside a measure: {line!r}")
        if name == "rest":
            continue
        if name not in INSTRUMENTS:
            raise ValueError(f"unknown instrument {name!r}")
        for beat, group in zip(current.beats, groups):
            for slot, char in enumerate(group):
                if char != "-":
                    beat.slots[slot][name] = HIT_MARKS[char]
    numerator, denominator = (int(x) for x in header.get("time", "4/4").split("/"))
    feel = header.get("feel", "straight")
    beats_per_bar = numerator // 3 if feel == "compound" else numerator
    start = int(header.get("first_beat", 0))
    for measure in measures:
        measure.start_beat = start
        start += len(measure.beats)
    swing = None
    if header.get("swing"):
        ratio, kind = header["swing"].split()
        first, second = (int(x) for x in ratio.split(":"))
        swing = (first, second, kind)
    return Score(title=header.get("title", ""), bpm=int(header.get("tempo", 120)), beats_per_bar=beats_per_bar,
                 feel=feel, measures=measures, beat_times=list(beat_times or []), swing=swing,
                 parts=header["parts"].split(",") if header.get("parts") else None)

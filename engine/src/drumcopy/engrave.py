"""Score IR -> MusicXML with standard drum-set engraving rules.

Rules applied:
- two voices: hands with stems up (voice 1), feet with stems down (voice 2);
- each beat is spelled on its own and beamed as one group (16th secondary beams, hooks);
- triplet beats carry a tuplet bracket; compound meter needs none;
- empty voices in a bar are hidden when the other voice plays; empty beats merge into half rests;
- integer metronome mark; per-beat hidden tempo keeps playback aligned with the recording;
- identical consecutive bars use the one-bar repeat sign, repeated 2- and 4-bar blocks use
  repeat barlines with an explicit count;
- systems follow 4-bar phrases: four bars per line, two (or one) when the bars are too
  dense to fit, so that no bar is left alone on a stretched line.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

import numpy as np

from .instruments import INSTRUMENTS, ORDER

DIVISIONS = 12  # per quarter: 16ths (3), triplet eighths (4), eighths (6)
TYPE_BY_DURATION = {3: ("16th", 0), 6: ("eighth", 0), 9: ("eighth", 1), 12: ("quarter", 0),
                    18: ("quarter", 1), 24: ("half", 0), 36: ("half", 1), 48: ("whole", 0)}


# ---------------------------------------------------------------- beat spelling

def _beat_length(score, measure=None):
    return 18 if score.is_compound(measure) else 12


def _unit(compound, division):
    if compound:
        return {3: 6, 6: 3}.get(division, 6)
    return {4: 3, 3: 4, 2: 6}[division]


def spell_beat(score, beat, voice, compound=None):
    """Tokens for one voice in one beat: dicts with kind, duration, instruments, type, dots, tuplet."""
    compound = score.is_compound() if compound is None else compound
    unit = _unit(compound, beat.division)
    onsets = [(slot, {k: m for k, m in hits.items() if INSTRUMENTS[k].voice == voice})
              for slot, hits in enumerate(beat.slots)]
    onsets = [(slot, hits) for slot, hits in onsets if hits]
    tokens = []
    if not onsets:
        length = 18 if compound else 12
        kind, dots = _written(length)
        return [{"kind": "rest", "duration": length, "slots": beat.division, "start": 0, "type": kind, "dots": dots}]
    if onsets[0][0] > 0:
        tokens.append({"kind": "rest", "slots": onsets[0][0], "start": 0})
    for i, (slot, hits) in enumerate(onsets):
        end = onsets[i + 1][0] if i + 1 < len(onsets) else beat.division
        tokens.append({"kind": "note", "slots": end - slot, "start": slot, "hits": hits})
    triplet = not compound and beat.division == 3 and not (len(tokens) == 1 and tokens[0]["slots"] == 3)
    for token in tokens:
        token.setdefault("duration", token["slots"] * unit)
        if triplet:
            # Written value is the untupleted one: 3 triplet eighths fill a quarter.
            written = token["slots"] * 6
            token["type"], token["dots"] = TYPE_BY_DURATION[written]
            token["tuplet"] = True
        else:
            token["type"], token["dots"] = _written(token["duration"])
    if triplet:
        tokens[0]["tuplet_start"] = True
        tokens[-1]["tuplet_stop"] = True
    _beam(tokens)
    return tokens


def _written(duration):
    if duration in TYPE_BY_DURATION:
        return TYPE_BY_DURATION[duration]
    raise ValueError(f"cannot spell duration {duration}")


def _beam(tokens):
    notes = [t for t in tokens if t["kind"] == "note" and t["type"] in ("eighth", "16th")]
    if len(notes) < 2:
        return
    for i, note in enumerate(notes):
        level1 = "begin" if i == 0 else "end" if i == len(notes) - 1 else "continue"
        note["beams"] = [level1]
        if note["type"] == "16th":
            left = i > 0 and notes[i - 1]["type"] == "16th" and _adjacent(tokens, notes[i - 1], note)
            right = i + 1 < len(notes) and notes[i + 1]["type"] == "16th" and _adjacent(tokens, note, notes[i + 1])
            if left and right:
                note["beams"].append("continue")
            elif left:
                note["beams"].append("end")
            elif right:
                note["beams"].append("begin")
            else:
                note["beams"].append("backward hook" if i == len(notes) - 1 else "forward hook")


def _adjacent(tokens, a, b):
    return tokens.index(b) == tokens.index(a) + 1


# ---------------------------------------------------------------- voices per measure

def measure_tokens(score, measure, voice):
    compound = score.is_compound(measure)
    per_beat = [spell_beat(score, beat, voice, compound) for beat in measure.beats]
    if voice == 1:
        return per_beat  # voice 1 stays beat by beat: it carries the per-beat tempo anchors
    merged, i = [], 0
    while i < len(per_beat):
        empty = _empty(per_beat[i])
        # Two silent beats in either half of a 4-beat bar: one half rest (dotted half in 12/8).
        if empty and i % 2 == 0 and i + 1 < len(per_beat) and _empty(per_beat[i + 1]) and len(measure.beats) == 4:
            length = 2 * _beat_length(score, measure)
            kind, dots = _written(length)
            merged.append([{"kind": "rest", "duration": length, "type": kind, "dots": dots}])
            i += 2
            continue
        merged.append(per_beat[i])
        i += 1
    return merged


def _empty(tokens):
    return len(tokens) == 1 and tokens[0]["kind"] == "rest"


def _is_silent(groups):
    return all(t["kind"] == "rest" for g in groups for t in g)


# ---------------------------------------------------------------- repeats

# Repeat blocks (|: :| Nx) are not written: the reader wants every bar printed, numbered as
# played. A repeated single bar is still a simile (%), which keeps the bar and its number.
REPEAT_BLOCKS = ()


def plan_repeats(measures, marked=(), blocks=REPEAT_BLOCKS):
    """Per measure: None, ('simile',), ('start', times) / ('end', times) for repeat blocks
    (of the given lengths in bars; none by default). A repeat never swallows a bar that
    starts a section or carries a tempo mark (marked)."""
    plan = [dict() for _ in measures]
    keys = [m.key() for m in measures]
    i = 0
    while i < len(measures):
        if measures[i].pickup or measures[i].is_empty():
            i += 1
            continue
        best = (0, 1, 1)  # (saved bars, block length, repetitions)
        for block in tuple(b for b in (4, 2) if b in blocks) + (1,):
            reps = 1
            while i + (reps + 1) * block <= len(measures) and \
                    keys[i + reps * block:i + (reps + 1) * block] == keys[i:i + block] and \
                    not any(measures[j].section or j in marked for j in range(i + reps * block, i + (reps + 1) * block)):
                reps += 1
            saved = block * (reps - 1)
            if reps >= 2 and saved > best[0]:
                best = (saved, block, reps)
        saved, block, reps = best
        if not saved:
            i += 1
            continue
        if block == 1:
            for j in range(i + 1, i + reps):
                plan[j]["simile"] = True
            plan[i]["simile_count_from"] = i
        else:
            plan[i]["repeat_start"] = True
            plan[i + block - 1]["repeat_end"] = reps
            for j in range(i + block, i + block * reps):
                plan[j]["skip"] = True
        i += block * reps
    return plan


# ---------------------------------------------------------------- systems

# Line width in sixteenth-note columns, measured on MuseScore 4.6 A4 output (default spacing):
# three bars of running sixteenths fit, four do not.
SYSTEM_WIDTH = 55
FIRST_SYSTEM_WIDTH = 47  # clef, time signature and tempo take room on the first line


def bar_width(measure, simile=False, compound=False):
    """Horizontal space of a bar in sixteenth-note columns.

    Both voices share columns; a column is as wide as the time to the next one, growing
    1.5x per doubling of duration (MuseScore's spacing ratio), plus one for the bar line.
    """
    if simile:
        return 6.0
    width = 1.0
    for beat in measure.beats:
        used = [s for s, slot in enumerate(beat.slots) if slot]
        starts = ([0] if not used or used[0] > 0 else []) + used
        for k, start in enumerate(starts):
            end = starts[k + 1] if k + 1 < len(starts) else beat.division
            sixteenths = 2 * (end - start) if compound else 4 * (end - start) / beat.division  # 12/8: slot = eighth
            width += 1.5 ** np.log2(sixteenths)
    return width


def rest_runs(score, plan, marked=()):
    """Runs of two or more silent bars, printed as one multi-measure rest: [(first, last)].
    A run stops at a section, a tempo mark, a change of meter or a repeat (MuseScore
    breaks multi-measure rests there too)."""
    runs, current = [], []
    for i, measure in enumerate(score.measures):
        silent = measure.is_empty() and not measure.pickup and not plan[i]
        if silent and current and not measure.section and i not in marked and \
                len(measure.beats) == len(score.measures[current[0]].beats) and \
                score.is_compound(measure) == score.is_compound(score.measures[current[0]]):
            current.append(i)
            continue
        if len(current) >= 2:
            runs.append((current[0], current[-1]))
        current = [i] if silent else []
    if len(current) >= 2:
        runs.append((current[0], current[-1]))
    return runs


def plan_systems(score, plan, runs=()):
    """Indices of the measures that start a new system.

    Bars are taken in 4-bar phrases (of printed bars); a phrase goes on one line if it
    fits, else it is split 2+2, else one bar per line. A multi-measure rest (runs) counts
    as one bar.
    """
    inside = {i for first, last in runs for i in range(first + 1, last + 1)}
    printed = [i for i, m in enumerate(score.measures) if not plan[i].get("skip") and i not in inside]
    pickup = [i for i in printed if score.measures[i].pickup]
    bars = [i for i in printed if not score.measures[i].pickup]
    width = {i: bar_width(score.measures[i], plan[i].get("simile"), score.is_compound(score.measures[i])) for i in printed}
    breaks, first = set(), True
    for start in range(0, len(bars), 4):
        phrase = bars[start:start + 4]
        budget = FIRST_SYSTEM_WIDTH - sum(width[i] for i in pickup) if first else SYSTEM_WIDTH
        if sum(width[i] for i in phrase) <= budget:
            lines = [phrase]
        elif all(sum(width[i] for i in half) <= SYSTEM_WIDTH for half in (phrase[:2], phrase[2:])):
            lines = [phrase[:2], phrase[2:]]
        else:
            lines = [[i] for i in phrase]
        for line in lines:
            if line and not first:
                breaks.add(line[0])
            first = False
    return breaks


# ---------------------------------------------------------------- MusicXML writer

def measure_signature(score, measure):
    beats = len(measure.beats)
    return (str(beats * 3), "8") if score.is_compound(measure) else (str(beats), "4")


def to_musicxml(score, for_editing=False):
    """for_editing: the file for notation programs (the .mxl for Sibelius, Dorico, Finale,
    MuseScore). Playback follows the tempo marks only, not a hidden tempo on every beat (those
    keep the PDF's playback with the recording, but show as a crowd of grey numbers in an
    editor), and a long title is set as a title and a subtitle line."""
    used = [k for k in ORDER if any(k in s for m in score.measures for b in m.beats for s in b.slots)] or ["SD"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
           '"http://www.musicxml.org/dtds/partwise.dtd">',
           '<score-partwise version="4.0">',
           f'  <work><work-title>{escape(score.title)}</work-title></work>',
           '  <identification><creator type="arranger">drumcopy (automatic transcription draft)</creator>'
           '<encoding><software>drumcopy</software></encoding></identification>',
           *(_title_credits(score.title) if for_editing else []),
           '  <part-list><score-part id="P1"><part-name>Drum Set</part-name><part-abbreviation>Dr.</part-abbreviation>']
    for key in used:
        out.append(f'    <score-instrument id="P1-{key}"><instrument-name>{INSTRUMENTS[key].name}</instrument-name></score-instrument>')
    for key in used:
        out.append(f'    <midi-instrument id="P1-{key}"><midi-channel>10</midi-channel>'
                   f'<midi-unpitched>{INSTRUMENTS[key].gm + 1}</midi-unpitched></midi-instrument>')
    out.append('  </score-part></part-list>')
    out.append('  <part id="P1">')

    changes = tempo_changes(score)
    plan = plan_repeats(score.measures, changes)
    runs = rest_runs(score, plan, changes)
    tempos = {} if for_editing else _steady_rests(playback_tempos(score, plan), runs)
    numerator, denominator = score.time_signature.split("/")
    number = 0 if score.measures and score.measures[0].pickup else 1
    breaks = plan_systems(score, plan, runs)
    # MuseScore joins silent bars into a multi-measure rest only if each holds a single rest.
    resting = {i for first, last in runs for i in range(first, last + 1)}
    for index, measure in enumerate(score.measures):
        info = plan[index]
        if info.get("skip"):
            continue
        attrs = f' implicit="yes"' if measure.pickup else ""
        out.append(f'    <measure number="{number}"{attrs}>')
        signature = (numerator, denominator) if measure.pickup else measure_signature(score, measure)
        if index == 0:
            out.append(f'      <attributes><divisions>{DIVISIONS}</divisions><key><fifths>0</fifths></key>'
                       f'<time><beats>{signature[0]}</beats><beat-type>{signature[1]}</beat-type></time>'
                       '<clef><sign>percussion</sign></clef></attributes>')
            out.extend(_tempo_mark(score, sound=for_editing))
        else:
            if index in breaks:
                out.append('      <print new-system="yes"/>')
            if signature != current_signature:
                # A short bar (e.g. 2/4 inside 4/4) and the return to the main meter.
                out.append(f'      <attributes><time><beats>{signature[0]}</beats><beat-type>{signature[1]}</beat-type>'
                           '</time></attributes>')
        current_signature = signature
        if measure.section:
            out.append(f'      <direction placement="above"><direction-type><rehearsal>{escape(measure.section)}'
                       '</rehearsal></direction-type></direction>')
        out.extend(_tempo_change_xml(score, mark, measure, sound=for_editing) for mark in changes.get(index, []))
        if info.get("repeat_start"):
            out.append('      <barline location="left"><bar-style>heavy-light</bar-style><repeat direction="forward"/></barline>')
        simile = info.get("simile")
        previous_simile = index > 0 and plan[index - 1].get("simile")
        if previous_simile and not simile:
            out.append('      <attributes><measure-style><measure-repeat type="stop"/></measure-style></attributes>')
        if simile and not previous_simile:
            out.append('      <attributes><measure-style><measure-repeat type="start" slashes="1">1</measure-repeat>'
                       '</measure-style></attributes>')
        if simile:
            out.extend(_simile_body(score, measure, tempos.get(index, {})))
        elif index in resting:
            out.extend(_sound(tempos.get(index, {}).get(0)))
            out.append(_rest_xml(_beat_length(score, measure) * len(measure.beats), 1, measure_rest=True))
        else:
            out.extend(_measure_body(score, measure, tempos.get(index, {})))
        if info.get("repeat_end"):
            times = info["repeat_end"]
            if times > 2:
                out.append(f'      <direction placement="above"><direction-type><words>{times}x</words></direction-type></direction>')
            out.append(f'      <barline location="right"><bar-style>light-heavy</bar-style>'
                       f'<repeat direction="backward" times="{times}"/></barline>')
        out.append('    </measure>')
        number += 1
    if score.measures:
        out[-1:-1] = ['      <barline location="right"><bar-style>light-heavy</bar-style></barline>'] \
            if not plan[-1].get("repeat_end") and not plan[-1].get("skip") else []
    out.append('  </part>')
    out.append('</score-partwise>')
    return "\n".join(out) + "\n"


PART_NAMES = {"kick": "Kick", "snare": "Snare", "hi-hat": "Hi-Hat", "toms": "Toms", "cymbals": "Cymbals"}


def _metronome_xml(score, bpm, measure=None, sound=False):
    compound = score.is_compound(measure)
    unit = '<beat-unit>quarter</beat-unit><beat-unit-dot/>' if compound else '<beat-unit>quarter</beat-unit>'
    play = f'<sound tempo="{bpm * (1.5 if compound else 1):g}"/>' if sound else ""
    return (f'      <direction placement="above"><direction-type><metronome parentheses="no">{unit}'
            f'<per-minute>{bpm}</per-minute></metronome></direction-type>{play}</direction>')


PAGE_TENTHS = (1200, 1697)  # A4 at 7 mm per 40 tenths (MuseScore's default staff size)


def _title_credits(title):
    """The page (A4) and the title lines placed on it: notation programs read a credit only
    with a position on a known page (without one MuseScore dropped the title)."""
    from .render import title_lines
    lines, size = title_lines(title)
    width, height = PAGE_TENTHS
    return ['  <defaults><scaling><millimeters>7</millimeters><tenths>40</tenths></scaling>'
            f'<page-layout><page-height>{height}</page-height><page-width>{width}</page-width></page-layout></defaults>',
            # One title, its lines split by a line break: two credits read as title and a smaller subtitle.
            f'  <credit page="1"><credit-type>title</credit-type><credit-words default-x="{width / 2:g}" '
            f'default-y="{height - 120}" justify="center" valign="top" font-size="{size:.0f}">'
            + "&#10;".join(escape(line) for line in lines) + '</credit-words></credit>']


def _tempo_change_xml(score, mark, measure=None, sound=False):
    if isinstance(mark, int):
        return _metronome_xml(score, mark, measure, sound)
    return (f'      <direction placement="above"><direction-type><words font-style="italic">{mark}</words>'
            '</direction-type></direction>')


# ---------------------------------------------------------------- tempo changes

TEMPO_TOLERANCE = 0.05  # a bar this far from the main tempo is slower or faster
TEMPO_HOLD = 0.03       # bars this close to each other hold one tempo
TRACKER_FRAME = 0.02    # beats come on a 20 ms grid (Beat This!, 50 fps): no finer tempo difference is measured
TEMPO_GLITCH = 0.08     # a bar this far from its smoothed neighbours is a tracker slip
A_TEMPO_BARS = 8        # a return after a longer excursion gets its metronome mark, not "a tempo"
UNSTEADY_BAR = 0.25     # beats inside one bar spread more than this: the beat tracker wandered


def tempo_plan(score):
    """(opening tempo, tempo marks) from the recording's beats; the marks are
    {measure index: [mark, ...]}, a mark being "rit.", "accel.", "a tempo" or a metronome value.

    Playback already follows the recording beat by beat (playback_tempos); the marks are for
    the reader. A bar's tempo is the median of its beats; a bar whose beats spread widely
    (fills, final chords, where the tracker wanders) or that slipped against its smoothed
    neighbours does not count. The song is read as tempo regions: three or more bars holding
    one tempo (within 3%, or one 20 ms tracker frame of a beat), valued at the median beat
    of those bars. The opening region gives the tempo at the head of the score. A region at
    a new tempo gets its metronome mark ("a tempo" when it returns to the tempo before the
    last change), with "rit." / "accel." where two or more bars lead away from the old
    tempo. Two or more bars off a tempo that then comes back are "rit." / "accel." ... "a
    tempo"; bars slowing down after the last region are "rit.". Songs with several tempos
    (Joel Raney "Love is Born": 103, 97, 84) are not measured against one song-wide median.
    """
    times = score.beat_times
    if not times or not score.measures or not score.bpm:
        return score.bpm, {}
    tempo = []
    for measure in score.measures:
        start, end = measure.start_beat, measure.start_beat + len(measure.beats)
        lengths = np.diff(times[start:end + 1]) if end < len(times) else np.array([])
        steady = len(lengths) >= 2 and (lengths.max() - lengths.min()) / np.median(lengths) <= UNSTEADY_BAR
        tempo.append(60 / float(np.median(lengths)) if steady and not measure.pickup else None)
    smooth = [float(np.median([x for x in tempo[max(0, i - 1):i + 2] if x is not None])) if t else None
              for i, t in enumerate(tempo)]
    clean = [t if t and abs(t / smooth[i] - 1) <= TEMPO_GLITCH else None for i, t in enumerate(tempo)]

    def held(values):
        middle = float(np.median(values))
        tolerance = max(TEMPO_HOLD, TRACKER_FRAME * middle / 60)
        return all(abs(v / middle - 1) <= tolerance for v in values)

    def beat_tempo(a, b):
        lengths = np.concatenate([np.diff(times[m.start_beat:m.start_beat + len(m.beats) + 1])
                                  for m in score.measures[a:b + 1]])
        return 60 / float(np.median(lengths))

    def same(x, y):
        return abs(x / y - 1) <= TEMPO_TOLERANCE

    def leaving(first, stop, reference):
        """First of two or more bars in first..stop-1 off the reference tempo the same way."""
        for k in range(first, stop - 1):
            a, b = smooth[k], smooth[k + 1]
            if a and b and not same(a, reference) and not same(b, reference) and (a > reference) == (b > reference):
                return k, ("accel." if a > reference else "rit.")
        return None

    regions, a = [], 0
    while a < len(clean):
        b = a
        while clean[a] is not None and b + 1 < len(clean) and clean[b + 1] is not None and held(clean[a:b + 2]):
            b += 1
        if b - a >= 2:
            regions.append((a, b, beat_tempo(a, b)))
            a = b + 1
        else:
            a += 1
    if not regions:
        return score.bpm, {}
    marks = {}
    history = [regions[0][2]]
    changed_at = regions[0][0]  # where the current tempo began
    for (_, last, _), (first, end, value) in zip(regions, regions[1:]):
        current = history[-1]
        away = leaving(last + 1, first, current)
        if same(value, current):
            if away:
                marks.setdefault(away[0], []).append(away[1])
                marks.setdefault(first, []).append("a tempo")
            continue
        if away:
            marks.setdefault(away[0], []).append("rit." if value < current else "accel.")
        # "a tempo" only after a short excursion: back to the tempo before it, at most 8 bars later.
        back = len(history) >= 2 and same(value, history[-2]) and first - changed_at <= A_TEMPO_BARS
        marks.setdefault(first, []).append("a tempo" if back else int(round(value)))
        history.append(value)
        changed_at = first
    away = leaving(regions[-1][1] + 1, len(smooth), history[-1])
    if away:
        marks.setdefault(away[0], []).append(away[1])
    return int(round(regions[0][2])), marks


def tempo_marks(score):
    """tempo_plan with the user's marks (Measure.tempo, from feedback) in place of the measured
    ones of those bars. A metronome value the user gives for the first bar is the opening tempo."""
    opening, marks = tempo_plan(score)
    marks = {i: list(m) for i, m in marks.items()}
    first = next((i for i, m in enumerate(score.measures) if not m.pickup), None)
    for i, measure in enumerate(score.measures):
        if measure.tempo is None:
            continue
        given = list(measure.tempo)
        if i == first and given and isinstance(given[0], int):
            opening = given.pop(0)
        if given:
            marks[i] = given
        else:
            marks.pop(i, None)
    return opening, marks


def tempo_changes(score):
    return tempo_marks(score)[1]


def _tempo_mark(score, sound=False):
    first = next((m for m in score.measures if not m.pickup), None)
    lines = [_metronome_xml(score, tempo_marks(score)[0], first, sound)]
    notes = []
    if score.parts:
        notes.append(" & ".join(PART_NAMES[p] for p in score.parts) + " only")
    if any("XS" in slot for m in score.measures for b in m.beats for slot in b.slots):
        notes.append("x on snare = cross-stick")  # x heads elsewhere are cymbals; say what this one is
    if notes:
        lines.append(f'      <direction placement="above"><direction-type><words font-style="italic">{escape(" · ".join(notes))}</words>'
                     '</direction-type></direction>')
    if score.swing:
        first, second, kind = score.swing
        label = "Swing" if kind == "eighth" else "Swing 16ths"
        if (first, second) != (2, 1):
            label += f" ({first}:{second})"
        lines.append(f'      <direction placement="above"><direction-type><words font-weight="bold">{label}</words>'
                     f'</direction-type><sound><swing><first>{first}</first><second>{second}</second>'
                     f'<swing-type>{kind}</swing-type></swing></sound></direction>')
    return lines


def playback_order(measures, plan):
    """(written measure index, played measure index) in performance order."""
    order, i = [], 0
    while i < len(measures):
        if plan[i].get("repeat_start"):
            end = next(j for j in range(i, len(measures)) if plan[j].get("repeat_end"))
            block, times = end - i + 1, plan[end]["repeat_end"]
            for p in range(times):
                order.extend((i + j, i + p * block + j) for j in range(block))
            i += block * times
        else:
            order.append((i, i))
            i += 1
    return order


def playback_tempos(score, plan):
    """Hidden per-beat tempos so that playback follows the recording.

    A repeated block replays the tempos of its first pass; the first beat after it
    absorbs the accumulated difference, so errors never carry over.
    """
    times = score.beat_times
    if not times or not score.measures:
        return {}
    seconds = {}
    clock = times[min(score.measures[0].start_beat, len(times) - 1)]
    for written, played in playback_order(score.measures, plan):
        start = score.measures[played].start_beat
        for b in range(len(score.measures[played].beats)):
            k = start + b
            nominal = times[k + 1] - times[k] if k + 1 < len(times) else times[-1] - times[-2]
            key = (written, b)
            if key not in seconds:
                target = times[k + 1] if k + 1 < len(times) else clock + nominal
                seconds[key] = float(np.clip(target - clock, 0.6 * nominal, 1.6 * nominal))
            clock += seconds[key]
    result = {}
    for (written, b), duration in seconds.items():
        quarters = 1.5 if score.is_compound(score.measures[written]) else 1.0
        result.setdefault(written, {})[b] = 60.0 * quarters / duration
    return result


def _steady_rests(tempos, runs):
    """One tempo for a multi-measure rest (a tempo change would split it): the run's mean,
    so that it lasts exactly as long as in the recording and the next bar starts in time."""
    for first, last in runs:
        seconds = [60.0 / t for i in range(first, last + 1) for t in tempos.get(i, {}).values()]
        if not seconds:
            continue
        tempos[first] = {0: 60.0 * len(seconds) / sum(seconds)}
        for i in range(first + 1, last + 1):
            tempos[i] = {}
    return tempos


def _measure_body(score, measure, tempos):
    lines = []
    beat_length = _beat_length(score, measure)
    total = beat_length * len(measure.beats)
    voices = {v: measure_tokens(score, measure, v) for v in (1, 2)}
    silent = {v: _is_silent(voices[v]) for v in (1, 2)}
    # Voice 1: one group per beat, each preceded by its tempo anchor.
    for b, group in enumerate(voices[1]):
        lines.extend(_sound(tempos.get(b)))
        if silent[1]:
            lines.append(_rest_xml(beat_length, 1, hidden=True))
        else:
            for token in group:
                lines.extend(_token_xml(token, 1))
    lines.append(f'      <backup><duration>{total}</duration></backup>')
    if silent[2]:
        # Hidden when the hands play; a single centred bar rest when the whole bar is silent.
        lines.append(_rest_xml(total, 2, hidden=not silent[1], measure_rest=silent[1]))
    else:
        for group in voices[2]:
            for token in group:
                lines.extend(_token_xml(token, 2))
    return lines


def _simile_body(score, measure, tempos):
    beat_length = _beat_length(score, measure)
    lines = []
    for b in range(len(measure.beats)):
        lines.extend(_sound(tempos.get(b)))
        lines.append(_rest_xml(beat_length, 1, hidden=True))
    return lines


def _sound(tempo):
    return [f'      <sound tempo="{tempo:.4f}"/>'] if tempo else []


def _rest_xml(duration, voice, hidden=False, measure_rest=False):
    attr = ' print-object="no"' if hidden else ""
    rtype = _written(duration)[0] if duration in TYPE_BY_DURATION else None
    type_xml = f"<type>{rtype}</type>" if rtype and not measure_rest else ""
    dot = "<dot/>" if duration in TYPE_BY_DURATION and TYPE_BY_DURATION[duration][1] and not measure_rest else ""
    rest = ('<rest measure="yes"><display-step>D</display-step><display-octave>5</display-octave></rest>'
            if measure_rest else "<rest/>")
    return f'      <note{attr}>{rest}<duration>{duration}</duration><voice>{voice}</voice>{type_xml}{dot}</note>'


def _token_xml(token, voice):
    tmod = "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>" \
        if token.get("tuplet") else ""
    dots = "<dot/>" * token["dots"]
    tuplet = ""
    if token.get("tuplet_start"):
        tuplet += '<tuplet type="start" bracket="yes" show-number="actual"/>'
    if token.get("tuplet_stop"):
        tuplet += '<tuplet type="stop"/>'
    if token["kind"] == "rest":
        notations = f"<notations>{tuplet}</notations>" if tuplet else ""
        return [f'      <note><rest/><duration>{token["duration"]}</duration><voice>{voice}</voice>'
                f'<type>{token["type"]}</type>{dots}{tmod}{notations}</note>']
    lines = []
    stem = "up" if voice == 1 else "down"
    hits = sorted(token["hits"].items(), key=lambda kv: ORDER.index(kv[0]))
    for n, (key, mark) in enumerate(hits):
        inst = INSTRUMENTS[key]
        chord = "<chord/>" if n else ""
        beams = "".join(f'<beam number="{i + 1}">{b}</beam>' for i, b in enumerate(token.get("beams", []))) if not n else ""
        articulations = ""
        if mark == "accent":
            articulations += "<articulations><accent/></articulations>"
        technical = "<technical><open/></technical>" if inst.articulation == "open" else ""
        inner = tuplet if not n else ""
        notations = f"<notations>{inner}{articulations}{technical}</notations>" if (inner or articulations or technical) else ""
        notehead = f'<notehead parentheses="yes">{inst.notehead}</notehead>' if mark == "ghost" else f"<notehead>{inst.notehead}</notehead>"
        lines.append(f'      <note>{chord}<unpitched><display-step>{inst.step}</display-step>'
                     f'<display-octave>{inst.octave}</display-octave></unpitched><duration>{token["duration"]}</duration>'
                     f'<instrument id="P1-{key}"/><voice>{voice}</voice><type>{token["type"]}</type>{dots}{tmod}'
                     f'<stem>{stem}</stem>{notehead}{beams}{notations}</note>')
    return lines


# ---------------------------------------------------------------- compressed MusicXML

MXL_CONTAINER = ('<?xml version="1.0" encoding="UTF-8"?>\n<container>\n  <rootfiles>\n'
                 '    <rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/>\n'
                 '  </rootfiles>\n</container>\n')


def to_mxl(musicxml_text, path):
    """Compressed MusicXML (.mxl): the exchange file Sibelius, Dorico, Finale and MuseScore
    open directly (Sibelius's own .sib cannot be written without Sibelius). A zip holding the
    MusicXML and META-INF/container.xml, "mimetype" first and stored, as the format asks."""
    import zipfile
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.recordare.musicxml", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", MXL_CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("score.musicxml", musicxml_text, compress_type=zipfile.ZIP_DEFLATED)
    return path


# ---------------------------------------------------------------- MIDI

def to_midi(score, path):
    """Score content as a General MIDI drum track, placed on the recording's beat times."""
    import pretty_midi

    times = score.beat_times
    midi = pretty_midi.PrettyMIDI(initial_tempo=float(score.bpm))
    track = pretty_midi.Instrument(program=0, is_drum=True, name="Drum Set")
    plan = plan_repeats(score.measures)
    source = None
    for index, measure in enumerate(score.measures):
        if not plan[index].get("simile"):
            source = measure
        for b, beat in enumerate(measure.beats):
            span = beat_span(times, measure.start_beat + b)
            if span is None:
                continue
            for s, hits in enumerate(beat.slots):
                when = span[0] + _fraction(score, beat.division, s, measure) * span[1]
                for key, mark in hits.items():
                    velocity = {"accent": 120, "ghost": 45}.get(mark, 96)
                    track.notes.append(pretty_midi.Note(velocity, INSTRUMENTS[key].gm, when, when + 0.08))
    midi.instruments.append(track)
    midi.write(str(path))
    return path


def beat_span(times, k):
    """(start, length) of beat k in seconds. The beat list ends on the last tracked beat; a
    beat at or past it (the last bar of a song) takes the length of the beat before, so its
    notes are not lost from the MIDI or the drawing."""
    if k + 1 < len(times):
        return times[k], times[k + 1] - times[k]
    if len(times) < 2:
        return None
    length = times[-1] - times[-2]
    return times[-1] + (k - (len(times) - 1)) * length, length


def _fraction(score, division, slot, measure=None):
    if score.swing and not score.is_compound(measure):
        first, second, kind = score.swing
        ratio = first / (first + second)
        if kind == "eighth" and division == 2 and slot == 1:
            return ratio
        if kind == "16th" and division == 4 and slot in (1, 3):
            return (slot - 1) / 4 + ratio / 2
    return slot / division

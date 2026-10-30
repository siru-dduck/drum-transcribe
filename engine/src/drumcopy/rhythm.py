"""Beat grid, tempo level, meter, feel and quantization.

Decisions follow common drum-chart conventions:
- quarter-note tempo kept in a readable range, with the snare backbeat on 2 and 4;
- per-beat choice between sixteenth and triplet subdivisions, measured on the hits;
- a global feel: straight, swing (eighths written straight with a swing mark) or compound (12/8).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

STRAIGHT, SWING, COMPOUND = "straight", "swing", "compound"


@dataclass
class Grid:
    beats: np.ndarray                 # seconds of every notated beat (incl. pickup)
    beats_per_bar: int
    first_downbeat: int               # index into beats of the first bar line
    feel: str = STRAIGHT
    templates: list = field(default_factory=list)     # per beat: hit positions (fractions of the beat)
    swing: tuple = None                                # (first, second, "eighth"|"16th") when swung
    tempo_level: float = 1.0          # factor applied to the tracker's beat level
    evidence: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)     # decisions fixed by an agent instead of evidence
    bar_starts: list = None                            # beat index of every bar line (short bars allowed)
    bar_compound: dict = None                          # bar start -> dotted beats (True) where the user set the meter

    def bar_lines(self):
        """Beat index of every bar line (tracked, or regular from the first downbeat)."""
        return list(self.bar_starts) if self.bar_starts else list(range(self.first_downbeat, len(self.beats), self.beats_per_bar))

    def beat_in_bar(self, beat):
        """Position of a beat inside its bar, following short bars."""
        import bisect
        lines = self.bar_lines()
        k = bisect.bisect_right(lines, beat) - 1
        return int(beat - lines[k]) if k >= 0 else int(beat - self.first_downbeat) % self.beats_per_bar

    @property
    def bpm(self):
        """Tempo from a straight-line fit of beat times, robust to local jitter."""
        index = np.arange(len(self.beats))
        slope = np.polyfit(index, self.beats, 1)[0]
        return 60.0 / slope


# ---------------------------------------------------------------- beat cleanup

def clean_beats(beats, event_times, duration, strong_times=None):
    beats = np.asarray(sorted(beats), dtype=float)
    if len(beats) < 3:
        raise ValueError("not enough beats to build a grid")
    gaps = np.diff(beats)
    period = float(np.median(gaps))
    # Trackers sometimes flip between two metrical levels; the finer one keeps every beat
    # (choose_level can still halve it), dropping beats would pick a parity at random.
    if np.mean(np.abs(gaps / period - 0.5) < 0.15) > 0.1:
        period /= 2
    elif strong_times is not None:
        beats = repair_phase_flips(beats, strong_times, period)
    kept = [beats[0]]
    for t in beats[1:]:
        if t - kept[-1] >= 0.75 * period:
            kept.append(t)
    filled = [kept[0]]
    for t in kept[1:]:
        local = _local_period(filled, period)
        missing = int(round((t - filled[-1]) / local)) - 1
        for k in range(1, missing + 1):
            filled.append(filled[-1] + (t - filled[-1]) / (missing + 2 - k))
        filled.append(t)
    beats = np.asarray(filled)
    first = min([beats[0]] + list(event_times[:1]))
    last = max([beats[-1]] + list(event_times[-1:]))
    head_period = float(np.median(np.diff(beats[:5])))
    tail_period = float(np.median(np.diff(beats[-5:])))
    head = []
    t = beats[0] - head_period
    while t > first - 0.5 * head_period and t > -head_period:
        head.insert(0, t)
        t -= head_period
    tail = []
    t = beats[-1] + tail_period
    while t < last + 0.5 * tail_period and t < duration + tail_period:
        tail.append(t)
        t += tail_period
    return np.concatenate([head, beats, tail])


FLIP_GAP = 0.6       # two beats closer than this (in beats) mark the tracker changing phase
FLIP_SPAN = 16       # flips this close (in beats) belong to one wandering stretch


def repair_phase_flips(beats, strong_times, period):
    """Where the tracker loses the beat for a moment it jumps to the off-beat and back, and
    marks each jump with two beats close together (Joel Raney "Lift Up Your Eyes" bars 104-105:
    beats 80-240 ms apart, the stretch between them half a beat off, so on-beat kicks were
    written on the "e" and "&"). A stretch of such jumps is replaced by beats evenly spaced
    between the steady beats on either side, if their distance is close to a whole number of
    beats and the kicks and snares (strong_times) fall on these beats more often than half a
    beat later; with fewer than 4 kicks and snares in the stretch nothing is changed."""
    beats = np.asarray(beats, dtype=float)
    jumps = list(np.where(np.diff(beats) < FLIP_GAP * period)[0])
    if not jumps:
        return beats
    hits = np.asarray(sorted(strong_times), dtype=float)
    stretches, current = [], [jumps[0]]
    for j in jumps[1:]:
        if j - current[-1] <= FLIP_SPAN:
            current.append(j)
        else:
            stretches.append(current)
            current = [j]
    stretches.append(current)
    for stretch in reversed(stretches):  # from the end, so earlier indices stay valid
        before, after = stretch[0], stretch[-1] + 2  # beats[before] .. beats[after] enclose the jumps
        if before < 1 or after >= len(beats) - 1:
            continue
        a, b = beats[before - 1], beats[after]  # last steady beat before, first after
        count = (b - a) / period
        if abs(count - round(count)) > 0.25 or round(count) < 2:
            continue
        even = np.linspace(a, b, int(round(count)) + 1)
        step = even[1] - even[0]
        if np.sum((hits > a) & (hits < b)) < 4:
            continue
        if _on_beat(hits, even, step) > _on_beat(hits, even[:-1] + step / 2, step):
            beats = np.concatenate([beats[:before - 1], even, beats[after + 1:]])
    return beats


def _on_beat(hits, beats, period):
    """Share of the hits between the first and last beat that fall on a beat (within 1/8 beat)."""
    inside = hits[(hits >= beats[0] - period / 8) & (hits <= beats[-1] + period / 8)]
    if not len(inside):
        return 0.0
    return float(np.mean(np.min(np.abs(inside[:, None] - beats[None, :]), axis=1) < period / 8))


PULSE_WINDOW = 8        # tracker beats per window judged at once
PULSE_MARGIN = 0.15     # grid fit the drum pulse must win by
PULSE_FIT = 0.7         # and reach on its own
PULSE_RUN = 3           # windows in a row (half-overlapping: 16 beats or more)
PULSE_TOLERANCE = 0.05  # seconds: a drum stroke on a grid point


def _grid_fit(strokes, period, start, end):
    """How well strokes sit on a beat grid of this period (best phase): F-measure of the share
    of strokes on a grid point and the share of grid points with a stroke."""
    best = (0.0, 0.0)
    for phase in np.arange(0, period, period / 24):
        grid = np.arange(start + phase, end, period)
        if len(grid) < 2:
            continue
        distance = np.abs(strokes[:, None] - grid[None, :])
        on = np.mean(distance.min(axis=1) < PULSE_TOLERANCE)
        used = np.mean(distance.min(axis=0) < PULSE_TOLERANCE)
        score = 2 * on * used / (on + used) if on + used else 0.0
        if score > best[0]:
            best = (score, phase)
    return best


def follow_drum_pulse(beats, events):
    """Where the drums keep a steady pulse 1.5 times the tracker's beat, the beat is the drums'.

    The tracker can follow the orchestra instead of the kit: in Joel Raney "Christmas Joy"
    bars 41-66 it beat 144 where hi-hat and kick kept 96 (3:2), so every drum stroke landed
    on a dotted-eighth. Level choice only knows 2:1. In windows of 8 tracker beats, the time-
    keeping strokes (kick, snare, hi-hat, cymbals) are fitted to a grid of the tracker's beat
    and of 1.5 times it; where the 1.5 grid wins clearly (by .15, reaching .7) for 3 windows in
    a row, those beats are replaced by a least-squares grid through the strokes (two such
    stretches at the same tempo, separated only by a rest of the drums of at most 32 beats,
    are one). Returns
    (beats, [(first, last) seconds of each replaced stretch])."""
    beats = np.asarray(beats, dtype=float)
    strokes = np.asarray(sorted(e["time"] for e in events if e["class"] in ("kick", "snare", "hi-hat", "cymbals")))
    if len(strokes) < 2 * PULSE_WINDOW or len(beats) < 2 * PULSE_WINDOW:
        return beats, []
    wins, silent = [], set()
    for i in range(0, len(beats) - PULSE_WINDOW, PULSE_WINDOW // 2):
        start, end = beats[i], beats[i + PULSE_WINDOW]
        inside = strokes[(strokes >= start) & (strokes < end)]
        period = float(np.median(np.diff(beats[i:i + PULSE_WINDOW + 1])))
        if len(inside) < PULSE_WINDOW // 2:
            silent.add(i)  # the drums rest: no evidence either way
            wins.append(None)
            continue
        own, _ = _grid_fit(inside, period, start, end)
        slow, phase = _grid_fit(inside, 1.5 * period, start, end)
        wins.append((i, slow, phase, period) if slow >= PULSE_FIT and slow > own + PULSE_MARGIN else None)
    stretches, run = [], []
    for w in wins + [None]:
        if w is not None:
            run.append(w)
            continue
        if len(run) >= PULSE_RUN:
            stretches.append(run)
        run = []
    # A rest of the drums (windows with too few strokes to judge, at most 32 beats) between two
    # stretches at the same drum tempo does not end it; any window that judged otherwise does.
    joined = []
    for run in stretches:
        if joined:
            gap = range(joined[-1][-1][0] + PULSE_WINDOW // 2, run[0][0], PULSE_WINDOW // 2)
            same = abs(np.median([w[3] for w in run]) / np.median([w[3] for w in joined[-1]]) - 1) < 0.03
            if same and len(gap) * PULSE_WINDOW // 2 <= 4 * PULSE_WINDOW and all(i in silent for i in gap):
                joined[-1] = joined[-1] + run
                continue
        joined.append(run)
    stretches = joined
    replaced = []
    for run in reversed(stretches):  # from the end, so earlier indices stay valid
        first, last = run[0][0], min(run[-1][0] + PULSE_WINDOW, len(beats) - 1)
        start, end = beats[first], beats[last]
        period = 1.5 * float(np.median([w[3] for w in run]))
        inside = strokes[(strokes >= start - period / 2) & (strokes <= end + period / 2)]
        _, phase = _grid_fit(inside, period, start, end)
        index = np.round((inside - start - phase) / period)
        on = np.abs(inside - (start + phase + index * period)) < PULSE_TOLERANCE
        if on.sum() < 4:
            continue
        slope, offset = np.polyfit(index[on], inside[on], 1)  # the drums' own tempo drift
        grid = offset + slope * np.arange(np.floor((start - offset) / slope), np.ceil((end - offset) / slope) + 1)
        grid = grid[(grid > beats[first - 1] + 0.5 * slope if first else grid >= start - slope)
                    & (grid < (beats[last + 1] - 0.5 * slope if last + 1 < len(beats) else end + slope))]
        beats = np.concatenate([beats[:first][beats[:first] < grid[0] - 0.5 * slope], grid,
                                beats[last + 1:][beats[last + 1:] > grid[-1] + 0.5 * slope]])
        replaced.append((round(float(grid[0]), 2), round(float(grid[-1]), 2)))
    return beats, sorted(replaced)


def _local_period(filled, period):
    if len(filled) < 3:
        return period
    # Bounded: a short stretch where the tracker doubled must not make every later gap "missing".
    return float(np.clip(np.median(np.diff(filled[-5:])), 0.8 * period, 1.25 * period))


# ---------------------------------------------------------------- helpers

def beat_position(beats, time):
    """Fractional beat index of a time (linear between beats, extrapolated at edges)."""
    i = int(np.clip(np.searchsorted(beats, time) - 1, 0, len(beats) - 2))
    return i + (time - beats[i]) / (beats[i + 1] - beats[i])


def _hits(events, cls):
    return np.array([e["time"] for e in events if e["class"] == cls])


def _activation_at(curve, fps, times):
    curve = np.asarray(curve)
    frames = np.clip(np.rint(np.asarray(times) * fps).astype(int), 0, len(curve) - 1)
    return np.array([curve[max(0, f - 1):f + 2].max() for f in frames])


# ---------------------------------------------------------------- tempo level

def _level_candidates(beats):
    double = np.empty(2 * len(beats) - 1)
    double[0::2] = beats
    double[1::2] = (beats[:-1] + beats[1:]) / 2
    return {1.0: beats, 2.0: double, 0.5: beats[0::2], -0.5: beats[1::2]}


def _backbeat_profile(beats, snare, bar_phase, beats_per_bar=4):
    """Share of all snare hits that land on each beat of the bar (off-beat hits count in the total)."""
    counts = np.zeros(beats_per_bar)
    for t in snare:
        position = beat_position(beats, t)
        nearest = int(round(position))
        if abs(position - nearest) < 0.12:
            counts[(nearest - bar_phase) % beats_per_bar] += 1
    return counts / len(snare) if len(snare) else counts


def _backbeat(profile):
    """Snare on 2 and 4, both of them: a one-sided profile is not a backbeat."""
    on = profile[1] + profile[3]
    return on * (1 - abs(profile[1] - profile[3]) / on) if on else 0.0


def _tempo_prior(bpm):
    # Readable quarter-note tempos cluster around 70-160 BPM.
    return -((np.log2(bpm / 110.0)) ** 2) / (2 * 0.55 ** 2)


def choose_level(beats, events, downbeat_curve, fps, force=None):
    """force: 0.5, 1 or 2 fixes the level; the half-tempo parity is still chosen from evidence."""
    snare = _hits(events, "snare")
    scores = {}
    for level, candidate in _level_candidates(beats).items():
        if len(candidate) < 4:
            continue
        bpm = 60.0 / float(np.median(np.diff(candidate)))
        score = _tempo_prior(bpm) + (0.6 if level == 1.0 else 0.0)
        phase = _best_phase(candidate, 4, events, downbeat_curve, fps)
        profile = _backbeat_profile(candidate, snare, phase)
        score += 3.0 * _backbeat(profile) - 1.0 * profile[2] * (profile[2] > 0.6)
        scores[level] = (round(float(score), 3), round(bpm, 1), [round(float(p), 2) for p in profile])
    _half_parity(scores, beats, downbeat_curve, fps)
    if choose_feel(correct_beat_lag(beats, events)[0], events)[0] == SWING:
        # Swung eighths at the tracker's level become swung sixteenths when halved;
        # jazz charts keep the fast tempo with swing eighths.
        for half in (0.5, -0.5):
            if half in scores:
                scores[half] = (round(scores[half][0] - 1.0, 3),) + scores[half][1:]
    allowed = [k for k in scores if force is None or abs(k) == force] or [1.0]
    level = max(allowed, key=lambda k: scores[k][0])
    return level, _level_candidates(beats)[level], scores


def _half_parity(scores, beats, downbeat_curve, fps):
    """Halving keeps every other beat; which half is a phase question, not a tempo one.

    The half carrying the tracker's downbeats wins when the evidence is clear; it takes
    the better of the two half-tempo scores (the snare profile of a half grid says
    nothing reliable about parity, e.g. jazz comping).
    """
    if 0.5 not in scores or -0.5 not in scores:
        return
    activation = _activation_at(downbeat_curve, fps, beats)
    even, odd = activation[0::2].mean(), activation[1::2].mean()
    if abs(even - odd) < 0.1:
        return
    keep, drop = (0.5, -0.5) if even > odd else (-0.5, 0.5)
    best = max(scores[keep][0], scores[drop][0])
    worst = min(scores[keep][0], scores[drop][0])
    scores[keep] = (best,) + scores[keep][1:]
    scores[drop] = (worst,) + scores[drop][1:]


# ---------------------------------------------------------------- meter and phase

def _best_phase(beats, beats_per_bar, events, downbeat_curve, fps):
    activation = _activation_at(downbeat_curve, fps, beats)
    kick = _hits(events, "kick")
    kick_on = np.array([np.any(np.abs(kick - t) < 0.05) for t in beats]) if len(kick) else np.zeros(len(beats))
    best, best_score = 0, -np.inf
    for phase in range(beats_per_bar):
        on = np.zeros(len(beats), bool)
        on[phase::beats_per_bar] = True
        score = activation[on].mean() - activation[~on].mean() + 0.3 * (kick_on[on].mean() - kick_on[~on].mean())
        if score > best_score:
            best, best_score = phase, score
    return best


def choose_meter(beats, events, downbeat_curve, fps, force=None):
    scores = {}
    for n in sorted({3, 4, force or 4}):
        phase = _best_phase(beats, n, events, downbeat_curve, fps)
        activation = _activation_at(downbeat_curve, fps, beats)
        on = np.zeros(len(beats), bool)
        on[phase::n] = True
        scores[n] = (float(activation[on].mean() - activation[~on].mean()), phase)
    # Four is the overwhelming default in popular music; three needs clear evidence.
    n = force or (3 if scores[3][0] > scores[4][0] + 0.15 else 4)
    return n, scores[n][1], {k: round(v[0], 3) for k, v in scores.items()}


# ---------------------------------------------------------------- bar lines with short bars

BAR_CLASSES = ("kick", "snare", "hi-hat", "toms", "cymbals")
SHORT_BAR_PENALTY = 8.0   # nats; measured on a reference with four 2/4 bars and on MDB (all 4/4)
DOWNBEAT_WEIGHT = 5.0


def _beat_vectors(beats, events):
    """Per beat: which class plays on which sixteenth (binary, classes x 4)."""
    x = np.zeros((len(beats), len(BAR_CLASSES) * 4))
    for e in events:
        position = beat_position(beats, e["time"])
        i = int(np.floor(position + 1 / 8))
        if 0 <= i < len(beats):
            x[i, BAR_CLASSES.index(e["class"]) * 4 + int(round((position - i) * 4)) % 4] = 1
    return x


def _bar_prior(x, downbeat, bar):
    """Song-independent cues: tracker downbeats, a cymbal on the one, a fill closing the bar."""
    prior = np.zeros((len(x), bar))
    prior[:, 0] += DOWNBEAT_WEIGHT * (downbeat - 0.5)
    prior[x[:, BAR_CLASSES.index("cymbals") * 4] > 0, 0] += 2.0
    toms = x[:, BAR_CLASSES.index("toms") * 4:(BAR_CLASSES.index("toms") + 1) * 4].sum(1)
    fill = toms >= 2
    prior[fill, bar - 1] += 1.5
    prior[1:][fill[:-1], 0] += 1.0
    return prior


def _bar_viterbi(x, prototypes, prior, bar, start, penalties):
    eps = 0.05
    p = np.clip(prototypes, eps, 1 - eps)
    emit = x @ np.log(p).T + (1 - x) @ np.log(1 - p).T
    emit[x.sum(1) == 0] = 0.0
    emit = emit + prior
    n = len(x)
    score = np.full((n, bar), -np.inf)
    back = np.zeros((n, bar), int)
    score[0, start] = emit[0, start]  # the opening phase is kept; moving it later costs a short bar
    for i in range(1, n):
        for pos in range(bar):
            if pos == 0:
                options = [(score[i - 1, bar - 1], bar - 1)] + [(score[i - 1, k - 1] - cost, k - 1) for k, cost in penalties.items()]
            else:
                options = [(score[i - 1, pos - 1], pos - 1)]
            best, arg = max(options)
            score[i, pos] = best + emit[i, pos]
            back[i, pos] = arg
    path = [int(np.argmax(score[-1]))]
    for i in range(n - 1, 0, -1):
        path.append(back[i, path[-1]])
    return np.array(path[::-1])


def track_bars(beats, events, first_downbeat, bar, downbeat_curve, fps, iterations=4):
    """Bar lines that follow the groove, allowing short bars (a 2/4 bar inside 4/4).

    Position-in-bar prototypes are learned from the song itself. The first pass uses the
    song-independent cues only, because a fixed-meter start would teach the prototypes
    its own mistakes.
    """
    if bar < 3 or len(beats) < 2 * bar:
        return None, []
    x = _beat_vectors(beats, events)
    prior = _bar_prior(x, _activation_at(downbeat_curve, fps, beats), bar)
    penalties = {k: SHORT_BAR_PENALTY * (1.0 if k == bar // 2 else 1.5) for k in range(2, bar)}
    start = (-first_downbeat) % bar
    positions = _bar_viterbi(x, np.full((bar, x.shape[1]), 0.5), prior, bar, start, penalties)
    active = x.sum(1) > 0
    for _ in range(iterations):
        prototypes = np.array([x[(positions == k) & active].mean(0) if np.any((positions == k) & active)
                               else np.full(x.shape[1], 0.05) for k in range(bar)])
        new = _bar_viterbi(x, prototypes, prior, bar, start, penalties)
        if np.array_equal(new, positions):
            break
        positions = new
    starts = [i for i in range(len(beats)) if positions[i] == 0]
    short = [(a, b - a) for a, b in zip(starts, starts[1:]) if b - a != bar]
    return starts, short


# ---------------------------------------------------------------- subdivision and feel

# Swing ratios that notation software understands (first:second of a beat division).
SWING_RATIOS = ((3, 2), (5, 3), (2, 1), (5, 2), (3, 1))
STRAIGHT16 = (0.0, 0.25, 0.5, 0.75)
TRIPLET = (0.0, 1 / 3, 2 / 3)


def correct_beat_lag(beats, events):
    """Shift the grid by the median offset of hits close to a beat (trackers often lag the kit)."""
    offsets = []
    for e in events:
        if e["class"] not in ("kick", "snare", "hi-hat"):
            continue
        position = beat_position(beats, e["time"])
        nearest = int(round(position))
        if abs(position - nearest) < 0.1 and 0 <= nearest < len(beats) - 1:
            offsets.append((position - nearest) * (beats[nearest + 1] - beats[nearest]))
    if len(offsets) < 8:
        return beats, 0.0
    lag = float(np.median(offsets))
    return beats + lag, lag


def snap_beats(beats, events, window=0.1, weight=0.5):
    """Move each beat onto the hits played on it (trackers drift where the playing is loose)."""
    offsets = [[] for _ in beats]
    for e in events:
        if e["class"] not in ("kick", "snare", "hi-hat", "cymbals"):
            continue
        position = beat_position(beats, e["time"])
        nearest = int(round(position))
        if abs(position - nearest) < window and 0 <= nearest < len(beats):
            offsets[nearest].append(e["time"] - beats[nearest])
    snapped = np.array([t + weight * float(np.median(o)) if o else t for t, o in zip(beats, offsets)])
    return snapped if np.all(np.diff(snapped) > 0) else beats


def _fractions(beats, events):
    per_beat = [[] for _ in range(len(beats))]
    for e in events:
        position = beat_position(beats, e["time"])
        index = int(np.floor(position + 1 / 24))
        fraction = position - index
        if 0 <= index < len(beats) and fraction > 1 / 12:
            per_beat[index].append(fraction)
    return per_beat


def _nearest_ratio(value):
    first, second = min(SWING_RATIOS, key=lambda r: abs(r[0] / sum(r) - value))
    return first, second


def _template_error(fractions, template):
    positions = np.array(template + (1.0,))
    return float(np.mean([np.min(np.abs(positions - f)) for f in fractions]))


FEELS = (STRAIGHT, SWING, "swing16", COMPOUND)


def choose_feel(beats, events, force=None):
    """Global feel and one position template per beat.

    straight: sixteenths, with local triplets where clearly better;
    swing:    eighths played long-short, written straight with a swing ratio;
    swing16:  sixteenths played long-short inside each eighth;
    compound: full triplet subdivision, written in 12/8 (or 6/8, 9/8).
    """
    per_beat = _fractions(beats, events)
    flat = np.array([f for fr in per_beat for f in fr])
    evidence = {"offbeat_hits": int(len(flat))}
    if len(flat) < 8 and force is None:
        return STRAIGHT, None, [STRAIGHT16] * len(beats), evidence
    if not len(flat):
        flat = np.array([0.5])

    # Eighth off-beat cluster and sixteenth clusters.
    eighth = flat[(flat > 0.42) & (flat < 0.78)]
    early = flat[(flat > 0.12) & (flat < 0.42)]
    late = flat[(flat >= 0.78)]
    m8 = float(np.median(eighth)) if len(eighth) else 0.5
    m_early = float(np.median(early)) if len(early) else 0.25
    m_late = float(np.median(late)) if len(late) else 0.75
    sixteenth_share = (len(early) + len(late)) / len(flat)
    triplet_middle = float(np.mean(np.abs(flat - 1 / 3) < 0.06))
    evidence.update(eighth_median=round(m8, 3), sixteenth_share=round(sixteenth_share, 3),
                    early_median=round(m_early, 3), late_median=round(m_late, 3), triplet_middle=round(triplet_middle, 3))

    candidates = {STRAIGHT: (STRAIGHT16, None)}
    if 0.54 <= m8 <= 0.78:
        first, second = _nearest_ratio(m8)
        candidates[SWING] = ((0.0, first / (first + second)), (first, second, "eighth"))
    if len(early) >= 4 and len(late) >= 4 and 0.29 <= m_early <= 0.4 and 0.79 <= m_late <= 0.9:
        first, second = _nearest_ratio(2 * (m_early + (m_late - 0.5)) / 2)
        r = first / (first + second) / 2
        candidates["swing16"] = ((0.0, r, 0.5, 0.5 + r), (first, second, "16th"))
    candidates[COMPOUND] = (TRIPLET, None)
    # A forced feel without a measured ratio uses the common 2:1 (triplet) swing.
    candidates.setdefault(force or STRAIGHT, {SWING: ((0.0, 2 / 3), (2, 1, "eighth")),
                                              "swing16": ((0.0, 1 / 3, 0.5, 0.5 + 1 / 3), (2, 1, "16th"))}.get(force))

    def cost(template):
        # Mean distance to the template, plus a small price per position (simpler is better).
        return np.mean([_template_error(fr, template) for fr in per_beat if fr]) + 0.004 * len(template)

    costs = {name: cost(template) for name, (template, _) in candidates.items()}
    evidence["feel_costs"] = {k: round(float(v), 4) for k, v in costs.items()}
    feel = min(costs, key=costs.get)
    # Compound and swing must beat straight clearly; straight is the reading default.
    if feel != STRAIGHT and costs[feel] > 0.8 * costs[STRAIGHT]:
        feel = STRAIGHT
    if force:
        feel = force
    template, swing = candidates[feel]

    templates = []
    for fractions in per_beat:
        chosen = template
        if fractions and feel in (STRAIGHT, SWING, "swing16"):
            here, triplet = _template_error(fractions, template), _template_error(fractions, TRIPLET)
            if len(fractions) >= 2 and triplet < 0.5 * here and here > 0.03:
                chosen = TRIPLET
            elif feel == SWING and _template_error(fractions, STRAIGHT16) < 0.5 * here:
                chosen = STRAIGHT16  # a straight sixteenth figure inside a swing tune
        templates.append(chosen)
    return feel, swing, templates, evidence


# ---------------------------------------------------------------- entry point

def build_grid(events, beat_tracking, duration, tempo_level=None, beats_per_bar=None, feel=None, downbeat_shift=0):
    """Overrides (tempo_level, beats_per_bar, feel, downbeat_shift) let an agent correct a decision;
    everything not overridden is still decided from the evidence."""
    if tempo_level is not None and tempo_level not in (0.5, 1, 2):
        raise ValueError("tempo_level must be 0.5, 1 or 2")
    if beats_per_bar is not None and beats_per_bar not in (2, 3, 4, 5, 6, 7):
        raise ValueError("beats_per_bar must be between 2 and 7")
    if feel is not None and feel not in FEELS:
        raise ValueError(f"feel must be one of {', '.join(FEELS)}")
    overrides = {k: v for k, v in dict(tempo_level=tempo_level, beats_per_bar=beats_per_bar, feel=feel,
                                       downbeat_shift=downbeat_shift).items() if v}
    times = sorted(e["time"] for e in events)
    fps = beat_tracking["fps"]
    curve = beat_tracking["downbeat_activation"]
    strong = sorted(e["time"] for e in events if e["class"] in ("kick", "snare"))
    beats = clean_beats(beat_tracking["beats"], times, duration, strong)
    level, beats, level_scores = choose_level(beats, events, curve, fps, force=tempo_level)
    beats = clean_beats(beats, times, duration, strong)
    beats, drum_pulse = follow_drum_pulse(beats, events)
    beats, lag = correct_beat_lag(beats, events)
    beats = snap_beats(beats, events)
    beats_per_bar, phase, meter_scores = choose_meter(beats, events, curve, fps, force=beats_per_bar)
    phase = (phase + int(downbeat_shift or 0)) % beats_per_bar  # +1: bar lines one beat later
    feel, swing, templates, feel_evidence = choose_feel(beats, events, force=feel)
    bar_starts, short_bars = None, []
    if not overrides.get("beats_per_bar") and not overrides.get("downbeat_shift"):
        # An agent fixing the meter or the bar lines gets exactly the regular bars it asked for.
        bar_starts, short_bars = track_bars(beats, events, phase, beats_per_bar, curve, fps)
        if bar_starts:
            phase = bar_starts[0]
    grid = Grid(beats=beats, beats_per_bar=beats_per_bar, first_downbeat=phase, feel=feel,
                templates=templates, swing=swing, tempo_level=abs(level),
                evidence={"level_scores": {str(k): v for k, v in level_scores.items()},
                          "meter_scores": meter_scores, "beat_lag_seconds": round(lag, 4),
                          "short_bars": [[int(a), int(b)] for a, b in short_bars], "drum_pulse": drum_pulse,
                          **feel_evidence},
                overrides=overrides, bar_starts=bar_starts)
    grid.evidence["drumless_stretches"] = follow_tracker_without_drums(grid, events, beat_tracking)
    return grid


DRUMLESS = 8.0  # seconds without kick, snare or hi-hat: the beat there comes from the other instruments
AGREE = 0.6      # share of beats one grid finds in the other (within 70 ms); below it both ways: they contradict


def follow_tracker_without_drums(grid, events, beat_tracking, gap=DRUMLESS):
    """Where the drums are silent and the grid contradicts the tracker, the tracker's own beats
    and bar lines come back. The song-wide beat length the rules settle on (clean_beats) can
    be far from such a stretch's own: a choir intro at quarter = 73 before a drum section whose
    tracked beats run at 0.3 s was "filled" to 161 beats where the tracker heard 103, at a
    ratio no metre explains (Christmas Joy). Contradict means neither grid holds the other:
    most tracker beats have no grid beat near them and most grid beats no tracker beat. A grid
    at a related level stays (twice or half the tracker, or the tracker with gaps filled: Lift
    Up Your Eyes, the West Sky intro), and so does one where the tracker itself counts too
    fast (a 3/4 rubato at 1.23x). The drums' bar lines around the stretch stay; a bar at the
    seam may come out short or long. Returns the stretches replaced."""
    from .feedback import apply_structure

    strokes = sorted(e["time"] for e in events if e["class"] in ("kick", "snare", "hi-hat"))
    raw = np.asarray(beat_tracking["beats"], dtype=float)
    downs = np.asarray(beat_tracking.get("downbeats", []), dtype=float)
    if len(raw) < 4:
        return []
    edges = [float(raw[0]) - 1.0] + strokes + [float(beat_tracking["duration_seconds"]) + 1.0]
    entries, used = [], []
    for a, z in zip(edges, edges[1:]):
        if z - a < gap:
            continue
        period = float(np.median(np.diff(raw[(raw > a) & (raw < z)]))) if np.sum((raw > a) & (raw < z)) > 2 else 0.5
        inside = raw[(raw > a + period) & (raw < z - period)]  # one beat of margin: the seams stay the drums'
        if len(inside) < 4:
            continue
        held = np.asarray(grid.beats)[(grid.beats >= inside[0] - 0.05) & (grid.beats <= inside[-1] + 0.05)]
        if len(held):
            recall = np.mean([np.min(np.abs(held - t)) < 0.07 for t in inside])
            precision = np.mean([np.min(np.abs(inside - t)) < 0.07 for t in held])
            if recall >= AGREE or precision >= AGREE:
                continue
        lines = [float(d) for d in downs if inside[0] - 0.02 <= d <= inside[-1] + 0.02]
        lines = [float(inside[np.argmin(np.abs(inside - d))]) for d in lines]
        entries.append({"kind": "beats", "time": float(inside[0]), "end": float(inside[-1]),
                        "times": [float(t) for t in inside], "downbeats": lines, "rephase": False, "added": ""})
        used.append([round(float(inside[0]), 2), round(float(inside[-1]), 2)])
    if entries:
        apply_structure(grid, entries, events)
        grid.evidence["user_structure"] = 0  # these are the tracker's, not the user's
    return used


def quantize(events, grid):
    """Map each hit to (beat index, slot) of its beat's template; same instrument on a slot merges."""
    placed = {}
    for e in events:
        position = beat_position(grid.beats, e["time"])
        index = int(np.floor(position + 1 / 24))
        if index < 0 or index >= len(grid.beats):
            continue
        fraction = position - index
        positions = np.array(grid.templates[index] + (1.0,))
        slot = int(np.argmin(np.abs(positions - fraction)))
        if slot == len(positions) - 1:
            index, slot = index + 1, 0
            if index >= len(grid.beats):
                continue
        key = (index, slot, e["instrument"])
        if key not in placed or e.get("confidence", 1) > placed[key].get("confidence", 1):
            placed[key] = {**e, "beat": index, "slot": slot, "division": len(grid.templates[index])}
    return sorted(placed.values(), key=lambda e: (e["beat"], e["slot"]))

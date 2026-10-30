"""End-to-end: audio (file or URL) -> events -> grid -> score IR -> MusicXML/PDF/MIDI.

Every stage writes a file in the output folder so an agent can inspect it,
change one thing (thresholds, the score text) and re-run only what follows.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from . import engrave, feedback, kit, patterns, paths, render, rhythm, sections
from .instruments import INSTRUMENT_CLASS
from .paths import CACHE, MODELS
from .score import from_grid, from_text, to_text


def fetch(source, downloads=paths.DOWNLOADS):
    """Local path as is; URLs through yt-dlp (the latest through uvx when uv is there). The
    best audio stream is downloaded and turned into WAV with ffmpeg here, so yt-dlp needs
    neither ffmpeg nor ffprobe of its own."""
    if Path(source).exists():
        return Path(source), Path(source).stem
    downloads.mkdir(parents=True, exist_ok=True)
    base = paths.yt_dlp() + ["--no-playlist"]
    info = subprocess.run(base + ["--print", "%(id)s\t%(title)s", "--skip-download", source], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip().splitlines()[-1]
    video_id, title = info.split("\t", 1)
    target = downloads / f"{video_id}.wav"
    if not target.is_file():
        subprocess.run(base + ["-q", "-f", "bestaudio/best", "-o", str(downloads / "%(id)s.source.%(ext)s"), source],
                       check=True)
        downloaded = next(downloads.glob(f"{video_id}.source.*"))
        subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-i", str(downloaded), "-vn", "-ar", "44100", str(target)],
                       check=True)
        downloaded.unlink()
    return target, title


def analyze(audio):
    from .engines import analyze as run_models
    return run_models(audio, CACHE, MODELS)


def transcribe(source, out_dir, title=None, thresholds=None, render_pdf=True, overrides=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    audio, default_title = fetch(source)
    models = analyze(audio)
    result = notate(models["stem_activations"], models["mix_activations"], models["beats"], models["drums"],
                    title or default_title, out, thresholds=thresholds, render_pdf=render_pdf, overrides=overrides)
    result.update(audio=str(audio), drums=models["drums"])
    (out / "report.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


RHYTHM_OVERRIDES = ("tempo_level", "beats_per_bar", "feel", "downbeat_shift")
OVERRIDES = RHYTHM_OVERRIDES + ("ghosts", "cross_sticks", "wireless_cross_sticks", "open_hihat", "parts")
PARTS = ("kick", "snare", "hi-hat", "toms", "cymbals")


def parse_parts(value):
    """'kick,snare' or a list -> sorted classes in kit order; 'all'/None -> None (every part)."""
    if value in (None, "", "all") or value == ["all"]:
        return None
    items = value.split(",") if isinstance(value, str) else list(value)
    items = [i.strip().lower().replace("hihat", "hi-hat").replace("toms", "toms") for i in items if i.strip()]
    aliases = {"bd": "kick", "bass": "kick", "sd": "snare", "hh": "hi-hat", "tom": "toms", "cymbal": "cymbals"}
    items = [aliases.get(i, i) for i in items]
    unknown = [i for i in items if i not in PARTS]
    if unknown:
        raise ValueError(f"unknown part(s) {unknown}; choose from {', '.join(PARTS)} or 'all'")
    chosen = [p for p in PARTS if p in items]
    return None if len(chosen) == len(PARTS) else chosen


def notate(stem_activations, mix_activations, beat_tracking, drums_wav, title, out, thresholds=None,
           render_pdf=True, normalize=True, crash_rule=True, overrides=None, ghosts=False, cross_sticks=True,
           open_hihat=False, section_marks=True):
    """Model outputs -> score files. Separate from the models so it can be re-run cheaply.

    overrides: agent corrections of rhythm decisions (see rhythm.build_grid) and the ghost /
    cross-stick / open hi-hat switches (see kit); None values are ignored, overrides win over
    the arguments. Ghost notes are off by default (parentheses on quiet snares made the
    scores harder to read than they helped).
    """
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None and k in OVERRIDES}
    ghosts = overrides.get("ghosts", ghosts)
    cross_sticks = overrides.get("cross_sticks", cross_sticks)
    open_hihat = overrides.get("open_hihat", open_hihat)
    rhythm_overrides = {k: v for k, v in overrides.items() if k in RHYTHM_OVERRIDES}
    parts = parse_parts(overrides.get("parts"))
    if "parts" in overrides:
        overrides["parts"] = parts  # normalized; None = every part
        if parts is None:
            overrides.pop("parts")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    events = kit.detect(stem_activations, mix_activations, thresholds)
    events = kit.assign_instruments(events, drums_wav, stem_activations, open_hihat=open_hihat)
    grid = rhythm.build_grid(events, beat_tracking, beat_tracking["duration_seconds"], **rhythm_overrides)
    corrections = feedback.load(out)
    structure = feedback.apply_structure(grid, corrections, events)  # the user's beats, bar lines, meters
    events = kit.drop_cymbal_retriggers(events, grid.beats)
    marks = {"open_hihat": sum(e["instrument"] == "HO" for e in events)}
    if cross_sticks:
        marks["cross_stick"] = kit.mark_cross_sticks(events, stem_activations, drums_wav, grid,
                                                     wireless=bool(overrides.get("wireless_cross_sticks")))
    marks["hand_drum_removed"] = kit.drop_hand_drums(events, drums_wav)
    marks["pitched_percussion_removed"] = kit.drop_pitched_percussion(events, drums_wav)
    marks["unconfirmed_kick_removed"] = kit.drop_unconfirmed_kicks(events, mix_activations)
    if ghosts:
        marks["ghost"] = kit.mark_ghosts(events, drums_wav, grid)
    (out / "events.json").write_text(json.dumps({"events": events}), encoding="utf-8")
    (out / "grid.json").write_text(json.dumps(_grid_json(grid)), encoding="utf-8")
    placed = rhythm.quantize(events, grid)
    score = from_grid(title, grid, placed)
    tempo_marks = feedback.apply_tempo(score, corrections)
    changes = {}
    if crash_rule:
        changes["crash_over_hihat"] = patterns.crash_over_hihat(score)
    if normalize:
        changes["normalized"] = patterns.normalize(score, grid, placed, kit.combine(stem_activations, mix_activations))
    if ghosts:
        changes["unified_marks"] = patterns.unify_marks(score)
    if section_marks:
        changes["sections"] = sections.label(score)
    if feedback.notes(corrections):
        # The user's corrections for this song come last: whatever the rules decided, a bar the
        # user fixed stays fixed (feedback.json, keyed by recording time).
        applied, skipped = feedback.apply(score, corrections)
        changes["feedback"] = {"applied": applied, "skipped": [e["time"] for e in skipped]}
    if structure or tempo_marks:
        changes.setdefault("feedback", {"applied": 0, "skipped": []}).update(
            structure=structure, tempo=tempo_marks, structure_skipped=len(grid.evidence.get("user_structure_skipped", [])))
    if parts:
        # Every decision above used the whole kit (tempo, bars, patterns, sections); only the
        # written parts are reduced, so kick/snare accuracy equals the full-kit score's.
        changes["parts_removed"] = _keep_parts(score, parts)
    (out / "changes.json").write_text(json.dumps(changes, default=str), encoding="utf-8")
    (out / "score.txt").write_text(to_text(score), encoding="utf-8")
    (out / "beat_times.json").write_text(json.dumps(score.beat_times), encoding="utf-8")
    result = engrave_outputs(score, out, render_pdf=render_pdf)
    result.update(grid=_grid_summary(grid), normalized_measures=len(changes.get("normalized", [])),
                  low_confidence_hits=sum(1 for h in placed if h.get("confidence", 1) < 0.35), overrides=overrides, marks=marks,
                  feedback=changes.get("feedback", {"applied": 0}),
                  sections=[{"measure": i + (0 if score.measures[0].pickup else 1), "label": name}
                            for i, name in changes.get("sections", [])])
    (out / "report.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def _keep_parts(score, parts):
    removed = 0
    for measure in score.measures:
        for beat in measure.beats:
            for slot in beat.slots:
                for key in [k for k in slot if INSTRUMENT_CLASS[k] not in parts]:
                    del slot[key]
                    removed += 1
    while score.measures and score.measures[-1].is_empty():
        score.measures.pop()
    if score.measures and score.measures[0].pickup and score.measures[0].is_empty():
        score.measures.pop(0)  # bars before the written parts come in stay: bar 1 is the start of the music
    score.parts = list(parts)
    return removed


def engrave_text(score_txt, out_dir=None):
    """Re-engrave after an agent or a person edited score.txt."""
    score_txt = Path(score_txt)
    out = Path(out_dir) if out_dir else score_txt.parent
    beat_times = json.loads((score_txt.parent / "beat_times.json").read_text(encoding="utf-8")) \
        if (score_txt.parent / "beat_times.json").is_file() else []
    score = from_text(score_txt.read_text(encoding="utf-8"), beat_times)
    return engrave_outputs(score, out)


def engrave_outputs(score, out, render_pdf=True):
    xml = out / "score.musicxml"
    text = engrave.to_musicxml(score)
    xml.write_text(text, encoding="utf-8")
    engrave.to_mxl(engrave.to_musicxml(score, for_editing=True), out / "score.mxl")  # Sibelius, Dorico, Finale
    engrave.to_midi(score, out / "score.mid")
    offset = score.beat_times[score.measures[0].start_beat] if score.measures and score.beat_times else 0.0
    first = 0 if score.measures and score.measures[0].pickup else 1
    result = {"title": score.title, "tempo": score.bpm, "time_signature": score.time_signature, "feel": score.feel,
              "measures": len(score.measures), "musicxml": str(xml), "mxl": str(out / "score.mxl"),
              "midi": str(out / "score.mid"),
              "audio_offset": round(float(offset), 4),
              "tempo_changes": [{"measure": index + first, "mark": mark}
                                for index, marks in sorted(engrave.tempo_changes(score).items()) for mark in marks]}
    if not render_pdf:
        return result
    try:
        pdf = render.to_pdf(xml, out / "score.pdf", pages_dir=out / "pages", mscz=out / "score.mscz")
        result["pdf"] = str(pdf)
        result["mscz"] = str(out / "score.mscz")
        result["pages"] = [str(p) for p in render.page_images(out / "pages")]
    except (FileNotFoundError, RuntimeError) as error:
        result["render_error"] = str(error)
    return result


def _grid_json(grid):
    return {"beats": [round(float(t), 4) for t in grid.beats], "beats_per_bar": grid.beats_per_bar,
            "first_downbeat": grid.first_downbeat, "feel": grid.feel, "swing": grid.swing,
            "templates": [[round(x, 4) for x in t] for t in grid.templates],
            "bpm": round(float(grid.bpm), 2), "tempo_level": grid.tempo_level, "evidence": grid.evidence,
            "overrides": grid.overrides,
            # Evaluation compatibility with phase 1 (beat/downbeat F).
            "beat_times_seconds": [float(t) for t in grid.beats],
            "bar_starts": grid.bar_lines(),
            "downbeat_times_seconds": [float(grid.beats[b]) for b in grid.bar_lines()]}


def _grid_summary(grid):
    return {"bpm": round(float(grid.bpm), 1), "beats_per_bar": grid.beats_per_bar, "feel": grid.feel,
            "tempo_level": grid.tempo_level, "first_downbeat": grid.first_downbeat,
            "short_bars": grid.evidence.get("short_bars", []),
            "swing": grid.swing, "triplet_beats": sum(len(t) == 3 for t in grid.templates), "evidence": grid.evidence}

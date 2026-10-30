"""drumcopy command line. Every command prints one JSON object (agent friendly).

  drumcopy transcribe <url|file> [-o DIR] [--title T] [--no-render] [overrides]
  drumcopy engrave DIR            re-engrave after editing DIR/score.txt
  drumcopy renotate DIR [--thresholds K,S,T,H,C] [--raw] [overrides] [--auto]
                                   redo notation from cached model outputs; overrides of the
                                   previous run are kept unless --auto
  overrides: --tempo-level {0.5,1,2} --beats-per-bar {3,4} --feel {straight,swing,swing16,compound}
             --downbeat-shift N --open-hihat/--no-open-hihat --ghosts/--no-ghosts --cross-sticks/--no-cross-sticks
  drumcopy inspect DIR [--measures 5-12]
  drumcopy player DIR             write DIR/player.html (audio + synced drum grid)
  drumcopy doctor [--fetch-models] check the installation (and download the model weights)
  drumcopy feedback DIR add|remove --bars 60-74 --beats 2,4 --instrument XS [--note T]
  drumcopy feedback DIR meter --bars 1-4 --beats-per-bar 6   bars 1-4 are 6/4
  drumcopy feedback DIR span (--bars 1-38 | --from 0.5 --to 85.0) [--count 24] [--signature 4/4]
                                   that stretch is COUNT bars of SIGNATURE (beats re-counted)
  drumcopy feedback DIR downbeat (--bars 12 --beats 3 | --time T)   a bar starts on that beat
  drumcopy feedback DIR tempo (--bars 4 | --time T) --mark rit.|accel.|a tempo|96|-
  drumcopy feedback DIR drop --time T [--kind span]   remove entries;  import FILE.json
                                   record what the user heard (kept with the song, applied on
                                   every renotate) and renotate; `feedback DIR list` shows it
  drumcopy tune [DIR] [--root R]   feedback screen in the browser (songs can be switched on it): listen with a click, tap
                                   beats, fix bar counts, meters, first beats and tempo marks
  drumcopy export DIR [DIR ...] [--format mxl|mscz|pdf|mid|musicxml] [--to FOLDER] [--name N ...] [--open]
                                   gather the scores under their song titles or the given names (default
                                   .mxl, which Sibelius, Dorico, Finale and MuseScore open), and show the
                                   folder; nothing re-transcribed
  drumcopy suggest DIR             strokes that sound like the user's confirmed corrections
  drumcopy check DIR               self-check: bars to ask the user about, with evidence
  drumcopy update [--check [--force]] [--auto on|off]
                                   newest GitHub release of the skill: check it (once a day), or
                                   update the skill folder and reinstall the engine; --auto sets
                                   whether the agent updates without asking
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from .paths import OUTPUTS


def _slug(text):
    # Letters of any script stay (Korean titles must not all become "untitled"); characters
    # that Windows or macOS do not allow in file names become "-".
    return re.sub(r"[^\w]+|_", "-", text.lower()).strip("-")[:60] or "untitled"


def cmd_transcribe(args):
    from .pipeline import fetch, transcribe

    audio, title = fetch(args.source)
    out = Path(args.out) if args.out else OUTPUTS / _slug(args.title or title)
    result = transcribe(audio, out, title=args.title or title, render_pdf=not args.no_render,
                        overrides=_overrides(args))
    from .player import build
    result["player"] = str(build(out))
    result["out_dir"] = str(out)
    return result


def cmd_engrave(args):
    from .pipeline import engrave_text
    from .player import build

    out = Path(args.dir)
    result = engrave_text(out / "score.txt", out)
    report = out / "report.json"
    if report.is_file():
        merged = {**json.loads(report.read_text(encoding="utf-8")), **result, "edited": True}
        report.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    result["player"] = str(build(out))
    return result


def cmd_renotate(args):
    from .engines import analyze
    from .pipeline import CACHE, MODELS, notate
    from .player import build

    out = Path(args.dir)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    models = analyze(report["audio"], CACHE, MODELS)
    thresholds = [float(x) for x in args.thresholds.split(",")] if args.thresholds else None
    # Earlier corrections stay in force (an agent fixing thresholds should not lose a tempo fix).
    overrides = {} if args.auto else dict(report.get("overrides") or {})
    overrides.update({k: v for k, v in _overrides(args).items() if v is not None})
    result = notate(models["stem_activations"], models["mix_activations"], models["beats"], models["drums"],
                    report.get("title", ""), out, thresholds=thresholds, normalize=not args.raw, crash_rule=not args.raw,
                    overrides=overrides, render_pdf=getattr(args, "render_pdf", True))
    result.update(audio=report["audio"], drums=models["drums"])
    (out / "report.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    result["player"] = str(build(out))
    return result


def _overrides(args):
    return {"tempo_level": args.tempo_level, "beats_per_bar": args.beats_per_bar, "feel": args.feel,
            "downbeat_shift": args.downbeat_shift, "ghosts": args.ghosts, "cross_sticks": args.cross_sticks,
            "wireless_cross_sticks": args.wireless_cross_sticks,
            "open_hihat": args.open_hihat,
            "parts": args.parts}


def _add_override_args(p):
    p.add_argument("--tempo-level", type=float, choices=(0.5, 1.0, 2.0),
                   help="notated beat relative to the tracker's beat: 0.5 halves the tempo, 2 doubles it")
    p.add_argument("--beats-per-bar", type=int, choices=(2, 3, 4, 5, 6, 7))
    p.add_argument("--feel", choices=("straight", "swing", "swing16", "compound"))
    p.add_argument("--downbeat-shift", type=int, help="move bar lines by N beats (+1 = one beat later)")
    p.add_argument("--ghosts", action=argparse.BooleanOptionalAction, default=None,
                   help="parenthesized ghost snares from loudness (default off)")
    p.add_argument("--cross-sticks", action=argparse.BooleanOptionalAction, default=None,
                   help="cross-sticks (side stick, XS) from the sound of snare/tom hits (default on)")
    p.add_argument("--wireless-cross-sticks", action=argparse.BooleanOptionalAction, default=None,
                   help="also read snare patterns whose wires do not ring as cross-sticks (default off: only for "
                        "songs known to have cross-stick sections; jazz ghost notes look the same)")
    p.add_argument("--parts", help="instruments to write, e.g. kick,snare (analysis still uses the whole kit); 'all' = full kit")
    p.add_argument("--open-hihat", action=argparse.BooleanOptionalAction, default=None,
                   help="open hi-hat marks from cymbal wash (default off: ~78%% precision)")


def cmd_inspect(args):
    from .score import from_text, to_text

    out = Path(args.dir)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    score = from_text((out / "score.txt").read_text(encoding="utf-8"))
    text = to_text(score)
    if args.measures:
        first, _, last = args.measures.partition("-")
        first, last = int(first), int(last or first)
        keep, lines, inside = [], text.splitlines(), True
        for line in lines:
            match = re.match(r"^m(\d+)", line)
            if match:
                inside = first <= int(match.group(1)) <= last
            elif not line.startswith("  "):
                inside = True
            if inside:
                keep.append(line)
        text = "\n".join(keep)
    keys = [m.key() for m in score.measures]
    changes = json.loads((out / "changes.json").read_text(encoding="utf-8")) if (out / "changes.json").is_file() else {}
    return {"title": report.get("title"), "tempo": report.get("tempo"), "time_signature": report.get("time_signature"),
            "feel": report.get("feel"), "measures": len(score.measures), "distinct_measures": len(set(keys)),
            "grid": {k: v for k, v in report.get("grid", {}).items() if k != "evidence"},
            "overrides": report.get("overrides", {}), "sections": report.get("sections", []),
            "marks": report.get("marks", {}),
            "grid_evidence": report.get("grid", {}).get("evidence"), "normalized": changes.get("normalized", []),
            "pages": report.get("pages", []), "pdf": report.get("pdf"), "score_text": text}


def cmd_player(args):
    from .player import build
    return {"player": str(build(args.dir))}


def cmd_feedback(args):
    """Record corrections for this song and renotate with them (seconds, cached models)."""
    from . import feedback
    from .score import from_text

    out = Path(args.dir)
    entries = feedback.load(out)
    if args.op == "list":
        return {"feedback": entries, "count": len(entries)}
    times = json.loads((out / "beat_times.json").read_text(encoding="utf-8"))
    score = from_text((out / "score.txt").read_text(encoding="utf-8"), times)
    note = args.note or ""
    new = []
    if args.op == "meter":
        if not (args.bars and args.beats_per_bar):
            raise ValueError("meter needs --bars (e.g. 1-4) and --beats-per-bar (e.g. 6)")
        new = [feedback.meter_entry(score, args.bars, args.beats_per_bar, note)]
    elif args.op == "span":
        if not (args.count or args.signature):
            raise ValueError("span needs --count (bars in that stretch) and/or --signature (e.g. 6/4, 12/8)")
        signature = args.signature or score.time_signature
        if args.bars:
            low, _, high = args.bars.partition("-")
            first_bar, last_bar = int(low), int(high or low)
            start = feedback.bar_time(score, first_bar)
            if args.count:  # the printed bars a-b are really COUNT bars: their beats are re-counted
                new = [feedback.span_entry(start, feedback.bar_time(score, last_bar, end=True), args.count, signature,
                                           note, bar=first_bar)]
            else:  # "bars 1-4 are 6/4": that many bars of the signature from bar a, on the tracked beats
                new = [feedback.span_entry(start, None, last_bar - first_bar + 1, signature, note, bar=first_bar)]
        elif args.start is not None and args.end is not None:
            new = [feedback.span_entry(args.start, args.end, args.count, signature, note)]
        else:
            raise ValueError("span needs --bars 1-38 or --from T --to T (seconds)")
    elif args.op == "downbeat":
        when = args.time if args.time is not None else feedback.position_time(score, int(args.bars), args.beats)
        new = [feedback.downbeat_entry(when, note)]
    elif args.op == "tempo":
        if args.mark is None:
            raise ValueError("tempo needs --mark (rit., accel., a tempo, a number, or - for none)")
        when = args.time if args.time is not None else feedback.bar_time(score, int(args.bars))
        new = [feedback.tempo_entry(when, args.mark, note)]
    elif args.op == "drop":
        if args.time is None:
            raise ValueError("drop needs --time (and --kind or --instrument to narrow it)")
        kept = feedback.drop(entries, args.time, args.kind or args.instrument)
        removed = len(entries) - len(kept)
        feedback.save(out, kept)
        result = _renotate_quietly(args.dir)
        result["feedback_removed"] = removed
        return result
    elif args.op == "import":
        if not args.file:
            raise ValueError("import needs --file FILE.json (a list of entries, e.g. saved from drumcopy tune)")
        new = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        if not (args.bars and args.instrument):
            raise ValueError("add/remove need --bars and --instrument (and --beats, default all)")
        positions = feedback.expand(score, args.bars, args.beats)
        new = feedback.entries_for(score, positions, args.instrument, "present" if args.op == "add" else "absent",
                                   note)
    feedback.save(out, feedback.merge(entries, new))
    result = _renotate_quietly(args.dir)
    result["feedback_added"] = new
    return result


def _renotate_quietly(directory, render_pdf=True):
    return cmd_renotate(argparse.Namespace(dir=directory, thresholds=None, raw=False, auto=False, render_pdf=render_pdf,
                                           **{k: None for k in _overrides_keys()}))


def _overrides_keys():
    return ("tempo_level", "beats_per_bar", "feel", "downbeat_shift", "ghosts", "cross_sticks",
            "wireless_cross_sticks", "open_hihat", "parts")


def cmd_tune(args):
    from .tune import serve
    return serve(args.dir, port=args.port, open_browser=not args.no_open, root=args.root)


EXPORT_FORMATS = ("mxl", "mscz", "pdf", "mid", "musicxml")


def _file_name(title):
    """A song title as a file name on Windows and macOS: letters of any script stay."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", title).strip().rstrip(".")
    return re.sub(r"\s+", " ", name)[:120] or "score"


def cmd_export(args):
    """The songs' scores in one format, copied under their titles into one folder. The score is
    taken as it stands (with the user's corrections); .mxl is wrapped from score.musicxml when
    missing, .mscz and .pdf need a rendered score (renotate or tune's "PDF 다시 만들기")."""
    from . import paths
    from .engrave import to_musicxml, to_mxl
    from .score import from_text

    target = Path(args.to).expanduser() if args.to else paths.EXPORTS
    target.mkdir(parents=True, exist_ok=True)
    names = list(getattr(args, "name", None) or [])
    if names and len(names) != len(args.dirs):
        raise ValueError(f"--name given {len(names)} times for {len(args.dirs)} song folders: one name per folder")
    written, missing = [], []
    for i, folder in enumerate(Path(d) for d in args.dirs):
        report = json.loads((folder / "report.json").read_text(encoding="utf-8")) if (folder / "report.json").is_file() else {}
        source = folder / ("score.mid" if args.format == "mid" else f"score.{args.format}")
        if args.format in ("mxl", "musicxml") and (folder / "score.txt").is_file():
            # The file for editing, from the score as it stands (the user's corrections are in it).
            times = json.loads((folder / "beat_times.json").read_text(encoding="utf-8"))
            text = to_musicxml(from_text((folder / "score.txt").read_text(encoding="utf-8"), times), for_editing=True)
            if args.format == "mxl":
                to_mxl(text, source)
            else:
                source = folder / "score-for-editing.musicxml"
                source.write_text(text, encoding="utf-8")
        elif args.format == "mxl" and (folder / "score.musicxml").is_file():
            to_mxl((folder / "score.musicxml").read_text(encoding="utf-8"), source)  # no score text: the MusicXML as it is
        if not source.is_file():
            missing.append(str(source))
            continue
        title = names[i] if names else (report.get("title") or folder.name)
        copy = target / f"{_file_name(title)}.{args.format}"
        shutil.copy2(source, copy)
        written.append(str(copy))
    if getattr(args, "open", False):
        _show_folder(target)
    return {"folder": str(target), "written": written, "missing": missing,
            "note": "open .mxl in Sibelius (File > Open/Import), Dorico, Finale or MuseScore; .sib cannot be written"}


def _show_folder(folder):
    """The folder in Finder, Explorer or the desktop's file manager."""
    import platform
    import subprocess
    system = platform.system()
    command = ["open", str(folder)] if system == "Darwin" else ["explorer", str(folder)] if system == "Windows" \
        else ["xdg-open", str(folder)]
    try:
        subprocess.run(command, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass  # no file manager (a server): the folder path is in the result


def cmd_suggest(args):
    from . import feedback
    return feedback.suggest(args.dir, limit=args.limit)


def cmd_check(args):
    from .check import run
    return run(args.dir, limit=args.limit)


def cmd_doctor(args):
    """What the engine needs, found or not; with --fetch-models the weights are downloaded."""
    import importlib
    import platform
    import shutil

    from . import paths, render
    checks = {"python": platform.python_version(), "platform": platform.platform(), "home": str(paths.HOME)}
    problems = []
    for module in ("numpy", "soundfile", "torch", "demucs", "adtof_pytorch", "beat_this"):
        try:
            importlib.import_module(module)
            checks[module] = "ok"
        except Exception as error:  # a broken install shows here, not later in a transcription
            checks[module] = f"missing: {error}"
            problems.append(module)
    for name, find in (("ffmpeg", paths.ffmpeg), ("musescore", render.musescore)):
        try:
            checks[name] = find()
        except FileNotFoundError as error:
            checks[name] = f"missing: {error}"
            problems.append(name if name == "ffmpeg" else "musescore (PDF only)")
    checks["yt_dlp"] = " ".join(paths.yt_dlp())
    try:
        paths.OUTPUTS.mkdir(parents=True, exist_ok=True)
        checks["writable"] = str(paths.OUTPUTS)
    except OSError as error:
        checks["writable"] = f"no: {error}"
        problems.append("home not writable")
    if args.fetch_models and "torch" not in problems:
        from .engines import BEAT_THIS_SHA256, BEAT_THIS_URLS, DEMUCS_SHA256, DEMUCS_URL, fetch_weights
        fetch_weights(DEMUCS_URL, DEMUCS_SHA256, paths.MODELS / "demucs/955717e8-8726e21a.th")
        fetch_weights(BEAT_THIS_URLS, BEAT_THIS_SHA256, paths.MODELS / "beat_this/final0.ckpt")
    checks["models"] = {name: (paths.MODELS / name).is_file() for name in
                        ("demucs/955717e8-8726e21a.th", "beat_this/final0.ckpt")}
    if not all(checks["models"].values()):
        problems.append("model weights (run doctor --fetch-models)")
    checks["ok"] = not [p for p in problems if "PDF only" not in p]
    checks["problems"] = problems
    return checks


def cmd_update(args):
    from . import update
    if args.auto:
        return update.set_auto(args.auto == "on")
    return update.check(force=args.force) if args.check else update.run()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="drumcopy", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("transcribe")
    p.add_argument("source")
    p.add_argument("-o", "--out")
    p.add_argument("--title")
    p.add_argument("--no-render", action="store_true")
    _add_override_args(p)
    p.set_defaults(func=cmd_transcribe)
    p = sub.add_parser("engrave")
    p.add_argument("dir")
    p.set_defaults(func=cmd_engrave)
    p = sub.add_parser("renotate")
    p.add_argument("dir")
    p.add_argument("--thresholds", help="kick,snare,toms,hihat,cymbals peak thresholds (default .22,.24,.32,.22,.30)")
    p.add_argument("--raw", action="store_true", help="no pattern normalization, no crash rule")
    _add_override_args(p)
    p.add_argument("--auto", action="store_true", help="drop all earlier overrides, decide everything from evidence")
    p.set_defaults(func=cmd_renotate)
    p = sub.add_parser("inspect")
    p.add_argument("dir")
    p.add_argument("--measures")
    p.set_defaults(func=cmd_inspect)
    p = sub.add_parser("player")
    p.add_argument("dir")
    p.set_defaults(func=cmd_player)
    p = sub.add_parser("feedback")
    p.add_argument("dir")
    p.add_argument("op", choices=("add", "remove", "meter", "span", "downbeat", "tempo", "drop", "import", "list"))
    p.add_argument("--bars", help="bar numbers as printed: 60-74 or 95,96")
    p.add_argument("--beats", default="all", help="2,4 or 1& or 3e ... (default all; downbeat: the beat)")
    p.add_argument("--instrument", help="BD, SD or XS (kick, snare, cross-stick)")
    p.add_argument("--beats-per-bar", type=int, help="for meter: beats in each of those bars (6 for 6/4)")
    p.add_argument("--from", dest="start", type=float, help="span: start (seconds), the first beat of a bar")
    p.add_argument("--to", dest="end", type=float, help="span: end (seconds), the first beat of the bar after it")
    p.add_argument("--count", type=int, help="span: number of bars in it (beats are re-counted)")
    p.add_argument("--signature", help="span: 4/4, 6/4, 3/4, 12/8, 6/8 ...")
    p.add_argument("--time", type=float, help="downbeat / tempo / drop: recording time (seconds)")
    p.add_argument("--mark", help="tempo: rit., accel., a tempo, poco rit., a number (96) or - (no mark)")
    p.add_argument("--kind", help="drop: only entries of this kind (span, tempo, downbeat, beats, meter)")
    p.add_argument("--file", help="import: JSON list of entries")
    p.add_argument("--note")
    p.set_defaults(func=cmd_feedback)
    p = sub.add_parser("tune")
    p.add_argument("dir", nargs="?", help="song folder (default: the most recently changed song; another can be chosen on the page)")
    p.add_argument("--root", help="folder of song folders to choose from (default: the song's parent, or the outputs folder)")
    p.add_argument("--port", type=int, default=0, help="default: a free port")
    p.add_argument("--no-open", action="store_true", help="do not open the browser")
    p.set_defaults(func=cmd_tune)
    p = sub.add_parser("export")
    p.add_argument("dirs", nargs="+", help="song folders")
    p.add_argument("--format", choices=EXPORT_FORMATS, default="mxl")
    p.add_argument("--to", help="folder to gather them in (default: <home>/work/exports)")
    p.add_argument("--name", action="append", help="file name for each folder, in order (default: the song title)")
    p.add_argument("--open", action="store_true", help="show the folder in Finder / Explorer afterwards")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("suggest")
    p.add_argument("dir")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_suggest)
    p = sub.add_parser("check")
    p.add_argument("dir")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("doctor")
    p.add_argument("--fetch-models", action="store_true", help="download the Demucs and Beat This! weights")
    p.set_defaults(func=cmd_doctor)
    p = sub.add_parser("update")
    p.add_argument("--check", action="store_true", help="only say whether a newer release exists")
    p.add_argument("--force", action="store_true", help="with --check: ask GitHub now, not the last answer")
    p.add_argument("--auto", choices=("on", "off"), help="update at the start of a request without asking")
    p.set_defaults(func=cmd_update)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # JSON with Korean titles, also on a Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    import contextlib
    try:
        with contextlib.redirect_stdout(sys.stderr):  # model libraries print progress
            result = args.func(args)
    except Exception as error:  # one JSON error object, never a bare traceback
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

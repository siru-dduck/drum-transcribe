"""MCP server exposing drumcopy to agents (stdio). Not used by the skill any more: the CLI does
the same without tool descriptions in every conversation (user decision, 2026-10-30).

Heavy work (download, separation, detection) runs in a child process started by
`transcribe_start`; poll it with `transcribe_status`. Everything else is fast and
runs in-process. Model libraries never write to this process's stdout, which
carries the MCP protocol.

Register with the engine's Python (macOS/Linux .../bin/python, Windows ...\Scripts\python.exe):
    Claude Code: claude mcp add drumcopy -- <python> -m drumcopy.mcp_server
    Codex / ChatGPT desktop (~/.codex/config.toml):
        [mcp_servers.drumcopy]
        command = "<python>"
        args = ["-m", "drumcopy.mcp_server"]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .paths import HOME, OUTPUTS

server = MCPServer(
    "drumcopy",
    instructions=(
        "Transcribe songs (YouTube URL or audio file) into standard drum notation. "
        "Typical flow: transcribe_start -> transcribe_status until done -> get_score and look at the "
        "page images -> deliver the PDF -> the user listens and says what is wrong -> add_feedback "
        "(kept per song) -> suggest_corrections for similar strokes -> ask the user -> repeat. "
        "The score text is the editable source of truth; see drumcopy.score for its format."
    ),
)

_jobs: dict[str, dict] = {}


def _cli(*args):
    return [sys.executable, "-m", "drumcopy.cli", *args]


def _run_job(job_id, command):
    job = _jobs[job_id]
    HOME.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="replace", cwd=HOME, env={**os.environ, "PYTHONUTF8": "1"})
    job["pid"] = process.pid
    stdout, stderr = process.communicate()
    job["finished"] = time.time()
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        result = {"error": "BadOutput", "message": stdout[-2000:], "stderr": stderr[-2000:]}
    job["status"] = "failed" if "error" in result else "done"
    job["result"] = result


def _start(command, label):
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"status": "running", "label": label, "started": time.time()}
    threading.Thread(target=_run_job, args=(job_id, command), daemon=True).start()
    return job_id


@server.tool()
def transcribe_start(source: str, title: str | None = None, out_dir: str | None = None,
                     parts: list[str] | None = None) -> dict:
    """Start transcribing a YouTube URL or a local audio file. Returns a job id.

    First run of a song takes about 1-3 minutes (download, drum separation, detection);
    later runs of the same audio reuse cached model outputs.
    parts: instruments to write, e.g. ["kick", "snare"] (choices: kick, snare, hi-hat, toms,
    cymbals). Tempo, bar lines and feel are still decided from the whole kit. Default: full kit.
    """
    args = ["transcribe", source]
    if parts:
        args += ["--parts", ",".join(parts)]
    if title:
        args += ["--title", title]
    if out_dir:
        args += ["-o", out_dir]
    return {"job_id": _start(_cli(*args), source), "status": "running"}


@server.tool()
def transcribe_status(job_id: str) -> dict:
    """Status of a transcription/renotation job; when done, includes out_dir, pdf, page images and player."""
    job = _jobs.get(job_id)
    if job is None:
        return {"error": "unknown job id"}
    elapsed = round((job.get("finished") or time.time()) - job["started"], 1)
    return {"status": job["status"], "elapsed_seconds": elapsed, "result": job.get("result")}


@server.tool()
def get_score(out_dir: str, measures: str | None = None) -> dict:
    """Score text (editable), tempo/meter evidence, normalization log and page image paths.

    `measures` limits the text to a range like "9-16". Look at the page PNGs to review engraving.
    """
    from .cli import cmd_inspect
    return cmd_inspect(type("Args", (), {"dir": out_dir, "measures": measures}))


@server.tool()
def update_score(out_dir: str, score_text: str) -> dict:
    """Replace the score text and re-engrave MusicXML, PDF, page images and player.

    The text is validated first; on a format error nothing is written.
    """
    from .cli import cmd_engrave
    from .score import from_text, to_text

    folder = Path(out_dir)
    try:
        parsed = from_text(score_text)
    except (ValueError, KeyError) as error:
        return {"error": "InvalidScoreText", "message": str(error)}
    if not parsed.measures:
        return {"error": "InvalidScoreText", "message": "no measures"}
    previous = folder / "score.txt"
    backup = folder / f"score.{time.strftime('%Y%m%d-%H%M%S')}.txt"
    if previous.is_file():
        backup.write_text(previous.read_text(encoding="utf-8"), encoding="utf-8")
    previous.write_text(to_text(parsed), encoding="utf-8")
    result = cmd_engrave(type("Args", (), {"dir": out_dir}))
    result["backup"] = str(backup)
    return result


@server.tool()
def renotate(out_dir: str, thresholds: list[float] | None = None, raw: bool = False,
             tempo_level: float | None = None, beats_per_bar: int | None = None, feel: str | None = None,
             downbeat_shift: int | None = None, ghosts: bool | None = None, cross_sticks: bool | None = None,
             wireless_cross_sticks: bool | None = None, open_hihat: bool | None = None, parts: list[str] | None = None, auto: bool = False) -> dict:
    """Redo notation from cached model outputs (seconds, no re-separation). Returns a job id.

    thresholds: peak thresholds [kick, snare, toms, hihat, cymbals], default [.22,.24,.32,.22,.30];
    lower finds more (quieter) hits, higher removes false hits. raw=True disables pattern
    normalization and the crash-over-hi-hat rule.
    Rhythm overrides (use when the page shows a wrong decision; see grid evidence in get_score):
    tempo_level 0.5 halves / 2 doubles the notated tempo (1 = tracker's level);
    beats_per_bar 3 or 4; feel straight | swing | swing16 | compound (12/8);
    downbeat_shift N moves every bar line N beats later (negative = earlier), relative to the
    automatic choice (not cumulative).
    ghosts (default off) writes quiet snares as ghost notes; cross_sticks (default on) writes
    side-stick clicks as XS on the snare space; wireless_cross_sticks (default off) also reads
    snare patterns whose wires do not ring as cross-sticks - use it only when the user says a
    section is cross-stick but it is written as snare; open_hihat (default off, about 78%
    precision) marks open hi-hats - turn it on for songs with audible open hi-hat barks.
    parts: instruments to write, e.g. ["kick", "snare"]; ["all"] returns to the full kit.
    Overrides persist across renotate calls until auto=True.
    Overwrites score.txt (manual edits are lost).
    """
    args = ["renotate", out_dir]
    if tempo_level is not None:
        args += ["--tempo-level", str(float(tempo_level))]
    if beats_per_bar is not None:
        args += ["--beats-per-bar", str(beats_per_bar)]
    if feel:
        args += ["--feel", feel]
    if downbeat_shift is not None:
        args += [f"--downbeat-shift={int(downbeat_shift)}"]
    if ghosts is not None:
        args.append("--ghosts" if ghosts else "--no-ghosts")
    if cross_sticks is not None:
        args.append("--cross-sticks" if cross_sticks else "--no-cross-sticks")
    if wireless_cross_sticks is not None:
        args.append("--wireless-cross-sticks" if wireless_cross_sticks else "--no-wireless-cross-sticks")
    if open_hihat is not None:
        args.append("--open-hihat" if open_hihat else "--no-open-hihat")
    if parts:
        args += ["--parts", ",".join(parts)]
    if auto:
        args.append("--auto")
    if thresholds:
        args += ["--thresholds", ",".join(str(t) for t in thresholds)]
    if raw:
        args.append("--raw")
    return {"job_id": _start(_cli(*args), f"renotate {out_dir}"), "status": "running"}


@server.tool()
def add_feedback(out_dir: str, bars: str, instrument: str, beats: str = "all", action: str = "present",
                 note: str = "") -> dict:
    """Record what the user heard for this song, then renotate with it (a job id; seconds).

    bars as printed ("60-74", "95,96"), beats "2,4" / "1&" / "3e" / "all", instrument BD
    (kick), SD (snare) or XS (cross-stick), action "present" or "absent". XS present at a
    stroke also removes SD there (and SD present removes XS). Corrections are kept in
    <out_dir>/feedback.json by recording time and applied last on every renotate, so a bar
    the user fixed stays fixed. Ask the user before recording what they did not say.
    """
    op = "add" if action == "present" else "remove"
    args = ["feedback", out_dir, op, "--bars", bars, "--beats", beats, "--instrument", instrument]
    if note:
        args += ["--note", note]
    return {"job_id": _start(_cli(*args), f"feedback {out_dir}"), "status": "running"}


@server.tool()
def suggest_corrections(out_dir: str, limit: int = 20) -> dict:
    """Strokes of this song that sound like the user's confirmed corrections but are written
    otherwise (snare <-> cross-stick, missed cross-sticks), most certain first, with bar and
    beat. Learned from this song's feedback only. Ask the user to listen to these; record what
    they confirm with add_feedback. Not corrections by themselves."""
    from .feedback import suggest
    return suggest(out_dir, limit=limit)


@server.tool()
def list_transcriptions() -> dict:
    """Previous transcriptions under work/outputs with their title, tempo and PDF."""
    items = []
    for report in sorted(OUTPUTS.glob("*/report.json")):
        data = json.loads(report.read_text(encoding="utf-8"))
        items.append({"out_dir": str(report.parent), "title": data.get("title"), "tempo": data.get("tempo"),
                      "time_signature": data.get("time_signature"), "pdf": data.get("pdf")})
    return {"transcriptions": items}


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()

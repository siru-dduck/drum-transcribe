"""Feedback screen for a song's structure: `drumcopy tune DIR`.

Where there is no score to check against, the user's ears are the reference. A local page
(served to this machine only) plays the recording with a click on the beat grid the score
is written on, marks where the engine is unsure (no drums to count by, beats that jump, the
self-check's findings) and takes corrections the way a rhythm game takes input: tapping
beats and bar starts along the music, saying how many bars a stretch has and in which
meter, moving a bar's first beat or a beat by milliseconds, setting tempo marks. Every
correction becomes a feedback.json entry (see feedback.py) and is applied by a renotate
at once; the engine's rules do not change.
"""
from __future__ import annotations

import bisect
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np

from . import feedback

AUDIO_RATE = 22050                     # mono 16-bit for the page: a 4-minute song is ~11 MB
PAGE = Path(__file__).with_name("tune.html")
CHECKED = ("pulse", "offbeat", "unsteady", "shortbar")
QUESTIONS = {
    "nodrums": "드럼이 없는 구간입니다. 박과 마디를 다른 악기 소리로 추정했으니, 클릭을 켜고 들으며 "
               "마디 수와 첫 박이 맞는지 확인해 주세요.",
    "pulse": "드럼이 적힌 박과 다른 주기로 치는 것 같습니다. 박이 맞나요?",
    "offbeat": "킥과 스네어가 마디마다 뒷박에 있습니다. 박 격자가 반 박 밀렸을 수 있습니다.",
    "unsteady": "박 길이가 갑자기 바뀝니다(필인이나 변속). 박과 마디가 맞나요?",
    "shortbar": "짧은 마디가 있습니다. 실제로 짧은 마디인가요, 마디 경계가 틀렸나요?",
}


REQUIRED = ("score.txt", "beat_times.json", "report.json")


def songs(root):
    """Transcribed songs in a folder (one sub-folder each), most recently changed first."""
    found = []
    for folder in Path(root).iterdir() if Path(root).is_dir() else []:
        if folder.is_dir() and all((folder / name).is_file() for name in REQUIRED):
            report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            changed = max((folder / n).stat().st_mtime for n in ("score.txt", "feedback.json") if (folder / n).is_file())
            found.append({"song": folder.name, "title": report.get("title", folder.name), "measures": report.get("measures"),
                          "changed": changed, "corrections": len(feedback.load(folder))})
    return sorted(found, key=lambda s: -s["changed"])


def serve(out_dir=None, port=0, open_browser=True, root=None):
    """The screen for one song folder; another song (or another folder of songs) can be chosen
    on the page. Without a folder: the most recently changed song under the outputs folder."""
    from .paths import OUTPUTS
    if out_dir:
        out = Path(out_dir).resolve()
        root = Path(root).resolve() if root else out.parent
    else:
        root = Path(root or OUTPUTS).resolve()
        listed = songs(root)
        if not listed:
            raise FileNotFoundError(f"no transcribed song in {root}: transcribe one first")
        out = root / listed[0]["song"]
    for name in REQUIRED:
        if not (out / name).is_file():
            raise FileNotFoundError(f"{out / name}: transcribe the song first")
    where = {"out": out, "root": root}
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(where, threading.Lock()))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(json.dumps({"url": url, "dir": str(out), "root": str(root), "stop": "Ctrl+C"}, ensure_ascii=False),
          file=sys.__stdout__, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"stopped": True, "url": url, "last_song": str(where["out"])}


def state(out):
    """Everything the page draws: beats, bars, tempo marks, strokes, the user's entries, flags."""
    from . import engrave
    from .score import from_text, signature_text

    out = Path(out)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    times = json.loads((out / "beat_times.json").read_text(encoding="utf-8"))
    score = from_text((out / "score.txt").read_text(encoding="utf-8"), times)
    events = json.loads((out / "events.json").read_text(encoding="utf-8"))["events"] \
        if (out / "events.json").is_file() else []
    entries = feedback.load(out)
    opening, marks = engrave.tempo_marks(score)
    first = 0 if score.measures and score.measures[0].pickup else 1
    last = len(times) - 1
    bars = []
    for i, measure in enumerate(score.measures):
        k = measure.start_beat
        bars.append({"n": i + first, "k": k, "beats": len(measure.beats), "t": times[min(k, last)],
                     "end": times[min(k + len(measure.beats), last)],
                     "sig": signature_text(len(measure.beats), score.is_compound(measure)),
                     "marks": [str(m) if isinstance(m, int) else m for m in marks.get(i, [])],
                     "user_tempo": measure.tempo is not None, "empty": measure.is_empty(), "pickup": measure.pickup})
    opening_bar = next((b for b in bars if not b["pickup"]), None)
    if opening_bar is not None:
        opening_bar["marks"] = [str(opening)] + opening_bar["marks"]
    strokes = [{"t": round(e["time"], 3), "c": e["class"], "i": e["instrument"]} for e in events]
    from .check import _written
    # What the score says (the user's corrections included), for the drum track; the raw
    # detections (strokes) are kept for snapping dragged beats onto hits.
    notes = [{"t": round(float(t), 3), "k": key} for t, key, _ in _written(score, times)]
    audio = {"mix": bool(report.get("audio")) and Path(report["audio"]).is_file(),
             "drums": bool(report.get("drums")) and Path(str(report.get("drums"))).is_file()}
    pages = sorted(p.name for p in (out / "pages").glob("page-*.png")) if (out / "pages").is_dir() else []
    pages.sort(key=lambda name: int("".join(c for c in name if c.isdigit()) or 0))
    return {"title": report.get("title", out.name), "song": out.name, "root": str(out.parent),
            "beats": times, "bars": bars, "strokes": strokes, "notes": notes,
            "entries": entries, "flags": flags(out, score, times, events, entries), "audio": audio,
            "pages": pages, "pdf": (out / "score.pdf").is_file(), "compound": score.feel == "compound",
            "stamp": int(time.time())}


def flags(out, score, times, events, entries):
    """Stretches worth a listen: no drums to count by, and the self-check's rhythm findings.
    A stretch the user already gave the structure of is not flagged again."""
    first = 0 if score.measures and score.measures[0].pickup else 1
    last = len(times) - 1
    span = lambda m: (times[min(m.start_beat, last)], times[min(m.start_beat + len(m.beats), last)])
    fixed = [(e["time"], e.get("end") or e["time"]) for e in feedback.structure(entries)]
    covered = lambda a, b: any(x - 0.05 <= a and b <= y + 0.05 for x, y in fixed)
    found = []
    # Kick, snare and hi-hat keep time; a lone cymbal (often a swell, or a bell leaking into
    # the drum stem) does not give the beat.
    timekeeping = sorted(e["time"] for e in events if e["class"] in ("kick", "snare", "hi-hat"))
    run = []
    for i, measure in enumerate(score.measures + [None]):
        drumless = False
        if measure is not None and not measure.pickup:
            a, b = span(measure)
            drumless = bisect.bisect_left(timekeeping, b) - bisect.bisect_left(timekeeping, a) < 2 \
                and not covered(a, b)  # bars the user already gave the structure of are settled
        if drumless:
            run.append(i)
            continue
        if len(run) >= 2:
            a, b = span(score.measures[run[0]])[0], span(score.measures[run[-1]])[1]
            if not covered(a, b):
                found.append({"kind": "nodrums", "from": run[0] + first, "to": run[-1] + first,
                              "t": round(a, 3), "end": round(b, 3), "text": QUESTIONS["nodrums"]})
        run = []
    try:
        from .check import run as self_check
        issues = self_check(out, limit=50)["issues"]
    except Exception:  # an incomplete output folder: the flags above still help
        issues = []
    for issue in issues:
        if issue["kind"] not in CHECKED:
            continue
        low, _, high = str(issue["bars"]).partition("-")
        a_bar, b_bar = int(low), int(high or low)
        if not (0 <= a_bar - first < len(score.measures) and 0 <= b_bar - first < len(score.measures)):
            continue
        a, b = span(score.measures[a_bar - first])[0], span(score.measures[b_bar - first])[1]
        if covered(a, b):
            continue
        found.append({"kind": issue["kind"], "from": a_bar, "to": b_bar, "t": round(a, 3), "end": round(b, 3),
                      "text": QUESTIONS[issue["kind"]], "evidence": issue.get("evidence", "")})
    return sorted(found, key=lambda f: f["t"])


def entries_from(items, source="user (tune)"):
    """The page's corrections, rebuilt through feedback's constructors (checked, rounded)."""
    built = []
    for item in items:
        kind, note = item.get("kind"), item.get("note", "")
        if kind == "span":
            entry = feedback.span_entry(item["time"], item["end"], item.get("bars"), item["signature"], note)
        elif kind == "beats":
            entry = feedback.beats_entry(item["times"], item.get("downbeats", []), note)
        elif kind == "downbeat":
            entry = feedback.downbeat_entry(item["time"], note, item.get("from"))
        elif kind == "move":
            entry = feedback.move_entry(item["time"], item["to"], note)
        elif kind == "shift":
            entry = feedback.shift_entry(item["time"], item["end"], item["ms"], note)
        elif kind == "tempo":
            entry = feedback.tempo_entry(item["time"], item["mark"], note)
        else:
            raise ValueError(f"unknown correction kind {kind!r}")
        entry["source"] = source
        built.append(entry)
    return built


def apply(out, add=(), remove=()):
    """Save the corrections and renotate (no PDF: seconds). Returns the new state."""
    from .cli import _renotate_quietly

    entries = feedback.load(out)
    for item in remove:
        entries = feedback.drop(entries, item["time"], item.get("kind") or item.get("instrument"))
    entries = feedback.merge(entries, entries_from(add))
    feedback.save(out, entries)
    _renotate_quietly(str(out), render_pdf=False)
    return state(out)


def render_pages(out):
    from . import render
    render.to_pdf(out / "score.musicxml", out / "score.pdf", pages_dir=out / "pages", mscz=out / "score.mscz")
    return {"pages": [p.name for p in render.page_images(out / "pages")], "stamp": int(time.time())}


def audio_file(out, which):
    """The recording (or the drum stem) as mono 16-bit at AUDIO_RATE, made once per song."""
    import soundfile as sf
    from scipy.signal import resample_poly

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    source = Path(str(report.get("audio" if which == "mix" else "drums") or ""))
    if not source.is_file():
        raise FileNotFoundError(f"no {which} audio for this song")
    target = out / ".tune" / f"{which}.wav"
    if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    audio, rate = sf.read(str(source), always_2d=True)
    mono = audio.mean(axis=1)
    if rate != AUDIO_RATE:
        from math import gcd
        g = gcd(int(rate), AUDIO_RATE)
        mono = resample_poly(mono, AUDIO_RATE // g, int(rate) // g)
    target.parent.mkdir(exist_ok=True)
    sf.write(str(target), np.clip(mono, -1, 1), AUDIO_RATE, subtype="PCM_16")
    return target


TYPES = {".png": "image/png", ".pdf": "application/pdf", ".wav": "audio/wav", ".html": "text/html; charset=utf-8",
         ".mxl": "application/vnd.recordare.musicxml", ".mscz": "application/octet-stream", ".mid": "audio/midi"}
DOWNLOADS = ("/score.mxl", "/score.mscz", "/score.mid")


def _handler(where, lock):
    """where: {"out": the song folder on screen, "root": the folder its songs are listed from}."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet: the terminal shows the JSON lines only
            pass

        def _send(self, status, body, kind="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path):
            if not path.is_file():
                return self._send(404, {"error": "not found"})
            self._send(200, path.read_bytes(), TYPES.get(path.suffix, "application/octet-stream"))

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/":
                    return self._send(200, PAGE.read_bytes(), TYPES[".html"])
                if path == "/api/state":
                    return self._send(200, state(where["out"]))
                if path in ("/audio/mix", "/audio/drums"):
                    with lock:
                        target = audio_file(where["out"], path.rsplit("/", 1)[1])
                    return self._file(target)
                if path.startswith("/pages/") and "/" not in path[len("/pages/"):]:
                    return self._file(where["out"] / "pages" / path[len("/pages/"):])
                if path == "/api/songs":
                    return self._send(200, {"root": str(where["root"]), "song": where["out"].name, "songs": songs(where["root"])})
                if path == "/score.pdf":
                    return self._file(where["out"] / "score.pdf")
                if path in DOWNLOADS:
                    return self._file(where["out"] / path[1:])
                return self._send(404, {"error": "not found"})
            except Exception as error:
                return self._send(500, {"error": type(error).__name__, "message": str(error)})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                with lock:
                    if path == "/api/apply":
                        return self._send(200, apply(where["out"], body.get("add", []), body.get("remove", [])))
                    if path == "/api/render":
                        return self._send(200, render_pages(where["out"]))
                    if path == "/api/open":
                        # Another folder of songs (a local path the user typed), and/or a song in it.
                        root = Path(body["root"]).expanduser().resolve() if body.get("root") else where["root"]
                        if not root.is_dir():
                            raise ValueError(f"폴더가 없습니다: {root}")
                        listed = songs(root)
                        name = body.get("song") or (listed[0]["song"] if listed else None)
                        if not name or not all((root / name / n).is_file() for n in REQUIRED):
                            raise ValueError(f"이 폴더에 채보한 곡이 없습니다: {root}" if not name else f"채보한 곡이 아닙니다: {root / name}")
                        where["root"], where["out"] = root, root / name
                        return self._send(200, state(where["out"]))
                return self._send(404, {"error": "not found"})
            except (ValueError, KeyError) as error:
                return self._send(400, {"error": type(error).__name__, "message": str(error)})
            except Exception as error:
                return self._send(500, {"error": type(error).__name__, "message": str(error)})

    return Handler

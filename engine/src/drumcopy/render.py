"""MusicXML -> PDF (MuseScore CLI) and page images for visual review.

MuseScore first imports the MusicXML into its own format, which is patched before the
PDF export: MuseScore 4.6 imports parenthesized (ghost) noteheads as two symbols
stacked on the notehead, so only the tips of the parentheses show, and it does not wrap
a title that is wider than the page.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .paths import LOCKS, TOOLS

STYLE = Path(__file__).with_name("drumcopy.mss")  # last system is not stretched unless nearly full
CANDIDATES = (
    TOOLS / "MuseScore 4.app/Contents/MacOS/mscore",
    Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore"),
    *(Path(os.environ.get(root, "")) / "MuseScore 4/bin/MuseScore4.exe"
      for root in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA") if os.environ.get(root)),
)


def musescore():
    override = os.environ.get("DRUMCOPY_MUSESCORE")
    if override:
        return override
    for candidate in CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    for name in ("mscore", "musescore", "mscore4", "MuseScore4"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError("MuseScore 4 not found: install it (Windows: winget install -e --id Musescore.Musescore) "
                            "or set DRUMCOPY_MUSESCORE to its executable")


@contextmanager
def _lock():
    """One MuseScore at a time (it crashes when two exports run together)."""
    path = LOCKS / "musescore.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:  # LK_LOCK gives up after 10 s; keep waiting
                    continue
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _mscore(source, target, options=()):
    """MuseScore occasionally aborts (SIGABRT) on export; it is retried. A PNG target is
    written one file per page (page.png -> page-1.png, page-2.png, ...)."""
    command = [musescore(), "-S", str(STYLE), *options, "-o", str(target), str(source)]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("QT_", "QML"))}
    written = Path(target).with_name(Path(target).stem + "-1.png") if str(target).endswith(".png") else Path(target)
    for attempt in range(3):
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=180)
        if result.returncode == 0 and written.is_file():
            return
        if result.returncode != -6:
            break
    raise RuntimeError(f"MuseScore export failed ({result.returncode}): {result.stderr[-800:]}")


def place_parentheses(mscx):
    """Move the imported parenthesis symbols to the sides of their notehead (offsets in spaces)."""
    mscx = re.sub(r"(<name>noteheadParenthesisLeft</name>)", r'\1<offset x="-0.8" y="0"/>', mscx)
    return re.sub(r"(<name>noteheadParenthesisRight</name>)", r'\1<offset x="1.45" y="0"/>', mscx)


TITLE_SIZE = 22.0       # MuseScore's title font size (pt)
TITLE_MIN_SIZE = 12.0
LINE_WIDTH = 510.0      # A4 width inside the default margins (pt)


def _text_width(text):
    """Rough width in ems: Hangul/CJK 1, Latin capitals .65, lower case and digits .5, the rest .3."""
    width = 0.0
    for char in html.unescape(text):
        if ord(char) >= 0x1100:
            width += 1.0
        elif char.isupper():
            width += 0.65
        elif char.isalnum():
            width += 0.5
        else:
            width += 0.3
    return width


def title_lines(title):
    """A title as it fits the page: one line, or two split at the space that balances them, and
    the font size (points) that fits."""
    if _text_width(title) * TITLE_SIZE <= 0.95 * LINE_WIDTH:
        return [title], TITLE_SIZE
    spaces = [i for i, char in enumerate(title) if char == " "]
    if not spaces:
        return [title], TITLE_SIZE
    cut = min(spaces, key=lambda i: max(_text_width(title[:i]), _text_width(title[i + 1:])))
    lines = [title[:cut], title[cut + 1:]]
    return lines, max(TITLE_MIN_SIZE, min(TITLE_SIZE, 0.95 * LINE_WIDTH / max(_text_width(line) for line in lines)))


def fit_title(mscx):
    """MuseScore does not wrap a title: a long one runs off the page. It is split at the space
    that best balances the two lines, and set smaller if it still does not fit."""
    match = re.search(r"(<style>title</style>\s*<text>)(.*?)(</text>)", mscx, re.S)
    if not match or "\n" in match.group(2):
        return mscx
    title = match.group(2)
    if _text_width(title) * TITLE_SIZE <= 0.95 * LINE_WIDTH:
        return mscx
    spaces = [i for i, char in enumerate(title) if char == " "]
    if not spaces:
        return mscx
    cut = min(spaces, key=lambda i: max(_text_width(title[:i]), _text_width(title[i + 1:])))
    lines = [title[:cut], title[cut + 1:]]
    size = max(TITLE_MIN_SIZE, min(TITLE_SIZE, 0.95 * LINE_WIDTH / max(_text_width(line) for line in lines)))
    text = f'<font size="{size:.0f}"/>' + "\n".join(lines)
    return mscx[:match.start(2)] + text + mscx[match.end(2):]


def to_pdf(musicxml, pdf, pages_dir=None, dpi=110, mscz=None):
    """MusicXML -> PDF through MuseScore, and the pages as PNG images into pages_dir
    (page-1.png, ...) from the same engraving: what the PDF shows, for an agent to look at.
    mscz: also the MuseScore file of that engraving (title fitted, parentheses placed)."""
    pdf = Path(pdf).resolve()
    with _lock(), tempfile.TemporaryDirectory() as folder:
        mscx = Path(folder) / "score.mscx"
        _mscore(Path(musicxml).resolve(), mscx)
        mscx.write_text(fit_title(place_parentheses(mscx.read_text(encoding="utf-8"))), encoding="utf-8")
        _mscore(mscx, pdf)
        if mscz is not None:
            _mscore(mscx, Path(mscz).resolve())
        if pages_dir is not None:
            pages_dir = Path(pages_dir).resolve()
            pages_dir.mkdir(parents=True, exist_ok=True)
            for old in pages_dir.glob("page-*.png"):
                old.unlink()  # a shorter score must not keep the last pages of a longer one
            _mscore(mscx, pages_dir / "page.png", ("-r", str(dpi)))
    return pdf


def page_images(pages_dir):
    """page-1.png, page-2.png, ... in page order."""
    return sorted(Path(pages_dir).glob("page-*.png"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))

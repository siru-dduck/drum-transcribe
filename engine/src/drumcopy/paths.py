"""Where drumcopy keeps its data, and how it finds the external programs it runs.

In the development checkout (editable install) everything stays under the repository, as
before. An installed copy (the skill bundle, any OS) uses DRUMCOPY_HOME, by default
~/.drumcopy: model weights, the model cache, downloads, outputs and locks live there, so
the skill folder itself can stay read-only.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]


def home():
    if os.environ.get("DRUMCOPY_HOME"):
        return Path(os.environ["DRUMCOPY_HOME"]).expanduser()
    if (_CHECKOUT / "pyproject.toml").is_file() and (_CHECKOUT / "src/drumcopy").is_dir():
        return _CHECKOUT  # development checkout
    return Path.home() / ".drumcopy"


HOME = home()
CACHE = HOME / "work/cache/engines"
MODELS = HOME / "work/models"
OUTPUTS = HOME / "work/outputs"
EXPORTS = HOME / "work/exports"   # files gathered for other notation programs (drumcopy export)
DOWNLOADS = HOME / "data/downloads"
LOCKS = HOME / "work/locks"
TOOLS = HOME / "work/tools"


def ffmpeg():
    """ffmpeg on PATH, else the copy shipped with the imageio-ffmpeg package (installed by the
    skill's setup, so Windows needs no separate ffmpeg)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as error:
        raise FileNotFoundError("ffmpeg not found: install it or `pip install imageio-ffmpeg`") from error


def yt_dlp():
    """The latest yt-dlp through uvx when uv is there (YouTube changes often), else the copy
    installed next to drumcopy."""
    if shutil.which("uvx"):
        return ["uvx", "--from", "yt-dlp[default]@latest", "yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]

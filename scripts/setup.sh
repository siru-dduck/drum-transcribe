#!/bin/sh
# drumcopy engine setup for macOS / Linux. Python is not needed beforehand: uv installs it.
#   sh scripts/setup.sh [--no-musescore]
# Installs into $DRUMCOPY_HOME (default ~/.drumcopy): Python 3.11, the engine (PyTorch, Demucs,
# ADTOF, Beat This!), the model weights and, on macOS with Homebrew, MuseScore 4 for the PDF.
# Needs internet and about 3 GB. Prints the `drumcopy doctor` report at the end.
set -e
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="$SKILL/engine"
HOME_DIR="${DRUMCOPY_HOME:-$HOME/.drumcopy}"
VENV="$HOME_DIR/venv"
PY="$VENV/bin/python"
[ -f "$ENGINE/pyproject.toml" ] || { echo "engine folder not found next to this script: $ENGINE" >&2; exit 1; }
mkdir -p "$HOME_DIR"

echo "[1/5] uv"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
fi

echo "[2/5] Python 3.11 and the virtual environment ($VENV)"
uv python install 3.11
[ -x "$PY" ] || uv venv --python 3.11 "$VENV"

echo "[3/5] engine packages (PyTorch, Demucs, ADTOF, Beat This!)"
# ADTOF-pytorch (drum detection) comes from its author's repository, at the commit drumcopy was tested with.
ADTOF="adtof-pytorch @ https://github.com/xavriley/ADTOF-pytorch/archive/85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9.zip"
# --reinstall-package: after an update the engine folder changed but may keep its path.
uv pip install --python "$PY" --reinstall-package drumcopy "drumcopy[engine] @ file://$ENGINE" "$ADTOF" "$ENGINE/vendor/beat_this" \
    yt-dlp imageio-ffmpeg

echo "[4/5] MuseScore 4 (PDF)"
if [ "$1" != "--no-musescore" ] && [ -z "$DRUMCOPY_MUSESCORE" ] && ! command -v mscore >/dev/null 2>&1 \
        && [ ! -x "/Applications/MuseScore 4.app/Contents/MacOS/mscore" ]; then
    if command -v brew >/dev/null 2>&1; then
        brew install --cask musescore
    else
        echo "install MuseScore 4 from https://musescore.org (PDF output needs it)"
    fi
fi

echo "[5/5] model weights and check"
"$PY" -m drumcopy.cli doctor --fetch-models

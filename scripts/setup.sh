#!/bin/sh
# drumcopy engine setup for macOS / Linux. Python is not needed beforehand: uv installs it.
#   sh scripts/setup.sh [--no-musescore]
# Installs into $DRUMCOPY_HOME (default ~/.drumcopy): uv, Python 3.11, the engine (PyTorch, Demucs,
# ADTOF, Beat This!), the model weights and, on macOS with Homebrew, MuseScore 4 for the PDF.
# Needs internet and about 3 GB. Prints the `drumcopy doctor` report at the end.
set -e
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="$SKILL/engine"
HOME_DIR="${DRUMCOPY_HOME:-$HOME/.drumcopy}"
VENV="$HOME_DIR/venv"
PYTHONS="$HOME_DIR/python"
PY="$VENV/bin/python"
[ -f "$ENGINE/pyproject.toml" ] || { echo "engine folder not found next to this script: $ENGINE" >&2; exit 1; }
mkdir -p "$HOME_DIR"

echo "[1/5] uv"
UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
    for candidate in "$HOME_DIR/bin/uv" "$HOME/.local/bin/uv"; do
        if [ -x "$candidate" ]; then UV="$candidate"; break; fi
    done
fi
if [ -z "$UV" ]; then
    # into $HOME_DIR/bin, without touching the shell profile
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME_DIR/bin" UV_NO_MODIFY_PATH=1 sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME_DIR/bin" UV_NO_MODIFY_PATH=1 sh
    else
        echo "curl or wget is needed to download uv" >&2
        exit 1
    fi
    UV="$HOME_DIR/bin/uv"
    [ -x "$UV" ] || { echo "uv was not installed into $HOME_DIR/bin (see the messages above)" >&2; exit 1; }
fi
echo "uv: $UV"

echo "[2/5] Python 3.11 and the virtual environment ($VENV)"
# Python itself lives in $HOME_DIR too, as on Windows (where an agent's sandbox cannot start
# it from uv's default place): one folder holds the whole engine.
export UV_PYTHON_INSTALL_DIR="$PYTHONS" UV_PYTHON_BIN_DIR="$PYTHONS/bin"
"$UV" python install 3.11
if [ -f "$VENV/pyvenv.cfg" ] && ! grep -qF "$PYTHONS" "$VENV/pyvenv.cfg"; then
    echo "moving the engine onto the Python in $PYTHONS (packages come again from uv's cache)"
    rm -rf "$VENV"
fi
[ -x "$PY" ] || "$UV" venv --python 3.11 --python-preference only-managed "$VENV"

echo "[3/5] engine packages (PyTorch, Demucs, ADTOF, Beat This!)"
# ADTOF-pytorch (drum detection) comes from its author's repository, at the commit drumcopy was tested with.
ADTOF="adtof-pytorch @ https://github.com/xavriley/ADTOF-pytorch/archive/85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9.zip"
# --reinstall-package: after an update the engine folder changed but may keep its path.
"$UV" pip install --python "$PY" --reinstall-package drumcopy "drumcopy[engine] @ file://$ENGINE" "$ADTOF" "$ENGINE/vendor/beat_this" \
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

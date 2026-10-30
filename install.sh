#!/bin/sh
# Install the drum-transcribe skill for Claude Code and Codex on macOS / Linux. Python and git
# are not needed: the engine's setup installs everything it uses.
#   curl -LsSf https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.sh | sh
#   sh install.sh [--to SKILLS_FOLDER] [--no-setup]
# Puts the newest release into the skills folder of every agent found on this computer
# (~/.claude/skills, $CODEX_HOME/skills or ~/.codex/skills; Claude Code's when none is), then
# runs its scripts/setup.sh, which installs the engine into ~/.drumcopy. A git clone, or a
# copy that is not a release, is left alone.
set -e
REPO="siru-dduck/drum-transcribe"
NAME=drum-transcribe
TO=""
SETUP=1
while [ $# -gt 0 ]; do
    case "$1" in
        --to) TO="$2"; shift 2 ;;
        --no-setup) SETUP=0; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

fetch() {
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
    else echo "curl or wget is needed" >&2; return 1
    fi
}
command -v unzip >/dev/null 2>&1 || { echo "unzip is needed (for example: sudo apt install unzip)" >&2; exit 1; }

if [ -n "$TO" ]; then
    TARGETS="$TO"
else
    TARGETS=""
    if [ -d "$HOME/.claude" ]; then TARGETS="$HOME/.claude/skills"; fi
    CODEX="${CODEX_HOME:-$HOME/.codex}"
    if [ -d "$CODEX" ]; then TARGETS="$TARGETS${TARGETS:+
}$CODEX/skills"; fi
    if [ -z "$TARGETS" ]; then TARGETS="$HOME/.claude/skills"; fi
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "Looking for the newest release of $REPO"
VERSION=""
URL=""
if fetch "https://api.github.com/repos/$REPO/releases/latest" "$WORK/release.json" 2>/dev/null; then
    VERSION="$(sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' "$WORK/release.json" | head -n 1)"
    URL="$(sed -n "s|.*\"browser_download_url\": *\"\([^\"]*/$NAME-$VERSION\.zip\)\".*|\1|p" "$WORK/release.json" | head -n 1)"
    [ -n "$URL" ] || URL="$(sed -n 's/.*"zipball_url": *"\([^"]*\)".*/\1/p' "$WORK/release.json" | head -n 1)"
fi
if [ -z "$URL" ]; then
    VERSION=main
    URL="https://github.com/$REPO/archive/refs/heads/main.zip"
fi
echo "Downloading $URL"
fetch "$URL" "$WORK/skill.zip"
unzip -q "$WORK/skill.zip" -d "$WORK/files"
SRC="$(find "$WORK/files" -path '*/engine/pyproject.toml' | head -n 1)"
SRC="${SRC%/engine/pyproject.toml}"
if [ -z "$SRC" ] || [ ! -f "$SRC/SKILL.md" ]; then echo "no skill folder in $URL" >&2; exit 1; fi

: > "$WORK/installed"
printf '%s\n' "$TARGETS" | while IFS= read -r SKILLS; do
    DEST="$SKILLS/$NAME"
    if [ -d "$DEST/.git" ]; then echo "$DEST is a git clone: left as it is (it updates itself with git pull)"; continue; fi
    if [ -f "$DEST/SKILL.md" ] && [ ! -f "$DEST/release.json" ]; then
        echo "$DEST is not a release copy (a development folder?): left as it is"; continue
    fi
    mkdir -p "$DEST"
    find "$DEST" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    cp -R "$SRC/." "$DEST/"
    echo "Installed $NAME $VERSION into $DEST"
    echo "$DEST" >> "$WORK/installed"
done
FIRST="$(head -n 1 "$WORK/installed")"

if [ -n "$FIRST" ] && [ "$SETUP" = 1 ]; then
    echo "Setting up the engine (Python, PyTorch, models; about 3 GB, 5 to 15 minutes)"
    sh "$FIRST/scripts/setup.sh" < /dev/null
fi
if [ -n "$FIRST" ]; then
    echo "Done. Restart Claude Code or Codex, then ask it to make a drum score of a song (a YouTube link or an audio file)."
fi

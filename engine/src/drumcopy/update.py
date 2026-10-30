"""Keep an installed skill up to date with its GitHub releases.

The wrapper scripts (scripts/drumcopy, scripts\\drumcopy.ps1) pass the skill folder in
DRUMCOPY_SKILL. Only a release install updates itself: its folder has release.json, written
by scripts/build_release.py, naming the GitHub repository. A development folder has none and
is never touched.

  check()     the newest release against the installed version; GitHub is asked at most once
              a day (once an hour after a failure) and an offline check just says so
  run()       a git clone pulls (fast-forward only, never over local changes); a zip install
              gets the release zip after the old folder is copied to <home>/backups. Then the
              new setup script reinstalls the engine (without the MuseScore step).
  set_auto()  whether the agent updates at the start of a request without asking (default on)

Songs, corrections and model weights live in DRUMCOPY_HOME, outside the skill folder, so an
update never touches them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from . import paths

API = "https://api.github.com/repos/{repo}/releases/latest"
DAY, HOUR = 24 * 3600, 3600
STATE = paths.HOME / "work/update.json"   # the last check and the auto-update choice
BACKUPS = paths.HOME / "backups"
LOGS = paths.HOME / "work/logs"
KEEP = 3                                   # backups kept


def skill_dir():
    where = os.environ.get("DRUMCOPY_SKILL")
    return Path(where) if where else None


def install_kind(skill):
    if skill is None or not (skill / "SKILL.md").is_file():
        return "unknown"
    if not (skill / "release.json").is_file():
        return "dev"
    return "git" if (skill / ".git").exists() else "zip"


def version_of(skill):
    found = re.search(r'^version\s*=\s*"([^"]+)"', (skill / "engine/pyproject.toml").read_text(encoding="utf-8"), re.M)
    return found.group(1) if found else None


def engine_version():
    from importlib import metadata
    try:
        return metadata.version("drumcopy")
    except metadata.PackageNotFoundError:
        return None


def newer(a, b):
    """Is version a newer than b? (0.10.0 is newer than 0.9.1)"""
    key = lambda v: tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])
    return key(a) > key(b)


def latest(repo, timeout=5):
    """The newest published release: its version, the package to download and its page."""
    request = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json", "User-Agent": "drumcopy-update"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        release = json.load(response)
    version = release["tag_name"].lstrip("vV")
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    package = assets.get(f"drum-transcribe-{version}.zip") or next(
        (url for name, url in assets.items() if name.endswith(".zip")), None)
    return {"version": version, "zip": package or release["zipball_url"], "page": release["html_url"],
            "notes": (release.get("body") or "")[:1500]}


def _state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def set_auto(on):
    state = _state()
    state["auto"] = bool(on)
    _save(state)
    return {"auto_update": state["auto"]}


def check(force=False):
    skill = skill_dir()
    kind = install_kind(skill)
    state = _state()
    info = {"install": kind, "skill": str(skill) if skill else None, "auto_update": state.get("auto", True)}
    if kind in ("unknown", "dev"):
        info.update(available=False, reason="not a release install (a development folder, or no DRUMCOPY_SKILL)")
        return info
    installed = version_of(skill)
    engine = engine_version()
    info.update(installed=installed, engine=engine, engine_matches=engine == installed)
    repo = json.loads((skill / "release.json").read_text(encoding="utf-8"))["repo"]
    seen = state.get("latest") if state.get("repo") == repo else None
    fresh = seen and time.time() - state.get("checked", 0) < (HOUR if seen.get("error") else DAY)
    if force or not fresh:
        try:
            seen = latest(repo)
        except (OSError, ValueError, KeyError) as error:  # offline or rate limited: ask again later
            seen = {"error": f"{type(error).__name__}: {error}"}
        state.update(repo=repo, latest=seen, checked=time.time())
        _save(state)
    if seen.get("error"):
        info.update(available=False, error=seen["error"])
        return info
    info.update(latest=seen["version"], available=newer(seen["version"], installed), page=seen["page"],
                notes=seen["notes"], download=seen["zip"])
    return info


def run():
    """Update to the newest release (and reinstall the engine if it is older than the skill)."""
    info = check(force=True)
    if info["install"] in ("unknown", "dev"):
        return {**info, "updated": False}
    if info.get("error"):
        raise RuntimeError(f"could not reach GitHub: {info['error']}")
    skill = Path(info["skill"])
    result = {"updated": False, "from": info["installed"], "to": info["installed"], "install": info["install"]}
    if info["available"]:
        if info["install"] == "git":
            _pull(skill)
        else:
            result["backup"] = str(_replace(skill, info["download"], info["installed"]))
        result.update(updated=True, to=version_of(skill), page=info["page"],
                      read_again="SKILL.md: the instructions may have changed")
    if result["updated"] or not info["engine_matches"]:
        result["setup"] = _setup(skill)
    else:
        result["reason"] = "already the newest release"
    return result


def _git(skill, *args):
    return subprocess.run(["git", "-C", str(skill), *args], capture_output=True, text=True)


def _pull(skill):
    if _git(skill, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise RuntimeError(f"{skill} has local changes: update it by hand (git stash, git pull)")
    pulled = _git(skill, "pull", "--ff-only")
    if pulled.returncode:
        raise RuntimeError(f"git pull failed: {pulled.stderr.strip()}")


def _unpack(url, work):
    """Download the release zip into work and return the skill folder inside it."""
    archive = work / "release.zip"
    request = urllib.request.Request(url, headers={"User-Agent": "drumcopy-update"})
    with urllib.request.urlopen(request, timeout=120) as response, open(archive, "wb") as out:
        shutil.copyfileobj(response, out)
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            target = Path(package.extract(item, work / "files"))
            mode = item.external_attr >> 16 & 0o777
            if mode and not item.is_dir():
                os.chmod(target, mode)  # zipfile drops the executable bit of the scripts
    roots = [found.parent for found in (work / "files").rglob("SKILL.md")
             if (found.parent / "engine/pyproject.toml").is_file()]
    if len(roots) != 1:
        raise RuntimeError("the release zip has no skill folder in it")
    return roots[0]


def _clear(folder):
    for item in list(folder.iterdir()):
        shutil.rmtree(item) if item.is_dir() else item.unlink()


def _replace(skill, url, version):
    """Swap the skill folder's files for the release's, keeping a copy of the old ones."""
    with tempfile.TemporaryDirectory(prefix="drumcopy-update-") as work:
        new = _unpack(url, Path(work))
        backup = BACKUPS / f"skill-{version}-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copytree(skill, backup)
        try:
            _clear(skill)  # the folder itself stays: a shell may be sitting in it
            for item in new.iterdir():
                (shutil.copytree if item.is_dir() else shutil.copy2)(item, skill / item.name)
        except OSError:
            _clear(skill)
            shutil.copytree(backup, skill, dirs_exist_ok=True)
            raise
    for old in sorted(BACKUPS.glob("skill-*"), key=lambda p: p.stat().st_mtime)[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return backup


def _setup(skill):
    """Reinstall the engine from the skill folder with its own setup script."""
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"update-{time.strftime('%Y%m%d-%H%M%S')}.log"
    if os.name == "nt":
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(skill / "scripts/setup.ps1"), "-NoMuseScore"]
    else:
        command = ["sh", str(skill / "scripts/setup.sh"), "--no-musescore"]
    with open(log, "w", encoding="utf-8") as out:
        done = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT)
    return {"ok": done.returncode == 0, "log": str(log)}

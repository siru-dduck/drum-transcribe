# drumcopy engine setup for Windows. Python is not needed beforehand: uv installs it.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-NoMuseScore]
# Installs into %DRUMCOPY_HOME% (default %USERPROFILE%\.drumcopy): Python 3.11, the engine
# (PyTorch, Demucs, ADTOF, Beat This!), the model weights and, through winget, MuseScore 4
# for the PDF. Needs internet and about 3 GB. Prints the `drumcopy doctor` report at the end.
param([switch]$NoMuseScore)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Skill = Split-Path -Parent $PSScriptRoot
$Engine = Join-Path $Skill "engine"
$DataHome = if ($env:DRUMCOPY_HOME) { $env:DRUMCOPY_HOME } else { Join-Path $env:USERPROFILE ".drumcopy" }
$Venv = Join-Path $DataHome "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path (Join-Path $Engine "pyproject.toml"))) { throw "engine folder not found next to this script: $Engine" }
New-Item -ItemType Directory -Force -Path $DataHome | Out-Null

Write-Host "[1/5] uv"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "[2/5] Python 3.11 and the virtual environment ($Venv)"
uv python install 3.11
if (-not (Test-Path $Py)) { uv venv --python 3.11 $Venv }

Write-Host "[3/5] engine packages (PyTorch CPU, Demucs, ADTOF, Beat This!)"
$EngineUri = ([System.Uri]$Engine).AbsoluteUri
# ADTOF-pytorch (drum detection) comes from its author's repository, at the commit drumcopy was tested with.
$Adtof = "adtof-pytorch @ https://github.com/xavriley/ADTOF-pytorch/archive/85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9.zip"
uv pip install --python $Py "drumcopy[engine] @ $EngineUri" $Adtof (Join-Path $Engine "vendor\beat_this") yt-dlp imageio-ffmpeg
if ($LASTEXITCODE -ne 0) { throw "package install failed" }

Write-Host "[4/5] MuseScore 4 (PDF)"
$haveMuseScore = (Test-Path "$env:ProgramFiles\MuseScore 4\bin\MuseScore4.exe") -or $env:DRUMCOPY_MUSESCORE
if (-not $haveMuseScore -and -not $NoMuseScore) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id MuseScore.MuseScore --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "winget not found: install MuseScore 4 from https://musescore.org (PDF output needs it)"
    }
}

Write-Host "[5/5] model weights and check"
$env:PYTHONUTF8 = "1"
& $Py -m drumcopy.cli doctor --fetch-models

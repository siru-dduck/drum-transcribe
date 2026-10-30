# drumcopy engine setup for Windows. Python is not needed beforehand: uv installs it.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-NoMuseScore]
# Installs into %DRUMCOPY_HOME% (default %USERPROFILE%\.drumcopy): uv, Python 3.11, the engine
# (PyTorch, Demucs, ADTOF, Beat This!), the model weights and, through winget, MuseScore 4
# for the PDF. Needs internet and about 3 GB. Prints the `drumcopy doctor` report at the end.
# Runs in Windows PowerShell 5.1 and PowerShell 7, also when an agent captures its output.
param([switch]$NoMuseScore)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }  # no console when an agent runs it
$env:PYTHONUTF8 = "1"

$Skill = Split-Path -Parent $PSScriptRoot
$Engine = Join-Path $Skill "engine"
$DataHome = if ($env:DRUMCOPY_HOME) { $env:DRUMCOPY_HOME } else { Join-Path $env:USERPROFILE ".drumcopy" }
$Venv = Join-Path $DataHome "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Bin = Join-Path $DataHome "bin"
if (-not (Test-Path (Join-Path $Engine "pyproject.toml"))) { throw "engine folder not found next to this script: $Engine" }
New-Item -ItemType Directory -Force -Path $Bin | Out-Null

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    # uv, winget and Python print progress on stderr. When an agent captures the output,
    # Windows PowerShell 5.1 turns every such line into an error, which would stop the script
    # at the first one (the Python download). So they are shown as text; the exit code decides.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "$_" } }
    finally { $ErrorActionPreference = $saved }
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed (exit code $LASTEXITCODE)" }
}

function Save-Url([string]$Url, [string]$Path) {
    # Invoke-WebRequest, then BITS. Inside an agent's Windows sandbox (Codex) the first fails
    # with SEC_E_NO_CREDENTIALS; after uv is here, uv and Python download on their own.
    try { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path; return }
    catch { $first = $_.Exception.Message }
    try { Start-BitsTransfer -Source $Url -Destination $Path -ErrorAction Stop; return }
    catch {
        $hint = ""
        if ($first -match "SEC_E_NO_CREDENTIALS|AcquireCredentialsHandle|secure channel|SSL/TLS") {
            $hint = "`nThe download is blocked inside the agent's sandbox. Run this script outside the sandbox " +
                    "(approve network / full access for it), or paste this into PowerShell yourself:`n" +
                    "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        }
        throw "could not download $Url ($first)$hint"
    }
}

Write-Host "[1/5] uv"
$Uv = @((Get-Command uv -ErrorAction SilentlyContinue).Path, (Join-Path $Bin "uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Uv) {
    # x86_64 also on ARM64 Windows: PyTorch has x64 wheels for Python 3.11, which run emulated
    $zip = Join-Path $env:TEMP "uv-x86_64-pc-windows-msvc.zip"
    Save-Url "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" $zip
    Expand-Archive -Path $zip -DestinationPath $Bin -Force
    Remove-Item $zip
    $Uv = (Get-ChildItem $Bin -Recurse -Filter uv.exe | Select-Object -First 1).FullName
    if (-not $Uv) { throw "uv.exe not found in $Bin after unpacking" }
}
Write-Host "uv: $Uv"

Write-Host "[2/5] Python 3.11 and the virtual environment ($Venv)"
Invoke-Native $Uv @("python", "install", "3.11")
if (-not (Test-Path $Py)) { Invoke-Native $Uv @("venv", "--python", "3.11", $Venv) }

Write-Host "[3/5] engine packages (PyTorch CPU, Demucs, ADTOF, Beat This!)"
$EngineUri = ([System.Uri]$Engine).AbsoluteUri
# ADTOF-pytorch (drum detection) comes from its author's repository, at the commit drumcopy was tested with.
$Adtof = "adtof-pytorch @ https://github.com/xavriley/ADTOF-pytorch/archive/85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9.zip"
# --reinstall-package: after an update the engine folder changed but may keep its path.
Invoke-Native $Uv @("pip", "install", "--python", $Py, "--reinstall-package", "drumcopy", "drumcopy[engine] @ $EngineUri",
                    $Adtof, (Join-Path $Engine "vendor\beat_this"), "yt-dlp", "imageio-ffmpeg")

Write-Host "[4/5] MuseScore 4 (PDF)"
$haveMuseScore = (Test-Path "$env:ProgramFiles\MuseScore 4\bin\MuseScore4.exe") -or $env:DRUMCOPY_MUSESCORE
if (-not $haveMuseScore -and -not $NoMuseScore) {
    $installed = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            Invoke-Native "winget" @("install", "-e", "--id", "MuseScore.MuseScore", "--accept-package-agreements", "--accept-source-agreements")
            $installed = $true
        } catch { Write-Host "winget could not install MuseScore 4: $($_.Exception.Message)" }
    }
    if (-not $installed) { Write-Host "Install MuseScore 4 from https://musescore.org for the PDF (everything else works without it)" }
}

Write-Host "[5/5] model weights and check"
Invoke-Native $Py @("-m", "drumcopy.cli", "doctor", "--fetch-models")

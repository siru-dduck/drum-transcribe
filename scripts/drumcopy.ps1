# drumcopy CLI for Windows: runs the engine installed by setup.ps1 with all arguments passed on.
#   powershell -ExecutionPolicy Bypass -File scripts\drumcopy.ps1 transcribe <url|file> --parts kick,snare
$DataHome = if ($env:DRUMCOPY_HOME) { $env:DRUMCOPY_HOME } else { Join-Path $env:USERPROFILE ".drumcopy" }
$Py = if ($env:DRUMCOPY_PYTHON) { $env:DRUMCOPY_PYTHON } else { Join-Path $DataHome "venv\Scripts\python.exe" }
if (-not (Test-Path $Py)) {
    Write-Output '{"error": "NotInstalled", "message": "drumcopy engine not installed: run scripts\\setup.ps1"}'
    exit 2
}
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& $Py -m drumcopy.cli @args
exit $LASTEXITCODE

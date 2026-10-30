# Install the drum-transcribe skill for Claude Code and Codex on Windows. Python and git are
# not needed: the engine's setup installs everything it uses.
#   irm https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.ps1 | iex
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-To <skills folder>] [-NoSetup]
# Puts the newest release into the skills folder of every agent found on this PC
# (%USERPROFILE%\.claude\skills, %CODEX_HOME%\skills or %USERPROFILE%\.codex\skills; Claude
# Code's when none is), then runs its scripts\setup.ps1, which installs the engine into
# %USERPROFILE%\.drumcopy. A git clone, or a copy that is not a release, is left alone.
param([string]$To, [switch]$NoSetup)
# The body runs in its own scope: through `irm | iex` it would otherwise change the settings
# (error handling, progress) of the PowerShell window it was pasted into.
& {
    param([string]$To, [switch]$NoSetup)
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $Repo = "siru-dduck/drum-transcribe"
    $Name = "drum-transcribe"

    function Save-Url([string]$Url, [string]$Path) {
        # Invoke-WebRequest, then BITS (inside an agent's Windows sandbox the first may be blocked).
        try { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path; return }
        catch { $first = $_.Exception.Message }
        try { Start-BitsTransfer -Source $Url -Destination $Path -ErrorAction Stop; return }
        catch {
            $hint = ""
            if ($first -match "SEC_E_NO_CREDENTIALS|AcquireCredentialsHandle|secure channel|SSL/TLS") {
                $hint = "`nThe download is blocked inside the agent's sandbox. Run the installer outside the sandbox " +
                        "(approve network / full access for it), or paste this into PowerShell yourself:`n" +
                        "  irm https://raw.githubusercontent.com/$Repo/main/install.ps1 | iex"
            }
            throw "could not download $Url ($first)$hint"
        }
    }

    $targets = @()
    if ($To) { $targets = @($To) } else {
        $codex = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
        if (Test-Path (Join-Path $env:USERPROFILE ".claude")) { $targets += Join-Path $env:USERPROFILE ".claude\skills" }
        if (Test-Path $codex) { $targets += Join-Path $codex "skills" }
        if (-not $targets) { $targets = @(Join-Path $env:USERPROFILE ".claude\skills") }
    }

    Write-Host "Looking for the newest release of $Repo"
    try {
        $release = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "$Name-install" }
        $version = $release.tag_name.TrimStart("v")
        $asset = $release.assets | Where-Object { $_.name -eq "$Name-$version.zip" } | Select-Object -First 1
        $url = if ($asset) { $asset.browser_download_url } else { $release.zipball_url }
    } catch {
        $version = "main"
        $url = "https://github.com/$Repo/archive/refs/heads/main.zip"
    }

    $work = Join-Path $env:TEMP "$Name-install-$(Get-Random)"
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    try {
        $zip = Join-Path $work "skill.zip"
        Write-Host "Downloading $url"
        Save-Url $url $zip
        Expand-Archive -Path $zip -DestinationPath (Join-Path $work "files") -Force
        $found = Get-ChildItem (Join-Path $work "files") -Recurse -Filter SKILL.md |
            Where-Object { Test-Path (Join-Path $_.DirectoryName "engine\pyproject.toml") } | Select-Object -First 1
        if (-not $found) { throw "no skill folder in $url" }
        $installed = $null
        foreach ($skills in $targets) {
            $dest = Join-Path $skills $Name
            if (Test-Path (Join-Path $dest ".git")) { Write-Host "$dest is a git clone: left as it is (it updates itself with git pull)"; continue }
            if ((Test-Path (Join-Path $dest "SKILL.md")) -and -not (Test-Path (Join-Path $dest "release.json"))) {
                Write-Host "$dest is not a release copy (a development folder?): left as it is"; continue
            }
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Get-ChildItem $dest -Force | Remove-Item -Recurse -Force
            Copy-Item -Path (Join-Path $found.DirectoryName "*") -Destination $dest -Recurse -Force
            Write-Host "Installed $Name $version into $dest"
            if (-not $installed) { $installed = $dest }
        }
    } finally {
        Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($installed -and -not $NoSetup) {
        Write-Host "Setting up the engine (Python, PyTorch, models; about 3 GB, 5 to 15 minutes)"
        $saved = $ErrorActionPreference
        $ErrorActionPreference = "Continue"  # progress on stderr is not an error (Windows PowerShell 5.1)
        try { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $installed "scripts\setup.ps1") 2>&1 | ForEach-Object { Write-Host "$_" } }
        finally { $ErrorActionPreference = $saved }
        if ($LASTEXITCODE -ne 0) {
            throw "engine setup failed; run it again: powershell -ExecutionPolicy Bypass -File `"$installed\scripts\setup.ps1`""
        }
    }
    if ($installed) {
        Write-Host "Done. Restart Claude Code or Codex, then ask it to make a drum score of a song (a YouTube link or an audio file)."
    }
} -To $To -NoSetup:$NoSetup

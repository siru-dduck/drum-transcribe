@echo off
rem Installs the drum-transcribe skill for Claude Code and Codex: double-click this file.
rem It runs the one-line installer https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.ps1,
rem which downloads the newest release and sets up the engine (about 3 GB, 5 to 15 minutes).
rem No Python or git needed. Saved as UTF-8 without BOM, CRLF line ends.
chcp 65001 >nul
title drum-transcribe
echo.
echo  drum-transcribe 드럼 악보 스킬을 설치합니다.
echo  Installing the drum-transcribe skill (drum scores for Claude Code and Codex).
echo.
echo  인터넷으로 약 3GB를 받아 5~15분 걸립니다. 끝날 때까지 이 창을 닫지 마세요.
echo  About 3 GB to download, 5 to 15 minutes. Please keep this window open.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.ps1 | iex"
if errorlevel 1 goto failed
echo.
echo  설치가 끝났습니다. Claude Code나 Codex를 다시 시작한 뒤
echo  "이 노래 드럼 악보 만들어줘" 하고 유튜브 링크나 음원 파일을 주세요.
echo.
echo  Done. Restart Claude Code or Codex, then ask it to make a drum score
echo  of a song, with a YouTube link or an audio file.
goto end
:failed
echo.
echo  설치하지 못했습니다. 위에 나온 마지막 몇 줄을 캡처해서 알려 주세요.
echo  https://github.com/siru-dduck/drum-transcribe/issues
echo.
echo  The install failed. Please share the last lines above.
:end
echo.
pause

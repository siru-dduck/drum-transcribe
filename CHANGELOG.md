# 바뀐 내용 (Changelog)

## v0.2.4

- 업데이트 확인이 Codex 샌드박스 안에서 실패하던 문제를 고쳤습니다. 확인 결과를 `~/.drumcopy`에 저장하지 못하면 확인 전체가 실패했습니다. 이제 저장하지 못해도 결과를 알려 줍니다. GitHub 접속이 막히면 샌드박스 밖에서 한 번 확인하라는 안내를 붙입니다.
- GitHub에 접속할 때 운영체제 인증서 대신 엔진에 함께 설치된 certifi 인증서를 씁니다. 샌드박스 안에서 운영체제 인증서를 읽지 못하는 경우에 대비한 것입니다.
- Windows에서 사용자 이름이 한글이면 설치 명령을 실행할 때마다 가상 환경을 다시 만들던 문제를 고쳤습니다. Windows PowerShell 5.1이 UTF-8 설정 파일을 다른 인코딩으로 읽었습니다.

### English

- Fixed the update check failing inside Codex's sandbox: when it could not save its answer in `~/.drumcopy`, the whole check failed. It now answers anyway, and when GitHub is out of reach it adds a hint to check once outside the sandbox.
- GitHub is reached with certifi's certificates, installed with the engine, instead of the operating system's store, which a sandbox may not let it read.
- Fixed the virtual environment being rebuilt on every install run on Windows when the user name is Korean: Windows PowerShell 5.1 read a UTF-8 settings file in another encoding.

## v0.2.3

- Windows에서 MuseScore 4(PDF용)가 설치되지 않던 문제를 고쳤습니다. winget 패키지 이름이 `Musescore.Musescore`인데 대소문자가 달라 찾지 못했습니다.
- 유튜브용 JavaScript 런타임(deno)과 yt-dlp의 확인 절차 스크립트를 엔진에 함께 설치합니다. 없으면 "No supported JavaScript runtime" 경고가 나고 일부 영상을 받지 못할 수 있었습니다. 설치하거나 업데이트할 때마다 yt-dlp도 최신으로 올립니다.
- Windows 설치 창에서 한글(사용자 이름이 든 경로)이 깨져 보이던 문제와, 필요 없는 "is not on your PATH" 경고를 없앴습니다.

### English

- Fixed MuseScore 4 (for the PDF) not installing on Windows: the winget package is `Musescore.Musescore`, and the case did not match.
- The engine now comes with a JavaScript runtime for YouTube (deno) and yt-dlp's challenge scripts. Without them yt-dlp warned "No supported JavaScript runtime" and some videos could fail to download. yt-dlp is also brought up to date on every install or update.
- Korean text (a user name in a path) no longer comes out garbled in the Windows install window, and the needless "is not on your PATH" warning is gone.

## v0.2.2

- Codex(Windows)에서 채보가 시작되지 않던 문제를 고쳤습니다. uv가 Python 본체를 AppData에 두는데 Codex 샌드박스는 AppData의 프로그램을 실행하지 못해, `uv trampoline failed to spawn Python child process (os error 5)`가 났습니다. 이제 Python도 `~/.drumcopy/python`에 설치합니다. 이미 설치한 PC는 설치 명령을 한 번 더 실행하면 엔진이 옮겨집니다.
- README와 SKILL.md에 Codex 샌드박스 안내를 넣었습니다. 엔진 폴더 쓰기와 인터넷만 여는 `config.toml` 설정을 적었습니다.

### English

- Fixed transcription not starting in Codex on Windows. uv keeps Python itself in AppData, and Codex's sandbox cannot start programs there, so the engine failed with `uv trampoline failed to spawn Python child process (os error 5)`. Python now goes into `~/.drumcopy/python` as well. On a PC that already has the engine, run the install command once more to move it.
- READMEs and SKILL.md explain Codex's sandbox, with a `config.toml` setting that opens only the engine folder and the internet.

## v0.2.1

- 한 줄 설치: Windows는 `irm https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.ps1 | iex`, macOS·Linux는 `curl -LsSf https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.sh | sh`. Python과 git 없이 최신 릴리즈를 Claude Code와 Codex의 스킬 폴더에 넣고 엔진까지 설치합니다.
- Windows 설치 고침: 에이전트가 설치 스크립트를 실행하면 Windows PowerShell 5.1이 uv의 진행 메시지를 오류로 바꿔, Python을 받는 단계에서 설치가 멈췄습니다. 이제 종료 코드로 성공 여부를 판단합니다.
- uv를 `~/.drumcopy/bin`에 직접 받습니다. 셸 설정을 바꾸지 않고, 다운로드가 막히면 BITS로 한 번 더 시도합니다.
- Codex의 Windows 샌드박스에서 다운로드가 막히면(`SEC_E_NO_CREDENTIALS`) 샌드박스 밖에서 실행하라고 안내합니다.
- README 맨 위에 에이전트용 안내를 넣었습니다. 에이전트가 이 저장소를 Python 패키지로 착각하지 않게 합니다.

### English

- One-line install: `irm https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.ps1 | iex` on Windows, `curl -LsSf https://raw.githubusercontent.com/siru-dduck/drum-transcribe/main/install.sh | sh` on macOS and Linux. Without Python or git, it puts the newest release into the skills folders of Claude Code and Codex and installs the engine.
- Windows setup fix: when an agent ran the setup script, Windows PowerShell 5.1 turned uv's progress messages into errors and the setup stopped at the Python download. Exit codes now decide.
- uv is downloaded straight into `~/.drumcopy/bin`, without changing the shell profile; a blocked download is tried once more with BITS.
- When Codex's Windows sandbox blocks downloads (`SEC_E_NO_CREDENTIALS`), the scripts say to run them outside the sandbox.
- A note for AI agents at the top of the READMEs, so they don't take the repository for a Python package.

## v0.2.0

- 자동 업데이트: 에이전트가 새 요청을 시작할 때 새 버전을 확인하고(하루 한 번), 있으면 알린 뒤 업데이트합니다.
  - git으로 받은 폴더는 `git pull`로, zip으로 받은 폴더는 릴리즈의 `drum-transcribe-버전.zip`으로 바꾸고, 엔진도 다시 설치합니다.
  - 사용자가 고친 파일이 있는 git 폴더는 건드리지 않습니다. zip 설치본은 이전 폴더를 `~/.drumcopy/backups`에 남깁니다.
  - 곡과 교정 기록은 그대로입니다. "자동 업데이트 꺼줘"라고 하면 묻고 나서 바꿉니다(`drumcopy update --auto off`).
- 새 명령 `drumcopy update [--check] [--auto on|off]`.

### English

- Automatic updates: at the start of a new request the agent checks for a new version (at most once a day) and, if there is one, says so and updates.
  - A git clone is updated with `git pull`, a zip install with the release's `drum-transcribe-VERSION.zip`; the engine is reinstalled too.
  - A git clone with your own changes is left alone. A zip install keeps the old folder in `~/.drumcopy/backups`.
  - Songs and corrections stay as they are. Say "turn off automatic updates" to be asked first (`drumcopy update --auto off`).
- New command `drumcopy update [--check] [--auto on|off]`.

## v0.1.0 (2026-10-30)

첫 공개 버전입니다.

- 유튜브 링크나 음원에서 킥, 스네어, 크로스스틱을 표준 드럼 악보로 채보합니다. 고스트 노트는 기본으로 뺍니다.
- PDF(MuseScore 4), MusicXML, 압축 MusicXML(.mxl, 시벨리우스·Dorico·Finale에서 바로 열림), MuseScore(.mscz), MIDI, `player.html`을 만듭니다.
- 6/4, 12/8, 3/4 같은 박자표 변화와 rit., accel., rubato 같은 템포 표기를 적습니다.
- 곡마다 교정을 저장하고, 다시 채보해도 유지합니다. 비슷한 소리가 나는 곳을 찾아 물어봅니다.
- `drumcopy tune`: 로직(Logic Pro) 편곡 창처럼 생긴 마디·박·템포 편집 화면입니다.
  - 클릭을 들으며 박 선과 마디선을 끌고, 구간의 마디 수와 박자표를 넣고, F·J 키로 박을 탭합니다.
  - 고치면 바로 저장되고 되돌릴 수 있습니다.
  - 맥과 Windows 모두에서 씁니다. 단축키는 맥 키 옆 괄호에 Windows 키를 함께 적습니다(예: ⌘Z(Windows Ctrl+Z)).
  - 처음 열면 단축키와 조작법을 애니메이션으로 보여 주는 안내가 뜹니다. 오른쪽 위 `?` 버튼으로 다시 봅니다.
- `drumcopy export`: 여러 곡의 MXL을 곡 이름으로 한 폴더에 모읍니다.
- 설치 스크립트(`setup.sh`, `setup.ps1`)가 Python, 분석 모델, MuseScore 4를 받아 맥, 리눅스, Windows에서 설치합니다.

### English

First public release.

- Transcribes kick, snare and cross-stick from a YouTube link or an audio file into a standard drum score. Ghost notes are left out by default.
- Writes PDF (MuseScore 4), MusicXML, compressed MusicXML (.mxl, opens directly in Sibelius, Dorico and Finale), MuseScore (.mscz), MIDI and `player.html`.
- Writes meter changes such as 6/4, 12/8 and 3/4, and tempo marks such as rit., accel. and rubato.
- Keeps corrections per song, so they survive re-transcription, and asks about places that sound similar.
- `drumcopy tune`: a bar, beat and tempo editor that looks like the arrange window of a DAW (Logic Pro).
  - Drag beat lines and bar lines while listening to a click, enter the number of bars and the meter for a range, and tap beats with the F and J keys.
  - Every edit is saved at once and can be undone.
  - Works on macOS and Windows. Shortcuts are written with the Mac key and the Windows key in parentheses, for example ⌘Z (Windows Ctrl+Z).
  - On first launch, an animated guide shows the shortcuts and gestures. Reopen it with the `?` button at the top right.
- `drumcopy export`: collects the MXL files of several songs, named after each song, in one folder.
- The setup scripts (`setup.sh`, `setup.ps1`) download Python, the analysis models and MuseScore 4, and install them on macOS, Linux and Windows.

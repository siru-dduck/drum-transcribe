# 바뀐 내용 (Changelog)

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

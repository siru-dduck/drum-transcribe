# drum-transcribe

[한국어](README.md) | **English**

An AI agent skill that turns a YouTube link or an audio file into a standard drum score for **kick, snare and cross-stick**, as PDF, MusicXML and MIDI. Tell an agent such as Claude Code or Codex "make a drum score of this song"; it installs the skill's engine (drumcopy), runs it, reviews the score and hands it to you.

![The bar, beat and tempo editor: the meter track changes from 4/4 to 12/8, the tempo track has an accel. mark, and beat lines over the recording's waveform and kick and cross-stick strokes line up with the bar lines.](images/tune.png)

*The bar, beat and tempo editor (`drumcopy tune`, Korean interface). Drag beat lines and bar lines while listening to a click, and add meters and tempo marks.*

## What it does

- **Kick, snare and cross-stick transcription:** separates the drums, finds the strokes and writes them on the beat grid. Ghost notes are left out by default.
- **Meter and tempo:** writes meter changes such as 6/4, 12/8 and 3/4, and tempo marks such as rit., accel. and rubato. Bar 1 is where the music starts, and long drum rests are grouped into multi-bar rests.
- **Outputs:**
  - PDF, engraved with MuseScore 4.
  - MusicXML and compressed MusicXML (.mxl), which open directly in Sibelius, Dorico, Finale and MuseScore.
  - MuseScore file (.mscz).
  - MIDI, aligned to the original recording.
  - `player.html`, which plays the recording together with the score.
- **Fixes per song:** an automatic transcription is a draft. Say "bar 25 on is cross-stick" or "remove the snare in bar 58" and the agent saves it as a correction for that song. Corrections survive re-transcription, and the agent asks about places that sound similar.
- **Bar, beat and tempo editor:** `drumcopy tune` opens an editor in the browser that looks like the arrange window of a DAW (Logic Pro).
  - Drag beat lines or bar lines while listening to a metronome click.
  - Select a range and enter the number of bars and the meter.
  - Tap only the downbeats with the F key and the beats in between are filled in to fit the meter.
  - Add tempo marks on the tempo track.
  - Every edit is saved at once; undo with ⌘Z (Windows Ctrl+Z).
  - On first launch, an animated guide shows the shortcuts and gestures. Works on macOS and Windows.
  - Places the engine is unsure about (such as an intro without drums) are marked.
- **Export to other notation programs:** `drumcopy export` collects the MXL files of several songs, named after each song, in one folder.

## Install

You don't need Python beforehand. On first use the agent runs `scripts/setup.sh` (macOS, Linux) or `scripts/setup.ps1` (Windows), which downloads everything it needs. It needs an internet connection and about 3 GB of disk space.

It downloads Python 3.11, PyTorch and the analysis models (Demucs, ADTOF, Beat This!), the model weights, and MuseScore 4. MuseScore 4 is only needed for PDF and .mscz; without it, only those two are skipped.

**Claude Code**

```sh
git clone https://github.com/siru-dduck/drum-transcribe ~/.claude/skills/drum-transcribe
```

On Windows, clone it into `%USERPROFILE%\.claude\skills\drum-transcribe`. Then tell Claude Code "make a drum score of this song https://youtu.be/...".

Without git, download `drum-transcribe-VERSION.zip` (for example `drum-transcribe-0.1.0.zip`) from [Releases](https://github.com/siru-dduck/drum-transcribe/releases), unzip it, and put the `drum-transcribe` folder in `~/.claude/skills/` (`%USERPROFILE%\.claude\skills\` on Windows). You don't need `Source code (zip)` on the same page; GitHub adds it to every release automatically. Changes are listed in [CHANGELOG.md](CHANGELOG.md).

**Updates**

When a new version is out, the agent tells you at the start of a new request and updates right away. It asks GitHub at most once a day, and your songs and corrections stay as they are. Say "turn off automatic updates" to be asked first, or "update drum-transcribe" to update now.

**Codex and other agents**

Download this folder and tell the agent to read `SKILL.md` and follow it. The skill only uses a command-line tool (`scripts/drumcopy`, or `scripts\drumcopy.ps1` on Windows).

## Examples

```text
Make a drum score of this song https://youtu.be/XXXXXXXX
Just the kick and snare, please (file: ~/Music/song.wav)
From bar 60, beats 2 and 4 are cross-stick
I want to fix the bars and tempo on screen
Make an MXL I can open in Sibelius
```

## Limits

- It is not 100% right in one pass, especially for recordings with muddy drums, long intros without drums, and rubato passages. That is why it comes with a way to fix things (saved corrections, suggestions for similar places, the editor).
- It focuses on kick, snare and cross-stick for now. Hi-hat, toms and cymbals are used in the analysis but not written in the score.
- The first transcription takes 1 to 3 minutes per song; rebuilding the same song takes a few seconds. No GPU needed.
- Only Sibelius can write Sibelius files (.sib). The skill makes an .mxl that Sibelius opens directly instead.

## License

- The code in this repository is licensed under [PolyForm Noncommercial 1.0.0](LICENSE). **Anyone** may use, change and share it **for non-commercial purposes**, such as personal practice, churches, schools, clubs and research. Commercial use, such as a paid service or making scores for sale, is not allowed.
- The drum detection model [ADTOF](https://github.com/MZehren/ADTOF) is also under a non-commercial license (CC BY-NC-SA 4.0). The other projects used and their licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- You need the right to use the audio you transcribe. The scores this skill makes are drafts for study and practice and give no rights to the songs.

Bug reports and suggestions are welcome in Issues.

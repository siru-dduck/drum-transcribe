# Third-party notices

drumcopy's own code is under the license in `LICENSE`. It relies on the projects below, each
under its own terms. Only Beat This! is included in this folder; everything else is
downloaded from its source by `scripts/setup.sh` / `scripts/setup.ps1` (or installed by you).

| Component | Role | License | How it reaches your computer |
| --- | --- | --- | --- |
| [Beat This!](https://github.com/CPJKU/beat_this) (Foscarin, Schlüter, Widmer, JKU Linz) | beat and downbeat tracking | MIT (`engine/vendor/beat_this/LICENSE`) | code included here; model weights downloaded from the authors' release |
| [ADTOF](https://github.com/MZehren/ADTOF) (Zehren, Alunno, Bientinesi) | drum stroke detection model | CC BY-NC-SA 4.0 | weights come with ADTOF-pytorch, below |
| [ADTOF-pytorch](https://github.com/xavriley/ADTOF-pytorch) (Xavier Riley) | PyTorch port of ADTOF and its weights | no license stated by the author | installed from the author's repository at commit `85c192e` by the setup scripts; not redistributed here |
| [Demucs](https://github.com/facebookresearch/demucs) (Meta AI) | drum stem separation | MIT | installed from PyPI; weights downloaded from the authors' release |
| [PyTorch](https://pytorch.org), [librosa](https://librosa.org), NumPy, SciPy, soundfile, pretty_midi | runtime libraries | their own licenses (BSD, ISC, MIT) | installed from PyPI |
| [MuseScore 4](https://musescore.org) | MusicXML to PDF | GPL-3.0 | installed separately (winget / Homebrew / musescore.org) |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp), ffmpeg (through imageio-ffmpeg) | downloading and decoding audio | Unlicense; LGPL/GPL | installed from PyPI |

ADTOF is licensed for non-commercial use only (Creative Commons Attribution-NonCommercial-
ShareAlike 4.0). drumcopy uses its model to detect drum strokes, so drumcopy as a whole is
for non-commercial use as well.

Papers to cite when you publish results made with drumcopy:

- M. Zehren, M. Alunno, P. Bientinesi. ADTOF: A large dataset of non-synthetic music for
  automatic drum transcription. ISMIR 2021. / High-Quality and Reproducible Automatic Drum
  Transcription from Crowdsourced Data. Signals 4(4), 2023.
- F. Foscarin, J. Schlüter, G. Widmer. Beat This! Accurate beat tracking without DBN
  postprocessing. ISMIR 2024.
- S. Rouard, F. Massa, A. Défossez. Hybrid Transformers for Music Source Separation.
  ICASSP 2023.

You are responsible for having the right to use the recordings you transcribe. drumcopy
makes a draft score for study and practice; it does not grant any rights to the music.

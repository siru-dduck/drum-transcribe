"""Model stages: drum separation (Demucs), onset detection (ADTOF), beat tracking (Beat This!).

Each stage caches its output under <cache>/<audio sha256>/ so notation can be
re-run without touching the models.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

CLASSES = ("kick", "snare", "toms", "hi-hat", "cymbals")  # ADTOF output order (LABELS_5)
ADTOF_FPS = 100
BEAT_FPS = 50
DEFAULT_THRESHOLDS = (0.22, 0.24, 0.32, 0.22, 0.30)

DEMUCS_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th"
DEMUCS_SHA256 = "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
BEAT_THIS_URLS = (
    "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt",
    "https://huggingface.co/teamup-tech/Beat-This-weights/resolve/main/final0.ckpt",
)
BEAT_THIS_SHA256 = "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_weights(urls, expected, target):
    """Download pinned weights; any mirror is accepted only if the hash matches."""
    target = Path(target)
    if target.is_file() and sha256(target) == expected:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    import urllib.request

    errors = []
    for url in ([urls] if isinstance(urls, str) else urls):
        partial = target.with_suffix(".download")
        try:  # urllib, not curl: the same on every OS
            with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as stream:
                shutil.copyfileobj(response, stream)
            if sha256(partial) == expected:
                partial.replace(target)
                return target
            errors.append(f"{url}: hash mismatch")
        except OSError as error:
            errors.append(f"{url}: {error}")
        partial.unlink(missing_ok=True)
    raise RuntimeError("weights unavailable: " + "; ".join(errors))


def decode(audio, samplerate, channels):
    from .paths import ffmpeg

    raw = subprocess.run([ffmpeg(), "-v", "error", "-i", str(audio), "-f", "f32le", "-ar", str(samplerate),
                          "-ac", str(channels), "pipe:1"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, channels).T.copy()


def separate_drums(audio, out_dir, models_dir):
    """htdemucs drum stem, written as float WAV."""
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.states import load_model

    out = Path(out_dir) / "drums.wav"
    if out.is_file():
        return out
    weights = fetch_weights(DEMUCS_URL, DEMUCS_SHA256, Path(models_dir) / "demucs/955717e8-8726e21a.th")
    torch.manual_seed(0)
    # Pinned official checkpoint (hash verified) stores the model class, so full unpickling is required.
    model = load_model(torch.load(weights, map_location="cpu", weights_only=False)).eval()
    wav = torch.from_numpy(decode(audio, model.samplerate, 2))
    reference = wav.mean(0)
    mean, scale = reference.mean(), reference.std()
    if not torch.isfinite(scale) or scale <= 1e-8:
        raise ValueError("silent or invalid audio")
    with torch.no_grad():
        sources = apply_model(model, ((wav - mean) / scale)[None], device="cpu", shifts=0, split=True,
                              overlap=0.25, progress=False, num_workers=0)[0]
    drums = (sources[model.sources.index("drums")] * scale + mean).T.numpy()
    peak = float(np.max(np.abs(drums)))
    if peak > 1:
        drums = drums / peak
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, drums, model.samplerate, subtype="FLOAT")
    return out


def adtof_activations(audio, out_path):
    """Frame-wise (100 fps) activations for the five ADTOF classes."""
    out_path = Path(out_path)
    if out_path.is_file():
        return np.load(out_path)
    import adtof_pytorch as adtof
    import torch

    model = adtof.create_frame_rnn_model(adtof.calculate_n_bins())
    model = adtof.load_pytorch_weights(model, adtof.get_default_weights_path(), strict=True).eval()
    with torch.no_grad():
        activations = model(adtof.load_audio_for_model(str(audio))).cpu().numpy()[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, activations)
    return activations


def pick_peaks(activations, thresholds=DEFAULT_THRESHOLDS):
    """Events with the peak activation kept as a confidence value."""
    import adtof_pytorch as adtof

    peaks = adtof.PeakPicker(thresholds=list(thresholds), fps=ADTOF_FPS).pick(activations[None], labels=adtof.LABELS_5)[0]
    pitch_to_class = dict(zip(adtof.LABELS_5, CLASSES))
    events = []
    for pitch, times in peaks.items():
        column = CLASSES.index(pitch_to_class[pitch])
        for time in times:
            frame = min(int(round(time * ADTOF_FPS)), len(activations) - 1)
            confidence = float(activations[max(0, frame - 1):frame + 2, column].max())
            events.append({"time": round(float(time), 4), "class": pitch_to_class[pitch], "confidence": round(confidence, 3)})
    return sorted(events, key=lambda e: (e["time"], e["class"]))


def track_beats(audio, out_path, models_dir):
    """Beat This! beats/downbeats plus the frame activations used for meter decisions."""
    out_path = Path(out_path)
    if out_path.is_file():
        return json.loads(out_path.read_text(encoding="utf-8"))
    import torch
    from beat_this.inference import Audio2Frames
    from beat_this.model.postprocessor import Postprocessor

    weights = fetch_weights(BEAT_THIS_URLS, BEAT_THIS_SHA256, Path(models_dir) / "beat_this/final0.ckpt")
    signal = decode(audio, 22050, 1)[0]
    model = Audio2Frames(checkpoint_path=str(weights), device="cpu", float16=False)
    beat_logits, downbeat_logits = model(signal, 22050)
    beats, downbeats = Postprocessor(type="minimal")(beat_logits, downbeat_logits)
    result = {
        "fps": BEAT_FPS,
        "duration_seconds": len(signal) / 22050,
        "beats": [round(float(t), 4) for t in beats],
        "downbeats": [round(float(t), 4) for t in downbeats],
        "beat_activation": np.round(torch.sigmoid(beat_logits).cpu().numpy(), 4).tolist(),
        "downbeat_activation": np.round(torch.sigmoid(downbeat_logits).cpu().numpy(), 4).tolist(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result), encoding="utf-8")
    return result


def analyze(audio, cache_root, models_dir, separate=True):
    """Run (or reuse) every model stage for one audio file."""
    audio = Path(audio).resolve()
    folder = Path(cache_root) / sha256(audio)[:16]
    folder.mkdir(parents=True, exist_ok=True)
    drums = separate_drums(audio, folder, models_dir) if separate else audio
    stem_activations = adtof_activations(drums, folder / ("adtof_drums.npy" if separate else "adtof_mix.npy"))
    # Toms and cymbals are detected better on the full mix (phase 1, 3.1).
    mix_activations = adtof_activations(audio, folder / "adtof_mix.npy")
    beats = track_beats(audio, folder / "beats.json", models_dir)
    return {"folder": str(folder), "audio": str(audio), "drums": str(drums),
            "stem_activations": stem_activations, "mix_activations": mix_activations, "beats": beats}

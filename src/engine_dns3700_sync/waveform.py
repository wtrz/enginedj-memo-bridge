from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

WAVEFORM_COLUMNS = 320


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def calculate_waveform(path: Path, sample_rate: int, ddj_duration: int) -> bytes:
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg was not found on PATH")

    command = [
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(sample_rate),
        "-ac", "2", "pipe:1",
    ]
    try:
        raw = subprocess.check_output(command)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg could not decode {path.name}") from exc

    audio = np.frombuffer(raw, dtype="<f4")
    if audio.size == 0 or audio.size % 2:
        raise RuntimeError(f"ffmpeg returned invalid audio for {path.name}")
    audio = audio.reshape(-1, 2)

    target_samples = round((ddj_duration / 75.0) * sample_rate)
    if len(audio) < target_samples:
        audio = np.pad(audio, ((0, target_samples - len(audio)), (0, 0)))
    else:
        audio = audio[:target_samples]

    magnitude = np.max(np.abs(audio), axis=1)
    edges = np.linspace(0, len(magnitude), WAVEFORM_COLUMNS + 1).astype(int)
    values: list[int] = []
    for index in range(WAVEFORM_COLUMNS):
        segment = magnitude[edges[index] : edges[index + 1]]
        if segment.size == 0:
            values.append(1)
            continue
        rms = float(np.sqrt(np.mean(segment * segment)))
        p95 = float(np.percentile(segment, 95))
        peak = float(np.max(segment))
        score = max(p95, rms * 1.25, peak * 0.70)
        values.append(max(1, min(15, round(10.0 * score + 1.0))))
    return bytes(values)

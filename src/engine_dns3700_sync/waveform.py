from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
import struct
import zlib
from pathlib import Path

import numpy as np

WAVEFORM_COLUMNS = 320
LOW_BAND_HZ = (20.0, 500.0)
MID_BAND_HZ = (500.0, 2000.0)
HIGH_BAND_HZ = (2000.0, 20000.0)


@dataclass
class EngineOverviewWaveform:
    points: list[tuple[int, int, int]]
    samples_per_point: float
    maximum_point: tuple[int, int, int] = (255, 255, 255)


def decode_ddm_waveform(value: str | bytes | None) -> list[int]:
    if value is None:
        return []
    raw = value if isinstance(value, bytes) else value.encode("latin-1", errors="replace")
    return list(raw)


def waveform_markers_from_sample_offsets(sample_offsets: list[float], total_samples: float) -> list[float]:
    if total_samples <= 0:
        return []
    return [min(max(sample_offset / total_samples, 0.0), 1.0) for sample_offset in sample_offsets if sample_offset >= 0]


def ddj_markers_from_positions(position_values: list[str], ddj_duration: int) -> list[float]:
    if ddj_duration <= 0:
        return []
    total_seconds = ddj_duration / 75.0
    if total_seconds <= 0:
        return []
    markers: list[float] = []
    for value in position_values:
        if not value:
            continue
        try:
            position = int(value)
        except (TypeError, ValueError):
            continue
        seconds = max(position, 0) / 900.0
        markers.append(min(max(seconds / total_seconds, 0.0), 1.0))
    return markers


def _band_mask(frequencies: np.ndarray, low_hz: float, high_hz: float) -> np.ndarray:
    return (frequencies >= low_hz) & (frequencies < high_hz)


def _window_band_levels(segment: np.ndarray, sample_rate: int) -> tuple[float, float, float, float]:
    if segment.size == 0:
        return (0.0, 0.0, 0.0, 0.0)
    mono = np.mean(segment.astype(np.float32), axis=1)
    if mono.size == 0:
        return (0.0, 0.0, 0.0, 0.0)

    broadband_rms = float(np.sqrt(np.mean(mono * mono)))
    if mono.size < 8:
        return (broadband_rms, broadband_rms, broadband_rms, broadband_rms)

    window = np.hanning(mono.size).astype(np.float32)
    spectrum = np.fft.rfft(mono * window)
    magnitudes = np.abs(spectrum)
    frequencies = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)

    def band_level(bounds: tuple[float, float]) -> float:
        mask = _band_mask(frequencies, bounds[0], bounds[1])
        if not np.any(mask):
            return 0.0
        values = magnitudes[mask]
        energy = float(np.sqrt(np.mean(values * values)))
        peak = float(np.max(values))
        return max(energy, peak * 0.35)

    return (
        broadband_rms,
        band_level(LOW_BAND_HZ),
        band_level(MID_BAND_HZ),
        band_level(HIGH_BAND_HZ),
    )


def _normalise_levels(levels: list[tuple[float, float, float, float]]) -> list[int]:
    if not levels:
        return []
    array = np.asarray(levels, dtype=np.float64)
    broadband = array[:, 0]
    low = array[:, 1]
    mid = array[:, 2]
    high = array[:, 3]

    def norm(values: np.ndarray) -> np.ndarray:
        if not np.any(values > 0):
            return np.zeros_like(values)
        reference = max(float(np.percentile(values, 95)), float(np.max(values)) * 0.35, 1e-9)
        return np.clip(values / reference, 0.0, 1.35)

    broadband_n = norm(broadband)
    low_n = norm(low)
    mid_n = norm(mid)
    high_n = norm(high)

    score = (
        broadband_n * 0.45
        + low_n * 0.20
        + mid_n * 0.22
        + high_n * 0.13
    )
    score = np.power(np.clip(score, 0.0, 1.0), 0.82)
    quantized = np.clip(np.rint(1.0 + score * 14.0), 1, 15).astype(np.uint8)
    return quantized.tolist()


def _qt_zlib_uncompress(blob: bytes) -> bytes:
    if not blob:
        return b""
    if len(blob) < 4:
        raise RuntimeError("Engine overview waveform blob is shorter than 4 bytes")
    expected_size = int.from_bytes(blob[:4], "big", signed=True)
    payload = zlib.decompress(blob[4:])
    if expected_size >= 0 and len(payload) != expected_size:
        raise RuntimeError("Engine overview waveform blob length does not match header")
    return payload


def decode_engine_overview_waveform(blob: bytes | None) -> EngineOverviewWaveform:
    if not blob:
        return EngineOverviewWaveform([], 0.0)
    data = _qt_zlib_uncompress(bytes(blob))
    if len(data) < 24:
        return EngineOverviewWaveform([], 0.0)

    point_count_1 = int.from_bytes(data[0:8], "big", signed=True)
    point_count_2 = int.from_bytes(data[8:16], "big", signed=True)
    if point_count_1 != point_count_2 or point_count_1 < 0:
        raise RuntimeError("Engine overview waveform blob has conflicting length fields")

    samples_per_point = struct.unpack(">d", data[16:24])[0]
    point_count = point_count_1
    point_data_length = 3 * point_count
    expected_length = 24 + point_data_length
    if len(data) < expected_length:
        raise RuntimeError("Engine overview waveform blob is shorter than expected")

    offset = 24
    points: list[tuple[int, int, int]] = []
    for index in range(point_count):
        start = offset + index * 3
        end = start + 3
        low, mid, high = data[start:end]
        points.append((low, mid, high))

    maximum_point = (255, 255, 255)
    remaining = data[offset + point_data_length :]
    if len(remaining) >= 3:
        maximum_point = (remaining[0], remaining[1], remaining[2])
    elif points:
        maximum_point = (
            max(point[0] for point in points),
            max(point[1] for point in points),
            max(point[2] for point in points),
        )
    return EngineOverviewWaveform(points, samples_per_point, maximum_point)


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

    edges = np.linspace(0, len(audio), WAVEFORM_COLUMNS + 1).astype(int)
    levels: list[tuple[float, float, float, float]] = []
    for index in range(WAVEFORM_COLUMNS):
        segment = audio[edges[index] : edges[index + 1]]
        levels.append(_window_band_levels(segment, sample_rate))
    return bytes(_normalise_levels(levels))

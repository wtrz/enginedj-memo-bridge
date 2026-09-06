import struct
import zlib

import numpy as np

from enginedj_memo_bridge.waveform import (
    _normalise_levels,
    _window_band_levels,
    ddj_markers_from_positions,
    decode_ddm_waveform,
    decode_engine_overview_waveform,
    waveform_markers_from_sample_offsets,
)


def _wrap_qt_zlib(payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big", signed=True) + zlib.compress(payload)


def test_decode_engine_overview_waveform_reads_points_and_maximum_point():
    payload = (
        (2).to_bytes(8, "big", signed=True)
        + (2).to_bytes(8, "big", signed=True)
        + struct.pack(">d", 512.0)
        + bytes([10, 20, 30, 40, 50, 60])
        + bytes([90, 100, 110])
    )

    waveform = decode_engine_overview_waveform(_wrap_qt_zlib(payload))

    assert waveform.samples_per_point == 512.0
    assert waveform.points == [(10, 20, 30), (40, 50, 60)]
    assert waveform.maximum_point == (90, 100, 110)


def test_decode_ddm_waveform_returns_byte_values():
    assert decode_ddm_waveform("\x01\x0f") == [1, 15]


def test_waveform_markers_from_sample_offsets_normalizes_positions():
    assert waveform_markers_from_sample_offsets([0.0, 500.0, 1000.0, 2000.0], 1000.0) == [0.0, 0.5, 1.0, 1.0]


def test_window_band_levels_emphasizes_matching_frequency_band():
    sample_rate = 44100
    samples = np.arange(sample_rate // 5, dtype=np.float32)
    tone = np.sin(2.0 * np.pi * 1200.0 * samples / sample_rate).astype(np.float32)
    stereo = np.column_stack((tone, tone))

    broadband, low, mid, high = _window_band_levels(stereo, sample_rate)

    assert broadband > 0
    assert mid > low
    assert mid > high


def test_normalise_levels_returns_ddj_waveform_byte_range():
    values = _normalise_levels([
        (0.1, 0.1, 0.0, 0.0),
        (0.3, 0.0, 0.5, 0.0),
        (0.8, 0.2, 0.1, 0.7),
    ])

    assert len(values) == 3
    assert all(1 <= value <= 15 for value in values)
    assert values[0] < values[1] < values[2]


def test_normalise_levels_preserves_contrast_between_quiet_and_loud_sections():
    values = _normalise_levels([
        (0.03, 0.02, 0.01, 0.00),
        (0.10, 0.07, 0.04, 0.01),
        (0.45, 0.25, 0.20, 0.08),
        (0.95, 0.50, 0.40, 0.15),
    ])

    assert values[0] <= 2
    assert values[1] < values[2]
    assert values[2] <= 11
    assert values[3] >= 13


def test_ddj_markers_from_positions_uses_id3_cue_units_and_duration():
    markers = ddj_markers_from_positions(["900", "1800", "", "bad", "3600"], 300)

    assert markers == [0.25, 0.5, 1.0]
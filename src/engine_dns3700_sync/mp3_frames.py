from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MpegInfo:
    frame_count: int
    sample_rate: int
    samples_per_frame: int
    ddj_duration: int
    bitrates_kbps: frozenset[int]

    @property
    def is_vbr(self) -> bool:
        return len(self.bitrates_kbps) > 1


BITRATES = {
    ("1", "III"): [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None],
    ("1", "II"): [None, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, None],
    ("1", "I"): [None, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, None],
    ("2", "III"): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
    ("2", "II"): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
    ("2", "I"): [None, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, None],
}

SAMPLE_RATES = {
    "1": [44100, 48000, 32000, None],
    "2": [22050, 24000, 16000, None],
    "2.5": [11025, 12000, 8000, None],
}


def _skip_id3v2(data: bytes) -> int:
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    size = (
        ((data[6] & 0x7F) << 21)
        | ((data[7] & 0x7F) << 14)
        | ((data[8] & 0x7F) << 7)
        | (data[9] & 0x7F)
    )
    footer = 10 if data[5] & 0x10 else 0
    return 10 + size + footer


def _parse_header(header: bytes) -> dict[str, int | str] | None:
    if len(header) != 4:
        return None
    value = int.from_bytes(header, "big")
    if (value & 0xFFE00000) != 0xFFE00000:
        return None

    version = {0b00: "2.5", 0b10: "2", 0b11: "1"}.get((value >> 19) & 0b11)
    layer = {0b01: "III", 0b10: "II", 0b11: "I"}.get((value >> 17) & 0b11)
    if not version or not layer:
        return None

    bitrate_index = (value >> 12) & 0xF
    sample_rate_index = (value >> 10) & 0x3
    padding = (value >> 9) & 1
    table_version = "1" if version == "1" else "2"
    bitrate = BITRATES[(table_version, layer)][bitrate_index]
    sample_rate = SAMPLE_RATES[version][sample_rate_index]
    if not bitrate or not sample_rate:
        return None

    if layer == "I":
        frame_size = int(((12 * bitrate * 1000) / sample_rate + padding) * 4)
        samples_per_frame = 384
    elif layer == "III" and version != "1":
        frame_size = int((72 * bitrate * 1000) / sample_rate + padding)
        samples_per_frame = 576
    else:
        frame_size = int((144 * bitrate * 1000) / sample_rate + padding)
        samples_per_frame = 1152

    return {
        "frame_size": frame_size,
        "samples_per_frame": samples_per_frame,
        "sample_rate": sample_rate,
        "bitrate": bitrate,
    }


def inspect_mp3(path: Path) -> MpegInfo:
    data = path.read_bytes()
    position = _skip_id3v2(data)
    end = len(data)
    if end >= 128 and data[end - 128 : end - 125] == b"TAG":
        end -= 128

    count = 0
    sample_rate = 0
    samples_per_frame = 0
    bitrates: set[int] = set()

    while position + 4 <= end:
        header = _parse_header(data[position : position + 4])
        if not header:
            position += 1
            continue
        frame_size = int(header["frame_size"])
        if frame_size <= 0 or position + frame_size > end:
            break
        count += 1
        sample_rate = int(header["sample_rate"])
        samples_per_frame = int(header["samples_per_frame"])
        bitrates.add(int(header["bitrate"]))
        position += frame_size

    if count == 0 or sample_rate == 0 or samples_per_frame == 0:
        raise ValueError(f"No valid MPEG audio frames found in {path}")

    ddj_duration = int(count * samples_per_frame * 75 / sample_rate)
    return MpegInfo(
        frame_count=count,
        sample_rate=sample_rate,
        samples_per_frame=samples_per_frame,
        ddj_duration=ddj_duration,
        bitrates_kbps=frozenset(bitrates),
    )

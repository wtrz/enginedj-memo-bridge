from __future__ import annotations

import math
import struct
import zlib

from .models import Color, QuickCue, SavedLoop


class BlobDecodeError(ValueError):
    pass


def _require(data: bytes, offset: int, length: int, context: str) -> None:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise BlobDecodeError(f"Truncated {context} at byte {offset}")


def qt_zlib_uncompress(blob: bytes) -> bytes:
    if not blob:
        return b""
    if len(blob) < 4:
        raise BlobDecodeError("Compressed Engine blob is shorter than four bytes")
    expected_size = int.from_bytes(blob[:4], "big", signed=True)
    if expected_size < 0 or expected_size > 100_000_000:
        raise BlobDecodeError(f"Implausible Engine blob size: {expected_size}")
    try:
        result = zlib.decompress(blob[4:])
    except zlib.error as exc:
        raise BlobDecodeError(f"Could not decompress Engine blob: {exc}") from exc
    if len(result) != expected_size:
        raise BlobDecodeError(
            f"Engine blob size mismatch: expected {expected_size}, got {len(result)}"
        )
    return result


def parse_quick_cues(blob: bytes | None) -> tuple[list[QuickCue], float | None]:
    if not blob:
        return [], None
    data = qt_zlib_uncompress(bytes(blob))
    if len(data) < 25:
        raise BlobDecodeError("Quick-cue blob is shorter than 25 bytes")

    offset = 0
    count = struct.unpack_from(">q", data, offset)[0]
    offset += 8
    if count < 0 or count > 64:
        raise BlobDecodeError(f"Implausible quick-cue count: {count}")

    cues: list[QuickCue] = []
    for slot in range(1, count + 1):
        _require(data, offset, 1, "quick-cue label length")
        label_length = data[offset]
        offset += 1
        _require(data, offset, label_length + 12, "quick cue")
        label = data[offset : offset + label_length].decode("utf-8", errors="replace")
        offset += label_length
        sample_offset = struct.unpack_from(">d", data, offset)[0]
        offset += 8
        color = Color(*data[offset : offset + 4])
        offset += 4

        # Empty Engine slots commonly carry a non-useful non-positive value.
        if math.isfinite(sample_offset) and (sample_offset > 0 or bool(label)):
            cues.append(
                QuickCue(
                    slot=slot,
                    sample_offset=sample_offset,
                    label=label,
                    color=color,
                )
            )

    _require(data, offset, 17, "main cue")
    adjusted_main_cue = struct.unpack_from(">d", data, offset)[0]
    offset += 8
    is_adjusted = bool(data[offset])
    offset += 1
    default_main_cue = struct.unpack_from(">d", data, offset)[0]

    selected = adjusted_main_cue if is_adjusted else default_main_cue
    main_cue = selected if math.isfinite(selected) and selected >= 0 else None
    return cues, main_cue


def parse_loops(blob: bytes | None) -> list[SavedLoop]:
    if not blob:
        return []
    data = bytes(blob)
    if len(data) < 8:
        raise BlobDecodeError("Loop blob is shorter than eight bytes")

    offset = 0
    count = struct.unpack_from("<q", data, offset)[0]
    offset += 8
    if count < 0 or count > 64:
        raise BlobDecodeError(f"Implausible loop count: {count}")

    loops: list[SavedLoop] = []
    for slot in range(1, count + 1):
        _require(data, offset, 1, "loop label length")
        label_length = data[offset]
        offset += 1
        _require(data, offset, label_length + 22, "saved loop")
        label = data[offset : offset + label_length].decode("utf-8", errors="replace")
        offset += label_length
        start = struct.unpack_from("<d", data, offset)[0]
        offset += 8
        end = struct.unpack_from("<d", data, offset)[0]
        offset += 8
        is_start_set = bool(data[offset])
        is_end_set = bool(data[offset + 1])
        offset += 2
        color = Color(*data[offset : offset + 4])
        offset += 4

        if (
            is_start_set
            and is_end_set
            and math.isfinite(start)
            and math.isfinite(end)
            and start >= 0
            and end > start
        ):
            loops.append(
                SavedLoop(
                    slot=slot,
                    start_sample_offset=start,
                    end_sample_offset=end,
                    is_start_set=is_start_set,
                    is_end_set=is_end_set,
                    label=label,
                    color=color,
                )
            )
    return loops

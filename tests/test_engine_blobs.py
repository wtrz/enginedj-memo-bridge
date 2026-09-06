import struct
import zlib

from enginedj_memo_bridge.engine_blobs import parse_loops, parse_quick_cues


def compressed(payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big", signed=True) + zlib.compress(payload)


def test_quick_cue_blob():
    payload = bytearray()
    payload += struct.pack(">q", 2)
    payload += bytes([3]) + b"One" + struct.pack(">d", 44100.0) + bytes([255, 1, 2, 3])
    payload += bytes([3]) + b"Two" + struct.pack(">d", 88200.0) + bytes([255, 4, 5, 6])
    payload += struct.pack(">d", 22050.0)
    payload += bytes([1])
    payload += struct.pack(">d", 0.0)
    cues, main = parse_quick_cues(compressed(bytes(payload)))
    assert [cue.slot for cue in cues] == [1, 2]
    assert cues[1].sample_offset == 88200.0
    assert main == 22050.0


def test_loop_blob():
    payload = bytearray()
    payload += struct.pack("<q", 1)
    payload += bytes([4]) + b"Loop"
    payload += struct.pack("<d", 44100.0)
    payload += struct.pack("<d", 88200.0)
    payload += bytes([1, 1, 255, 10, 20, 30])
    loops = parse_loops(bytes(payload))
    assert len(loops) == 1
    assert loops[0].slot == 1
    assert loops[0].start_sample_offset == 44100.0

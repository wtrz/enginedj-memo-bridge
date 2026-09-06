from pathlib import Path

from enginedj_memo_bridge.models import EngineTrack, ExistingTags, ScanResult, SlotMappings, SyncOptions, TagPlan
from enginedj_memo_bridge.mp3_frames import MpegInfo
from enginedj_memo_bridge.sync_service import SyncService
from enginedj_memo_bridge.sync_service import _current_denon_fields, _planned_denon_fields


def test_wave_fields_keep_raw_value_and_display_summary():
    existing = ExistingTags(3, {"DDM/WAVE": "\x01\x02\x03"}, {}, 3)

    current = _current_denon_fields(existing)

    assert current["DDM/WAVE"] == "invalid (3 bytes)"
    assert current["DDM/WAVE_DISPLAY"] == "invalid (3 bytes)"


def test_planned_wave_fields_include_display_summary():
    plan = TagPlan(txxx={"DDM/WAVE": "\x01\x02"}, standard_text={})

    planned = _planned_denon_fields(plan)

    assert planned["DDM/WAVE"] == "\x01\x02"
    assert planned["DDM/WAVE_DISPLAY"] == "2 bytes"


def test_sync_only_processes_selected_update_rows(monkeypatch):
    written: list[Path] = []

    def fake_write_plan_atomic(path, plan, options):
        written.append(path)

    monkeypatch.setattr("enginedj_memo_bridge.sync_service.inspect_mp3", lambda path: MpegInfo(1000, 44100, 1152, 75, frozenset({320})))
    monkeypatch.setattr("enginedj_memo_bridge.sync_service.read_existing_tags", lambda path: ExistingTags(3, {}, {}))
    monkeypatch.setattr("enginedj_memo_bridge.sync_service.write_plan_atomic", fake_write_plan_atomic)

    tracks = [
        EngineTrack("1", "db", Path("selected.mp3")),
        EngineTrack("2", "db", Path("unselected.mp3")),
        EngineTrack("3", "db", Path("up-to-date.mp3")),
    ]
    results = [
        ScanResult(tracks[0], "Update required", True, selected=True),
        ScanResult(tracks[1], "Update required", True, selected=False),
        ScanResult(tracks[2], "Up to date", False, selected=True),
    ]

    options = SyncOptions(write_waveform_if_missing=False)
    completed = SyncService(Path("library.db"), SlotMappings.defaults(), options).sync(results)

    assert written == [Path("selected.mp3")]
    assert [result.track.path for result in completed] == [Path("selected.mp3")]
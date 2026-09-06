from pathlib import Path

from enginedj_memo_bridge.models import EngineTrack, QuickCue, SavedLoop, SlotMappings, SourceKind, SyncOptions
from enginedj_memo_bridge.sync_service import _resolved_mappings


def test_smart_mapping_prefers_main_then_hot_cues_then_loop_one_for_ab():
    track = EngineTrack(
        origin_id="1",
        origin_database_uuid="db",
        path=Path("track.mp3"),
        main_cue_sample_offset=100.0,
        quick_cues=[QuickCue(2, 200.0), QuickCue(5, 500.0)],
        loops=[SavedLoop(1, 300.0, 400.0, True, True), SavedLoop(3, 600.0, 700.0, True, True)],
    )

    resolved = _resolved_mappings(track, SlotMappings.defaults(), SyncOptions(smart_mapping=True))

    assert resolved.cue.kind is SourceKind.MAIN_CUE
    assert resolved.slot_1.kind is SourceKind.HOT_CUE and resolved.slot_1.index == 2
    assert resolved.slot_2.kind is SourceKind.HOT_CUE and resolved.slot_2.index == 5
    assert resolved.slot_3.kind is SourceKind.SAVED_LOOP and resolved.slot_3.index == 1
    assert resolved.ab_loop.kind is SourceKind.SAVED_LOOP and resolved.ab_loop.index == 1


def test_smart_mapping_leaves_loop_slots_empty_when_experimental_loops_disabled():
    track = EngineTrack(
        origin_id="1",
        origin_database_uuid="db",
        path=Path("track.mp3"),
        quick_cues=[QuickCue(4, 200.0)],
        loops=[SavedLoop(2, 300.0, 400.0, True, True)],
    )

    resolved = _resolved_mappings(
        track,
        SlotMappings.defaults(),
        SyncOptions(smart_mapping=True, experimental_auto_loops=False),
    )

    assert resolved.slot_1.kind is SourceKind.HOT_CUE and resolved.slot_1.index == 4
    assert resolved.slot_2.kind is SourceKind.NONE
    assert resolved.slot_3.kind is SourceKind.NONE
    assert resolved.ab_loop.kind is SourceKind.SAVED_LOOP and resolved.ab_loop.index == 2
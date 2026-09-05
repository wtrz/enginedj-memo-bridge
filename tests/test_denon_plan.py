from pathlib import Path

from engine_dns3700_sync.denon_tags import build_tag_plan
from engine_dns3700_sync.models import (
    EngineTrack,
    ExistingTags,
    MappingSource,
    QuickCue,
    SavedLoop,
    SlotMappings,
    SourceKind,
    SyncOptions,
)
from engine_dns3700_sync.mp3_frames import MpegInfo


def test_mapping_to_denon_frames():
    track = EngineTrack(
        origin_id="1",
        origin_database_uuid="db",
        path=Path("track.mp3"),
        bpm=128.0,
        main_cue_sample_offset=44100.0,
        quick_cues=[QuickCue(8, 88200.0, "HC8")],
        loops=[SavedLoop(6, 132300.0, 220500.0, True, True, "L6")],
    )
    mappings = SlotMappings(
        cue=MappingSource(SourceKind.MAIN_CUE),
        slot_1=MappingSource(SourceKind.HOT_CUE, 8),
        slot_2=MappingSource(SourceKind.SAVED_LOOP, 6),
        slot_3=MappingSource(SourceKind.NONE),
        ab_loop=MappingSource(SourceKind.SAVED_LOOP, 6),
    )
    mpeg = MpegInfo(1000, 44100, 1152, 1959, frozenset({320}))
    plan = build_tag_plan(track, mpeg, mappings, SyncOptions(), ExistingTags(3, {}, {}))
    assert plan.txxx["DDJ/CUET"] == "900"
    assert plan.txxx["DDJ/H1PT"] == "1800"
    assert plan.txxx["DDJ/H2PT"] == "2700"
    assert plan.txxx["DDJ/H2AP"] == "1280"
    assert "DDJ/H2BT" not in plan.txxx
    assert "DDJ/H2LN" not in plan.txxx
    assert "DDJ/H2SZ" not in plan.txxx
    assert plan.txxx["DDJ/L1AT"] == "2700"
    assert plan.txxx["DDJ/L1BT"] == "4500"
    assert plan.txxx["DDJ/STUP"].endswith("1 2 0 ")
    assert plan.standard_text["TBPM"] == "01280"
    assert not any("Auto Loop stores start+BPM only" in warning for warning in plan.warnings)

from engine_dns3700_sync.models import ExistingTags, TagPlan
from engine_dns3700_sync.sync_service import _current_denon_fields, _planned_denon_fields


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
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from .denon_tags import build_tag_plan, plan_differences, read_existing_tags, write_plan_atomic
from .engine_db import EngineDatabase
from .models import MappingSource, ScanResult, SlotMappings, SourceKind, SyncOptions
from .mp3_frames import inspect_mp3
from .waveform import calculate_waveform

ProgressCallback = Callable[[int, int, str], None]


def _wave_status(existing) -> str:
    if existing.waveform_length is None:
        return "missing"
    if existing.waveform_length == 320:
        return "320 bytes"
    return f"invalid ({existing.waveform_length} bytes)"


def _current_denon_fields(existing) -> dict[str, str]:
    txxx = existing.txxx
    loop_parts = [part for part in (txxx.get("DDJ/L1AT", ""), txxx.get("DDJ/L1BT", "")) if part]
    return {
        "DDJ/CUET": txxx.get("DDJ/CUET", ""),
        "DDJ/H1PT": txxx.get("DDJ/H1PT", ""),
        "DDJ/H2PT": txxx.get("DDJ/H2PT", ""),
        "DDJ/H3PT": txxx.get("DDJ/H3PT", ""),
        "DDJ/L1AT_L1BT": " / ".join(loop_parts),
        "DDJ/STUP": txxx.get("DDJ/STUP", ""),
        "DDM/WAVE": _wave_status(existing),
    }


def _planned_denon_fields(plan) -> dict[str, str]:
    txxx = plan.txxx
    loop_parts = [part for part in (txxx.get("DDJ/L1AT", ""), txxx.get("DDJ/L1BT", "")) if part]
    return {
        "DDJ/CUET": txxx.get("DDJ/CUET", ""),
        "DDJ/H1PT": txxx.get("DDJ/H1PT", ""),
        "DDJ/H2PT": txxx.get("DDJ/H2PT", ""),
        "DDJ/H3PT": txxx.get("DDJ/H3PT", ""),
        "DDJ/L1AT_L1BT": " / ".join(loop_parts),
        "DDJ/STUP": txxx.get("DDJ/STUP", ""),
        "DDM/WAVE": "320 bytes" if "DDM/WAVE" in txxx else "missing",
    }


def _none_source() -> MappingSource:
    return MappingSource(SourceKind.NONE)


def _smart_mappings(track, options: SyncOptions) -> SlotMappings:
    hot_cues = sorted(track.quick_cues, key=lambda cue: cue.slot)
    loops = sorted(track.loops, key=lambda loop: loop.slot)

    if track.main_cue_sample_offset is not None:
        cue = MappingSource(SourceKind.MAIN_CUE)
    elif hot_cues:
        cue = MappingSource(SourceKind.HOT_CUE, hot_cues[0].slot)
    elif loops:
        cue = MappingSource(SourceKind.SAVED_LOOP, loops[0].slot)
    else:
        cue = _none_source()

    slot_sources: list[MappingSource] = [
        MappingSource(SourceKind.HOT_CUE, cue_item.slot) for cue_item in hot_cues[:3]
    ]
    if options.experimental_auto_loops and len(slot_sources) < 3:
        needed = 3 - len(slot_sources)
        slot_sources.extend(
            MappingSource(SourceKind.SAVED_LOOP, loop.slot) for loop in loops[:needed]
        )
    while len(slot_sources) < 3:
        slot_sources.append(_none_source())

    loop_one = next((loop for loop in loops if loop.slot == 1), None)
    ab_loop = MappingSource(SourceKind.SAVED_LOOP, loop_one.slot) if loop_one else (
        MappingSource(SourceKind.SAVED_LOOP, loops[0].slot) if loops else _none_source()
    )

    return SlotMappings(
        cue=cue,
        slot_1=slot_sources[0],
        slot_2=slot_sources[1],
        slot_3=slot_sources[2],
        ab_loop=ab_loop,
    )


def _resolved_mappings(track, mappings: SlotMappings, options: SyncOptions) -> SlotMappings:
    return _smart_mappings(track, options) if options.smart_mapping else mappings


def _mapping_summary(mappings: SlotMappings) -> str:
    return ", ".join([
        f"cue={mappings.cue.label}",
        f"s1={mappings.slot_1.label}",
        f"s2={mappings.slot_2.label}",
        f"s3={mappings.slot_3.label}",
        f"ab={mappings.ab_loop.label}",
    ])


class SyncService:
    def __init__(self, database_path: Path, mappings: SlotMappings, options: SyncOptions):
        self.database = EngineDatabase(database_path)
        self.mappings = mappings
        self.options = options

    def scan(
        self,
        since: datetime | None,
        playlist_id: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> list[ScanResult]:
        tracks = self.database.fetch_tracks_modified_since(since, playlist_id)
        results: list[ScanResult] = []
        total = len(tracks)
        for index, track in enumerate(tracks, start=1):
            if progress:
                progress(index, total, track.path.name or track.title)
            results.append(self._scan_track(track))
        return results

    def _scan_track(self, track) -> ScanResult:
        if not track.path or not track.path.exists():
            return ScanResult(track, "Missing file", False, warnings=track.warnings, error=str(track.path))
        if track.path.suffix.lower() != ".mp3":
            return ScanResult(track, "Unsupported", False, warnings=track.warnings, error="MVP supports MP3 only")
        try:
            mpeg = inspect_mp3(track.path)
            existing = read_existing_tags(track.path)
            if not track.sample_rate:
                track.sample_rate = mpeg.sample_rate
            mappings = _resolved_mappings(track, self.mappings, self.options)
            plan = build_tag_plan(track, mpeg, mappings, self.options, existing, waveform=None)
            differences = plan_differences(plan, existing)
            if self.options.force_regenerate_waveform:
                differences.append("DDM/WAVE regenerate")
            elif self.options.write_waveform_if_missing and existing.waveform_length != 320:
                differences.append("DDM/WAVE missing/invalid")
            needs_update = bool(differences)
            return ScanResult(
                track=track,
                status="Update required" if needs_update else "Up to date",
                needs_update=needs_update,
                differences=sorted(set(differences + [_mapping_summary(mappings)] if self.options.smart_mapping else differences)),
                planned_fields=_planned_denon_fields(plan),
                current_fields=_current_denon_fields(existing),
                warnings=plan.warnings,
            )
        except Exception as exc:
            return ScanResult(track, "Error", False, warnings=track.warnings, error=str(exc))

    def sync(
        self,
        results: list[ScanResult],
        progress: ProgressCallback | None = None,
    ) -> list[ScanResult]:
        selected = [result for result in results if result.selected and result.needs_update]
        total = len(selected)
        completed: list[ScanResult] = []
        for index, result in enumerate(selected, start=1):
            track = result.track
            if progress:
                progress(index, total, track.path.name or track.title)
            try:
                mpeg = inspect_mp3(track.path)
                if not track.sample_rate:
                    track.sample_rate = mpeg.sample_rate
                existing = read_existing_tags(track.path)
                waveform = None
                needs_waveform = (
                    self.options.force_regenerate_waveform
                    or (self.options.write_waveform_if_missing and existing.waveform_length != 320)
                )
                if needs_waveform:
                    waveform = calculate_waveform(track.path, mpeg.sample_rate, mpeg.ddj_duration)
                mappings = _resolved_mappings(track, self.mappings, self.options)
                plan = build_tag_plan(track, mpeg, mappings, self.options, existing, waveform)
                write_plan_atomic(track.path, plan, self.options)
                completed.append(
                    ScanResult(track, "Synced", False, warnings=plan.warnings, differences=[])
                )
            except Exception as exc:
                completed.append(
                    ScanResult(track, "Error", True, warnings=result.warnings, error=str(exc))
                )
        return completed

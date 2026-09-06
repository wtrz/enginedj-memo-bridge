from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from mutagen.id3 import (
    ID3,
    ID3NoHeaderError,
    TALB,
    TBPM,
    TCON,
    TIT2,
    TKEY,
    TPE1,
    TRCK,
    TXXX,
    Encoding,
)

from .models import (
    EngineTrack,
    ExistingTags,
    MappingSource,
    SlotMappings,
    SourceKind,
    SyncOptions,
    TagPlan,
)
from .mp3_frames import MpegInfo

DENON_TXXX = {
    "DDJ/VER", "DDJ/DUR", "DDJ/CUET", "DDJ/STUP", "DDJ/L1AT", "DDJ/L1BT",
    "DDJ/L1AP", "DDJ/H1PT", "DDJ/H1AP", "DDJ/H2PT",
    "DDJ/H2AP", "DDJ/H3PT", "DDJ/H3AP", "DDM/WAVE",
}

STANDARD_FRAME_MAP = {
    "TIT2": TIT2,
    "TPE1": TPE1,
    "TALB": TALB,
    "TCON": TCON,
    "TRCK": TRCK,
    "TKEY": TKEY,
    "TBPM": TBPM,
}


def read_existing_tags(path: Path) -> ExistingTags:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return ExistingTags(None, {}, {})

    txxx: dict[str, str] = {}
    waveform_length = None
    for frame in tags.getall("TXXX"):
        value = frame.text[0] if frame.text else ""
        txxx[frame.desc] = value
        if frame.desc == "DDM/WAVE":
            waveform_length = len(value.encode("latin-1", errors="replace"))

    standard: dict[str, str] = {}
    for frame_id in STANDARD_FRAME_MAP:
        frames = tags.getall(frame_id)
        if frames and getattr(frames[0], "text", None):
            standard[frame_id] = str(frames[0].text[0])

    version = tags.version[1] if tags.version and tags.version[1] in {3, 4} else None
    return ExistingTags(version, txxx, standard, waveform_length)


def _seconds(sample_offset: float | None, sample_rate: int) -> float | None:
    if sample_offset is None or sample_offset < 0 or sample_rate <= 0:
        return None
    return sample_offset / sample_rate


def _denon_position(seconds: float) -> str:
    return str(max(0, round(seconds * 900)))


def _denon_bpm(bpm: float | None) -> str | None:
    if bpm is None or bpm <= 0:
        return None
    return str(round(bpm * 10))


def _tbpm(bpm: float | None) -> str | None:
    value = _denon_bpm(bpm)
    return value.zfill(5) if value else None


def _resolve_point(track: EngineTrack, source: MappingSource, sample_rate: int) -> float | None:
    if source.kind is SourceKind.NONE:
        return None
    if source.kind is SourceKind.MAIN_CUE:
        return _seconds(track.main_cue_sample_offset, sample_rate)
    if source.kind is SourceKind.HOT_CUE and source.index:
        cue = track.quick_cue(source.index)
        return _seconds(cue.sample_offset, sample_rate) if cue else None
    if source.kind is SourceKind.SAVED_LOOP and source.index:
        loop = track.saved_loop(source.index)
        return _seconds(loop.start_sample_offset, sample_rate) if loop else None
    return None


def _existing_stup_prefix(existing: ExistingTags) -> list[str]:
    tokens = existing.txxx.get("DDJ/STUP", "").split()
    if len(tokens) >= 6:
        return tokens[:6]
    return ["01", "01", "1", "1", "00", "00"]


def build_tag_plan(
    track: EngineTrack,
    mpeg: MpegInfo,
    mappings: SlotMappings,
    options: SyncOptions,
    existing: ExistingTags,
    waveform: bytes | None = None,
) -> TagPlan:
    warnings = list(track.warnings)
    txxx: dict[str, str] = {
        "DDJ/VER": "0100",
        "DDJ/DUR": str(mpeg.ddj_duration),
    }
    remove = set(DENON_TXXX) - {"DDM/WAVE"}
    standard: dict[str, str] = {}

    if options.rewrite_normal_metadata:
        standard.update({
            "TIT2": track.title,
            "TPE1": track.artist,
            "TALB": track.album,
            "TCON": track.genre,
            "TRCK": track.track_number,
            "TKEY": track.key,
        })
    if options.write_denon_bpm:
        formatted_bpm = _tbpm(track.bpm)
        if formatted_bpm:
            standard["TBPM"] = formatted_bpm

    cue_seconds = _resolve_point(track, mappings.cue, mpeg.sample_rate)
    if cue_seconds is not None:
        txxx["DDJ/CUET"] = _denon_position(cue_seconds)
    elif mappings.cue.kind is not SourceKind.NONE:
        warnings.append(f"Cue source is not set: {mappings.cue.label}")

    slot_types: list[str] = []
    for slot_number, source in enumerate(
        [mappings.slot_1, mappings.slot_2, mappings.slot_3], start=1
    ):
        if source.kind is SourceKind.NONE:
            slot_types.append("0")
            continue
        if source.kind in {SourceKind.MAIN_CUE, SourceKind.HOT_CUE}:
            position = _resolve_point(track, source, mpeg.sample_rate)
            if position is None:
                slot_types.append("0")
                warnings.append(f"DN slot {slot_number} source is not set: {source.label}")
                continue
            txxx[f"DDJ/H{slot_number}PT"] = _denon_position(position)
            slot_types.append("1")
            continue
        if source.kind is SourceKind.SAVED_LOOP:
            loop = track.saved_loop(source.index or 0)
            if not loop:
                slot_types.append("0")
                warnings.append(f"DN slot {slot_number} loop is not set: {source.label}")
                continue
            if not options.experimental_auto_loops:
                slot_types.append("0")
                warnings.append(f"Skipped experimental auto-loop mapping for DN slot {slot_number}")
                continue
            start = _seconds(loop.start_sample_offset, mpeg.sample_rate)
            if start is None:
                slot_types.append("0")
                continue
            txxx[f"DDJ/H{slot_number}PT"] = _denon_position(start)
            bpm_value = _denon_bpm(track.bpm)
            if bpm_value:
                txxx[f"DDJ/H{slot_number}AP"] = bpm_value
            slot_types.append("2")

    if "DDJ/STUP" not in existing.txxx:
        warnings.append("DDJ/STUP prefix uses the provisional default derived from the captured DN-S3700 file")
    txxx["DDJ/STUP"] = " ".join(_existing_stup_prefix(existing) + slot_types) + " "

    if mappings.ab_loop.kind is SourceKind.SAVED_LOOP and mappings.ab_loop.index:
        loop = track.saved_loop(mappings.ab_loop.index)
        if loop:
            start = _seconds(loop.start_sample_offset, mpeg.sample_rate)
            end = _seconds(loop.end_sample_offset, mpeg.sample_rate)
            if start is not None and end is not None:
                txxx["DDJ/L1AT"] = _denon_position(start)
                txxx["DDJ/L1BT"] = _denon_position(end)
                bpm_value = _denon_bpm(track.bpm)
                if bpm_value:
                    txxx["DDJ/L1AP"] = bpm_value
        else:
            warnings.append(f"A/B loop source is not set: {mappings.ab_loop.label}")

    if waveform is not None:
        if len(waveform) != 320:
            raise ValueError("DDM/WAVE must contain exactly 320 bytes")
        txxx["DDM/WAVE"] = waveform.decode("latin-1")
    elif "DDM/WAVE" in existing.txxx:
        txxx["DDM/WAVE"] = existing.txxx["DDM/WAVE"]

    if mpeg.is_vbr and not options.allow_vbr_memo:
        warnings.append("VBR MP3: DN-S3700 memo recall may not work reliably")

    return TagPlan(txxx=txxx, standard_text=standard, remove_txxx=remove, waveform=waveform, warnings=warnings)


def plan_differences(plan: TagPlan, existing: ExistingTags) -> list[str]:
    differences: list[str] = []
    for key, expected in plan.txxx.items():
        if existing.txxx.get(key) != expected:
            differences.append(key)
    for key in plan.remove_txxx:
        if key in existing.txxx and key not in plan.txxx:
            differences.append(f"remove {key}")
    for key, expected in plan.standard_text.items():
        if expected and existing.standard_text.get(key) != expected:
            differences.append(key)
    return differences


def _backup_path(source: Path, backup_directory: Path) -> Path:
    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:10]
    destination = backup_directory / f"{digest}_{source.name}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def write_plan_atomic(source: Path, plan: TagPlan, options: SyncOptions) -> None:
    if options.create_backup:
        if not options.backup_directory:
            raise ValueError("Backup is enabled but no backup directory was configured")
        backup = _backup_path(source, options.backup_directory)
        if not backup.exists():
            shutil.copy2(source, backup)

    fd, temporary_name = tempfile.mkstemp(prefix=f".{source.stem}.", suffix=source.suffix, dir=source.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        try:
            tags = ID3(temporary)
            version = tags.version[1] if tags.version[1] in {3, 4} else 3
        except ID3NoHeaderError:
            tags = ID3()
            version = 3

        for description in DENON_TXXX:
            tags.delall(f"TXXX:{description}")
        for description, value in plan.txxx.items():
            tags.add(TXXX(encoding=Encoding.LATIN1, desc=description, text=[value]))

        for frame_id, value in plan.standard_text.items():
            if not value:
                continue
            tags.delall(frame_id)
            tags.add(STANDARD_FRAME_MAP[frame_id](encoding=Encoding.LATIN1, text=[value]))

        tags.save(temporary, v2_version=version)
        verified = read_existing_tags(temporary)
        remaining = plan_differences(plan, verified)
        if remaining:
            raise RuntimeError(f"Tag verification failed: {', '.join(remaining)}")
        os.replace(temporary, source)
        # Ensure Engine DJ Sync Manager can detect that the source audio file changed,
        # even when ID3 padding keeps the file size identical.
        os.utime(source, None)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)

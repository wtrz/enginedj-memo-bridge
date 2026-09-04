from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class SourceKind(str, Enum):
    NONE = "none"
    MAIN_CUE = "main_cue"
    HOT_CUE = "hot_cue"
    SAVED_LOOP = "saved_loop"


@dataclass(frozen=True)
class MappingSource:
    kind: SourceKind
    index: int | None = None

    @property
    def token(self) -> str:
        if self.index is None:
            return self.kind.value
        return f"{self.kind.value}:{self.index}"

    @classmethod
    def from_token(cls, token: str) -> "MappingSource":
        if ":" not in token:
            return cls(SourceKind(token), None)
        kind, raw_index = token.split(":", 1)
        return cls(SourceKind(kind), int(raw_index))

    @property
    def label(self) -> str:
        if self.kind is SourceKind.NONE:
            return "None"
        if self.kind is SourceKind.MAIN_CUE:
            return "Engine main cue"
        if self.kind is SourceKind.HOT_CUE:
            return f"Engine Hot Cue {self.index}"
        if self.kind is SourceKind.SAVED_LOOP:
            return f"Engine Saved Loop {self.index}"
        return self.token


@dataclass(frozen=True)
class Color:
    a: int = 255
    r: int = 255
    g: int = 255
    b: int = 255


@dataclass(frozen=True)
class QuickCue:
    slot: int
    sample_offset: float
    label: str = ""
    color: Color = Color()


@dataclass(frozen=True)
class SavedLoop:
    slot: int
    start_sample_offset: float
    end_sample_offset: float
    is_start_set: bool
    is_end_set: bool
    label: str = ""
    color: Color = Color()


@dataclass
class EngineTrack:
    origin_id: str
    origin_database_uuid: str
    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    track_number: str = ""
    key: str = ""
    bpm: float | None = None
    sample_rate: int | None = None
    last_edit_time: datetime | None = None
    quick_cues: list[QuickCue] = field(default_factory=list)
    loops: list[SavedLoop] = field(default_factory=list)
    main_cue_sample_offset: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def identity(self) -> str:
        return f"{self.origin_database_uuid}:{self.origin_id}"

    def quick_cue(self, slot: int) -> Optional[QuickCue]:
        return next((cue for cue in self.quick_cues if cue.slot == slot), None)

    def saved_loop(self, slot: int) -> Optional[SavedLoop]:
        return next((loop for loop in self.loops if loop.slot == slot), None)


@dataclass(frozen=True)
class EnginePlaylist:
    id: str
    name: str
    depth: int = 0


@dataclass(frozen=True)
class SlotMappings:
    cue: MappingSource
    slot_1: MappingSource
    slot_2: MappingSource
    slot_3: MappingSource
    ab_loop: MappingSource

    @classmethod
    def defaults(cls) -> "SlotMappings":
        return cls(
            cue=MappingSource(SourceKind.MAIN_CUE),
            slot_1=MappingSource(SourceKind.HOT_CUE, 1),
            slot_2=MappingSource(SourceKind.HOT_CUE, 2),
            slot_3=MappingSource(SourceKind.HOT_CUE, 3),
            ab_loop=MappingSource(SourceKind.SAVED_LOOP, 1),
        )


@dataclass(frozen=True)
class SyncOptions:
    write_waveform_if_missing: bool = True
    force_regenerate_waveform: bool = False
    write_denon_bpm: bool = True
    rewrite_normal_metadata: bool = False
    create_backup: bool = False
    backup_directory: Path | None = None
    allow_vbr_memo: bool = False
    experimental_auto_loops: bool = True
    smart_mapping: bool = False


@dataclass
class ExistingTags:
    id3_major_version: int | None
    txxx: dict[str, str]
    standard_text: dict[str, str]
    waveform_length: int | None = None


@dataclass
class TagPlan:
    txxx: dict[str, str]
    standard_text: dict[str, str]
    remove_txxx: set[str] = field(default_factory=set)
    waveform: bytes | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    track: EngineTrack
    status: str
    needs_update: bool
    differences: list[str] = field(default_factory=list)
    planned_fields: dict[str, str] = field(default_factory=dict)
    current_fields: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    selected: bool = True

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from .engine_blobs import BlobDecodeError, parse_loops, parse_quick_cues
from .models import EnginePlaylist, EngineTrack


QUICK_CUE_COLUMNS = (
    "quickCues",
    "quick_cues",
    "perf_quickCues",
    "perf_quick_cues",
    "hotCues",
    "hot_cues",
    "cuePoints",
    "cue_points",
    "cueBlob",
    "cue_blob",
)

LOOP_COLUMNS = (
    "loops",
    "perf_loops",
    "savedLoops",
    "saved_loops",
    "loopPoints",
    "loop_points",
    "loopBlob",
    "loop_blob",
)


def default_engine_database() -> Path:
    candidates = [
        Path.home() / "Music" / "Engine Library" / "Database2" / "m.db",
        Path.home() / "OneDrive" / "Music" / "Engine Library" / "Database2" / "m.db",
    ]
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def _choose(columns: set[str], *candidates: str) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _clean_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _timestamp_to_datetime(value: object) -> datetime | None:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    # Be defensive if a future schema uses milliseconds.
    if raw > 10_000_000_000:
        raw /= 1000.0
    try:
        return datetime.fromtimestamp(raw).astimezone()
    except (OSError, OverflowError, ValueError):
        return None


def _normalise_file_url(value: str) -> str:
    if value.startswith("file://"):
        parsed = urlparse(value)
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    return unquote(value)


def _resolve_path(path_value: object, filename_value: object, db_path: Path) -> Path:
    raw_path = _normalise_file_url(_clean_text(path_value))
    filename = _clean_text(filename_value)

    if raw_path:
        candidate = Path(raw_path)
        if filename and candidate.name.lower() != filename.lower():
            candidate = candidate / filename
        if candidate.is_absolute():
            return candidate

        # Engine media databases can contain relative paths. Try likely roots.
        roots = [Path.home() / "Music", db_path.parent.parent, db_path.parent.parent.parent]
        for root in roots:
            resolved = root / candidate
            if resolved.exists():
                return resolved
        return roots[0] / candidate

    return Path(filename) if filename else Path()


class EngineDatabaseError(RuntimeError):
    pass


class EngineDatabase:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise EngineDatabaseError(f"Engine DJ database not found: {self.path}")
        uri = f"file:{self.path.as_posix()}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=10)
        except sqlite3.Error as exc:
            raise EngineDatabaseError(f"Could not open Engine DJ database: {exc}") from exc
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def schema_report(self) -> str:
        with self.connect() as connection:
            lines = [f"Database: {self.path}", ""]
            objects = connection.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table','view') ORDER BY type, name"
            ).fetchall()
            for item in objects:
                lines.append(f"[{item['type']}] {item['name']}")
                escaped = item["name"].replace('"', '""')
                columns = connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()
                for column in columns:
                    lines.append(f"  {column['name']}: {column['type']}")
            return "\n".join(lines)

    def _table_columns(self, connection: sqlite3.Connection, table: str) -> set[str]:
        escaped = table.replace('"', '""')
        return {row["name"] for row in connection.execute(f'PRAGMA table_info("{escaped}")')}

    def _playlist_mapping_table(
        self,
        connection: sqlite3.Connection,
        tables: set[str],
    ) -> tuple[str, str, str] | None:
        preferred_names = ("PlaylistEntity", "PlaylistTrack", "PlaylistSongMap", "PlaylistEntry")
        ordered_tables = [table for table in preferred_names if table in tables] + sorted(
            table for table in tables if table not in preferred_names
        )
        for table in ordered_tables:
            if table == "Playlist" or table == "Track" or table == "PerformanceData":
                continue
            columns = self._table_columns(connection, table)
            playlist_col = _choose(
                columns,
                "playlistId",
                "playlist_id",
                "parentPlaylistId",
                "parent_playlist_id",
                "listId",
                "list_id",
            )
            track_col = _choose(
                columns,
                "trackId",
                "track_id",
                "songId",
                "song_id",
                "mediaId",
                "media_id",
                "trackUuid",
                "track_uuid",
            )
            if playlist_col and track_col:
                return table, playlist_col, track_col
        return None

    def fetch_playlists(self) -> list[EnginePlaylist]:
        with self.connect() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "Playlist" not in tables:
                return []

            playlist_columns = self._table_columns(connection, "Playlist")
            id_col = _choose(playlist_columns, "id", "playlistId", "playlist_id")
            name_col = _choose(playlist_columns, "name", "title")
            if not id_col or not name_col:
                return []

            parent_col = _choose(playlist_columns, "parentId", "parent_id", "parentListId", "parent_list_id")
            rows = connection.execute(
                f'SELECT p."{id_col}" AS playlist_id, p."{name_col}" AS playlist_name'
                + (f', p."{parent_col}" AS parent_id' if parent_col else '')
                + ' FROM "Playlist" p ORDER BY p."{0}" COLLATE NOCASE, p."{1}"'.format(name_col, id_col)
            ).fetchall()

            by_id: dict[str, tuple[str, str | None]] = {}
            for row in rows:
                playlist_id = _clean_text(row["playlist_id"])
                if not playlist_id:
                    continue
                by_id[playlist_id] = (
                    _clean_text(row["playlist_name"]),
                    _clean_text(row["parent_id"]) if parent_col else None,
                )

            def lineage(playlist_id: str) -> list[str]:
                parts: list[str] = []
                seen: set[str] = set()
                current = playlist_id
                while current and current not in seen and current in by_id:
                    seen.add(current)
                    name, parent = by_id[current]
                    if name:
                        parts.append(name)
                    current = parent or ""
                return list(reversed(parts))

            children_by_parent: dict[str, list[str]] = {}
            roots: list[str] = []
            for playlist_id, (_, parent_id) in by_id.items():
                if parent_id and parent_id in by_id and parent_id != playlist_id:
                    children_by_parent.setdefault(parent_id, []).append(playlist_id)
                else:
                    roots.append(playlist_id)

            def sort_ids(ids: list[str]) -> list[str]:
                return sorted(ids, key=lambda item_id: (by_id[item_id][0].lower(), item_id))

            ordered: list[EnginePlaylist] = []

            def visit(playlist_id: str):
                parts = lineage(playlist_id)
                ordered.append(
                    EnginePlaylist(
                        id=playlist_id,
                        name=parts[-1] if parts else playlist_id,
                        depth=max(len(parts) - 1, 0),
                    )
                )
                for child_id in sort_ids(children_by_parent.get(playlist_id, [])):
                    visit(child_id)

            for root_id in sort_ids(roots):
                visit(root_id)

            return ordered

    def fetch_tracks_modified_since(
        self,
        since: datetime | None,
        playlist_id: str | None = None,
    ) -> list[EngineTrack]:
        with self.connect() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "Track" not in tables:
                raise EngineDatabaseError("The selected database does not contain a Track table")

            track_columns = self._table_columns(connection, "Track")
            performance_columns = self._table_columns(connection, "PerformanceData") if "PerformanceData" in tables else set()
            last_edit_col = _choose(track_columns, "lastEditTime", "modifiedTime", "updatedAt")

            select_columns = ['t.*']
            sql = ' FROM "Track" t'
            row_columns = set(track_columns)
            where_clauses: list[str] = []
            parameters: list[object] = []
            perf_track_id = _choose(performance_columns, "trackId", "track_id")
            perf_quick = _choose(performance_columns, "quickCues", "quick_cues")
            perf_loops = _choose(performance_columns, "loops", "savedLoops", "saved_loops", "loopPoints", "loop_points", "loopBlob", "loop_blob")
            perf_overview_waveform = _choose(performance_columns, "overviewWaveFormData", "overview_waveform_data")
            if perf_track_id and (perf_quick or perf_loops or perf_overview_waveform):
                sql += f' LEFT JOIN "PerformanceData" p ON p."{perf_track_id}" = t."id"'
                if perf_quick:
                    select_columns.append(f'p."{perf_quick}" AS "perf_quickCues"')
                    row_columns.add("perf_quickCues")
                if perf_loops:
                    select_columns.append(f'p."{perf_loops}" AS "perf_loops"')
                    row_columns.add("perf_loops")
                if perf_overview_waveform:
                    select_columns.append(f'p."{perf_overview_waveform}" AS "perf_overviewWaveFormData"')
                    row_columns.add("perf_overviewWaveFormData")
            if playlist_id:
                mapping_info = self._playlist_mapping_table(connection, tables)
                if not mapping_info:
                    raise EngineDatabaseError("The selected database does not expose a supported Engine DJ playlist mapping table")
                mapping_table, map_playlist_id, map_track_id = mapping_info
                sql += f' INNER JOIN "{mapping_table}" pt ON pt."{map_track_id}" = t."id"'
                if "PlaylistAllChildren" in tables:
                    sql += f' LEFT JOIN "PlaylistAllChildren" pac ON pac."childListId" = pt."{map_playlist_id}"'
                    where_clauses.append(f'(pt."{map_playlist_id}" = ? OR pac."id" = ?)')
                    parameters.extend([playlist_id, playlist_id])
                else:
                    where_clauses.append(f'pt."{map_playlist_id}" = ?')
                    parameters.append(playlist_id)

            sql = 'SELECT ' + ', '.join(select_columns) + sql
            if since and last_edit_col:
                where_clauses.append(f't."{last_edit_col}" >= ?')
                parameters.append(int(since.timestamp()))
            if where_clauses:
                sql += ' WHERE ' + ' AND '.join(where_clauses)
            if last_edit_col:
                sql += f' ORDER BY t."{last_edit_col}" DESC'

            rows = connection.execute(sql, tuple(parameters)).fetchall()
            return [self._row_to_track(row, row_columns, last_edit_col) for row in rows]

    def _row_to_track(
        self,
        row: sqlite3.Row,
        columns: set[str],
        last_edit_col: str | None,
    ) -> EngineTrack:
        def value(*names: str):
            column = _choose(columns, *names)
            return row[column] if column else None

        path = _resolve_path(
            value("path", "filePath", "absolutePath", "uri"),
            value("filename", "fileName"),
            self.path,
        )

        warnings: list[str] = []
        if not _choose(columns, *QUICK_CUE_COLUMNS):
            warnings.append("Engine cue blob columns were not found in Track or PerformanceData; hot cues are unavailable")
        if not _choose(columns, *LOOP_COLUMNS):
            warnings.append("Engine loop blob columns were not found in Track or PerformanceData; saved loops are unavailable")
        if not last_edit_col:
            warnings.append("Engine Track.lastEditTime was not found; the date filter could not be applied")
        quick_cues = []
        loops = []
        main_cue = None

        quick_blob = value(*QUICK_CUE_COLUMNS)
        loop_blob = value(*LOOP_COLUMNS)
        try:
            quick_cues, main_cue = parse_quick_cues(quick_blob)
        except BlobDecodeError as exc:
            warnings.append(f"Could not decode Engine hot cues: {exc}")
        try:
            loops = parse_loops(loop_blob)
        except BlobDecodeError as exc:
            warnings.append(f"Could not decode Engine loops: {exc}")

        bpm = _to_float(value("bpmAnalyzed", "bpm_analyzed")) or _to_float(value("bpm"))
        origin_id = _clean_text(value("originId", "origin_id", "id"))
        origin_uuid = _clean_text(
            value("originDatabaseUuid", "origingDatabaseUuid", "origin_database_uuid")
        )

        return EngineTrack(
            origin_id=origin_id,
            origin_database_uuid=origin_uuid,
            path=path,
            title=_clean_text(value("title")),
            artist=_clean_text(value("artist")),
            album=_clean_text(value("album")),
            genre=_clean_text(value("genre")),
            track_number=_clean_text(value("trackNumber", "track", "trackNo")),
            key=_clean_text(value("key", "keyText")),
            bpm=bpm,
            sample_rate=_to_int(value("sampleRate", "samplerate")),
            last_edit_time=_timestamp_to_datetime(row[last_edit_col]) if last_edit_col else None,
            quick_cues=quick_cues,
            loops=loops,
            main_cue_sample_offset=main_cue,
            overview_waveform=value("perf_overviewWaveFormData", "overviewWaveFormData", "overview_waveform_data"),
            warnings=warnings,
        )

import sqlite3
from pathlib import Path

from enginedj_memo_bridge.engine_db import EngineDatabase


def test_row_to_track_accepts_alias_blob_columns(tmp_path: Path):
    db = EngineDatabase(tmp_path / "m.db")
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        'CREATE TABLE "Track" ('
        'id TEXT, '
        'originDatabaseUuid TEXT, '
        'path TEXT, '
        'filename TEXT, '
        'sampleRate INTEGER, '
        'lastEditTime INTEGER, '
        'hotCues BLOB, '
        'loopPoints BLOB'
        ')'
    )
    connection.execute(
        'INSERT INTO "Track" (id, originDatabaseUuid, path, filename, sampleRate, lastEditTime, hotCues, loopPoints) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        ("1", "db", "C:/Music", "track.mp3", 44100, 1, None, None),
    )
    row = connection.execute('SELECT * FROM "Track"').fetchone()

    track = db._row_to_track(row, {"id", "originDatabaseUuid", "path", "filename", "sampleRate", "lastEditTime", "hotCues", "loopPoints"}, "lastEditTime")

    assert track.path == Path("C:/Music/track.mp3")
    assert "Engine cue blob columns were not found in Track or PerformanceData; hot cues are unavailable" not in track.warnings
    assert "Engine loop blob columns were not found in Track or PerformanceData; saved loops are unavailable" not in track.warnings


def test_fetch_tracks_reads_performance_data_blobs(tmp_path: Path):
    db_path = tmp_path / "m.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        'CREATE TABLE "Track" ('
        'id INTEGER, '
        'path TEXT, '
        'filename TEXT, '
        'sampleRate INTEGER, '
        'originDatabaseUuid TEXT, '
        'lastEditTime INTEGER'
        ')'
    )
    connection.execute(
        'CREATE TABLE "PerformanceData" ('
        'trackId INTEGER, '
        'quickCues BLOB, '
        'loops BLOB'
        ')'
    )
    connection.execute(
        'INSERT INTO "Track" (id, path, filename, sampleRate, originDatabaseUuid, lastEditTime) VALUES (?, ?, ?, ?, ?, ?)',
        (1, 'C:/Music', 'track.mp3', 44100, 'db', 1),
    )
    connection.execute(
        'INSERT INTO "PerformanceData" (trackId, quickCues, loops) VALUES (?, ?, ?)',
        (1, None, None),
    )
    connection.commit()
    connection.close()

    tracks = EngineDatabase(db_path).fetch_tracks_modified_since(None)

    assert len(tracks) == 1
    assert tracks[0].path == Path('C:/Music/track.mp3')
    assert "Engine cue blob columns were not found in Track or PerformanceData; hot cues are unavailable" not in tracks[0].warnings
    assert "Engine loop blob columns were not found in Track or PerformanceData; saved loops are unavailable" not in tracks[0].warnings


def test_fetch_playlists_builds_hierarchical_names(tmp_path: Path):
    db_path = tmp_path / "m.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        'CREATE TABLE "Playlist" ('
        'id TEXT, '
        'name TEXT, '
        'parentId TEXT'
        ')'
    )
    connection.execute('INSERT INTO "Playlist" (id, name, parentId) VALUES (?, ?, ?)', ("root", "Root", None))
    connection.execute('INSERT INTO "Playlist" (id, name, parentId) VALUES (?, ?, ?)', ("child", "Child", "root"))
    connection.commit()
    connection.close()

    playlists = EngineDatabase(db_path).fetch_playlists()

    assert [playlist.id for playlist in playlists] == ["root", "child"]
    assert [playlist.name for playlist in playlists] == ["Root", "Child"]
    assert [playlist.depth for playlist in playlists] == [0, 1]


def test_fetch_playlists_keeps_children_directly_under_their_parent(tmp_path: Path):
    db_path = tmp_path / "m.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        'CREATE TABLE "Playlist" ('
        'id TEXT, '
        'title TEXT, '
        'parentListId TEXT'
        ')'
    )
    connection.execute('INSERT INTO "Playlist" (id, title, parentListId) VALUES (?, ?, ?)', ("root-a", "A", None))
    connection.execute('INSERT INTO "Playlist" (id, title, parentListId) VALUES (?, ?, ?)', ("root-b", "B", None))
    connection.execute('INSERT INTO "Playlist" (id, title, parentListId) VALUES (?, ?, ?)', ("child-a1", "A1", "root-a"))
    connection.execute('INSERT INTO "Playlist" (id, title, parentListId) VALUES (?, ?, ?)', ("child-b1", "B1", "root-b"))
    connection.execute('INSERT INTO "Playlist" (id, title, parentListId) VALUES (?, ?, ?)', ("child-a2", "A2", "root-a"))
    connection.commit()
    connection.close()

    playlists = EngineDatabase(db_path).fetch_playlists()

    assert [playlist.id for playlist in playlists] == ["root-a", "child-a1", "child-a2", "root-b", "child-b1"]
    assert [playlist.depth for playlist in playlists] == [0, 1, 1, 0, 1]


def test_fetch_tracks_can_filter_by_playlist(tmp_path: Path):
    db_path = tmp_path / "m.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        'CREATE TABLE "Track" ('
        'id INTEGER, '
        'path TEXT, '
        'filename TEXT, '
        'sampleRate INTEGER, '
        'originDatabaseUuid TEXT, '
        'lastEditTime INTEGER'
        ')'
    )
    connection.execute(
        'CREATE TABLE "PlaylistTrack" ('
        'playlistId TEXT, '
        'trackId INTEGER'
        ')'
    )
    connection.execute(
        'INSERT INTO "Track" (id, path, filename, sampleRate, originDatabaseUuid, lastEditTime) VALUES (?, ?, ?, ?, ?, ?)',
        (1, 'C:/Music', 'one.mp3', 44100, 'db', 100),
    )
    connection.execute(
        'INSERT INTO "Track" (id, path, filename, sampleRate, originDatabaseUuid, lastEditTime) VALUES (?, ?, ?, ?, ?, ?)',
        (2, 'C:/Music', 'two.mp3', 44100, 'db', 200),
    )
    connection.execute('INSERT INTO "PlaylistTrack" (playlistId, trackId) VALUES (?, ?)', ("playlist-a", 2))
    connection.execute('INSERT INTO "PlaylistTrack" (playlistId, trackId) VALUES (?, ?)', ("playlist-b", 1))
    connection.commit()
    connection.close()

    tracks = EngineDatabase(db_path).fetch_tracks_modified_since(None, "playlist-a")

    assert [track.path for track in tracks] == [Path('C:/Music/two.mp3')]


def test_fetch_tracks_can_filter_by_playlist_with_alternate_mapping_table(tmp_path: Path):
    db_path = tmp_path / "m.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        'CREATE TABLE "Track" ('
        'id INTEGER, '
        'path TEXT, '
        'filename TEXT, '
        'sampleRate INTEGER, '
        'originDatabaseUuid TEXT, '
        'lastEditTime INTEGER'
        ')'
    )
    connection.execute(
        'CREATE TABLE "SongPlaylistMap" ('
        'listId TEXT, '
        'mediaId INTEGER'
        ')'
    )
    connection.execute(
        'INSERT INTO "Track" (id, path, filename, sampleRate, originDatabaseUuid, lastEditTime) VALUES (?, ?, ?, ?, ?, ?)',
        (1, 'C:/Music', 'one.mp3', 44100, 'db', 100),
    )
    connection.execute(
        'INSERT INTO "Track" (id, path, filename, sampleRate, originDatabaseUuid, lastEditTime) VALUES (?, ?, ?, ?, ?, ?)',
        (2, 'C:/Music', 'two.mp3', 44100, 'db', 200),
    )
    connection.execute('INSERT INTO "SongPlaylistMap" (listId, mediaId) VALUES (?, ?)', ("playlist-a", 1))
    connection.commit()
    connection.close()

    tracks = EngineDatabase(db_path).fetch_tracks_modified_since(None, "playlist-a")

    assert [track.path for track in tracks] == [Path('C:/Music/one.mp3')]


def test_fetch_tracks_includes_child_playlists_when_view_exists(tmp_path: Path):
    db_path = tmp_path / "m.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        'CREATE TABLE "Track" ('
        'id INTEGER, '
        'path TEXT, '
        'filename TEXT, '
        'sampleRate INTEGER, '
        'originDatabaseUuid TEXT, '
        'lastEditTime INTEGER'
        ')'
    )
    connection.execute(
        'CREATE TABLE "PlaylistEntity" ('
        'id INTEGER, '
        'listId INTEGER, '
        'trackId INTEGER'
        ')'
    )
    connection.execute(
        'CREATE TABLE "PlaylistAllChildren" ('
        'id INTEGER, '
        'childListId INTEGER'
        ')'
    )
    connection.execute(
        'INSERT INTO "Track" (id, path, filename, sampleRate, originDatabaseUuid, lastEditTime) VALUES (?, ?, ?, ?, ?, ?)',
        (1, 'C:/Music', 'parent.mp3', 44100, 'db', 100),
    )
    connection.execute(
        'INSERT INTO "Track" (id, path, filename, sampleRate, originDatabaseUuid, lastEditTime) VALUES (?, ?, ?, ?, ?, ?)',
        (2, 'C:/Music', 'child.mp3', 44100, 'db', 200),
    )
    connection.execute('INSERT INTO "PlaylistEntity" (id, listId, trackId) VALUES (?, ?, ?)', (1, 10, 1))
    connection.execute('INSERT INTO "PlaylistEntity" (id, listId, trackId) VALUES (?, ?, ?)', (2, 11, 2))
    connection.execute('INSERT INTO "PlaylistAllChildren" (id, childListId) VALUES (?, ?)', (10, 11))
    connection.commit()
    connection.close()

    tracks = EngineDatabase(db_path).fetch_tracks_modified_since(None, "10")

    assert [track.path for track in tracks] == [Path('C:/Music/child.mp3'), Path('C:/Music/parent.mp3')]
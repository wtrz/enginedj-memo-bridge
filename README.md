# EngineDJ Memo Bridge

EngineDJ Memo Bridge is a desktop GUI sync tool, currently developed and tested primarily on Windows, that reads Engine DJ's SQLite database **read-only** and writes DDJMMAN / legacy Denon DN-S3700-style memo data into MP3 ID3 tags before an Engine DJ USB export.

## Status and important warnings

EngineDJ Memo Bridge is early-release software intended for careful, manual use. It modifies MP3 ID3 tags in-place. Always keep a backup of your music collection before first use and review the scan results before syncing.

Known release limitations:

- MP3 files only; WAV, AIFF and FLAC metadata are not supported yet.
- DDJMMAN / DN-S3700 numbered Auto Loop slots preserve loop start+BPM only. Use DN A/B loop mapping when exact loop end must be preserved.
- Generated `DDM/WAVE` waveform data is approximate.
- Engine DJ schema compatibility is defensive, but new Engine DJ versions should be validated with the built-in schema report.
- Public Windows/macOS builds are unsigned unless otherwise stated and may show operating system security warnings.

## Features

- Remembers the Engine DJ `m.db` location with Qt `QSettings`.
- Defaults to `~/Music/Engine Library/Database2/m.db`, with OneDrive Music fallbacks.
- Filters Engine tracks using `Track.lastEditTime` and a date picker when that column exists.
- Reads Engine metadata, quick cues, main cue and saved-loop blobs using a Python implementation of the structures documented by `libdjinterop`.
- Lets the user map:
  - DN Cue
  - DN Slot 1
  - DN Slot 2
  - DN Slot 3
  - DN A/B loop
- Any Engine Hot Cue 1-8 can map to a DN Hot Start slot.
- Any Engine Saved Loop 1-8 can map to the DN A/B loop.
- Engine saved loops can map to a numbered DN Auto Loop slot as start+BPM only; use DN A/B loop when exact loop length must be preserved.
- Scans first and shows only actual ID3 differences.
- Requires confirmation before writing selected ID3 changes.
- Writes source MP3 files atomically and verifies the written tags.
- Optional full-file backup.
- Creates an approximate 320-byte `DDM/WAVE` waveform when missing.
- Generates a schema report to diagnose future Engine DJ schema changes.

### Current waveform understanding

- EngineDJ overview waveforms appear to store three-band magnitude points plus timing metadata.
- Community DDJMMAN / DN-style waveform observations suggest the rendered colours roughly track these frequency regions:
  - blue: ~20-500 Hz
  - green: ~500-2000 Hz
  - white: ~2000-20000 Hz
- The visual result appears blended rather than using perfectly hard crossover boundaries.
- The current `DDM/WAVE` writer is still approximate and should not yet be treated as a confirmed frequency-band-faithful reproduction of Denon DJ Music Manager output.

## Known Denon tag mapping

| Purpose | Tag |
|---|---|
| Format version | `TXXX:DDJ/VER = 0100` |
| Duration | `TXXX:DDJ/DUR`, physical MPEG duration in 1/75 second units |
| Main cue | `TXXX:DDJ/CUET`, approximately 900 time units per second based on DN-S3700 device testing |
| Hot Start N | `TXXX:DDJ/HnPT`, approximately 900 time units per second based on DN-S3700 device testing |
| Auto Loop N start | `TXXX:DDJ/HnPT`, approximately 900 time units per second based on DN-S3700 device testing |
| Auto Loop N BPM | `TXXX:DDJ/HnAP`, BPM × 10 |
| A/B loop start/end | `TXXX:DDJ/L1AT`, `DDJ/L1BT`, approximately 900 time units per second based on DN-S3700 device testing |
| A/B loop BPM | `TXXX:DDJ/L1AP`, BPM × 10 |
| Slot types | Final three fields of `TXXX:DDJ/STUP`: `0` empty, `1` Hot Start, `2` Auto Loop |
| Waveform | `TXXX:DDM/WAVE`, exactly 320 low-value bytes |
| BPM | `TBPM`, BPM × 10, padded to five digits |

## Important limitation: Auto Loop length

Current inspected DN-S3700 memo files show numbered Auto Loop slots storing the start point, BPM and slot type only. No Auto Loop beat-size or loop-end field has been identified in the MP3 memo data. Therefore saved-loop-to-numbered-slot mapping preserves the loop start+BPM only. Use the separate DN A/B loop mapping when exact Engine loop start/end must be preserved.

## Installation from source

Install Python 3.11+ and ffmpeg. Ensure `ffmpeg` / `ffmpeg.exe` is on `PATH`.

On Windows:

```powershell
cd enginedj-memo-bridge
py -m pip install -e .
py -m enginedj_memo_bridge
```

Or run `run.bat`.

On macOS/Linux:

```bash
cd enginedj-memo-bridge
python3 -m pip install -e .
python3 -m enginedj_memo_bridge
```

## Building packaged apps

Packaged desktop builds are platform-specific. Build Windows on Windows and macOS on macOS.

### Windows

```bat
build_windows.bat
```

The Windows build output is:

```text
dist\EngineDJ-Memo-Bridge\EngineDJ-Memo-Bridge.exe
```

If you move or share the Windows build, zip/copy the whole folder:

```text
dist\EngineDJ-Memo-Bridge\
```

Do not copy only the `.exe`; it needs the `_internal` folder next to it.

### macOS

```bash
./build_macos.sh
```

The macOS build output is:

```text
dist/EngineDJ Memo Bridge.app
```

Unsigned macOS builds may require right-clicking the app and choosing **Open** the first time. Public distribution without Gatekeeper warnings requires Apple code signing and notarization.

## GitHub releases

Release artifacts are built by GitHub Actions when a version tag is pushed:

```bash
git tag v0.1.3
git push origin v0.1.3
```

The release workflow builds and uploads Windows and macOS zip files. Keep the tag version aligned with `pyproject.toml`.

## Recommended workflow

1. Make a backup of the music collection before first use.
2. Finish analysis, cue and loop editing in Engine DJ.
3. Avoid running this tool while Engine DJ is actively analyzing files or exporting to USB.
4. Open the sync tool.
5. Choose the modification date and mappings.
6. Click **Scan**.
7. Review warnings and selected tracks.
8. Click **Sync selected ID3 tags**.
9. Export the already-tagged music to USB from Engine DJ.

## Safety and compatibility

- The Engine database is opened with SQLite `mode=ro` and `PRAGMA query_only=ON`.
- No tables, triggers or stored data are added to Engine DJ.
- MP3 writes are made to a temporary same-folder copy, verified, then atomically replace the source. The final file modification time is explicitly updated so USB sync can detect a changed source even when ID3 padding keeps the size unchanged.
- Existing ID3v2.3/v2.4 major version is preserved.
- The current release supports MP3 only. WAV, AIFF and FLAC metadata are future work.
- VBR tracks are shown with a warning because legacy DN-S3700 memo behavior may be unreliable.
- The current `libdjinterop` public support matrix ends at Engine DJ Desktop 4.3.0. This project therefore introspects the actual schema and includes a schema-report function rather than assuming all later versions are identical.

## Additional design decisions worth considering

1. **Playlist scope:** date filtering can include many irrelevant tracks. Add Engine playlist/crate selection next.
2. **Auto Loop length:** collect controlled DN-S3700 samples for 1, 2, 4, 8 and 16 beat loops and complete the `STUP` mapping.
3. **Variable-tempo tracks:** `HnAP/L1AP` currently uses track BPM. A per-position beat-grid BPM lookup would be more accurate.
4. **File path resolution:** external drives can use paths different from the main collection. Schema report and missing-file display help, but mounted-drive remapping should be added.
5. **USB preflight:** add a final report for unsupported sample rates, VBR, missing files and invalid tag lengths.
6. **Undo:** the optional complete-file backup is safe but space-heavy. A dedicated ID3-only backup/restore format would be smaller.
7. **Engine DJ 5.x validation:** test against a real current `m.db`; the application intentionally fails visibly instead of guessing when blobs or columns change.
8. **USB replacement verification:** test one already-exported track end-to-end. Community reports indicate Sync Manager recopies changed source audio/tag files, but the app should eventually verify the resulting USB file rather than assuming every Engine DJ version behaves identically.

## Attribution

The Engine quick-cue and loop binary layouts were implemented from the public `libdjinterop` project documentation/source. No `libdjinterop` source code is bundled. See its LGPL-3.0 license before directly incorporating that library itself.

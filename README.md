# EngineDJ Memo Bridge

EngineDJ Memo Bridge is a desktop GUI tool for DJs who want to carry Engine DJ cue and loop work into legacy Denon DJ / DDJMMAN-style MP3 memo tags before exporting to USB.

The app reads the Engine DJ SQLite database **read-only**, shows a scan preview of the ID3 tag changes it plans to make, and then writes selected DDJMMAN / DN-S3700-style memo data into the original MP3 files.

> [!IMPORTANT]
> This is early-release software. It modifies MP3 ID3 tags in-place. Always keep a backup of your music collection and review scan results before syncing.

## What it does

EngineDJ Memo Bridge helps bridge this workflow:

1. Edit/analyze tracks, cues and loops in Engine DJ.
2. Scan your Engine DJ library with EngineDJ Memo Bridge.
3. Preview which MP3 files need DDJMMAN / Denon memo tag updates.
4. Write selected ID3 tag updates into the source MP3 files.
5. Export the updated source files to USB using Engine DJ.

The Engine DJ database itself is never modified.

## Download

Packaged builds are published from GitHub Releases when release tags are built successfully.

Current public release artifacts are:

- `EngineDJ-Memo-Bridge-Windows-x64.zip`

### Windows

Download and extract the Windows ZIP, then run:

```text
EngineDJ-Memo-Bridge\EngineDJ-Memo-Bridge.exe
```

Do not move or copy only the `.exe`; it needs the `_internal` folder next to it.

### macOS

macOS app releases are disabled for now while packaging and runner compatibility are validated. macOS users can still run from source if they are comfortable installing Python dependencies manually.

### Security warnings

Public Windows builds are unsigned unless a release explicitly says otherwise. Windows SmartScreen or Microsoft Defender may warn that the publisher cannot be verified.

## Quick start

1. Make a backup of your music collection before first use.
2. Finish analysis, cue and loop editing in Engine DJ.
3. Avoid running this tool while Engine DJ is actively analyzing files or exporting to USB.
4. Open EngineDJ Memo Bridge.
5. Select your Engine DJ `m.db` database if it is not found automatically.
6. Choose a date filter, playlist filter and cue/loop mappings.
7. Click **Scan**.
8. Review warnings, differences and selected tracks.
9. Click **Sync selected DDJMMAN ID3 tags**.
10. Confirm the write operation.
11. Export the already-tagged music to USB from Engine DJ.

## Features

- Reads Engine DJ `m.db` read-only.
- Remembers the selected database location with Qt settings.
- Auto-detects common Engine DJ database locations, including OneDrive Music paths.
- Filters tracks by Engine DJ modification date when available.
- Optionally filters tracks by Engine DJ playlist.
- Maps Engine DJ main cue, Hot Cues 1-8 and Saved Loops 1-8 to legacy Denon memo targets.
- Supports smart mapping for common cue/loop layouts.
- Uses an EngineDJ-inspired dark interface theme.
- Scans first and shows only actual ID3 differences.
- Requires confirmation before writing selected ID3 changes.
- Writes source MP3 files atomically and verifies written tags.
- Can create optional full-file backups before writing.
- Can create an approximate 320-byte `DDM/WAVE` waveform when missing.
- Includes an Engine DJ schema report tool for diagnosing database compatibility.

## Supported platforms

| Platform | Status |
|---|---|
| Windows x64 | Primary tested platform |
| macOS | Source use only for now; packaged app releases are disabled |
| Linux | Source/development use only unless otherwise stated |

Packaged app releases currently target Windows only. The macOS build script remains in the repository for future validation.

## Supported file types

| File type | Status |
|---|---|
| MP3 | Supported |
| WAV | Not supported yet |
| AIFF | Not supported yet |
| FLAC | Not supported yet |

## Known limitations

- This is an early public beta; test on a small subset of files before using it on a large collection.
- MP3 ID3 tags are modified in-place after confirmation.
- Numbered DDJMMAN / DN-S3700 Auto Loop slots preserve loop start+BPM only. Use DN A/B loop mapping when exact Engine loop start/end must be preserved.
- Generated `DDM/WAVE` waveform data is approximate and should not be treated as a verified Denon DJ Music Manager reproduction.
- VBR MP3 files are shown with a warning because legacy DN-S3700 memo recall may be unreliable.
- External-drive path remapping is limited; missing files are shown in the scan results.
- Engine DJ schema compatibility is defensive, but new Engine DJ versions should be validated with the built-in schema report.
- USB replacement behavior should be verified with your Engine DJ version and workflow.

## Safety and compatibility

- The Engine DJ database is opened with SQLite `mode=ro` and `PRAGMA query_only=ON`.
- No Engine DJ database tables, triggers or data are created or modified.
- MP3 writes are made to a temporary same-folder copy, verified, then atomically replace the source file.
- The final source file modification time is updated so Engine DJ Sync Manager can detect a changed file even when ID3 padding keeps the file size identical.
- Existing ID3v2.3/v2.4 major version is preserved when possible.
- Optional backups are complete file copies stored under `~/Music/EngineDJ Memo Bridge Backups`.

## Installing from source

Install Python 3.11+ and ffmpeg. Ensure `ffmpeg` / `ffmpeg.exe` is on `PATH`.

On Windows:

```powershell
cd enginedj-memo-bridge
py -m pip install -e .
py -m enginedj_memo_bridge
```

Or run:

```bat
run.bat
```

On macOS/Linux:

```bash
cd enginedj-memo-bridge
python3 -m pip install -e .
python3 -m enginedj_memo_bridge
```

## Building from source

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

### Windows build

```bat
build_windows.bat
```

Output:

```text
dist\EngineDJ-Memo-Bridge\EngineDJ-Memo-Bridge.exe
```

When sharing the Windows build, zip/copy the whole folder:

```text
dist\EngineDJ-Memo-Bridge\
```

### macOS build

The macOS build script is kept for development/testing, but GitHub release artifacts for macOS are disabled for now.

```bash
./build_macos.sh
```

Output:

```text
dist/EngineDJ Memo Bridge.app
```

## Development

Run tests:

```bash
python -m pytest
```

Release artifacts are built by GitHub Actions when a version tag is pushed:

```bash
git tag v0.1.3
git push origin v0.1.3
```

Keep the tag version aligned with `pyproject.toml` and `src/enginedj_memo_bridge/__init__.py`.

## Technical notes

### Known Denon tag mapping

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

### Current waveform understanding

- Engine DJ overview waveforms appear to store three-band magnitude points plus timing metadata.
- Community DDJMMAN / DN-style waveform observations suggest rendered colours roughly track these frequency regions:
  - blue: ~20-500 Hz
  - green: ~500-2000 Hz
  - white: ~2000-20000 Hz
- The visual result appears blended rather than using perfectly hard crossover boundaries.
- The current `DDM/WAVE` writer is approximate.

## Attribution

The Engine quick-cue and loop binary layouts were implemented from the public `libdjinterop` project documentation/source. No `libdjinterop` source code is bundled. See its LGPL-3.0 license before directly incorporating that library itself.

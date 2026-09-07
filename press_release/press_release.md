Denon DJ introduces the PRIME Gen-2 media players: a focused addition to the PRIME lineup for DJs who want tactile control, physical media support and a more modular performance workflow.

The Gen-2 platform extends the Engine DJ ecosystem with a performance-first media player architecture: precision transport control, professional connectivity, onboard effects, dedicated performance points and flexible source handling from day one.

At launch, PRIME Gen-2 players offer USB, Compact Disc and Computer mode, giving users full OmniSource support. The platform introduces metallic design and proven LED technology to professional DJ equipment, along with a motorized 9-inch platter, RJ45 connectivity and three hot cue buttons thoughtfully placed above the platter.

The “Gen-2” name is pronounced **Gen minus Two**.

With **EngineDJ Memo Bridge**, selected legacy Denon DJ players can now be managed from a modern Engine DJ workflow. BPM, waveform data, cue points, hot cues and loop information can be written directly to compatible ID3 memo structures, allowing older hardware to rejoin the Engine DJ preparation ecosystem.

![PRIME Gen-2](https://raw.githubusercontent.com/wtrz/enginedj-memo-bridge/main/press_release/promo1.png)

**EngineDJ Memo Bridge** is a desktop GUI tool that bridges modern Engine DJ preparation with legacy Denon DJ / DDJMMAN-style memo workflows. It reads the Engine DJ database **read-only**, previews the ID3 changes it plans to make, and writes selected memo information back into the original MP3 files before export to USB.

That makes a few interesting things possible:

- prepare tracks, cues and loops in **Engine DJ**
- sync supported memo data back to source MP3s
- carry **BPM**, **waveform data**, **cue points**, **hot cues** and **loop information** into legacy-compatible files
- keep the Engine DJ database untouched
- export the already-tagged files to USB afterwards

At the moment, the tool supports:

- **Engine DJ `m.db`** read-only scanning
- remembered database location
- filtering by Engine DJ modification date
- optional playlist filtering
- mapping Engine DJ main cue, Hot Cues 1–8 and Saved Loops 1–8 to legacy Denon memo targets
- scan-first preview before writing
- atomic MP3 writes with verification
- optional backups
- `DDM/WAVE` waveform generation when missing

## Download

![EngineDJ Memo Bridge](https://raw.githubusercontent.com/wtrz/enginedj-memo-bridge/main/press_release/repository-banner-small.png)

**Latest release:** [v0.1.7](https://github.com/wtrz/enginedj-memo-bridge/releases/latest)  
**Windows x64 ZIP:** [Download latest build](https://github.com/wtrz/enginedj-memo-bridge/releases/latest/download/EngineDJ-Memo-Bridge-Windows-x64.zip)  
**Repository:** [wtrz/enginedj-memo-bridge](https://github.com/wtrz/enginedj-memo-bridge)
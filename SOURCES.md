# Research sources

- Engine DJ third-party database guidelines:
  https://support.enginedj.com/en/support/solutions/articles/69000834165
- libdjinterop project and support matrix:
  https://github.com/xsco/libdjinterop
- Engine quick-cue blob reference:
  https://raw.githubusercontent.com/xsco/libdjinterop/master/src/djinterop/engine/v2/quick_cues_blob.cpp
- Engine saved-loop blob reference:
  https://raw.githubusercontent.com/xsco/libdjinterop/master/src/djinterop/engine/v2/loops_blob.cpp
- Engine zlib wrapper and binary encoding reference:
  https://raw.githubusercontent.com/xsco/libdjinterop/master/src/djinterop/engine/encode_decode_utils.cpp
- DN-S3700 manual index:
  https://www.manualslib.com/manual/376636/Denon-Dn-S3700.html
- Denon legacy downloads:
  https://www.denondj.com/downloads.html
- Denon DJ forum discussion with sinus-sweep waveform observations:
  https://community.enginedj.com/

The DN-S3700 TXXX field names and values in this project were also derived from controlled inspection of user-supplied MP3 files written by Denon DJ Music Manager and the DN-S3700 itself.

Additional waveform observation from community testing: DDJMMAN / DN-style waveform colours appear to roughly emphasize blue for about 20-500 Hz, green for about 500-2000 Hz, and white for about 2000-20000 Hz, with some overlap/blending between adjacent bands. A sinus sweep screenshot was shared as qualitative evidence.

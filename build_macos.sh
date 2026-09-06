#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"

# PyInstaller on macOS expects an .icns icon. If one is not already present,
# generate it from the repository PNG using macOS built-in tools.
if [[ ! -f logo-enginedj-memo-bridge.icns ]]; then
  ICONSET="build/logo-enginedj-memo-bridge.iconset"
  mkdir -p "$ICONSET"
  sips -z 16 16     logo-enginedj-memo-bridge.png --out "$ICONSET/icon_16x16.png" >/dev/null
  sips -z 32 32     logo-enginedj-memo-bridge.png --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 32 32     logo-enginedj-memo-bridge.png --out "$ICONSET/icon_32x32.png" >/dev/null
  sips -z 64 64     logo-enginedj-memo-bridge.png --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 128 128   logo-enginedj-memo-bridge.png --out "$ICONSET/icon_128x128.png" >/dev/null
  sips -z 256 256   logo-enginedj-memo-bridge.png --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 256 256   logo-enginedj-memo-bridge.png --out "$ICONSET/icon_256x256.png" >/dev/null
  sips -z 512 512   logo-enginedj-memo-bridge.png --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 512 512   logo-enginedj-memo-bridge.png --out "$ICONSET/icon_512x512.png" >/dev/null
  sips -z 1024 1024 logo-enginedj-memo-bridge.png --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o logo-enginedj-memo-bridge.icns
fi

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "EngineDJ Memo Bridge" \
  --icon logo-enginedj-memo-bridge.icns \
  --add-data "logo-enginedj-memo-bridge.png:." \
  --paths src \
  src/enginedj_memo_bridge/__main__.py

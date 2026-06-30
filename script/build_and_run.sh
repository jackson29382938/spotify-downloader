#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="SpotDLDownloader"
BUNDLE_NAME="Spotify Downloader"
BUNDLE_ID="local.spotify.downloader"
MIN_SYSTEM_VERSION="14.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$BUNDLE_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_DOWNLOADER="$APP_RESOURCES/downloader"
APP_RESOURCE_BIN="$APP_RESOURCES/bin"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"
PACKAGE_ZIP="$DIST_DIR/Spotify Downloader Portable.zip"
PORTABLE_BUILD_DIR="$ROOT_DIR/.build/portable-downloader"
PORTABLE_DOWNLOADER="$PORTABLE_BUILD_DIR/spotify_dl"
PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-python3}"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

cd "$ROOT_DIR"

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

ensure_python_env() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Creating local Python environment..."
    rm -rf "$ROOT_DIR/.venv"
    "$PYTHON_BOOTSTRAP" -m venv "$ROOT_DIR/.venv"
  fi

  if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import PyInstaller  # noqa: F401
import mutagen  # noqa: F401
import requests  # noqa: F401
import yt_dlp  # noqa: F401
PY
  then
    echo "Installing downloader packaging dependencies..."
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt" pyinstaller
  fi
}

swift build
BUILD_BINARY="$(swift build --show-bin-path)/$APP_NAME"

if [[ ! -x "$PORTABLE_DOWNLOADER" || "$ROOT_DIR/spotify_dl.py" -nt "$PORTABLE_DOWNLOADER" ]]; then
  ensure_python_env
  echo "Packaging standalone downloader..."
  rm -rf "$PORTABLE_BUILD_DIR"
  mkdir -p "$PORTABLE_BUILD_DIR"
  "$PYTHON_BIN" -m PyInstaller \
    --clean \
    --onefile \
    --name spotify_dl \
    --distpath "$PORTABLE_BUILD_DIR" \
    --workpath "$ROOT_DIR/.build/pyinstaller-work" \
    --specpath "$ROOT_DIR/.build/pyinstaller-spec" \
    --collect-all yt_dlp \
    "$ROOT_DIR/spotify_dl.py"
  chmod +x "$PORTABLE_DOWNLOADER"
else
  echo "Using cached standalone downloader."
fi

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_MACOS" "$APP_DOWNLOADER" "$APP_RESOURCE_BIN"
cp "$BUILD_BINARY" "$APP_BINARY"
chmod +x "$APP_BINARY"
cp "$PORTABLE_DOWNLOADER" "$APP_DOWNLOADER/spotify_dl"
chmod +x "$APP_DOWNLOADER/spotify_dl"

FFMPEG_SOURCE="${FFMPEG_PATH:-}"
if [[ -z "$FFMPEG_SOURCE" || ! -x "$FFMPEG_SOURCE" ]]; then
  for candidate in \
    "$ROOT_DIR/vendor/ffmpeg" \
    "$HOME/.spotdl/ffmpeg" \
    "$(command -v ffmpeg || true)"
  do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      FFMPEG_SOURCE="$candidate"
      break
    fi
  done
fi

if [[ -n "$FFMPEG_SOURCE" && -x "$FFMPEG_SOURCE" ]]; then
  cp "$FFMPEG_SOURCE" "$APP_RESOURCE_BIN/ffmpeg"
  chmod +x "$APP_RESOURCE_BIN/ffmpeg"
else
  echo "warning: ffmpeg was not found; the app can launch, but downloads may fail." >&2
fi

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleName</key>
  <string>Spotify Downloader</string>
  <key>CFBundleDisplayName</key>
  <string>Spotify Downloader</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSDownloadsFolderUsageDescription</key>
  <string>Spotify Downloader saves downloaded music to your selected folder.</string>
  <key>NSDocumentsFolderUsageDescription</key>
  <string>Spotify Downloader can save downloaded music to folders you choose.</string>
  <key>NSDesktopFolderUsageDescription</key>
  <string>Spotify Downloader can save downloaded music to folders you choose.</string>
</dict>
</plist>
PLIST

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_BUNDLE" >/dev/null
  codesign --verify --deep --strict "$APP_BUNDLE"
fi

open_app() {
  /usr/bin/open -n "$APP_BUNDLE"
}

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    sleep 1
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  --package|package)
    rm -f "$PACKAGE_ZIP"
    ditto -c -k --sequesterRsrc --keepParent "$APP_BUNDLE" "$PACKAGE_ZIP"
    echo "$PACKAGE_ZIP"
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--package]" >&2
    exit 2
    ;;
esac

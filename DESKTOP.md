# Linux and Windows desktop app

The Qt desktop app uses the same Python downloader as the native macOS app.
It provides audio/video downloads, metadata preview, per-track status, pause and
resume, retry of failed sources, local diagnostics, download history, and local
library metadata/lyrics tools. Apple Music automation remains macOS-only.

## Run from source

Use Python 3.12+, FFmpeg and Node 22+ (or Deno 2+). FFmpeg and a JavaScript runtime
must be on PATH. The app does not install external tools automatically.

Linux (Debian/Ubuntu): install FFmpeg with `sudo apt install ffmpeg`. Install Node
from its official distribution or your package manager. Qt needs a graphical
desktop and platform libraries; on minimal Debian/Ubuntu systems install
`libegl1 libopengl0 libxcb-cursor0`. Current PySide6 wheels require glibc 2.34+.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python desktop_app.py
```

Windows: install Python 3.12+, FFmpeg and Node 22+ using official distributions
or your trusted package manager, and restart the terminal after updating PATH.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\.venv\Scripts\python.exe desktop_app.py
```

Run **Diagnostics & activity → Local checks** before downloading. Network checks
also require access to Spotify. Browser cookies are read locally by yt-dlp only
when explicitly selected; preview currently does not use browser cookies.

Pause cancels the current helper and retains completed files and manifests.
Resume reuses the original links and options with existing-file behavior set to
skip. An interrupted file may restart. Stop keeps completed files and clears the
resume action. No action deletes completed downloads. Retry submits failed
sources again and skips completed files; it is not a per-track metadata refetch.
Library operations require confirmation before modifying tags or deleting
successfully embedded `.lrc` sidecars. Back up your library before applying edits.

## Test and package

Install `requirements-desktop-build.txt`, then run:

```sh
# Linux headless testing; omit the prefix on a graphical desktop.
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q Tests
QT_QPA_PLATFORM=offscreen .venv/bin/python desktop_app.py --smoke-test
.venv/bin/python script/build_desktop.py --package
```

On Windows use `.\.venv\Scripts\python.exe` and set
`$env:QT_QPA_PLATFORM="offscreen"` for headless tests.

The build creates `dist/SpotifyDownloader/` and a platform-specific ZIP. Extract
the entire folder and launch `SpotifyDownloader` (Linux) or
`SpotifyDownloader.exe` (Windows). Keep `helper/` and `_internal/` alongside the
launcher. Python and Qt are bundled; FFmpeg and Node/Deno remain external
prerequisites. Builds are unsigned, require their native OS, and are not
installers. Windows can display an unknown-publisher warning.

The build script tests the actual packaged GUI-to-helper path with local
diagnostics before making the ZIP. It records exact installed dependencies in
`build-info.json`. `.github/workflows/desktop.yml` runs tests and native builds on
Linux and Windows and uploads ZIP artifacts; it does not publish releases.

The native SwiftUI app and its existing `script/build_and_run.sh` remain available
on macOS 14+. A Linux build does not validate the Windows or SwiftUI app.

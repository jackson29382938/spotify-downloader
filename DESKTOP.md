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

The build reads `VERSION` and creates `dist/SpotifyDownloader/` and a versioned
platform-specific ZIP (for example `SpotifyDownloader-1.2.0-Linux-x86_64.zip`). Extract
the entire folder and launch `SpotifyDownloader` (Linux) or
`SpotifyDownloader.exe` (Windows). Keep `helper/` and `_internal/` alongside the
launcher. Python and Qt are bundled; FFmpeg and Node/Deno remain external
prerequisites. Builds are unsigned, require their native OS, and are not
installers. Windows can display an unknown-publisher warning.

The build script tests the actual packaged GUI-to-helper path with local
diagnostics before making the ZIP. It records exact installed dependencies in
`build-info.json`. `.github/workflows/desktop.yml` runs tests and native builds on
Linux and Windows and uploads ZIP artifacts; it also compiles/tests the native
Swift app on macOS and verifies its packaged helper. It does not publish releases.

The native SwiftUI app and its existing `script/build_and_run.sh` remain available
on macOS 14+. The script reads the same `VERSION` file. CI and release builds set
`BUNDLE_FFMPEG=0` and require FFmpeg on the destination Mac; copying a Homebrew
executable alone would not make its dependent libraries portable. Local Mac
builds retain the existing optional FFmpeg bundling behavior.

A Linux build does not validate the Windows or SwiftUI app.

## Publish a verified release

Create an annotated version tag at a commit whose **Desktop builds** run passed
on all three platforms. Run **Publish verified release** in GitHub Actions with
that tag and the successful build run ID. The publisher checks that the tag,
`VERSION`, CI commit, required native jobs and archive versions match. It uploads
the three native ZIPs plus `SHA256SUMS`, verifies GitHub's uploaded SHA-256
digests, and only then publishes the draft release. It refuses failed/mismatched
builds or changes to an already-published release with different assets.

The publisher uses the runner's repository token; no extra credential is needed.
This also supports publication when a cloud task's upload proxy cannot forward
GitHub binary asset requests correctly. The current Mac download targets Apple
Silicon; Intel Macs can build the native app from source.

## Queue recovery and match details (1.2.0)

The Linux/Windows Qt app saves an unfinished queue before starting a download.
After restarting, press Resume to use the original links, folder and options;
completed files are skipped. Closing an active download keeps the queue, while
Stop deliberately discards it. Successful completion clears it. Failed or
interrupted jobs remain recoverable. An unfinished file can restart.

Saved queues are local application settings and include source links and output
paths. Browser cookie selections are not saved; choose them again for a new
Download if authentication is needed. Recovery never starts downloads automatically.
This queue recovery feature applies to the Qt application, not the native SwiftUI app.

Diagnostics now records each selected YouTube title, URL, duration and matching
reason before its download begins. This is an explanation of the automatic match,
not a manual approval step. Spotify metadata Preview does not search YouTube.
Local checks provide FFmpeg and JavaScript runtime installation advice for the
current operating system. Restart the app after installing those dependencies.

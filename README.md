# Spotify + YouTube Downloader

Native macOS app plus a Python downloader that avoids `spotdl`. It reads public
Spotify embed metadata for tracks/playlists, searches YouTube with `yt-dlp`,
downloads audio, and writes local metadata when `mutagen` is available. It can
also download direct YouTube video URLs as MP4 files.

Use this only with music you own, have permission to download, or are otherwise
allowed to store locally. See [DISCLAIMER.md](DISCLAIMER.md) for the full local
usage notice.

## Full-history Sunnify parity

This app keeps its native SwiftUI shell and Python downloader, but independently
adopts the useful Sunnify behaviors that fit here, including pre-2.0 history and
the `2.0.12` release line. The latest upstream review was against commit
`29ae242` from June 24, 2026. See [SUNNIFY_PARITY.md](SUNNIFY_PARITY.md) for the
full ledger and [NOTICE.md](NOTICE.md) for attribution.

- Spotify tracks, playlists, albums, locale URLs, and `spotify:` URIs.
- Full-playlist fallback when Spotify's embed page exposes only the first page.
- Strict YouTube matching by title, artist, and duration, with an optional
  closest-duration fallback for hard-to-match international tracks.
- Per-track artwork and real album metadata when Spotify exposes it.
- Resume manifests inside playlist/album folders plus existing-file handling.
- Track-number filename prefixes that can be turned off.
- MP3 tags saved as ID3v2.3 for wider player compatibility, plus metadata for
  M4A, FLAC, Opus, and Ogg. WAV downloads are left untagged.
- Rotating diagnostic logs in `~/Library/Logs/Spotify Downloader`.
- More resilient Spotify page parsing for embed-layout changes.
- Resume-aware large-playlist metadata fetching, so completed tracks do not
  force another round of per-track Spotify lookups on the next run.
- Preview-before-download, a native queue/detail view, retry failed items,
  diagnostics copy, helper health checks, and download history.

## Mac App

Paste Spotify or YouTube URLs on separate lines, choose **Audio** or
**YouTube Video**, then press **Preview** to inspect detected tracks, artwork,
output folders, and possible errors. Press **Download** when the queue looks
right.

- **Audio** downloads Spotify tracks/playlists/albums or direct YouTube URLs as audio.
- **YouTube Video** downloads direct YouTube URLs as MP4 video files.

Defaults:

- Test track: `https://open.spotify.com/track/1gQzzNczLJ05y9KVx40hVU?si=45ba5354a24e4bca`
- Download folder: your macOS `Downloads` folder
- Parallel downloads: 4 worker threads
- Format: MP3 at `192k`
- Matching: strict by default
- Filenames: track-number prefixes on by default

Run it from Codex with the **Run** action, or from Terminal:

```bash
./script/build_and_run.sh
```

The run script creates or repairs `.venv` when needed, installs the downloader
requirements plus PyInstaller, and then bundles the Python helper into the app.
It also ad-hoc signs the generated app and verifies the bundle when `codesign`
is available.

The portable app bundle is created at:

```text
dist/Spotify Downloader.app
```

To build a zip that preserves the app bundle:

```bash
./script/build_and_run.sh --package
```

That creates:

```text
dist/Spotify Downloader Portable.zip
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python spotify_dl.py doctor
```

The Mac app automatically uses `.venv/bin/python` when that environment exists.

If `doctor` reports that FFmpeg is missing:

```bash
brew install ffmpeg
```

## Command Line

Preview the default test track without downloading:

```bash
python3 spotify_dl.py preview --json \
  "https://open.spotify.com/track/1gQzzNczLJ05y9KVx40hVU?si=45ba5354a24e4bca"
```

Check local helper diagnostics:

```bash
python3 spotify_dl.py health --json
```

Preview metadata cleanup for an existing music folder:

```bash
python3 spotify_dl.py library "$HOME/Music" --json
```

Apply matched title, artist, album, genre, artwork, and lyrics updates:

```bash
python3 spotify_dl.py library "$HOME/Music" --apply
```

Download a track:

```bash
python3 spotify_dl.py download \
  "https://open.spotify.com/track/1gQzzNczLJ05y9KVx40hVU?si=45ba5354a24e4bca"
```

Download a playlist with more parallel workers:

```bash
python3 spotify_dl.py download --threads 8 \
  "https://open.spotify.com/playlist/5muwkD7R2mvt4ejSrymQsb?si=c95c68b2234d4f80"
```

Useful options:

```bash
# Download a YouTube video as MP4
python3 spotify_dl.py download --media video \
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Download a YouTube URL as audio
python3 spotify_dl.py download --media audio \
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Change output folder
python3 spotify_dl.py download -o "$HOME/Downloads/Music" <spotify-url>

# M4A output
python3 spotify_dl.py download --format m4a --bitrate 192k <spotify-url>

# Replace existing files instead of skipping them
python3 spotify_dl.py download --overwrite force <spotify-url>

# Refresh metadata for existing files
python3 spotify_dl.py download --overwrite metadata <spotify-url>

# Turn off playlist/album track-number filename prefixes
python3 spotify_dl.py download --no-track-number-prefix <spotify-url>

# Use the closest duration match when strict title/artist matching fails
python3 spotify_dl.py download --allow-closest-match <spotify-url>

# Write verbose diagnostics to the rotating log
python3 spotify_dl.py download --debug-log <spotify-url>

# Emit newline-delimited JSON progress events while still preserving CLI behavior
python3 spotify_dl.py download --json-events <spotify-url>
```

Download history is appended to:

```text
~/Library/Application Support/Spotify Downloader/download-history.jsonl
```

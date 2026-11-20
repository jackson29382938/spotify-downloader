# Spotify Downloader 1.2.1

- When a selected browser's cookies cannot be loaded, downloads report the
  issue once and continue without cookies for that run. Some videos still
  require a working signed-in browser.
- Lyrics tags contain clean text. MP3 files keep word or line timing in an
  embedded SYLT frame. Enable **Save .lrc for playback** to also save a
  timed lyrics file for compatible players.
- Use **Lyrics Tools → Remove Timestamps** to repair existing files. MP3s keep
  embedded timing, and other formats keep timing in an .lrc file. Apple Music
  displays custom lyrics for local files as plain text.

Extract the ZIP for your operating system. The macOS ZIP supports Apple Silicon
and requires macOS 14 or later. Install FFmpeg and Node 22+ (or Deno 2+)
separately. See DESKTOP.md for setup details.

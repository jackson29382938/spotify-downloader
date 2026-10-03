# Spotify Downloader 1.2.0

Linux and Windows desktop queues now survive application restarts. Recovered
queues wait for Resume and skip completed files using the original links, folder
and options. Closing an active download retains its queue; Stop discards it.
Failed jobs remain recoverable, and successful completion clears saved state.
Browser cookie selections are not persisted.

Diagnostics records each automatic YouTube match's title, URL, duration and
selection reason before downloading. Dependency checks now explain how to install
FFmpeg and Node/Deno on the destination operating system, including Windows.
These UI improvements apply to the Qt desktop application; the native Mac app
receives the shared helper diagnostics and match events.

A generated-media integration test exercises real yt-dlp transfer, FFmpeg MP3
conversion, metadata tagging, manifest recording and completed-file skipping on
all three native CI platforms. Queue recovery tests cover restart, failures,
success, explicit stop and damaged settings.

## Installation and limitations

Extract the complete ZIP for your OS. Install FFmpeg and Node 22+ (or Deno 2+)
separately and restart the application. On macOS: `brew install ffmpeg node`.
The native Mac app requires macOS 14+ and the packaged Mac download supports Apple
Silicon. Intel Macs can build from source. Linux/Windows bundles are unsigned;
the Mac app is ad-hoc signed and is not Apple-notarized.

The generated-media test validates the local pipeline, not YouTube authentication,
live service availability or Apple Music access. Those still require a real user
session. Matching remains automatic and heuristic; Spotify Preview does not use
browser cookies or preselect YouTube uploads. Completed files survive interruption,
but partial files may restart. See DESKTOP.md for queue recovery and setup details.

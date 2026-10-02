# Spotify Downloader 1.1.0

This release adds Linux and Windows desktop applications alongside the native
macOS app. All use the shared Python downloader.

## New desktop applications

- Metadata preview and audio/video downloads with per-track progress.
- Pause/resume that keeps completed files, plus retry of failed sources.
- Local diagnostics, download history, and library metadata/lyrics tools.
- Portable ZIPs with Python and Qt bundled for Linux and Windows.

## Reliability and safety fixes

- Bound Unicode filenames by bytes and preserve collision suffixes.
- Escape filename glob characters and reject resume paths outside a collection.
- Preserve existing files when diagnostics check output-folder writability.
- Report preview failures and blocked network access accurately.
- Discover Windows `.exe` runtimes and stop scheduling work after cancellation.
- Prevent equal clock readings from counting a bot-check response twice.
- Make history-write failure tests portable across operating systems.

## Installation

Download the ZIP for your OS and processor architecture and extract it completely.
For Linux/Windows, keep the helper and internal folders beside the launcher.
See DESKTOP.md in the ZIP or repository for source installation and platform
library requirements.

FFmpeg and Node 22+ (or Deno 2+) must be installed separately and available on
PATH on the destination machine. The macOS release intentionally does not bundle
Homebrew's dynamically linked FFmpeg executable. On macOS, `brew install ffmpeg
node` supplies those prerequisites; the native app requires macOS 14+.

Linux/Windows bundles are unsigned. The native macOS app is ad-hoc signed, not
Apple-notarized, so macOS can require explicit approval to open it. Apple Music
automation is supported only by the native Mac app and requires local permission.

## Validation and limitations

Native CI runs the Python/Qt suite and packaged-helper checks on Linux and
Windows. macOS CI runs the Python/Qt suite, Swift tests, app compilation, bundle
signature checks and packaged-helper health checks. Release assets must come from
one successful CI run for the release commit.

Interactive desktop behavior, Apple Music integration against a real library,
and authorized end-to-end downloads still need real-user validation. Preview
does not use browser cookies. Matching is heuristic and external services can
require authentication or rate-limit access. See AUDIT.md for the review scope
and remaining limits.

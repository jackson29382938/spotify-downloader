# Cross-platform application audit

This review covers the Python downloader, the new Qt client and helper boundary,
filename/resume handling, diagnostics, cancellation, and portable packaging.
The Swift sources and macOS build workflow were inspected for protocol and
platform constraints; they were not compiled on this Linux host. This is a
focused engineering audit, not a claim that every dependency or execution path
has been security-reviewed.

## Findings fixed

| Finding | Impact | Correction and evidence |
| --- | --- | --- |
| Collision suffix was truncated on maximum-length filenames | Reserving an existing 200-character filename could loop indefinitely | Reserve space for the suffix before sanitizing; regression test verifies `(2)` survives |
| Filename limit counted characters rather than UTF-8 bytes | International titles could exceed filesystem component limits | Cap sanitized stems at 200 UTF-8 bytes; test creates a real file with a long Unicode title |
| Existing-file lookup interpreted brackets as glob syntax | An unrelated filename could be considered an existing track | Escape the stem before globbing; bracketed-title regression |
| Resume manifests accepted absolute/traversal paths and external symlinks | A malformed local manifest could select files outside the collection folder | Require a direct child after resolution; traversal, Windows separator, NUL and symlink regressions |
| Diagnostics wrote and deleted a predictable probe filename | A pre-existing user file at that name could be overwritten | Use a unique temporary file; preservation regression |
| Network health accepted HTTP 403 and excluded network failures from `ok` | Blocked access could look healthy | Fail requested network checks on HTTP 4xx/5xx; regression for 403 |
| JavaScript/EJS checks did not affect local readiness | YouTube prerequisites could be missing despite a successful report | Include both in required local checks; missing-runtime regression |
| Preview returned exit code zero when sources failed | Automation could mistake partial/total failure for success | Keep JSON errors and return nonzero; GUI also inspects per-source errors |
| Discovery used extensionless paths on Windows | Locally installed/bundled FFmpeg and JS runtimes could be missed | Discover `.exe` paths; Windows-path regression |
| Cancellation could keep queuing a playlist or advance to another source | Work could continue after a stop request | Check the shared stop event before queueing or advancing; single/multiple worker regressions |
| Equal clock readings could count the same bot-check batch twice | Windows could exhaust retries too quickly | Treat requests at the cooldown boundary as already counted; deterministic zero/equal-clock regressions |
| History failure test assumed `/proc` was unwritable | The test created a real folder on Windows and incorrectly failed | Use a temporary regular file as the parent to produce a real, portable write failure |

## Desktop architecture and controls

- The GUI uses QProcess and argument arrays, with no shell interpolation. Paths
  containing spaces, shell operators and Unicode remain literal arguments.
- The helper runs in a dedicated POSIX session. On Windows it uses a
  non-inheritable Job Object with kill-on-close enabled. Cooperative cancellation
  is sent over stdin; a five-second timeout then kills the owned process tree.
  Closing the control pipe also cancels the helper if the owning GUI disappears.
  The POSIX descendant termination test ran locally. The native Windows Job
  Object test is included in CI and was skipped on Linux.
- Streaming reads preserve fragmented UTF-8 and final records without a newline.
  Records have a 16 MiB limit; activity keeps 2,000 blocks and history reads a
  bounded tail (at most 1 MiB / 500 entries). Unexpected JSON cannot count as a
  successful result. Start failure, timeout and oversized-output tests exercise
  actual subprocesses.
- Only one helper operation can run at a time. Controls are disabled while it
  runs. Pause waits for exit before enabling Resume, retains the original links
  and settings, and resumes with existing-file skipping. Stop clears Resume.
  Closing a busy window confirms cancellation and waits for helper exit.
- The desktop app never deletes completed downloads. Destructive library tag
  edits and successful `.lrc` deletion require a specific confirmation.
- PyInstaller builds the console helper separately from the windowed GUI, so
  frozen Windows helpers retain their JSON output streams. The build runs the
  packaged GUI-to-helper local health check before creating a ZIP and records
  exact installed dependency versions. FFmpeg and Node/Deno stay external.

## Validation

- Linux source suite: **122 passed, 1 skipped**. The skipped test requires native
  Windows Job Objects. Tests include existing backend regressions and Qt GUI /
  real subprocess integration checks.
- Local helper diagnostics and dependency consistency checks passed.
- Synthetic audio was generated and encoded with FFmpeg, tagged by the backend,
  and read back successfully. No third-party media was downloaded for this test.
- The source Qt interface was rendered offscreen and visually inspected. The
  packaged Linux GUI/helper path passed its offscreen smoke check. A real desktop
  session is still needed to assess display-server-specific behavior.
- Live Spotify preview returned the README track's title, artist, album and
  duration successfully. YouTube preview failed with a proxy HTTP 403; Spotify
  artwork at `image-cdn-fa.spotifycdn.com` was also denied. Network settings need
  to be applied before validating live YouTube access, artwork and downloads.
- Native Linux/Windows tests and ZIP builds are configured in
  `.github/workflows/desktop.yml`. Configuring CI is not evidence of a completed
  Windows build. macOS SwiftUI builds also remain unverified here.
- The first native CI run passed on Linux. Windows reported two test failures:
  the Linux-only history fixture and the equal-clock bot-check bug above. Both
  are corrected; Windows readiness still requires a successful native CI rerun.

## Remaining limits

This first Qt client preserves the core workflow rather than every native macOS
setting. Apple Music automation stays in the SwiftUI app. Preview does not use
the browser-cookie setting; authenticated YouTube preview can fail even when a
download using local cookies would work. Pause state is held for the current UI
session; completed files/manifests persist across restarts and can be reused by
submitting the original links again with skipping enabled. Partial files may
restart. Retry operates on failed sources, not individual failed-track metadata.

Network diagnostics currently probe Spotify only. They do not prove YouTube,
artwork, lyrics or lookup services are reachable. Metadata matching remains a
heuristic and may choose an incorrect upload; existing strict/flexible matching
tests were preserved. Local caches/manifests and library files are trusted local
inputs beyond the added path checks, not a hardened remote multi-user service.

Portable bundles are unsigned, need a compatible native OS, and require FFmpeg
and Node/Deno on PATH. Native Windows CI and macOS checks, actual display sessions,
and authorized end-to-end downloads are outstanding release validation.

## 1.2.0 follow-up

Reviewed Qt queue persistence against interruption, restart, successful completion,
failed downloads, explicit stop, closing an active operation and cancellation of
unrelated diagnostics. Queue recovery is schema-validated, limited to 1 MiB,
never auto-started and always skips existing completed files. Local settings
contain links and output paths; browser cookie choices are omitted. Damaged
settings are discarded with a visible explanation. Native SwiftUI queue recovery
is unchanged.

Selected-match events now expose the candidate title, URL, duration and selection
reason before transfer. Qt displays those in Diagnostics; this does not add a
manual candidate approval step. CLI and shared-helper diagnostics offer dependency
installation instructions for the destination OS.

The generated-audio integration test uses a local HTTP server and real yt-dlp,
FFmpeg, Mutagen and manifest logic. It verifies MP3 duration/tags and that a second
run preserves the completed file. External YouTube candidate search alone is
substituted with the controlled local fixture. This proves local transfer and
processing, not live YouTube authentication or real Apple Music library access.

Signing/notarization requires the owner's signing identities and certificates;
none are configured in the managed cloud. Releases remain unsigned/ad-hoc signed.
Intel Mac release packaging remains a future addition; source builds are available.

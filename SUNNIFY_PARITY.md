# Sunnify Parity Ledger

Reference repository: https://github.com/sunnypatell/sunnify-spotify-downloader

Last reviewed upstream commit: `29ae242` (`main`, 2026-06-24)

This app reimplements useful Sunnify behavior inside a native SwiftUI macOS app.
It does not vendor Sunnify's PyQt UI, web client, backend service, legacy mirror
downloaders, or release infrastructure.

## Status Key

- `Implemented`: present in this app.
- `Adapted`: implemented in a local/native form.
- `Excluded`: intentionally not included.
- `Not applicable`: upstream item does not fit this app.

## Pre-2.0 History

| Upstream facet | Status | Local handling |
| --- | --- | --- |
| Initial PyQt desktop app | Excluded | Replaced by native SwiftUI macOS app. |
| Windows executable packaging | Not applicable | This project targets macOS. |
| Legacy `spotifydown` / y2mate mirror strategy | Excluded | Replaced by public Spotify embed metadata plus yt-dlp. |
| Playlist offset pagination via legacy API | Adapted | Full playlists use Spotify embed plus spclient fallback. |
| ID3 metadata and cover embedding | Implemented | MP3 uses ID3v2.3; M4A/FLAC/Opus/Ogg are tagged where supported. |
| Flask backend / SSE streaming | Excluded | Native app uses local helper subprocess calls. |
| Next.js web preview client | Adapted | Native preview queue shows detected sources and tracks. |
| API status diagnostic script | Adapted | `spotify_dl.py health` reports helper, dependency, output, and optional network diagnostics. |
| Repo hygiene, issue templates, legal docs | Adapted | Local README, NOTICE, DISCLAIMER, and this parity ledger document scope and responsible use. |
| Provider migration from dead APIs to Spotify embed pages | Implemented | Spotify track, playlist, album, locale URLs, and `spotify:` URIs are supported. |

## 2.x Runtime Parity

| Version/facet | Status | Local handling |
| --- | --- | --- |
| 2.0.0 single-track support | Implemented | Spotify tracks and direct YouTube URLs are supported. |
| 2.0.0 stop/cancel | Adapted | Swift app terminates the helper and marks active queue items cancelled. |
| 2.0.0 health endpoint | Adapted | Local `health` command feeds the diagnostics panel. |
| 2.0.1 ffmpeg detection | Implemented | Helper checks bundled, project, Homebrew, and PATH locations. |
| 2.0.2 embed structure resilience | Implemented | Entity extraction tries known paths and recursive fallbacks. |
| 2.0.2 retryable network errors | Adapted | Spotify 429s retry with backoff; diagnostics surface failures. |
| 2.0.3 yt-dlp resilience | Implemented | Downloads retry and use alternate YouTube player clients when needed. |
| 2.0.4 parallel downloads | Implemented | Swift exposes concurrent worker count; helper uses thread pools. |
| 2.0.4 filename collision guard | Implemented | In-flight and existing output names are de-duplicated. |
| 2.0.5 per-track cover art | Implemented | Tracks are enriched from Spotify track embeds when needed. |
| 2.0.5 track number tags | Implemented | Track numbers are written to supported metadata containers. |
| 2.0.6 audio format/quality settings | Implemented | MP3, M4A, FLAC, Opus, Ogg, and WAV are available. |
| 2.0.6 metadata writers | Implemented | MP3/M4A/FLAC/Opus/Ogg tag writers are present; WAV skips gracefully. |
| 2.0.7 album downloads | Implemented | Spotify album URLs and URIs download into album folders. |
| 2.0.7 resume manifest | Implemented | Existing manifest entries skip completed tracks and metadata re-fetches. |
| 2.0.7 duration-based matching | Implemented | YouTube candidates are checked against Spotify duration. |
| 2.0.8 optional filename prefixes | Implemented | Prefixes remain on by this app's default and can be turned off. |
| 2.0.8 ID3v2.3 MP3 compatibility | Implemented | MP3 text and APIC cover frames are saved as v2.3. |
| 2.0.9 strict title/artist matching | Implemented | Strict matching rejects wrong-artist/title candidates by default. |
| 2.0.9 single-track album metadata | Implemented | Social-preview metadata supplies album names with caching. |
| 2.0.9 settings explanations | Adapted | Native settings and main-panel controls include inline help. |
| 2.0.10 SLSA/SBOM release pipeline | Excluded | Practical local packaging is included; full hosted supply chain is out of scope. |
| 2.0.10 macOS packaging hardening | Adapted | Build script uses app bundle staging, `ditto --keepParent`, ad-hoc signing, and `codesign --verify`. |
| 2.0.11 diagnostic logging | Implemented | Rotating logs include environment, ffmpeg, matching, failures, and history paths. |
| 2.0.11 open logs action | Implemented | Sidebar and settings expose logs folder. |
| 2.0.12 closest-match fallback | Implemented | Strict matching stays default; closest fallback is opt-in. |
| 2.0.12 lean default logs + debug toggle | Implemented | Default logs focus on failures; debug toggles verbose detail. |

## Native Additions Beyond Sunnify

| Feature | Status | Notes |
| --- | --- | --- |
| Preview-before-download | Implemented | `preview --json` feeds the native queue/detail view. |
| Structured queue | Implemented | Sources can be previewed, removed, revealed, retried, and cleared. |
| JSON event stream | Implemented | `download --json-events` emits newline-delimited progress events. |
| Download history | Implemented | Completed source sessions append to app support JSONL history. |
| Diagnostics copy/export | Adapted | The app copies issue-quality diagnostics to the clipboard. |
| YouTube video downloads | Implemented | Direct YouTube URLs can save MP4 video, which Sunnify does not center. |

## Intentional Exclusions

- Old mirror-based audio download APIs.
- Web hosting/deployment surfaces.
- Homebrew cask automation.
- Windows/Linux executable metadata.
- Full release attestations, SBOM generation, and hosted CI hardening.
- Sunnify visual branding and assets.

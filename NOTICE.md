# Notices

This project was reviewed against the full visible Sunnify repository history,
including pre-2.0 commits and the 2.x release series:

- Sunnify Spotify Downloader by Sunny Patel
- Repository: https://github.com/sunnypatell/sunnify-spotify-downloader
- Latest reviewed version: 2.0.12
- Latest reviewed commit: 29ae242, dated June 24, 2026

The macOS app in this repository keeps its own SwiftUI interface and standalone
Python helper. It does not vendor Sunnify's PyQt desktop app or web client.
Where Sunnify behavior was useful, it was adapted into this app's existing
backend shape with local code and tests. Pre-2.0 web/backend ideas were used as
native app concepts only; no web server or web client was imported.

Sunnify is distributed under its own custom educational-use license. Review that
upstream license before redistributing any combined or derived work.

# Working on this repo

- Commit finished work and push it straight to `main`. The owner pulls `main`
  onto their Mac, so work left only on a side branch never reaches the app.
- The Mac checkout updates with `./script/update.sh` (stashes stray local
  edits, pulls `main`, upgrades yt-dlp, rebuilds, and launches the app). Point
  the owner to it after pushing.
- Before pushing, run the helper tests: `.venv/bin/python -m pytest -q Tests`.
- The SwiftUI app only builds on macOS. If you could not compile it, say so
  plainly and ask the owner to run `./script/update.sh` and paste any errors.
- `spotify_dl.py` is the bundled Python helper; the Swift app talks to it
  through JSON events on stdout (`--json-events`).

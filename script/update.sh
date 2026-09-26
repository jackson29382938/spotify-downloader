#!/usr/bin/env bash
# Pull the latest main from GitHub, refresh yt-dlp, then rebuild and launch.
# Usage: ./script/update.sh [same modes as build_and_run.sh]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Local edits found; saving them with git stash so the update can continue."
  git stash push -m "auto-stash before update $(date '+%Y-%m-%d %H:%M')"
  echo "Your edits are saved. Bring them back later with: git stash pop"
fi

if [[ "$(git branch --show-current)" != "main" ]]; then
  git checkout main
fi
git pull --ff-only origin main
echo "Now at: $(git log --oneline -1)"

# YouTube changes often; the newest yt-dlp is usually what keeps downloads working.
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  "$ROOT_DIR/.venv/bin/python" -m pip install --quiet --upgrade "yt-dlp[default]"
fi

exec "$ROOT_DIR/script/build_and_run.sh" "$@"

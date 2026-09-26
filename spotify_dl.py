#!/usr/bin/env python3
"""Download Spotify audio and YouTube media through yt-dlp.

This intentionally does not use spotDL or Spotify API credentials. It reads the
public Spotify embed metadata, searches YouTube with yt-dlp, extracts audio, and
optionally tags output and writes lyrics. Direct YouTube URLs can be downloaded
as audio or full videos.

The script exposes several subcommands consumed by the native macOS app:

    doctor          Check yt-dlp and ffmpeg dependencies.
    download        Download Spotify or YouTube URLs.
    preview         Emit JSON describing the tracks a download would fetch.
    health          Emit a JSON diagnostics report.
    library         Scan/repair an existing music library's metadata.
    embed-lrc       Move .lrc sidecar lyrics into the audio files themselves.
    clean-lyrics    Strip timestamps from embedded lyrics (clean text for Apple Music).
    ffmpeg-install  Install ffmpeg with Homebrew on macOS.
"""

from __future__ import annotations

import argparse
import functools
import html
import io
import json
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote_plus, urlparse
import unicodedata

import requests as req
from yt_dlp import YoutubeDL

try:
    from mutagen.easyid3 import EasyID3
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3, ID3NoHeaderError, SYLT, USLT
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis

    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

try:
    from PIL import Image

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


SUNNIFY_PARITY = "1.0"

SPOTIFY_RE = re.compile(
    r"(?:https?://open\.spotify\.com/(?:intl-[a-z]{2,}(?:-[a-z]{2,})?/)?"
    r"(?P<kind>track|playlist|album)/|"
    r"spotify:(?P<uri_kind>track|playlist|album):)"
    r"(?P<id>[A-Za-z0-9]+)"
)
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
COOKIE_BROWSERS = ("safari", "chrome", "firefox", "chromium", "edge", "opera", "brave")
ARTWORK_SIZES = ("unlimited", "600", "1200")
LYRICS_API = "https://lrclib.net/api/get"
LYRICS_SEARCH_API = "https://lrclib.net/api/search"
LYRICS_STYLES = ("plain", "synced")
ITUNES_API = "https://itunes.apple.com/search"
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2/recording"
USER_AGENT = "Mozilla/5.0"

RUNNING_PROCESSES: set[subprocess.Popen[str]] = set()
RUNNING_LOCK = threading.Lock()
STOP_EVENT = threading.Event()
MANIFEST_LOCK = threading.Lock()
STEM_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()
LYRICS_CACHE_LOCK = threading.Lock()
LYRICS_CACHE: dict[object, dict | None] = {}
IN_FLIGHT_STEMS: set[str] = set()
MANIFEST_FILENAME = ".spotify-downloader-manifest.jsonl"
HISTORY_FILENAME = "download-history.jsonl"
LOG = logging.getLogger("spotify_downloader")
DEFAULT_MIN_CONFIDENCE = 0.72
# 0 = strictest YouTube matching, 1 = loosest (closest-duration fallback).
# 0.25 reproduces the long-standing strict defaults (30 s duration window).
DEFAULT_MATCH_FLEXIBILITY = 0.25
DEFAULT_RENAME_PATTERN = "{track_number}. {title} - {artist}"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav", ".aac"}
RESERVED_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
COMMON_TITLE_SUFFIX_RE = re.compile(
    r"\s*(?:[-(]\s*)?"
    r"(?:\d{4}\s+)?(?:official\s+)?(?:audio|video|lyrics?|visualizer|remaster(?:ed)?|"
    r"mono|stereo|live|sped\s+up|slowed|nightcore|clean|explicit)"
    r"(?:\s+\d{4})?\s*[)]?\s*$",
    re.IGNORECASE,
)
MODIFIER_KEYWORDS = (
    "sped up",
    "spedup",
    "slowed",
    "nightcore",
    "reverb",
    "8d",
    "bitcrushed",
    "remix",
    "instrumental",
    "acoustic",
    "cover",
    "live",
    "mashup",
    "demo",
)
LRC_TIMESTAMP_RE = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
LRC_TIMESTAMP_PARTS_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
LRC_METADATA_RE = re.compile(r"^\s*\[[A-Za-z#]+:[^\]]*\]\s*$")
# Spotify appends edition notes ("- 2015 Remaster", "(Mono Version)") that
# YouTube uploads rarely repeat. Tails made only of these words are dropped
# before searching and matching; anything else ("Live", "Remix") is kept.
NEUTRAL_VERSION_WORDS = {
    "remaster", "remastered", "remasterizado", "remasterizada", "version", "edit",
    "radio", "single", "album", "mono", "stereo", "original", "digital", "deluxe",
    "edition", "bonus", "track", "anniversary", "expanded", "explicit", "clean",
    "mix", "master", "st", "nd", "rd", "th",
}
FEATURE_SEGMENT_RE = re.compile(
    r"\s*(?:[(\[]\s*(?:feat\.?|featuring|ft\.?|with)\s+[^)\]]*[)\]]|-\s+(?:feat\.?|featuring|ft\.?|with)\s+.*$)",
    re.IGNORECASE,
)
DASH_TAIL_RE = re.compile(r"\s+-\s+(?P<tail>[^-]+?)\s*$")
BRACKET_TAIL_RE = re.compile(r"\s*[(\[](?P<tail>[^()\[\]]+)[)\]]\s*$")
SOUNDTRACK_TAIL_RE = re.compile(
    r"^from\b.*\b(?:soundtrack|motion picture|film|movie|series|musical|original score)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Track:
    name: str
    artists: str
    spotify_id: str | None = None
    duration_ms: int | None = None
    cover_url: str | None = None
    album: str | None = None


@dataclass(frozen=True)
class Lyrics:
    plain: str | None = None
    synced: str | None = None

    def __bool__(self) -> bool:
        return bool(self.plain or self.synced)

    def text(self, style: str = "plain") -> str | None:
        """Text for the standard lyrics tag: LRC timestamps only when asked for."""
        if style == "synced" and self.synced:
            return self.synced
        if self.plain:
            return self.plain
        return strip_lrc_timestamps(self.synced) if self.synced else None

    def synced_lines(self) -> list[tuple[str, int]]:
        return parse_lrc(self.synced) if self.synced else []


@dataclass(frozen=True)
class SpotifyCollection:
    name: str
    tracks: list[Track]
    use_subfolder: bool
    cover_url: str | None = None
    track_cover_fallback_url: str | None = None
    kind: str = "track"


@dataclass(frozen=True)
class DownloadResult:
    ok: bool
    label: str
    detail: str = ""
    path: str | None = None
    skipped: bool = False
    created_this_run: bool = False
    warning: str | None = None


@dataclass
class RunOptions:
    bitrate: str = "192k"
    fmt: str = "mp3"
    overwrite: str = "skip"
    track_number_prefix: bool = True
    allow_closest_match: bool = False
    match_flexibility: float = DEFAULT_MATCH_FLEXIBILITY
    lyrics: bool = True
    lyrics_style: str = "plain"
    write_lrc: bool = False
    cookies_browser: str | None = None
    artwork_max_size: int | None = None
    artwork_jpeg: bool = False
    json_events: bool = False
    media: str = "audio"
    ffmpeg_location: str | None = None
    retries: int = 2

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "RunOptions":
        return cls(
            bitrate=getattr(args, "bitrate", "192k"),
            fmt=getattr(args, "fmt", "mp3"),
            overwrite=getattr(args, "overwrite", "skip"),
            track_number_prefix=getattr(args, "track_number_prefix", True),
            allow_closest_match=getattr(args, "allow_closest_match", False),
            match_flexibility=max(0.0, min(1.0, getattr(args, "match_flexibility", DEFAULT_MATCH_FLEXIBILITY))),
            lyrics=getattr(args, "lyrics", True),
            lyrics_style=getattr(args, "lyrics_style", "plain"),
            write_lrc=getattr(args, "write_lrc", False),
            cookies_browser=getattr(args, "cookies_browser", None),
            artwork_max_size=artwork_size_value(getattr(args, "artwork_max_size", "unlimited")),
            artwork_jpeg=getattr(args, "artwork_jpeg", False),
            json_events=getattr(args, "json_events", False),
            media=getattr(args, "media", "audio"),
            retries=max(0, min(5, getattr(args, "retries", 2))),
        )


@dataclass
class LibraryTrackGuess:
    path: Path
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    duration_ms: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    from_filename: bool = False


@dataclass
class LibraryMetadata:
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    year: str | None = None
    duration_ms: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    artwork_url: str | None = None
    source: str = "unknown"
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Paths & logging
# ---------------------------------------------------------------------------


def app_support_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Spotify Downloader"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Spotify Downloader"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "spotify-downloader"


def history_path() -> Path:
    return app_support_dir() / HISTORY_FILENAME


def log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Spotify Downloader"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Spotify Downloader" / "logs"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "spotify-downloader" / "logs"


def setup_logging(debug: bool = False) -> Path:
    path = log_dir()
    path.mkdir(parents=True, exist_ok=True)
    log_path = path / "downloader.log"

    if not any(getattr(handler, "_spotify_downloader", False) for handler in LOG.handlers):
        handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        handler._spotify_downloader = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
        )
        LOG.addHandler(handler)
        LOG.propagate = False

    LOG.setLevel(logging.DEBUG if debug or os.environ.get("SPOTIFY_DOWNLOADER_DEBUG") else logging.INFO)
    LOG.info("session start python=%s platform=%s", sys.version.split()[0], sys.platform)
    return log_path


def safe(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")[:200]
    if not cleaned:
        return "Unknown"
    if cleaned.split(".")[0].upper() in RESERVED_DEVICE_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


# ---------------------------------------------------------------------------
# JSON events & history
# ---------------------------------------------------------------------------


OUTPUT_LOCK = threading.Lock()


def print(*values: object, sep: str | None = " ", end: str | None = "\n", file=None, flush: bool = False) -> None:  # noqa: A001
    """Thread-safe print: each call becomes one write of the whole line.

    The built-in print writes the text and the newline separately, so with
    several download threads a JSON progress event could be split by another
    thread's output. The app then missed that song's final state.
    """
    stream = file if file is not None else sys.stdout
    if stream is None:
        return
    text = (" " if sep is None else sep).join(str(value) for value in values) + ("\n" if end is None else end)
    with OUTPUT_LOCK:
        stream.write(text)
        if flush:
            stream.flush()


def emit_json_event(enabled: bool, event: str, **fields: object) -> None:
    if not enabled:
        return
    record: dict[str, object] = {"event": event, "timestamp": time.time()}
    record.update({key: value for key, value in fields.items() if value is not None})
    print(json.dumps(record, ensure_ascii=False), flush=True)


def append_history(record: dict[str, object]) -> None:
    path = history_path()
    payload = {"timestamp": datetime.now(timezone.utc).isoformat()}
    payload.update(record)
    with HISTORY_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


SPOTIFY_URL_TAIL_RE = re.compile(r"(?:[/?#]\S*)?")


def spotify_match(url: str) -> re.Match[str] | None:
    """Match only input that is itself a Spotify link, not text that contains one."""
    text = url.strip()
    match = SPOTIFY_RE.match(text)
    if not match or not SPOTIFY_URL_TAIL_RE.fullmatch(text[match.end():]):
        return None
    return match


def parse_spotify_url(url: str) -> tuple[str, str]:
    match = spotify_match(url)
    if not match:
        raise ValueError(f"not a supported Spotify track, playlist, or album URL: {url}")
    return (match.group("kind") or match.group("uri_kind")), match.group("id")


def is_spotify_url(url: str) -> bool:
    return spotify_match(url) is not None


def is_youtube_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and (
        host in YOUTUBE_HOSTS
        or host.endswith(".youtube.com")
        or host.endswith(".youtube-nocookie.com")
    )


# ---------------------------------------------------------------------------
# Spotify metadata
# ---------------------------------------------------------------------------


def spotify_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 20) -> req.Response:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_response: req.Response | None = None
    for attempt in range(4):
        response = req.get(url, headers=request_headers, timeout=timeout)
        last_response = response
        if response.status_code != 429:
            response.raise_for_status()
            return response
        delay = 1.5 ** attempt
        LOG.warning("Spotify rate-limited request, retrying in %.1fs: %s", delay, url)
        time.sleep(delay)

    assert last_response is not None
    last_response.raise_for_status()
    return last_response


def session_token_from(data: dict) -> str | None:
    paths = (
        ("props", "pageProps", "state", "settings", "session"),
        ("props", "pageProps", "settings", "session"),
        ("props", "pageProps", "session"),
    )
    for path in paths:
        value: object = data
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, dict) and isinstance(value.get("accessToken"), str):
            return value["accessToken"]
    return None


def _looks_like_entity(node: object) -> bool:
    if not isinstance(node, dict):
        return False
    if "trackList" in node:
        return True
    if node.get("type") == "track":
        return True
    has_name = "title" in node or "name" in node
    has_meta = "artists" in node or "uri" in node or "duration" in node
    return has_name and has_meta


def _search_for_entity(node: object) -> dict | None:
    if _looks_like_entity(node):
        return node  # type: ignore[return-value]
    if isinstance(node, dict):
        for value in node.values():
            found = _search_for_entity(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _search_for_entity(item)
            if found is not None:
                return found
    return None


def extract_spotify_entity(data: dict) -> dict:
    """Pull the track/collection entity out of a Spotify __NEXT_DATA__ payload."""
    known_paths = (
        ("props", "pageProps", "state", "data", "entity"),
        ("props", "pageProps", "data", "entity"),
        ("props", "pageProps", "state", "entity"),
    )
    for path in known_paths:
        value: object = data
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, dict):
            return value

    found = _search_for_entity(data)
    if found is not None:
        return found
    raise ValueError("Spotify embed metadata was not found.")


def entity_from_og_tags(html_text: str, kind: str) -> dict | None:
    """Recover a minimal entity from open-graph <meta> tags (HTML fallback)."""

    def meta(prop: str) -> str | None:
        match = re.search(
            rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)["\']',
            html_text,
            re.IGNORECASE,
        ) or re.search(
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']{re.escape(prop)}["\']',
            html_text,
            re.IGNORECASE,
        )
        return html.unescape(match.group(1)).strip() if match else None

    title = meta("og:title")
    if not title:
        return None

    description = meta("og:description") or ""
    image = meta("og:image")
    parts = [part.strip() for part in description.split("·") if part.strip()]
    subtitle = parts[0] if parts else "Unknown"

    entity: dict[str, object] = {"name": title, "title": title, "subtitle": subtitle, "type": kind}
    if image:
        entity["coverArt"] = {"sources": [{"url": image}]}
    return entity


def best_image(entity: dict) -> str | None:
    candidates: list[dict] = []
    visual_images = entity.get("visualIdentity", {}).get("image", []) if isinstance(entity.get("visualIdentity"), dict) else []
    cover_sources = entity.get("coverArt", {}).get("sources", []) if isinstance(entity.get("coverArt"), dict) else []
    candidates.extend(visual_images)
    candidates.extend(cover_sources)
    candidates = [item for item in candidates if isinstance(item, dict) and item.get("url")]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("maxWidth") or item.get("width") or 0, reverse=True)
    return candidates[0]["url"]


def artists_from(value: object, fallback: str = "Unknown") -> str:
    if isinstance(value, list):
        names = [item.get("name", "").strip() for item in value if isinstance(item, dict)]
        return ", ".join(name for name in names if name) or fallback
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def spotify_id_from(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"spotify:track:([A-Za-z0-9]+)", value)
    return match.group(1) if match else None


def parse_track_album_from_page(html_text: str) -> str | None:
    match = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        html_text,
        re.IGNORECASE,
    ) or re.search(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
        html_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    parts = [part.strip() for part in html.unescape(match.group(1)).split("·")]
    return parts[1] if len(parts) >= 3 and parts[1] else None


def fetch_track_album(spotify_id: str) -> str | None:
    try:
        response = spotify_get(
            f"https://open.spotify.com/track/{spotify_id}",
            timeout=15,
        )
        return parse_track_album_from_page(response.text)
    except Exception as exc:
        LOG.info("album fetch failed for %s: %s", spotify_id, exc)
        return None


def fetch_embed_page(kind: str, spotify_id: str) -> tuple[dict, str | None]:
    url = f"https://open.spotify.com/embed/{kind}/{spotify_id}"
    response = spotify_get(url, timeout=20)

    match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    if match:
        try:
            data = json.loads(match.group(1))
            return extract_spotify_entity(data), session_token_from(data)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            LOG.info("__NEXT_DATA__ parse failed for %s/%s: %s", kind, spotify_id, exc)

    fallback = entity_from_og_tags(response.text, kind)
    if fallback is not None:
        LOG.info("recovered %s/%s from open-graph tags", kind, spotify_id)
        return fallback, None

    raise ValueError("Spotify embed metadata was not found.")


def fetch_embed_entity(kind: str, spotify_id: str) -> dict:
    entity, _ = fetch_embed_page(kind, spotify_id)
    return entity


def track_from_entity(
    entity: dict,
    fallback_cover: str | None = None,
    album: str | None = None,
    spotify_id: str | None = None,
) -> Track:
    return Track(
        name=entity.get("title") or entity.get("name") or "Unknown",
        artists=artists_from(entity.get("artists"), entity.get("subtitle") or "Unknown"),
        spotify_id=spotify_id or spotify_id_from(entity.get("uri")),
        duration_ms=entity.get("duration"),
        cover_url=best_image(entity) or fallback_cover,
        album=album,
    )


def track_from_collection_item(item: dict, fallback_cover: str | None, album: str | None) -> Track:
    return Track(
        name=item.get("title") or item.get("name") or "Unknown",
        artists=artists_from(item.get("artists"), item.get("subtitle") or "Unknown"),
        spotify_id=spotify_id_from(item.get("uri")),
        duration_ms=item.get("duration"),
        cover_url=best_image(item) or fallback_cover,
        album=album,
    )


def fetch_spclient_track_ids(playlist_id: str, token: str) -> list[str]:
    url = f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}"
    response = spotify_get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
    )
    data = response.json()
    items = data.get("contents", {}).get("items", [])
    track_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri")
        if isinstance(uri, str) and uri.startswith("spotify:track:"):
            track_ids.append(uri.rsplit(":", 1)[-1])
    return track_ids


def fetch_track_by_id(spotify_id: str) -> Track:
    entity = fetch_embed_entity("track", spotify_id)
    return track_from_entity(entity, album=fetch_track_album(spotify_id), spotify_id=spotify_id)


def complete_playlist_tracks(
    playlist_id: str,
    token: str,
    embed_tracks: list[Track],
    cached_tracks: dict[tuple[str, int], Track] | None = None,
) -> list[Track]:
    cached_tracks = cached_tracks or {}
    try:
        ordered_ids = fetch_spclient_track_ids(playlist_id, token)
    except Exception as exc:
        LOG.info("full playlist lookup failed for %s: %s", playlist_id, exc)
        return embed_tracks

    if len(ordered_ids) <= len(embed_tracks) and not cached_tracks:
        return embed_tracks

    tracks_by_id = {track.spotify_id: track for track in embed_tracks if track.spotify_id}
    missing_ids = list(dict.fromkeys(
        spotify_id for index, spotify_id in enumerate(ordered_ids, 1)
        if spotify_id not in tracks_by_id and (spotify_id, index) not in cached_tracks
    ))
    if missing_ids:
        print(
            f"Spotify playlist has {len(ordered_ids)} tracks; fetching {len(missing_ids)} more.",
            file=sys.stderr,
            flush=True,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_track_by_id, spotify_id): spotify_id for spotify_id in missing_ids}
        for future in as_completed(futures):
            spotify_id = futures[future]
            try:
                tracks_by_id[spotify_id] = future.result()
            except Exception as exc:
                LOG.warning("track metadata fetch failed for %s: %s", spotify_id, exc)
                tracks_by_id[spotify_id] = Track(
                    name=f"Track {spotify_id}",
                    artists="Unknown Artist",
                    spotify_id=spotify_id,
                )

    ordered_tracks = [
        cached_tracks.get((spotify_id, index)) or tracks_by_id.get(spotify_id)
        for index, spotify_id in enumerate(ordered_ids, 1)
    ]
    ordered_tracks = [track for track in ordered_tracks if track is not None]
    return ordered_tracks or embed_tracks


def fetch_spotify(
    url: str, resume_output_root: str | None = None, resume_format: str | None = None
) -> SpotifyCollection:
    kind, spotify_id = parse_spotify_url(url)
    entity, token = fetch_embed_page(kind, spotify_id)
    name = entity.get("title") or entity.get("name") or kind.title()

    if kind == "track":
        track = track_from_entity(entity, spotify_id=spotify_id)
        if not track.album:
            track = Track(
                name=track.name,
                artists=track.artists,
                spotify_id=track.spotify_id,
                duration_ms=track.duration_ms,
                cover_url=track.cover_url,
                album=fetch_track_album(spotify_id),
            )
        return SpotifyCollection(
            name=safe(f"{track.artists} - {track.name}"),
            tracks=[track],
            use_subfolder=False,
            cover_url=track.cover_url,
            track_cover_fallback_url=track.cover_url,
            kind="track",
        )

    cover_url = best_image(entity)
    track_cover_fallback = cover_url if kind == "album" else None
    raw_tracks = entity.get("trackList") or []
    album_name = name if kind == "album" else None
    tracks = [
        track_from_collection_item(item, track_cover_fallback, album=album_name)
        for item in raw_tracks
        if (item.get("entityType") in (None, "track"))
    ]

    if not tracks:
        raise ValueError(f"No playable tracks found in Spotify {kind}: {name}")

    if kind == "playlist" and token:
        cached = {}
        if resume_output_root and resume_format:
            cached = load_manifest_tracks(Path(resume_output_root).expanduser() / safe(name), resume_format)
        tracks = complete_playlist_tracks(spotify_id, token, tracks, cached_tracks=cached)

    return SpotifyCollection(
        name=name,
        tracks=tracks,
        use_subfolder=True,
        cover_url=cover_url,
        track_cover_fallback_url=track_cover_fallback,
        kind=kind,
    )


# ---------------------------------------------------------------------------
# ffmpeg discovery
# ---------------------------------------------------------------------------


def os_environ(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def find_ffmpeg_location() -> str | None:
    env_path = Path(value).expanduser() if (value := os_environ("SPOTIFY_DOWNLOADER_FFMPEG")) else None
    if env_path and env_path.exists():
        return str(env_path)

    installed = app_support_dir() / "bin" / "ffmpeg"
    if installed.exists():
        return str(installed)

    executable_dir = Path(sys.executable).resolve().parent
    for candidate in (
        executable_dir.parent / "bin" / "ffmpeg",
        executable_dir / "ffmpeg",
    ):
        if candidate.exists():
            return str(candidate)

    for candidate in (
        Path.home() / ".spotdl" / "ffmpeg",
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ):
        if candidate.exists():
            return str(candidate)
    if shutil.which("ffmpeg"):
        return None
    print("Warning: ffmpeg was not found. yt-dlp audio conversion may fail.", flush=True)
    return None


def normalized_audio_quality(value: str) -> str:
    if re.fullmatch(r"\d+k", value, re.IGNORECASE):
        return value[:-1]
    if value in {"auto", "disable"}:
        return "0"
    return value


def artwork_size_value(raw: object) -> int | None:
    if raw in (None, "", "unlimited"):
        return None
    try:
        value = int(str(raw).rstrip("px"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# ---------------------------------------------------------------------------
# Process management & signals
# ---------------------------------------------------------------------------


def register_process(process: subprocess.Popen[str]) -> None:
    with RUNNING_LOCK:
        RUNNING_PROCESSES.add(process)


def unregister_process(process: subprocess.Popen[str]) -> None:
    with RUNNING_LOCK:
        RUNNING_PROCESSES.discard(process)


def terminate_children() -> None:
    with RUNNING_LOCK:
        processes = list(RUNNING_PROCESSES)
    for process in processes:
        if process.poll() is None:
            process.terminate()


def handle_signal(signum: int, frame: object) -> None:
    STOP_EVENT.set()
    terminate_children()
    raise KeyboardInterrupt


def stop_download_if_requested(status: dict[str, object]) -> None:
    """Let worker-thread yt-dlp transfers notice a pause/cancel immediately."""
    if STOP_EVENT.is_set():
        raise RuntimeError("cancelled")


# ---------------------------------------------------------------------------
# Artwork & tags
# ---------------------------------------------------------------------------


def image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def process_artwork(
    data: bytes,
    mime: str,
    max_size: int | None,
    to_jpeg: bool,
) -> tuple[bytes, str]:
    """Optionally downscale/convert cover art. Degrades gracefully without Pillow."""
    if max_size is None and not to_jpeg:
        return data, mime
    if not HAS_PILLOW:
        LOG.warning("artwork resize requested but Pillow is not installed; using original image")
        return data, mime
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            changed = False
            if max_size is not None and (image.width > max_size or image.height > max_size):
                image.thumbnail((max_size, max_size), Image.LANCZOS)
                changed = True
            target_mime = mime
            output = io.BytesIO()
            if to_jpeg:
                image = image.convert("RGB")
                image.save(output, format="JPEG", quality=90)
                target_mime = "image/jpeg"
                changed = True
            elif changed:
                fmt = "PNG" if mime == "image/png" else "JPEG"
                if fmt == "JPEG":
                    image = image.convert("RGB")
                image.save(output, format=fmt)
            if not changed:
                return data, mime
            return output.getvalue(), target_mime
    except Exception as exc:
        LOG.warning("artwork processing failed: %s", exc)
        return data, mime


def cover_bytes(path: Path, track: Track) -> tuple[bytes, str] | None:
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        thumbnail = path.with_suffix(suffix)
        if thumbnail.exists():
            data = thumbnail.read_bytes()
            thumbnail.unlink(missing_ok=True)
            return data, image_mime(data)

    if not track.cover_url:
        return None

    try:
        response = req.get(track.cover_url, timeout=15)
        response.raise_for_status()
        data = response.content
        return data, image_mime(data)
    except Exception as exc:
        LOG.info("cover fetch failed for %s: %s", track.name, exc)
        return None


def write_mp3_tags(
    path: Path,
    track: Track,
    pos: int | None,
    cover: tuple[bytes, str] | None,
) -> None:
    try:
        audio = EasyID3(str(path))
    except Exception:
        audio = EasyID3()
        audio.save(str(path))
        audio = EasyID3(str(path))

    audio["title"] = [track.name]
    audio["artist"] = [track.artists]
    if track.album:
        audio["album"] = [track.album]
    if pos is not None:
        audio["tracknumber"] = [str(pos)]
    audio.save(v2_version=3)

    if cover:
        try:
            id3 = ID3(str(path))
        except ID3NoHeaderError:
            id3 = ID3()
        data, mime = cover
        id3.delall("APIC")
        id3.add(APIC(encoding=1, mime=mime, type=3, desc="Cover", data=data))
        id3.update_to_v23()
        id3.save(str(path), v2_version=3)


def write_m4a_tags(
    path: Path,
    track: Track,
    pos: int | None,
    cover: tuple[bytes, str] | None,
) -> None:
    audio = MP4(str(path))
    audio["\xa9nam"] = [track.name]
    audio["\xa9ART"] = [track.artists]
    if track.album:
        audio["\xa9alb"] = [track.album]
    if pos is not None:
        audio["trkn"] = [(pos, 0)]
    if cover:
        data, mime = cover
        if mime == "image/png":
            audio["covr"] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_PNG)]
        elif mime == "image/jpeg":
            audio["covr"] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def write_flac_tags(
    path: Path,
    track: Track,
    pos: int | None,
    cover: tuple[bytes, str] | None,
) -> None:
    audio = FLAC(str(path))
    audio["title"] = [track.name]
    audio["artist"] = [track.artists]
    if track.album:
        audio["album"] = [track.album]
    if pos is not None:
        audio["tracknumber"] = [str(pos)]
    if cover:
        data, mime = cover
        picture = Picture()
        picture.type = 3
        picture.mime = mime
        picture.desc = "Cover"
        picture.data = data
        audio.clear_pictures()
        audio.add_picture(picture)
    audio.save()


def write_ogg_tags(path: Path, track: Track, pos: int | None) -> None:
    audio = OggOpus(str(path)) if path.suffix.lower() == ".opus" else OggVorbis(str(path))
    audio["title"] = [track.name]
    audio["artist"] = [track.artists]
    if track.album:
        audio["album"] = [track.album]
    if pos is not None:
        audio["tracknumber"] = [str(pos)]
    audio.save()


def embed_lyrics(path: Path, lyrics: Lyrics | None, style: str = "plain") -> bool:
    """Write lyrics into the audio file itself, touching only lyric tags.

    Every format gets the standard lyrics tag (USLT, \xa9lyr, or LYRICS), which
    Apple Music and most players display. MP3 also gets a SYLT frame so the
    timing travels inside the file instead of in a .lrc sidecar. With the
    "synced" style the standard tag holds timestamped LRC text, which players
    such as Poweramp, MusicBee, foobar2000, Jellyfin, and Navidrome scroll
    line by line.
    """
    if not HAS_MUTAGEN or not lyrics:
        return False
    text = lyrics.text(style)
    if not text:
        return False

    suffix = path.suffix.lower()
    if suffix == ".mp3":
        try:
            id3 = ID3(str(path))
        except ID3NoHeaderError:
            id3 = ID3()
        id3.delall("USLT")
        id3.delall("SYLT")
        id3.add(USLT(encoding=1, lang="eng", desc="", text=text))
        lines = lyrics.synced_lines()
        if lines:
            id3.add(SYLT(encoding=1, lang="eng", format=2, type=1, desc="", text=lines))
        id3.update_to_v23()
        id3.save(str(path), v2_version=3)
    elif suffix == ".m4a":
        audio = MP4(str(path))
        audio["\xa9lyr"] = [text]
        audio.save()
    elif suffix == ".flac":
        audio = FLAC(str(path))
        audio["lyrics"] = [text]
        audio.save()
    elif suffix in {".opus", ".ogg"}:
        audio = OggOpus(str(path)) if suffix == ".opus" else OggVorbis(str(path))
        audio["lyrics"] = [text]
        audio.save()
    else:
        return False
    return True


def tag(
    path: Path,
    track: Track,
    pos: int | None,
    lyrics: Lyrics | None = None,
    artwork_max_size: int | None = None,
    artwork_jpeg: bool = False,
    lyrics_style: str = "plain",
) -> str | None:
    if not HAS_MUTAGEN:
        return "metadata tagging unavailable: mutagen is not installed"

    try:
        suffix = path.suffix.lower()
        cover = cover_bytes(path, track) if suffix in {".mp3", ".m4a", ".flac"} else None
        if cover is not None:
            cover = process_artwork(cover[0], cover[1], artwork_max_size, artwork_jpeg)
        if suffix == ".mp3":
            write_mp3_tags(path, track, pos, cover)
        elif suffix == ".m4a":
            write_m4a_tags(path, track, pos, cover)
        elif suffix == ".flac":
            write_flac_tags(path, track, pos, cover)
        elif suffix in {".opus", ".ogg"}:
            write_ogg_tags(path, track, pos)
        embed_lyrics(path, lyrics, lyrics_style)
    except Exception as exc:
        LOG.warning("tagging failed for %s: %s", path, exc)
        print(f"  Warning: tagging failed for {path.name}: {exc}", flush=True)
        return f"metadata tagging failed: {exc}"
    return None


# ---------------------------------------------------------------------------
# Lyrics (LRCLib)
# ---------------------------------------------------------------------------


def strip_lrc_timestamps(synced: str) -> str:
    lines = []
    for raw_line in synced.splitlines():
        if LRC_METADATA_RE.match(raw_line):
            continue
        cleaned = LRC_TIMESTAMP_RE.sub("", raw_line).strip()
        lines.append(cleaned)
    return "\n".join(lines).strip("\n")


def parse_lrc(synced: str) -> list[tuple[str, int]]:
    """Return (line, milliseconds) pairs sorted by time, as SYLT expects."""
    lines: list[tuple[str, int]] = []
    for raw_line in synced.splitlines():
        stamps = list(LRC_TIMESTAMP_PARTS_RE.finditer(raw_line))
        if not stamps:
            continue
        text = LRC_TIMESTAMP_RE.sub("", raw_line).strip()
        for stamp in stamps:
            minutes, seconds, fraction = stamp.groups()
            fraction = fraction or "0"
            millis = int(fraction.ljust(3, "0")[:3])
            lines.append((text, (int(minutes) * 60 + int(seconds)) * 1000 + millis))
    lines.sort(key=lambda item: item[1])
    return lines


def lyrics_from_record(record: dict) -> str | None:
    plain = record.get("plainLyrics")
    if isinstance(plain, str) and plain.strip():
        return plain
    synced = record.get("syncedLyrics")
    if isinstance(synced, str) and synced.strip():
        return strip_lrc_timestamps(synced)
    return None


def lyrics_payload_from_record(record: dict | None) -> Lyrics | None:
    if not record:
        return None
    synced = record.get("syncedLyrics")
    payload = Lyrics(
        plain=lyrics_from_record(record),
        synced=synced if isinstance(synced, str) and synced.strip() else None,
    )
    return payload or None


def lyrics_from_lrc_text(text: str) -> Lyrics | None:
    if LRC_TIMESTAMP_RE.search(text):
        payload = Lyrics(plain=strip_lrc_timestamps(text) or None, synced=text.strip())
    else:
        payload = Lyrics(plain=text.strip() or None)
    return payload or None


def _search_lyrics_record(track: Track) -> dict | None:
    """Fallback for tracks whose exact title/album/duration misses on /api/get."""
    params = {
        "track_name": clean_track_title(track.name),
        "artist_name": primary_artist(track.artists),
    }
    response = req.get(LYRICS_SEARCH_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=15)
    if response.status_code != 200:
        return None
    results = response.json()
    if not isinstance(results, list):
        return None

    expected = duration_seconds(track)
    wanted_title = normalize_match_text(clean_track_title(track.name))
    wanted_modifiers = extract_modifiers(clean_track_title(track.name))
    best: tuple[float, dict] | None = None
    for item in results:
        if not isinstance(item, dict) or not (item.get("plainLyrics") or item.get("syncedLyrics")):
            continue
        item_title = clean_track_title(str(item.get("trackName") or ""))
        if wanted_title != normalize_match_text(item_title) or wanted_modifiers != extract_modifiers(item_title):
            continue
        duration = item.get("duration")
        diff = abs(float(duration) - expected) if expected and isinstance(duration, (int, float)) else 0.0
        if expected and diff > 5:
            continue
        score = diff - (1.0 if item.get("syncedLyrics") else 0.0)
        if best is None or score < best[0]:
            best = (score, item)
    return best[1] if best else None


def _lyrics_record(track: Track) -> dict | None:
    with LYRICS_CACHE_LOCK:
        if track in LYRICS_CACHE:
            return LYRICS_CACHE[track]

    params = {"track_name": track.name, "artist_name": track.artists}
    if track.album:
        params["album_name"] = track.album
    if track.duration_ms:
        params["duration"] = str(int(track.duration_ms / 1000))

    record: dict | None = None
    try:
        response = req.get(LYRICS_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=15)
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict):
                record = payload
        if record is None:
            record = _search_lyrics_record(track)
    except Exception as exc:
        LOG.info("lyrics lookup failed for %s - %s: %s", track.artists, track.name, exc)

    with LYRICS_CACHE_LOCK:
        LYRICS_CACHE[track] = record
    return record


def fetch_lyrics(track: Track) -> str | None:
    record = _lyrics_record(track)
    return lyrics_from_record(record) if record else None


def fetch_lyrics_payload(track: Track) -> Lyrics | None:
    return lyrics_payload_from_record(_lyrics_record(track))


def fetch_synced_lyrics(track: Track) -> str | None:
    record = _lyrics_record(track)
    if not record:
        return None
    synced = record.get("syncedLyrics")
    return synced if isinstance(synced, str) and synced.strip() else None


def write_lrc_sidecar(audio_path: Path, synced: str) -> Path | None:
    try:
        lrc_path = audio_path.with_suffix(".lrc")
        lrc_path.write_text(synced, encoding="utf-8")
        return lrc_path
    except Exception as exc:
        LOG.warning("could not write .lrc sidecar for %s: %s", audio_path, exc)
        return None


# ---------------------------------------------------------------------------
# Output naming & manifest
# ---------------------------------------------------------------------------


def existing_output(output_dir: Path, stem: str, fmt: str) -> Path | None:
    direct = output_dir / f"{stem}.{fmt}"
    if direct.exists():
        return direct
    for candidate in output_dir.glob(f"{stem}.*"):
        if candidate.suffix.lower() == f".{fmt.lower()}":
            return candidate
    return None


def track_key(track: Track, pos: int | None) -> str:
    if track.spotify_id:
        return f"spotify:{track.spotify_id}:{pos}" if pos is not None else f"spotify:{track.spotify_id}"
    duration = track.duration_ms or 0
    return f"{pos or 0}:{track.artists.casefold()}:{track.name.casefold()}:{duration}"


def read_manifest_entries(output_dir: Path) -> list[dict]:
    manifest = output_dir / MANIFEST_FILENAME
    entries: list[dict] = []
    if not manifest.exists():
        return entries
    try:
        with manifest.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        entries.append(item)
                except json.JSONDecodeError as exc:
                    LOG.warning("manifest line %s invalid in %s: %s", number, manifest, exc)
    except OSError as exc:
        LOG.warning("manifest read failed for %s: %s", manifest, exc)
    return entries


def load_manifest(output_dir: Path) -> dict[str, Path]:
    completed: dict[str, Path] = {}
    for item in read_manifest_entries(output_dir):
        key = item.get("key")
        file_name = item.get("file")
        if not isinstance(key, str) or not isinstance(file_name, str):
            continue
        path = output_dir / file_name
        if path.is_file():
            completed[key] = path
    return completed


def load_manifest_tracks(output_dir: Path, fmt: str) -> dict[tuple[str, int], Track]:
    tracks: dict[tuple[str, int], Track] = {}
    for item in read_manifest_entries(output_dir):
        key = item.get("key")
        file_name = item.get("file")
        metadata = item.get("track")
        if not isinstance(key, str) or not isinstance(file_name, str) or not isinstance(metadata, dict):
            continue
        match = re.fullmatch(r"spotify:([A-Za-z0-9]+):(\d+)", key)
        if not match or not (output_dir / file_name).is_file() or Path(file_name).suffix.lower() != f".{fmt}":
            continue
        name, artists = metadata.get("name"), metadata.get("artists")
        if not isinstance(name, str) or not isinstance(artists, str):
            continue
        tracks[(match.group(1), int(match.group(2)))] = Track(
            name=name, artists=artists, spotify_id=match.group(1),
            duration_ms=metadata.get("duration_ms"),
            cover_url=metadata.get("cover_url"), album=metadata.get("album"),
        )
    return tracks


def append_manifest(output_dir: Path, key: str, path: Path, track: Track | None = None) -> None:
    entry = {"key": key, "file": path.name}
    if track is not None:
        entry["track"] = asdict(track)
    with MANIFEST_LOCK:
        with (output_dir / MANIFEST_FILENAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def reserve_output_stem(output_dir: Path, stem: str, fmt: str, suffix: str | None) -> str:
    with STEM_LOCK:
        candidate = stem
        index = 2
        while f"{output_dir}:{candidate}.{fmt}" in IN_FLIGHT_STEMS or existing_output(output_dir, candidate, fmt):
            if suffix and index == 2:
                candidate = safe(f"{stem} [{suffix}]")
            else:
                candidate = safe(f"{stem} ({index})")
            index += 1
        IN_FLIGHT_STEMS.add(f"{output_dir}:{candidate}.{fmt}")
        return candidate


def release_output_stem(output_dir: Path, stem: str, fmt: str) -> None:
    with STEM_LOCK:
        IN_FLIGHT_STEMS.discard(f"{output_dir}:{stem}.{fmt}")


# ---------------------------------------------------------------------------
# YouTube matching
# ---------------------------------------------------------------------------


def normalize_match_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    value = COMMON_TITLE_SUFFIX_RE.sub("", value)
    value = re.sub(r"\b(feat|featuring|ft)\.?\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def artist_tokens(artists: str) -> list[str]:
    parts = re.split(r",|&|\band\b|\bfeat\.?\b|\bfeaturing\b|\bft\.?\b", artists, flags=re.IGNORECASE)
    return [normalize_match_text(part) for part in parts if normalize_match_text(part)]


def extract_modifiers(text: str) -> set[str]:
    lowered = text.casefold()
    found: set[str] = set()
    for keyword in MODIFIER_KEYWORDS:
        pattern = r"\b" + re.escape(keyword).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, lowered):
            found.add("sped up" if keyword == "spedup" else keyword)
    return found


def duration_seconds(track: Track) -> float | None:
    return track.duration_ms / 1000 if track.duration_ms else None


def _is_neutral_version_tail(tail: str) -> bool:
    if SOUNDTRACK_TAIL_RE.match(tail.strip()):
        return True
    words = re.findall(r"[a-z]+|\d+", unicodedata.normalize("NFKD", tail).casefold())
    return bool(words) and all(word.isdigit() or word in NEUTRAL_VERSION_WORDS for word in words)


def clean_track_title(name: str) -> str:
    """Drop featured-artist and edition tails Spotify adds to titles.

    "Run to the Hills - 2015 Remaster" -> "Run to the Hills"
    "Song (feat. Someone)"             -> "Song"
    "Song - Live at Wembley"           -> unchanged ("live" is a real version)
    """
    cleaned = FEATURE_SEGMENT_RE.sub("", name).strip()
    while True:
        match = DASH_TAIL_RE.search(cleaned) or BRACKET_TAIL_RE.search(cleaned)
        if not match or not _is_neutral_version_tail(match.group("tail")):
            break
        shorter = cleaned[: match.start()].strip()
        if not shorter:
            break
        cleaned = shorter
    return cleaned or name


def primary_artist(artists: str) -> str:
    tokens = re.split(r",|&|\bfeat\.?\b|\bfeaturing\b|\bft\.?\b", artists, flags=re.IGNORECASE)
    first = tokens[0].strip() if tokens else ""
    return first or artists


SEARCH_OPERATOR_RE = re.compile(r'(^|\s)[-+~]+(?=\S)')


def search_safe(text: str) -> str:
    """Remove characters YouTube treats as search operators.

    An artist named "-Prey" would otherwise exclude every result containing
    "Prey", and quotes would force exact-phrase matching.
    """
    text = SEARCH_OPERATOR_RE.sub(r"\1", text.replace('"', " "))
    return re.sub(r"\s+", " ", text).strip()


def youtube_search_queries(track: Track, limit: int = 10) -> list[str]:
    """Distinct search routes, cheapest and most reliable first.

    Searches are flat (no per-video page loads), so every route can be tried
    for one track without tripping YouTube's bot check.
    """
    title = search_safe(clean_track_title(track.name))
    base = f"{search_safe(track.artists)} - {title}"
    lead = f"{search_safe(primary_artist(track.artists))} - {title}"
    return [
        f"ytsearch{limit}:{base}",
        f"ytsearch{limit}:{lead} official audio",
        f"https://music.youtube.com/search?q={quote_plus(lead)}",
        f"ytsearch{limit}:{lead} topic",
        f"ytsearch{limit}:{lead} lyrics",
    ]


# Each retry downloads with a different set of YouTube player clients. Every
# set avoids clients that need a PO token for audio (android, ios, mweb,
# web_safari, android_vr), which is what produces "HTTP Error 403: Forbidden".
YOUTUBE_DOWNLOAD_STRATEGIES: tuple[tuple[str, list[str] | None, str], ...] = (
    ("default clients", None, "bestaudio/best"),
    ("TV client", ["tv", "default"], "bestaudio[ext=m4a]/bestaudio/best"),
    ("embedded player client", ["web_embedded", "default"], "bestaudio/best"),
    ("visionOS client", ["visionos"], "bestaudio[ext=webm]/bestaudio/best"),
    ("TV and embedded clients", ["tv", "web_embedded"], "ba[acodec^=opus]/bestaudio/best"),
    ("all no-token clients", ["tv", "web_embedded", "visionos", "default"], "bestaudio/best"),
)
YOUTUBE_RETRY_METHODS = tuple(name for name, _, _ in YOUTUBE_DOWNLOAD_STRATEGIES)
VIDEO_SPECIFIC_ERROR_MARKERS = (
    "video unavailable",
    "private video",
    "has been removed",
    "not available in your country",
    "sign in to confirm your age",
    "age-restricted",
    "members-only",
    "copyright",
    "premieres in",
    "live event will begin",
    "requested format is not available",
)


def is_bot_check_error(detail: str) -> bool:
    lowered = detail.casefold()
    return "confirm you" in lowered and "not a bot" in lowered


def is_video_specific_error(detail: str) -> bool:
    lowered = detail.casefold()
    return any(marker in lowered for marker in VIDEO_SPECIFIC_ERROR_MARKERS)


def friendly_error(detail: str) -> str:
    """Turn raw yt-dlp errors into something a person can act on."""
    lowered = detail.casefold()
    if is_bot_check_error(detail):
        return (
            "YouTube asked to confirm you're not a bot. Choose your browser under "
            "Settings > YouTube > Browser cookies, or lower concurrent downloads."
        )
    if "403" in lowered and "forbidden" in lowered:
        runtime_hint = "" if find_js_runtimes() else " Install Deno (brew install deno) so yt-dlp can unlock all streams."
        return "YouTube refused the audio stream (HTTP 403)." + runtime_hint
    if "429" in lowered or "too many requests" in lowered:
        return "YouTube is rate-limiting this network (HTTP 429). Lower concurrent downloads and retry later."
    return detail


def js_runtime_candidates() -> list[tuple[str, Path]]:
    executable_dir = Path(sys.executable).resolve().parent
    candidates: list[tuple[str, Path]] = []
    for name in ("deno", "node", "bun"):
        env_value = os_environ(f"SPOTIFY_DOWNLOADER_{name.upper()}")
        if env_value:
            candidates.append((name, Path(env_value).expanduser()))
        candidates.extend(
            (name, folder / name)
            for folder in (
                app_support_dir() / "bin",
                executable_dir,
                executable_dir.parent / "bin",
                Path.home() / ".deno" / "bin",
                Path("/opt/homebrew/bin"),
                Path("/usr/local/bin"),
            )
        )
        found = shutil.which(name)
        if found:
            candidates.append((name, Path(found)))
    return candidates


@functools.lru_cache(maxsize=1)
def find_js_runtimes() -> dict[str, dict[str, str]]:
    """JavaScript runtimes yt-dlp can use to solve YouTube's player challenges.

    yt-dlp only enables Deno by default and looks for it on PATH; a Finder-
    launched app has a minimal PATH, so pass every runtime we can find.
    """
    runtimes: dict[str, dict[str, str]] = {}
    for name, path in js_runtime_candidates():
        if name in runtimes:
            continue
        if path.is_file() and os.access(path, os.X_OK):
            runtimes[name] = {"path": str(path)}
    return runtimes


def has_ejs_scripts() -> bool:
    try:
        import yt_dlp_ejs  # noqa: F401
    except ImportError:
        return False
    return True


def with_js_runtimes(options: dict[str, object]) -> dict[str, object]:
    runtimes = find_js_runtimes()
    if runtimes:
        options["js_runtimes"] = {name: dict(config) for name, config in runtimes.items()}
    return options


def youtube_attempt_options(base_options: dict[str, object], attempt: int, audio: bool) -> dict[str, object]:
    """Change clients and preferred streams for every retry without dropping fallbacks."""
    index = max(0, min(attempt, len(YOUTUBE_DOWNLOAD_STRATEGIES) - 1))
    _, clients, audio_format = YOUTUBE_DOWNLOAD_STRATEGIES[index]
    options = with_js_runtimes(dict(base_options))
    if clients:
        options["extractor_args"] = {"youtube": {"player_client": clients}}
    if audio:
        options["format"] = audio_format
    return options


def youtube_search_options(cookies_browser: str | None = None, limit: int = 10) -> dict[str, object]:
    options: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        # Flat results already carry title, channel, and duration. Resolving
        # every result's player page was what triggered YouTube's bot check.
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "noplaylist": True,
        "playlistend": limit,
    }
    if cookies_browser:
        options["cookiesfrombrowser"] = (cookies_browser,)
    return options


def youtube_candidates_for_query(query: str, cookies_browser: str | None = None) -> list[dict]:
    with YoutubeDL(youtube_search_options(cookies_browser)) as ydl:
        info = ydl.extract_info(query, download=False)
    if not isinstance(info, dict):
        return []
    entries = info.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict)]


def gather_youtube_candidates(track: Track, limit: int = 10, cookies_browser: str | None = None) -> list[dict]:
    """Return the first tier of search results that yields candidates."""
    for query in youtube_search_queries(track, limit):
        try:
            entries = youtube_candidates_for_query(query, cookies_browser)
        except Exception as exc:
            LOG.warning("youtube search failed for %s: %s", query, exc)
            continue
        if entries:
            return entries
    return []


def find_youtube_candidate(
    track: Track,
    allow_closest: bool = False,
    cookies_browser: str | None = None,
    exclude_ids: set[str] | None = None,
    flexibility: float = DEFAULT_MATCH_FLEXIBILITY,
) -> tuple[dict | None, str]:
    """Search each tier independently so one extractor failure cannot abort all fallbacks."""
    reason = "no YouTube results"
    search_errors: list[str] = []
    completed_search = False
    excluded = exclude_ids or set()
    for query in youtube_search_queries(track):
        try:
            candidates = youtube_candidates_for_query(query, cookies_browser)
        except Exception as exc:
            detail = str(exc).strip()[:700]
            search_errors.append(detail)
            LOG.warning("youtube search failed for %s: %s", query, exc)
            continue

        completed_search = True
        candidates = [candidate for candidate in candidates if candidate.get("id") not in excluded]
        if not candidates:
            continue
        chosen, reason = choose_youtube_candidate(candidates, track, allow_closest, flexibility)
        if chosen:
            return chosen, reason

    if not completed_search and search_errors:
        return None, f"YouTube search failed: {search_errors[-1]}"
    return None, reason


def candidate_url(candidate: dict) -> str | None:
    for key in ("webpage_url", "original_url", "url"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            if key == "url" and not value.startswith(("http://", "https://")):
                return f"https://www.youtube.com/watch?v={value}"
            return value
    video_id = candidate.get("id")
    return f"https://www.youtube.com/watch?v={video_id}" if isinstance(video_id, str) else None


def choose_youtube_candidate(
    candidates: list[dict],
    track: Track,
    allow_closest: bool = False,
    flexibility: float = DEFAULT_MATCH_FLEXIBILITY,
) -> tuple[dict | None, str]:
    """Pick the upload that matches the track, or explain why none did.

    `flexibility` (0-1) loosens the rules step by step:
      - duration window grows from 20 s to 60 s (30 s at the 0.25 default);
      - from 0.4, a title may match by most of its words instead of all;
      - from 0.6, the artist may be missing when title and length agree;
      - at 1.0, the closest-length result is used as a last resort.
    """
    if not candidates:
        return None, "no YouTube results"

    flexibility = max(0.0, min(1.0, flexibility))
    duration_limit = 20 + 40 * flexibility
    word_coverage_needed = 1 - 0.5 * flexibility if flexibility >= 0.4 else 1.0
    allow_missing_artist = flexibility >= 0.6
    allow_closest = allow_closest or flexibility >= 1.0

    expected_duration = duration_seconds(track)
    cleaned_title = clean_track_title(track.name)
    title = normalize_match_text(cleaned_title)
    title_words = title.split()
    track_modifiers = extract_modifiers(cleaned_title)
    artists = artist_tokens(track.artists)

    def title_ok(candidate: dict) -> bool:
        candidate_text = normalize_match_text(str(candidate.get("title") or ""))
        if title and title in candidate_text:
            return True
        if word_coverage_needed >= 1.0 or len(title_words) < 2:
            return False
        candidate_words = set(candidate_text.split())
        covered = sum(1 for word in title_words if word in candidate_words)
        return covered / len(title_words) >= word_coverage_needed

    def title_exact(candidate: dict) -> bool:
        candidate_text = normalize_match_text(str(candidate.get("title") or ""))
        if not title or not candidate_text:
            return False
        return candidate_text == title or candidate_text.endswith(f" {title}")

    def artist_ok(candidate: dict) -> bool:
        combined = " ".join(
            normalize_match_text(str(candidate.get(key) or ""))
            for key in ("title", "uploader", "channel")
        )
        return not artists or any(artist and artist in combined for artist in artists)

    def modifier_ok(candidate: dict) -> bool:
        candidate_modifiers = extract_modifiers(str(candidate.get("title") or ""))
        return track_modifiers.issubset(candidate_modifiers)

    def same_version(candidate: dict) -> bool:
        # A studio track should not pick up a live, sped-up, or cover upload.
        return extract_modifiers(str(candidate.get("title") or "")) == track_modifiers

    def closest_by_duration(pool: list[dict]) -> tuple[dict | None, float]:
        timed = [candidate for candidate in pool if candidate.get("duration")]
        if not expected_duration or not timed:
            return None, 0.0
        chosen = min(timed, key=lambda item: abs(float(item["duration"]) - expected_duration))
        return chosen, abs(float(chosen["duration"]) - expected_duration)

    artist_available = any(artist_ok(candidate) for candidate in candidates)

    strict_pool = [candidate for candidate in candidates if title_ok(candidate) and artist_ok(candidate)]
    strict_pool = [candidate for candidate in strict_pool if same_version(candidate)] or strict_pool
    if strict_pool:
        chosen, diff = closest_by_duration(strict_pool)
        if chosen is not None:
            if diff <= duration_limit:
                return chosen, "title, artist, and duration matched"
            if not allow_closest:
                return None, f"closest title match was {diff:.0f}s off (limit {duration_limit:.0f}s)"
        elif not expected_duration:
            return strict_pool[0], "title and artist matched"

    # When the artist never appears in the results but the title (and any
    # version modifier such as "sped up") matches exactly, this is usually a
    # legitimate re-upload that simply is not labelled with the original artist.
    if track_modifiers and not artist_available:
        exact_pool = [
            candidate
            for candidate in candidates
            if title_exact(candidate) and modifier_ok(candidate)
        ]
        if exact_pool:
            if expected_duration:
                chosen, diff = closest_by_duration(exact_pool)
                if chosen is not None and diff <= duration_limit:
                    return chosen, f"title matched, artist unavailable ({diff:.0f}s off)"
            else:
                return exact_pool[0], "title matched, artist unavailable"

    if allow_missing_artist:
        title_pool = [candidate for candidate in candidates if title_ok(candidate) and same_version(candidate)]
        chosen, diff = closest_by_duration(title_pool)
        if chosen is not None and diff <= 5:
            return chosen, f"title and duration matched; artist not listed ({diff:.0f}s off)"

    if allow_closest and expected_duration:
        chosen, diff = closest_by_duration(candidates)
        if chosen is not None:
            return chosen, f"artist unmatched; closest duration match ({diff:.0f}s off)"
    if allow_closest:
        return candidates[0], "artist unmatched; closest result selected"

    return None, "no confident title and artist match"


def first_youtube_info(info: object) -> dict:
    if not isinstance(info, dict):
        raise ValueError("YouTube metadata was not returned.")

    entries = info.get("entries")
    if entries is not None:
        for entry in entries:
            if isinstance(entry, dict):
                return entry
        raise ValueError("No YouTube videos were found.")

    return info


def fetch_youtube_info(url: str, cookies_browser: str | None = None) -> dict:
    ydl_opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if cookies_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)
    with YoutubeDL(with_js_runtimes(ydl_opts)) as ydl:
        return first_youtube_info(ydl.extract_info(url, download=False))


def format_duration(seconds: object) -> str:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ""

    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f" ({hours:d}:{minutes:02d}:{secs:02d})"
    return f" ({minutes:d}:{secs:02d})"


def youtube_label(info: dict) -> str:
    title = str(info.get("title") or "YouTube video")
    uploader = str(info.get("uploader") or info.get("channel") or "").strip()
    return f"{uploader} - {title}" if uploader else title


def print_youtube_info(info: dict, media: str) -> None:
    title = str(info.get("title") or "YouTube video")
    uploader = str(info.get("uploader") or info.get("channel") or "").strip()
    suffix = format_duration(info.get("duration"))
    prefix = "YouTube video" if media == "video" else "YouTube audio"
    print(f"Found {prefix}: \"{title}\"{suffix}", flush=True)
    if uploader:
        print(f"  Channel: {uploader}", flush=True)


def youtube_output_template(output_dir: Path) -> str:
    return str(output_dir / "%(title).200B [%(id)s].%(ext)s")


def youtube_common_options(output_dir: Path, overwrite: str, cookies_browser: str | None = None) -> dict[str, object]:
    options: dict[str, object] = {
        "outtmpl": youtube_output_template(output_dir),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "overwrites": overwrite == "force",
        "continuedl": overwrite != "force",
        "progress_hooks": [stop_download_if_requested],
    }
    if cookies_browser:
        options["cookiesfrombrowser"] = (cookies_browser,)
    return options


def downloaded_file_detail(info: dict, ydl: YoutubeDL, preferred_ext: str | None = None) -> str:
    requested_downloads = info.get("requested_downloads")
    if isinstance(requested_downloads, list):
        for download in reversed(requested_downloads):
            if not isinstance(download, dict):
                continue
            for key in ("filepath", "_filename"):
                path_text = download.get(key)
                if not path_text:
                    continue
                path = Path(str(path_text))
                if preferred_ext:
                    converted = path.with_suffix(f".{preferred_ext}")
                    if converted.exists():
                        return converted.name
                return path.name

    candidate = Path(ydl.prepare_filename(info))
    if preferred_ext:
        converted = candidate.with_suffix(f".{preferred_ext}")
        if converted.exists():
            return converted.name
    return candidate.name if candidate.name else "saved"


def downloaded_file_path(info: dict, ydl: YoutubeDL, preferred_ext: str | None = None) -> Path | None:
    requested_downloads = info.get("requested_downloads")
    if isinstance(requested_downloads, list):
        for download in reversed(requested_downloads):
            if not isinstance(download, dict):
                continue
            for key in ("filepath", "_filename"):
                path_text = download.get(key)
                if not path_text:
                    continue
                path = Path(str(path_text))
                if preferred_ext:
                    converted = path.with_suffix(f".{preferred_ext}")
                    if converted.exists():
                        return converted
                if path.exists():
                    return path
    candidate = Path(ydl.prepare_filename(info))
    if preferred_ext:
        converted = candidate.with_suffix(f".{preferred_ext}")
        if converted.exists():
            return converted
    return candidate if candidate.exists() else None


def download_youtube_media(url: str, options: RunOptions) -> DownloadResult:
    if STOP_EVENT.is_set():
        return DownloadResult(False, url, "cancelled")

    output_dir = Path(options_output_dir.get()).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    preexisting_paths = set(output_dir.iterdir())
    ffmpeg_location = options.ffmpeg_location or find_ffmpeg_location()

    media_label = "video" if options.media == "video" else "audio"
    print(f"Downloading YouTube {media_label} to: {output_dir}", flush=True)

    ydl_opts = youtube_common_options(output_dir, options.overwrite, options.cookies_browser)
    preferred_ext: str | None

    if options.media == "video":
        ydl_opts.update(
            {
                "format": "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b",
                "merge_output_format": "mp4",
            }
        )
        preferred_ext = "mp4"
    else:
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": options.fmt,
                        "preferredquality": normalized_audio_quality(options.bitrate),
                    }
                ],
            }
        )
        preferred_ext = options.fmt

    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location

    error_detail = "yt-dlp did not produce an output file"
    total_attempts = max(1, options.retries + 1)
    for attempt in range(total_attempts):
        if STOP_EVENT.is_set():
            return DownloadResult(False, url, "cancelled")
        method = YOUTUBE_RETRY_METHODS[attempt]
        if attempt > 0:
            print(f"Retry {attempt}/{options.retries}: {method}", flush=True)
        attempt_options = youtube_attempt_options(ydl_opts, attempt, options.media == "audio")
        try:
            with YoutubeDL(attempt_options) as ydl:
                info = first_youtube_info(ydl.extract_info(url, download=True))
                path = downloaded_file_path(info, ydl, preferred_ext)
                detail = downloaded_file_detail(info, ydl, preferred_ext)
                if attempt > 0:
                    detail = f"{detail} via {method}"
                return DownloadResult(
                    True,
                    youtube_label(info),
                    detail,
                    str(path) if path else None,
                    created_this_run=path is not None and path not in preexisting_paths,
                )
        except Exception as exc:
            error_detail = str(exc).strip()[:700]
            LOG.warning("direct YouTube %s failed for %s: %s", method, url, error_detail[:300])
            if is_video_specific_error(error_detail):
                break

    return DownloadResult(False, url, friendly_error(error_detail))


# A thread-local-ish holder so YouTube media downloads know their folder.
class _OutputDirHolder:
    def __init__(self) -> None:
        self._value = "downloads"

    def set(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


options_output_dir = _OutputDirHolder()


def enriched_track(track: Track, fallback_cover_url: str | None) -> Track:
    if track.spotify_id and (not track.cover_url or not track.album):
        try:
            entity = fetch_embed_entity("track", track.spotify_id)
            enriched = track_from_entity(
                entity,
                fallback_cover=track.cover_url or fallback_cover_url,
                album=track.album or fetch_track_album(track.spotify_id),
                spotify_id=track.spotify_id,
            )
            return Track(
                name=track.name,
                artists=track.artists,
                spotify_id=track.spotify_id,
                duration_ms=track.duration_ms or enriched.duration_ms,
                cover_url=track.cover_url or enriched.cover_url,
                album=track.album or enriched.album,
            )
        except Exception as exc:
            LOG.info("track enrichment failed for %s - %s: %s", track.artists, track.name, exc)

    if fallback_cover_url and not track.cover_url:
        return Track(
            name=track.name,
            artists=track.artists,
            spotify_id=track.spotify_id,
            duration_ms=track.duration_ms,
            cover_url=fallback_cover_url,
            album=track.album,
        )

    return track


def apply_track_lyrics(path: Path, track: Track, options: RunOptions) -> Lyrics | None:
    """Look up lyrics for embedding; a .lrc sidecar is only written when asked for."""
    if not options.lyrics:
        return None
    lyrics = fetch_lyrics_payload(track)
    if lyrics and lyrics.synced and options.write_lrc:
        write_lrc_sidecar(path, lyrics.synced)
    return lyrics


def download_track(
    track: Track,
    output_dir: Path,
    pos: int | None,
    total: int,
    options: RunOptions,
    fallback_cover_url: str | None,
    manifest_done: dict[str, Path],
) -> DownloadResult:
    if STOP_EVENT.is_set():
        return DownloadResult(False, f"{track.artists} - {track.name}", "cancelled")

    ffmpeg_location = options.ffmpeg_location
    key = track_key(track, pos)
    label = f"{track.artists} - {track.name}"
    if key in manifest_done and manifest_done[key].suffix.lower() == f".{options.fmt}" and options.overwrite == "skip":
        return DownloadResult(True, label, f"resume skip: {manifest_done[key].name}", str(manifest_done[key]), True)

    width = max(2, len(str(total)))
    prefix = f"{pos:0{width}d}. " if options.track_number_prefix and pos is not None and total > 1 else ""
    stem = safe(f"{prefix}{track.name} - {track.artists}")

    existing = existing_output(output_dir, stem, options.fmt)
    if existing and options.overwrite == "skip":
        append_manifest(output_dir, key, existing, track)
        return DownloadResult(True, label, f"skip exists: {existing.name}", str(existing), True)
    if existing and options.overwrite == "metadata":
        working = enriched_track(track, fallback_cover_url)
        lyrics = apply_track_lyrics(existing, working, options)
        warning = tag(existing, working, pos, lyrics, options.artwork_max_size, options.artwork_jpeg, options.lyrics_style)
        append_manifest(output_dir, key, existing, working)
        detail = f"metadata refreshed: {existing.name}" if not warning else f"audio kept; {warning}"
        return DownloadResult(True, label, detail, str(existing), True, warning=warning)
    working_track = enriched_track(track, fallback_cover_url)
    total_attempts = max(1, options.retries + 1)
    reserved_stem: str | None = None
    error_detail = "no YouTube results"
    rejected_ids: set[str] = set()
    chosen: dict | None = None

    for attempt in range(total_attempts):
        if STOP_EVENT.is_set():
            if reserved_stem:
                release_output_stem(output_dir, reserved_stem, options.fmt)
            return DownloadResult(False, label, "cancelled")

        method = YOUTUBE_RETRY_METHODS[attempt]
        progress = min(0.85, 0.08 + (attempt / total_attempts) * 0.7)
        if attempt > 0:
            print(f"  Retry {attempt}/{options.retries} for {label}: {method}", flush=True)
            # Back off a little so a rate-limited network can recover.
            if STOP_EVENT.wait(min(8, 2 * attempt)):
                continue

        if chosen is None:
            message = "Searching" if attempt == 0 else f"Retry {attempt}/{options.retries}: searching again"
            track_progress_event(options, working_track, pos, total, "running", progress, message)
            chosen, reason = find_youtube_candidate(
                working_track,
                options.allow_closest_match,
                options.cookies_browser,
                rejected_ids,
                options.match_flexibility,
            )
            if not chosen:
                error_detail = reason
                LOG.info("no usable YouTube match for %s: %s", label, reason)
                if reason.startswith("YouTube search failed"):
                    continue
                # Every search route already ran; repeating them cannot help.
                break
            LOG.info("selected %s for %s (%s)", chosen.get("id"), label, reason)

        video_url = candidate_url(chosen)
        if not video_url:
            error_detail = "YouTube result did not include a playable URL"
            rejected_ids.add(str(chosen.get("id")))
            chosen = None
            continue

        message = "Downloading" if attempt == 0 else f"Retry {attempt}/{options.retries}: {method}"
        track_progress_event(options, working_track, pos, total, "running", progress + 0.05, message)
        if reserved_stem is None:
            reserved_stem = reserve_output_stem(output_dir, stem, options.fmt, working_track.spotify_id)

        base_options: dict[str, object] = {
            "format": "bestaudio/best",
            "outtmpl": str(output_dir / f"{reserved_stem}.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [stop_download_if_requested],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": options.fmt,
                    "preferredquality": normalized_audio_quality(options.bitrate),
                }
            ],
        }
        if ffmpeg_location:
            base_options["ffmpeg_location"] = ffmpeg_location
        if options.cookies_browser:
            base_options["cookiesfrombrowser"] = (options.cookies_browser,)

        attempt_options = youtube_attempt_options(base_options, attempt, audio=True)
        try:
            with YoutubeDL(attempt_options) as ydl:
                ydl.download([video_url])
            final = existing_output(output_dir, reserved_stem, options.fmt)
            if not final:
                error_detail = f"{method} produced no output file"
                continue

            lyrics = apply_track_lyrics(final, working_track, options)
            warning = tag(final, working_track, pos, lyrics, options.artwork_max_size, options.artwork_jpeg, options.lyrics_style)
            if existing and options.overwrite == "force":
                replacement_lrc = final.with_suffix(".lrc")
                original_lrc = existing.with_suffix(".lrc")
                final.replace(existing)
                if replacement_lrc.exists():
                    replacement_lrc.replace(original_lrc)
                else:
                    original_lrc.unlink(missing_ok=True)
                final = existing
            append_manifest(output_dir, key, final, working_track)
            detail = final.name if attempt == 0 else f"{final.name} via {method}"
            if warning:
                detail += f"; {warning}"
            release_output_stem(output_dir, reserved_stem, options.fmt)
            return DownloadResult(True, label, detail, str(final), created_this_run=existing is None, warning=warning)
        except Exception as exc:
            error_detail = str(exc).strip()[:700]
            LOG.warning("%s download failed for %s: %s", method, label, error_detail[:300])
            if is_video_specific_error(error_detail):
                # This upload is unusable (removed, region-locked, ...); pick another.
                rejected_ids.add(str(chosen.get("id")))
                chosen = None

    if reserved_stem:
        release_output_stem(output_dir, reserved_stem, options.fmt)
    return DownloadResult(False, label, friendly_error(error_detail)[:700])


# ---------------------------------------------------------------------------
# Download orchestration
# ---------------------------------------------------------------------------


def print_track_list(collection: SpotifyCollection) -> None:
    print(f"Found {len(collection.tracks)} track(s) in \"{collection.name}\"", flush=True)
    for index, track in enumerate(collection.tracks, 1):
        seconds = f" ({track.duration_ms // 1000}s)" if track.duration_ms else ""
        print(f"  {index:3d}. {track.artists} - {track.name}{seconds}", flush=True)


def track_progress_event(
    options: RunOptions,
    track: Track,
    pos: int | None,
    total: int,
    state: str,
    progress: float,
    message: str,
    path: str | None = None,
    skipped: bool = False,
    cover_url: str | None = None,
    created_this_run: bool = False,
) -> None:
    emit_json_event(
        options.json_events,
        "track_progress",
        key=track_key(track, pos),
        index=pos,
        total=total,
        label=f"{track.artists} - {track.name}",
        title=track.name,
        artists=track.artists,
        album=track.album or "",
        cover_url=cover_url or track.cover_url or "",
        progress=progress,
        state=state,
        message=message,
        path=path,
        skipped=skipped,
        created_this_run=created_this_run,
    )


def download_collection(
    collection: SpotifyCollection,
    options: RunOptions,
    output_root: str,
    threads: int,
    start: int,
) -> tuple[int, int, int, list[str], Path]:
    output_dir = Path(output_root).expanduser()
    if collection.use_subfolder:
        output_dir = output_dir / safe(collection.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_tracks = [
        (index, track)
        for index, track in enumerate(collection.tracks, 1)
        if index >= start
    ]
    if not selected_tracks:
        return 0, 0, 0, [], output_dir

    options.ffmpeg_location = options.ffmpeg_location or find_ffmpeg_location()
    manifest_done = load_manifest(output_dir)
    print(f"Downloading to: {output_dir}", flush=True)
    workers = min(16, max(1, threads))
    print(f"Using {workers} worker(s)", flush=True)
    if manifest_done and options.overwrite == "skip":
        print(f"Resume manifest: {len(manifest_done)} completed track(s)", flush=True)

    emit_json_event(
        options.json_events,
        "collection_start",
        title=collection.name,
        track_count=len(collection.tracks),
        selected_count=len(selected_tracks),
        total=len(selected_tracks),
        output_folder=str(output_dir),
    )

    ok = 0
    warnings = 0
    failed: list[str] = []

    def run_one(index: int, track: Track) -> tuple[int, Track, DownloadResult]:
        pos = index if collection.use_subfolder else None
        track_progress_event(options, track, pos, len(collection.tracks), "running", 0.05, "Searching")
        try:
            result = download_track(
                track,
                output_dir,
                pos,
                len(collection.tracks),
                options,
                collection.track_cover_fallback_url,
                manifest_done,
            )
        except Exception as exc:
            # One song's unexpected error must not stop the rest of the playlist.
            LOG.exception("unexpected error downloading %s - %s", track.artists, track.name)
            result = DownloadResult(False, f"{track.artists} - {track.name}", f"unexpected error: {exc}")
        return index, track, result

    def handle_result(index: int, track: Track, result: DownloadResult) -> None:
        nonlocal ok, warnings
        pos = index if collection.use_subfolder else None
        if result.ok:
            ok += 1
            warnings += bool(result.warning)
            state = "skipped" if result.skipped else "succeeded"
            track_progress_event(
                options, track, pos, len(collection.tracks), state, 1.0,
                result.detail, result.path, result.skipped,
                created_this_run=result.created_this_run,
            )
            print(f"  [{index}/{len(collection.tracks)}] Done: {result.label} ({result.detail})", flush=True)
        else:
            failed.append(f"{index}. {result.label}: {result.detail}")
            track_progress_event(options, track, pos, len(collection.tracks), "failed", 1.0, result.detail)
            print(f"  [{index}/{len(collection.tracks)}] Failed: {result.label}: {result.detail}", flush=True)

    if workers == 1:
        for index, track in selected_tracks:
            print(f"  [{index}/{len(collection.tracks)}] {track.artists} - {track.name}", flush=True)
            _, _, result = run_one(index, track)
            handle_result(index, track, result)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            selected = iter(selected_tracks)
            futures = {}

            def queue_next() -> bool:
                try:
                    index, track = next(selected)
                except StopIteration:
                    return False
                print(f"  [{index}/{len(collection.tracks)}] queued {track.artists} - {track.name}", flush=True)
                track_progress_event(options, track, index if collection.use_subfolder else None, len(collection.tracks), "queued", 0.0, "Queued")
                futures[executor.submit(run_one, index, track)] = (index, track)
                return True

            for _ in range(workers * 2):
                if not queue_next():
                    break
            while futures:
                finished, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in finished:
                    futures.pop(future)
                    index, track, result = future.result()
                    handle_result(index, track, result)
                    queue_next()

    fail_count = len(failed)
    print(f"Downloaded: {ok}/{len(selected_tracks)}", flush=True)
    if failed:
        print(f"Failed ({fail_count}):", flush=True)
        for item in failed:
            print(f"  {item}", flush=True)

    emit_json_event(
        options.json_events,
        "collection_finished",
        title=collection.name,
        ok_count=ok,
        failed_count=fail_count,
        warning_count=warnings,
        output_folder=str(output_dir),
    )

    return ok, fail_count, warnings, failed, output_dir


# ---------------------------------------------------------------------------
# Preview & health
# ---------------------------------------------------------------------------


def _collection_output_folder(output_dir: str, collection: SpotifyCollection) -> str:
    base = Path(output_dir).expanduser()
    if collection.use_subfolder:
        base = base / safe(collection.name)
    return str(base)


def preview_sources(urls: list[str], media: str = "audio", output_dir: str = "downloads") -> tuple[list[dict], list[dict]]:
    items: list[dict] = []
    errors: list[dict] = []

    for url in urls:
        try:
            if is_spotify_url(url):
                if media == "video":
                    raise ValueError("Spotify links can only be downloaded as audio.")
                collection = fetch_spotify(url)
                tracks = [
                    {
                        "position": index if collection.use_subfolder else None,
                        "title": track.name,
                        "artists": track.artists,
                        "album": track.album or "",
                        "spotify_id": track.spotify_id or "",
                        "duration_seconds": (track.duration_ms / 1000) if track.duration_ms else None,
                        "cover_url": track.cover_url or "",
                    }
                    for index, track in enumerate(collection.tracks, 1)
                ]
                detail = (
                    f"{len(collection.tracks)} tracks"
                    if collection.use_subfolder
                    else (collection.tracks[0].artists if collection.tracks else "")
                )
                items.append(
                    {
                        "url": url,
                        "kind": collection.kind,
                        "title": collection.name,
                        "detail": detail,
                        "track_count": len(collection.tracks),
                        "cover_url": collection.cover_url or "",
                        "output_folder": _collection_output_folder(output_dir, collection),
                        "tracks": tracks,
                    }
                )
            elif is_youtube_url(url):
                info = fetch_youtube_info(url)
                duration = info.get("duration")
                items.append(
                    {
                        "url": url,
                        "kind": "youtube",
                        "title": str(info.get("title") or "YouTube media"),
                        "detail": str(info.get("uploader") or info.get("channel") or ""),
                        "track_count": 1,
                        "cover_url": str(info.get("thumbnail") or ""),
                        "output_folder": str(Path(output_dir).expanduser()),
                        "tracks": [
                            {
                                "position": None,
                                "title": str(info.get("title") or "YouTube media"),
                                "artists": str(info.get("uploader") or info.get("channel") or ""),
                                "album": "",
                                "spotify_id": "",
                                "duration_seconds": float(duration) if isinstance(duration, (int, float)) else None,
                                "cover_url": str(info.get("thumbnail") or ""),
                            }
                        ],
                    }
                )
            else:
                raise ValueError(f"Unsupported URL: {url}")
        except Exception as exc:
            errors.append({"url": url, "message": str(exc)})

    return items, errors


def health_diagnostics(output_dir: str = "downloads", probe_network: bool = True) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        from yt_dlp.version import __version__ as yt_dlp_version

        add("yt-dlp", True, f"version {yt_dlp_version}")
    except Exception as exc:
        add("yt-dlp", False, f"import failed: {exc}")

    ffmpeg = find_ffmpeg_location() or shutil.which("ffmpeg")
    add("ffmpeg", bool(ffmpeg), ffmpeg or "not found; run ffmpeg-install or 'brew install ffmpeg'")

    runtimes = find_js_runtimes()
    add(
        "JavaScript runtime",
        bool(runtimes),
        ", ".join(f"{name} ({config['path']})" for name, config in runtimes.items())
        if runtimes
        else "missing; YouTube downloads may fail with HTTP 403. Run 'brew install deno'.",
    )
    ejs_ready = has_ejs_scripts()
    add("yt-dlp-ejs", ejs_ready, "ready" if ejs_ready else "missing; reinstall with pip install -r requirements.txt")

    add("mutagen", HAS_MUTAGEN, "ready" if HAS_MUTAGEN else "missing; tags will not be written")
    add("Pillow", HAS_PILLOW, "ready" if HAS_PILLOW else "optional; artwork resizing disabled")

    folder = Path(output_dir).expanduser()
    writable = False
    detail = ""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".spotify-downloader-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        writable = True
        detail = str(folder)
    except Exception as exc:
        detail = f"not writable: {exc}"
    add("output folder", writable, detail)

    history = history_path()
    add("history", True, str(history) if history.exists() else "no downloads recorded yet")

    if probe_network:
        try:
            response = req.get("https://open.spotify.com/", headers={"User-Agent": USER_AGENT}, timeout=10)
            add("Spotify reachable", response.status_code < 500, f"HTTP {response.status_code}")
        except Exception as exc:
            add("Spotify reachable", False, str(exc))

    required = {"yt-dlp", "ffmpeg", "output folder", "mutagen"}
    ok = all(check["ok"] for check in checks if check["name"] in required)

    return {
        "ok": ok,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sunnify_parity": SUNNIFY_PARITY,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Library repair
# ---------------------------------------------------------------------------


def text_ratio(left: str, right: str) -> float:
    left_norm = normalize_match_text(left)
    right_norm = normalize_match_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def filename_title_artist_pairs(path: Path) -> list[tuple[str, str]]:
    stem = path.stem
    stem = re.sub(r"^\s*\d{1,3}\s*[\.\)\-]?\s+", "", stem).strip()
    parts = [part.strip() for part in re.split(r"\s[-–—]\s", stem, maxsplit=1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        first, second = parts
        return [(first, second), (second, first)]
    return [(stem, "")]


def read_audio_tags(path: Path) -> dict[str, object]:
    info: dict[str, object] = {}
    if not HAS_MUTAGEN:
        return info
    try:
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            try:
                easy = EasyID3(str(path))
            except Exception:
                easy = {}
            info["title"] = (easy.get("title") or [None])[0]
            info["artist"] = (easy.get("artist") or [None])[0]
            info["album"] = (easy.get("album") or [None])[0]
            info["genre"] = (easy.get("genre") or [None])[0]
        elif suffix == ".m4a":
            audio = MP4(str(path))
            info["title"] = (audio.get("\xa9nam") or [None])[0]
            info["artist"] = (audio.get("\xa9ART") or [None])[0]
            info["album"] = (audio.get("\xa9alb") or [None])[0]
            info["genre"] = (audio.get("\xa9gen") or [None])[0]
        elif suffix in {".flac", ".ogg", ".opus"}:
            audio = FLAC(str(path)) if suffix == ".flac" else (OggOpus(str(path)) if suffix == ".opus" else OggVorbis(str(path)))
            info["title"] = (audio.get("title") or [None])[0]
            info["artist"] = (audio.get("artist") or [None])[0]
            info["album"] = (audio.get("album") or [None])[0]
            info["genre"] = (audio.get("genre") or [None])[0]
        try:
            length = getattr(getattr(__import__("mutagen").File(str(path)), "info", None), "length", None)
            if length:
                info["duration_ms"] = int(length * 1000)
        except Exception:
            pass
    except Exception as exc:
        LOG.info("could not read tags for %s: %s", path, exc)
    return info


def build_library_guess(path: Path) -> LibraryTrackGuess:
    tags = read_audio_tags(path)
    title = (tags.get("title") or "").strip() if isinstance(tags.get("title"), str) else ""
    artist = (tags.get("artist") or "").strip() if isinstance(tags.get("artist"), str) else ""
    from_filename = False
    if not title or not artist:
        pairs = filename_title_artist_pairs(path)
        if pairs:
            title = title or pairs[0][0]
            artist = artist or pairs[0][1]
            from_filename = True
    return LibraryTrackGuess(
        path=path,
        title=title,
        artist=artist,
        album=tags.get("album") if isinstance(tags.get("album"), str) else None,
        genre=tags.get("genre") if isinstance(tags.get("genre"), str) else None,
        duration_ms=tags.get("duration_ms") if isinstance(tags.get("duration_ms"), int) else None,
        from_filename=from_filename,
    )


def itunes_search_candidates(guess: LibraryTrackGuess) -> list[LibraryMetadata]:
    term = f"{guess.artist} {guess.title}".strip() or guess.title
    if not term:
        return []
    try:
        response = req.get(
            ITUNES_API,
            params={"term": term, "media": "music", "entity": "song", "limit": 5},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except Exception as exc:
        LOG.info("iTunes lookup failed for %s: %s", term, exc)
        return []

    candidates: list[LibraryMetadata] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        artwork = item.get("artworkUrl100")
        if isinstance(artwork, str):
            artwork = artwork.replace("100x100bb", "600x600bb")
        release = item.get("releaseDate")
        year = release[:4] if isinstance(release, str) and len(release) >= 4 else None
        candidates.append(
            LibraryMetadata(
                title=str(item.get("trackName") or ""),
                artist=str(item.get("artistName") or ""),
                album=item.get("collectionName"),
                genre=item.get("primaryGenreName"),
                year=year,
                duration_ms=item.get("trackTimeMillis"),
                track_number=item.get("trackNumber"),
                disc_number=item.get("discNumber"),
                artwork_url=artwork,
                source="Apple Music",
            )
        )
    return candidates


def musicbrainz_search_candidates(guess: LibraryTrackGuess) -> list[LibraryMetadata]:
    if not guess.title:
        return []
    query = f'recording:"{guess.title}"'
    if guess.artist:
        query += f' AND artist:"{guess.artist}"'
    try:
        response = req.get(
            MUSICBRAINZ_API,
            params={"query": query, "fmt": "json", "limit": 5},
            headers={"User-Agent": "SpotifyDownloader/1.0 (https://example.com)"},
            timeout=15,
        )
        response.raise_for_status()
        recordings = response.json().get("recordings", [])
    except Exception as exc:
        LOG.info("MusicBrainz lookup failed for %s: %s", guess.title, exc)
        return []

    candidates: list[LibraryMetadata] = []
    for item in recordings:
        if not isinstance(item, dict):
            continue
        artist_credit = item.get("artist-credit") or []
        artist = ", ".join(
            entry.get("name", "") for entry in artist_credit if isinstance(entry, dict)
        ).strip(", ")
        releases = item.get("releases") or []
        album = releases[0].get("title") if releases and isinstance(releases[0], dict) else None
        length = item.get("length")
        candidates.append(
            LibraryMetadata(
                title=str(item.get("title") or ""),
                artist=artist or (guess.artist or ""),
                album=album,
                duration_ms=int(length) if isinstance(length, (int, float)) else None,
                source="MusicBrainz",
            )
        )
    return candidates


def score_library_candidate(guess: LibraryTrackGuess, candidate: LibraryMetadata) -> float:
    title_score = text_ratio(guess.title, candidate.title) if guess.title else 0.0
    artist_score = text_ratio(guess.artist, candidate.artist) if guess.artist else 0.0
    if guess.duration_ms and candidate.duration_ms:
        diff = abs(guess.duration_ms - candidate.duration_ms)
        duration_score = max(0.0, 1.0 - diff / max(guess.duration_ms, 1))
    else:
        duration_score = 0.6
    if not guess.artist:
        if not guess.duration_ms or not candidate.duration_ms:
            return 0.0
        return title_score * 0.8 + duration_score * 0.2
    return title_score * 0.5 + artist_score * 0.35 + duration_score * 0.15


def identify_library_metadata(
    guess: LibraryTrackGuess,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> LibraryMetadata | None:
    candidates = itunes_search_candidates(guess) + musicbrainz_search_candidates(guess)
    best: LibraryMetadata | None = None
    best_score = 0.0
    for candidate in candidates:
        score = score_library_candidate(guess, candidate)
        if score > best_score:
            best_score = score
            best = candidate
    if best is None or best_score < min_confidence:
        return None
    best.confidence = best_score
    return best


def render_rename_pattern(
    pattern: str,
    metadata: LibraryMetadata,
    track_number: int | None = None,
    disc_number: int | None = None,
) -> str:
    number = track_number if track_number is not None else metadata.track_number
    disc = disc_number if disc_number is not None else metadata.disc_number
    tokens = {
        "track_number": f"{number:02d}" if isinstance(number, int) else "",
        "disc_number": f"{disc:d}" if isinstance(disc, int) else "",
        "title": metadata.title or "",
        "artist": metadata.artist or "",
        "album": metadata.album or "",
        "year": metadata.year or "",
        "genre": metadata.genre or "",
    }

    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return ""

    rendered = pattern.format_map(_SafeDict(tokens))
    rendered = re.sub(r"^\s*[\.\-]\s*", "", rendered).strip()
    return safe(rendered)


def apply_library_metadata(
    path: Path,
    metadata: LibraryMetadata,
    update_artwork: bool,
    overwrite_artwork: bool,
    lyrics_enabled: bool,
    lyrics_style: str = "plain",
) -> None:
    if not HAS_MUTAGEN:
        return
    track = Track(
        name=metadata.title,
        artists=metadata.artist,
        album=metadata.album,
        duration_ms=metadata.duration_ms,
        cover_url=metadata.artwork_url if update_artwork else None,
    )
    lyrics = fetch_lyrics_payload(track) if lyrics_enabled else None
    cover = None
    if update_artwork and metadata.artwork_url:
        existing_cover = _has_embedded_cover(path)
        if overwrite_artwork or not existing_cover:
            cover = cover_bytes(path, track)
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        write_mp3_tags(path, track, metadata.track_number, cover)
    elif suffix == ".m4a":
        write_m4a_tags(path, track, metadata.track_number, cover)
    elif suffix == ".flac":
        write_flac_tags(path, track, metadata.track_number, cover)
    elif suffix in {".opus", ".ogg"}:
        write_ogg_tags(path, track, metadata.track_number)
    embed_lyrics(path, lyrics, lyrics_style)


def _has_embedded_cover(path: Path) -> bool:
    if not HAS_MUTAGEN:
        return False
    try:
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            return bool(ID3(str(path)).getall("APIC"))
        if suffix == ".m4a":
            return bool(MP4(str(path)).get("covr"))
        if suffix == ".flac":
            return bool(FLAC(str(path)).pictures)
    except Exception:
        return False
    return False


def iter_library_files(folders: list[str], recursive: bool) -> list[Path]:
    paths: list[Path] = []
    for folder in folders:
        base = Path(folder).expanduser()
        if not base.exists():
            continue
        iterator = base.rglob("*") if recursive else base.glob("*")
        for path in iterator:
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                paths.append(path)
    return sorted(paths)


def repair_library(args: argparse.Namespace) -> int:
    json_events = getattr(args, "json_events", False)
    folders = list(args.folders)
    recursive = getattr(args, "recursive", True)
    apply = getattr(args, "apply", False)
    lyrics_enabled = getattr(args, "lyrics", True)
    lyrics_style = getattr(args, "lyrics_style", "plain")
    update_artwork = getattr(args, "artwork", True)
    overwrite_artwork = getattr(args, "overwrite_artwork", False)
    min_confidence = getattr(args, "min_confidence", DEFAULT_MIN_CONFIDENCE)
    rename_pattern = getattr(args, "rename_pattern", None)

    files = iter_library_files(folders, recursive)
    total = len(files)
    print(f"Scanning {total} audio file(s) in {len(folders)} folder(s).", flush=True)
    emit_json_event(json_events, "collection_start", title="Library Cleanup", track_count=total, selected_count=total, total=total)

    ok = 0
    failed = 0
    for index, path in enumerate(files, 1):
        if STOP_EVENT.is_set():
            break
        guess = build_library_guess(path)
        key = f"library:{path}"
        emit_json_event(
            json_events,
            "track_progress",
            key=key,
            index=index,
            total=total,
            label=path.name,
            title=guess.title or path.stem,
            artists=guess.artist or "",
            progress=0.1,
            state="running",
            message="Identifying",
        )
        try:
            match = identify_library_metadata(guess, min_confidence)
        except Exception as exc:
            match = None
            LOG.warning("identify failed for %s: %s", path, exc)

        if not match:
            failed += 1
            emit_json_event(
                json_events,
                "track_progress",
                key=key,
                index=index,
                total=total,
                label=path.name,
                progress=1.0,
                state="skipped",
                message="No confident match",
            )
            print(f"  [{index}/{total}] No confident match: {path.name}", flush=True)
            continue

        message = f"{match.artist} - {match.title} ({int(match.confidence * 100)}%) via {match.source}"
        final_path = path
        if apply:
            try:
                apply_library_metadata(path, match, update_artwork, overwrite_artwork, lyrics_enabled, lyrics_style)
                if rename_pattern:
                    new_stem = render_rename_pattern(rename_pattern, match, match.track_number)
                    if new_stem:
                        target = path.with_name(f"{new_stem}{path.suffix.lower()}")
                        if target != path and not target.exists():
                            path.rename(target)
                            final_path = target
                            message += f" -> {target.name}"
                ok += 1
                state = "succeeded"
            except Exception as exc:
                failed += 1
                state = "failed"
                message = f"apply failed: {exc}"
        else:
            ok += 1
            state = "succeeded"

        emit_json_event(
            json_events,
            "track_progress",
            key=key,
            index=index,
            total=total,
            label=final_path.name,
            title=match.title,
            artists=match.artist,
            album=match.album or "",
            cover_url=match.artwork_url or "",
            progress=1.0,
            state=state,
            message=message,
            path=str(final_path),
        )
        verb = "Updated" if apply else "Matched"
        print(f"  [{index}/{total}] {verb}: {message}", flush=True)

    print(f"{'Repaired' if apply else 'Matched'}: {ok}/{total}", flush=True)
    emit_json_event(json_events, "collection_finished", title="Library Cleanup", ok_count=ok, failed_count=failed)
    return 0 if failed == 0 else 1


def read_embedded_lyrics(path: Path) -> str | None:
    """The text in the file's standard lyrics tag, if any."""
    if not HAS_MUTAGEN:
        return None
    suffix = path.suffix.lower()
    try:
        if suffix == ".mp3":
            frames = ID3(str(path)).getall("USLT")
            return frames[0].text if frames else None
        if suffix == ".m4a":
            values = MP4(str(path)).get("\xa9lyr")
            return values[0] if values else None
        if suffix in {".flac", ".opus", ".ogg"}:
            audio = FLAC(str(path)) if suffix == ".flac" else (OggOpus(str(path)) if suffix == ".opus" else OggVorbis(str(path)))
            values = audio.get("lyrics")
            return values[0] if values else None
    except Exception as exc:
        LOG.info("could not read lyrics from %s: %s", path, exc)
    return None


def clean_lyrics_timestamps(args: argparse.Namespace) -> int:
    """Rewrite timestamped (LRC) lyrics tags as plain text.

    Apple Music shows the lyrics tag as-is and cannot scroll lyrics for local
    files, so "[00:42.92] Ooh yeah" appears literally. The plain text goes
    back into the lyrics tag; MP3 files keep the timing in a SYLT frame.
    """
    json_events = getattr(args, "json_events", False)
    files = [
        path
        for path in iter_library_files(list(args.folders), getattr(args, "recursive", True))
        if path.suffix.lower() in {".mp3", ".m4a", ".flac", ".opus", ".ogg"}
    ]
    total = len(files)
    print(f"Checking lyrics in {total} audio file(s).", flush=True)
    emit_json_event(json_events, "collection_start", title="Clean Lyrics", track_count=total, selected_count=total, total=total)

    cleaned = 0
    failed = 0
    for index, path in enumerate(files, 1):
        if STOP_EVENT.is_set():
            break
        text = read_embedded_lyrics(path)
        if not text or not LRC_TIMESTAMP_RE.search(text):
            continue
        try:
            if not embed_lyrics(path, lyrics_from_lrc_text(text), "plain"):
                raise ValueError("format does not support embedded lyrics")
            cleaned += 1
            state, message = "succeeded", "Removed timestamps from lyrics"
        except Exception as exc:
            failed += 1
            state, message = "failed", str(exc)
            LOG.warning("could not clean lyrics in %s: %s", path, exc)
        emit_json_event(
            json_events,
            "track_progress",
            key=f"clean-lyrics:{path}",
            index=index,
            total=total,
            label=path.name,
            title=path.stem,
            artists="",
            progress=1.0,
            state=state,
            message=message,
            path=str(path),
        )
        print(f"  [{index}/{total}] {message}: {path.name}", flush=True)

    print(f"Cleaned lyrics in {cleaned} file(s).", flush=True)
    emit_json_event(json_events, "collection_finished", title="Clean Lyrics", ok_count=cleaned, failed_count=failed)
    return 0 if failed == 0 else 1


def lrc_sidecar_pairs(folders: list[str], recursive: bool) -> list[tuple[Path, Path]]:
    """Audio files that have a same-named .lrc file next to them."""
    pairs: list[tuple[Path, Path]] = []
    for path in iter_library_files(folders, recursive):
        sidecar = path.with_suffix(".lrc")
        if sidecar.is_file():
            pairs.append((path, sidecar))
    return pairs


def embed_lrc_sidecars(args: argparse.Namespace) -> int:
    """Move lyrics from .lrc sidecar files into the audio files themselves."""
    json_events = getattr(args, "json_events", False)
    keep = getattr(args, "keep_lrc", False)
    style = getattr(args, "lyrics_style", "plain")
    pairs = lrc_sidecar_pairs(list(args.folders), getattr(args, "recursive", True))
    total = len(pairs)
    print(f"Found {total} audio file(s) with .lrc lyrics.", flush=True)
    emit_json_event(json_events, "collection_start", title="Embed Lyrics", track_count=total, selected_count=total, total=total)

    ok = 0
    failed = 0
    for index, (audio, sidecar) in enumerate(pairs, 1):
        if STOP_EVENT.is_set():
            break
        key = f"lyrics:{audio}"
        try:
            lyrics = lyrics_from_lrc_text(sidecar.read_text(encoding="utf-8", errors="replace"))
            if not embed_lyrics(audio, lyrics, style):
                raise ValueError("format does not support embedded lyrics" if lyrics else "lyrics file is empty")
            if not keep:
                sidecar.unlink(missing_ok=True)
            ok += 1
            state, message = "succeeded", "Embedded" if keep else "Embedded; removed .lrc"
        except Exception as exc:
            failed += 1
            state, message = "failed", str(exc)
            LOG.warning("could not embed %s into %s: %s", sidecar, audio, exc)
        emit_json_event(
            json_events,
            "track_progress",
            key=key,
            index=index,
            total=total,
            label=audio.name,
            title=audio.stem,
            artists="",
            progress=1.0,
            state=state,
            message=message,
            path=str(audio),
        )
        print(f"  [{index}/{total}] {message}: {audio.name}", flush=True)

    print(f"Embedded lyrics: {ok}/{total}", flush=True)
    emit_json_event(json_events, "collection_finished", title="Embed Lyrics", ok_count=ok, failed_count=failed)
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# ffmpeg installer
# ---------------------------------------------------------------------------


def install_ffmpeg(json_events: bool = False) -> int:
    if sys.platform != "darwin":
        print("Automatic ffmpeg install is only supported on macOS.", file=sys.stderr, flush=True)
        return 1

    brew = shutil.which("brew")
    if not brew:
        message = "Homebrew is required for automatic ffmpeg installation. Install ffmpeg manually and run diagnostics again."
        emit_json_event(json_events, "ffmpeg_install", state="failed", progress=1.0, message=message)
        print(message, file=sys.stderr, flush=True)
        return 1

    emit_json_event(json_events, "ffmpeg_install", state="running", progress=0.0, message="Installing ffmpeg with Homebrew")
    print("Installing ffmpeg with Homebrew...", flush=True)
    try:
        process = subprocess.Popen(
            [brew, "install", "ffmpeg"], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        register_process(process)
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    print(line.rstrip(), flush=True)
            installed = process.wait() == 0
        finally:
            unregister_process(process)
    except Exception as exc:
        emit_json_event(json_events, "ffmpeg_install", state="failed", progress=1.0, message=str(exc))
        print(f"ffmpeg install failed: {exc}", file=sys.stderr, flush=True)
        return 1

    target = shutil.which("ffmpeg") or find_ffmpeg_location()
    if not installed or not target:
        emit_json_event(json_events, "ffmpeg_install", state="failed", progress=1.0, message="Homebrew could not install ffmpeg")
        print("Homebrew could not install ffmpeg.", file=sys.stderr, flush=True)
        return 1

    try:
        result = subprocess.run([target, "-version"], capture_output=True, text=True, timeout=30)
        verified = result.returncode == 0
    except Exception as exc:
        verified = False
        LOG.warning("ffmpeg verification failed: %s", exc)

    if not verified:
        emit_json_event(json_events, "ffmpeg_install", state="failed", progress=1.0, message="verification failed")
        print("ffmpeg installed but did not run cleanly.", file=sys.stderr, flush=True)
        return 1

    emit_json_event(json_events, "ffmpeg_install", state="succeeded", progress=1.0, message=str(target))
    print(f"ffmpeg installed: {target}", flush=True)
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def doctor() -> int:
    missing = []
    ffmpeg = find_ffmpeg_location() or shutil.which("ffmpeg")

    if not ffmpeg or (ffmpeg.endswith("ffmpeg") and not Path(ffmpeg).exists() and not shutil.which("ffmpeg")):
        missing.append("ffmpeg")

    if missing:
        print("Missing: " + ", ".join(missing), flush=True)
        print("Install with: python3 -m pip install -r requirements.txt", flush=True)
        if "ffmpeg" in missing:
            print("Install ffmpeg with Homebrew: brew install ffmpeg", flush=True)
            print("Or run: spotify_dl ffmpeg-install", flush=True)
        return 1

    from yt_dlp.version import __version__ as yt_dlp_version

    print(f"yt-dlp {yt_dlp_version}; ffmpeg ready", flush=True)
    if not HAS_MUTAGEN:
        print("Warning: mutagen is missing, so tags will not be written.", flush=True)
    if not HAS_PILLOW:
        print("Note: Pillow is missing, so artwork resizing is disabled.", flush=True)
    if not find_js_runtimes():
        print("Warning: no JavaScript runtime found; YouTube may return HTTP 403. Install one with: brew install deno", flush=True)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def add_lyrics_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lyrics", dest="lyrics", action="store_true", default=True, help="Search and apply lyrics.")
    parser.add_argument("--no-lyrics", dest="lyrics", action="store_false", help="Do not search or apply lyrics.")
    add_lyrics_style_flag(parser)


def add_lyrics_style_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lyrics-style",
        dest="lyrics_style",
        choices=LYRICS_STYLES,
        default="plain",
        help="plain: readable text in the lyrics tag (Apple Music). synced: timestamped LRC text for players "
        "that scroll lyrics. MP3 files always get an embedded SYLT timing frame when timing is available.",
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Spotify audio and YouTube audio/video with yt-dlp."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check yt-dlp and ffmpeg dependencies.")

    ffmpeg_install = subparsers.add_parser("ffmpeg-install", help="Install ffmpeg with Homebrew (macOS).")
    ffmpeg_install.add_argument("--json-events", dest="json_events", action="store_true", help="Emit JSON progress events.")

    download = subparsers.add_parser("download", help="Download Spotify or YouTube URLs.")
    download.add_argument("urls", nargs="+", help="Spotify track/playlist/album URLs or YouTube video URLs.")
    download.add_argument("-o", "--output-dir", default="downloads", help="Base download folder.")
    download.add_argument("--media", choices=("audio", "video"), default="audio", help="Download audio, or full videos for YouTube URLs.")
    download.add_argument("-f", "--format", default="mp3", dest="fmt", choices=("mp3", "m4a", "flac", "opus", "ogg", "wav"), help="Audio output format.")
    download.add_argument("-b", "--bitrate", default="192k", help="Audio quality, e.g. 192k, 320k, 0.")
    download.add_argument("--threads", type=int, choices=range(1, 17), default=4, help="Parallel downloads per playlist (1-16).")
    download.add_argument("--retries", type=int, choices=range(0, 6), default=2, help="Additional attempts per failed track (0-5), using different search and download methods.")
    download.add_argument("--overwrite", choices=("skip", "metadata", "force"), default="skip", help="How to handle existing files.")
    download.add_argument("--track-number-prefix", dest="track_number_prefix", action="store_true", default=True, help="Prefix files with their track number.")
    download.add_argument("--no-track-number-prefix", dest="track_number_prefix", action="store_false", help="Do not prefix files with their track number.")
    download.add_argument("--allow-closest-match", action="store_true", help="Use the closest duration match if no confident match is found.")
    download.add_argument(
        "--match-flexibility",
        dest="match_flexibility",
        type=float,
        default=DEFAULT_MATCH_FLEXIBILITY,
        help="0 = strictest YouTube matching, 1 = loosest (default %(default)s). Higher values allow longer "
        "duration differences, partial titles, and uploads that do not name the artist.",
    )
    add_lyrics_flags(download)
    download.add_argument("--lrc", dest="write_lrc", action="store_true", default=False, help="Also write synced lyrics to a .lrc sidecar file.")
    download.add_argument("--no-lrc", dest="write_lrc", action="store_false", help="Do not write .lrc sidecar files (default).")
    download.add_argument("--cookies-browser", dest="cookies_browser", choices=COOKIE_BROWSERS, default=None, help="Load cookies from a browser for yt-dlp.")
    download.add_argument("--artwork-max-size", dest="artwork_max_size", choices=ARTWORK_SIZES, default="unlimited", help="Downscale embedded cover art to this many pixels.")
    download.add_argument("--artwork-jpeg", dest="artwork_jpeg", action="store_true", help="Convert embedded cover art to JPEG.")
    download.add_argument("--json-events", dest="json_events", action="store_true", help="Emit JSON progress events.")
    download.add_argument("--debug-log", action="store_true", help="Write verbose diagnostics to the log file.")
    download.add_argument("--start", type=int, default=1, help="Start from track N in playlists.")
    download.add_argument("--dry-run", action="store_true", help="List tracks without downloading.")

    preview = subparsers.add_parser("preview", help="Emit JSON describing what a download would fetch.")
    preview.add_argument("urls", nargs="+", help="Spotify or YouTube URLs.")
    preview.add_argument("-o", "--output-dir", default="downloads", help="Base download folder.")
    preview.add_argument("--media", choices=("audio", "video"), default="audio", help="Media kind.")
    preview.add_argument("--json", action="store_true", help="Emit JSON (always on).")

    health = subparsers.add_parser("health", help="Emit a JSON diagnostics report.")
    health.add_argument("-o", "--output-dir", default="downloads", help="Folder to validate as writable.")
    health.add_argument("--json", action="store_true", help="Emit JSON (always on).")
    health.add_argument("--no-network", dest="probe_network", action="store_false", default=True, help="Skip network probes.")

    library = subparsers.add_parser("library", help="Scan or repair an existing music library's metadata.")
    library.add_argument("folders", nargs="+", help="Folders to scan.")
    library.add_argument("--apply", action="store_true", help="Write metadata changes (otherwise scan only).")
    library.add_argument("--recursive", dest="recursive", action="store_true", default=True, help="Include subfolders.")
    library.add_argument("--no-recursive", dest="recursive", action="store_false", help="Do not include subfolders.")
    add_lyrics_flags(library)
    library.add_argument("--artwork", dest="artwork", action="store_true", default=True, help="Add missing cover art.")
    library.add_argument("--no-artwork", dest="artwork", action="store_false", help="Do not modify artwork.")
    library.add_argument("--overwrite-artwork", action="store_true", help="Replace existing cover art.")
    library.add_argument("--min-confidence", dest="min_confidence", type=float, default=DEFAULT_MIN_CONFIDENCE, help="Minimum match confidence (0-1).")
    library.add_argument("--rename-pattern", dest="rename_pattern", default=None, help="Rename applied files using this pattern.")
    library.add_argument("--json-events", dest="json_events", action="store_true", help="Emit JSON progress events.")
    library.add_argument("--debug-log", action="store_true", help="Write verbose diagnostics to the log file.")

    embed_lrc = subparsers.add_parser("embed-lrc", help="Embed existing .lrc sidecar lyrics into their audio files.")
    embed_lrc.add_argument("folders", nargs="+", help="Folders to scan.")
    embed_lrc.add_argument("--recursive", dest="recursive", action="store_true", default=True, help="Include subfolders.")
    embed_lrc.add_argument("--no-recursive", dest="recursive", action="store_false", help="Do not include subfolders.")
    embed_lrc.add_argument("--keep-lrc", action="store_true", help="Keep the .lrc files after embedding.")
    add_lyrics_style_flag(embed_lrc)
    embed_lrc.add_argument("--json-events", dest="json_events", action="store_true", help="Emit JSON progress events.")

    clean_lyrics = subparsers.add_parser(
        "clean-lyrics", help="Strip [00:12.34] timestamps from embedded lyrics so Apple Music shows clean text."
    )
    clean_lyrics.add_argument("folders", nargs="+", help="Folders to scan.")
    clean_lyrics.add_argument("--recursive", dest="recursive", action="store_true", default=True, help="Include subfolders.")
    clean_lyrics.add_argument("--no-recursive", dest="recursive", action="store_false", help="Do not include subfolders.")
    clean_lyrics.add_argument("--json-events", dest="json_events", action="store_true", help="Emit JSON progress events.")

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return create_parser().parse_args(argv)


def run_download(args: argparse.Namespace) -> int:
    options = RunOptions.from_args(args)
    options.ffmpeg_location = find_ffmpeg_location()
    options_output_dir.set(str(Path(args.output_dir).expanduser()))

    total_failures = 0
    def finish_source(url: str, ok: int, failed: int, warnings: int = 0) -> None:
        emit_json_event(
            options.json_events, "source_finished", source_url=url,
            ok_count=ok, failed_count=failed, warning_count=warnings,
        )

    for url_index, url in enumerate(args.urls, 1):
        if is_spotify_url(url):
            if args.media == "video":
                print("Spotify links can only be downloaded as audio.", file=sys.stderr, flush=True)
                total_failures += 1
                finish_source(url, 0, 1)
                continue

            print(f"Fetching Spotify metadata: {url}", flush=True)
            try:
                collection = fetch_spotify(
                    url,
                    resume_output_root=args.output_dir if options.overwrite == "skip" else None,
                    resume_format=options.fmt if options.overwrite == "skip" else None,
                )
            except Exception as exc:
                print(f"Failed to fetch Spotify metadata: {exc}", file=sys.stderr, flush=True)
                total_failures += 1
                finish_source(url, 0, 1)
                continue

            print_track_list(collection)
            if args.dry_run:
                finish_source(url, len(collection.tracks), 0)
                continue

            try:
                ok, failures, warnings, failed, output_dir = download_collection(
                    collection, options, args.output_dir, args.threads, args.start
                )
            except KeyboardInterrupt:
                print("Cancelled.", flush=True)
                return 130
            total_failures += failures
            append_history(
                {
                    "source_url": url,
                    "media": args.media,
                    "format": options.fmt,
                    "bitrate": options.bitrate,
                    "output_folder": str(output_dir),
                    "ok_count": ok,
                    "failed_count": failures,
                    "warning_count": warnings,
                    "failed": failed,
                }
            )
            finish_source(url, ok, failures, warnings)
            continue

        if is_youtube_url(url):
            print(f"Fetching YouTube metadata: {url}", flush=True)
            try:
                youtube_info = fetch_youtube_info(url, options.cookies_browser)
            except Exception as exc:
                print(f"Failed to fetch YouTube metadata: {exc}", file=sys.stderr, flush=True)
                total_failures += 1
                finish_source(url, 0, 1)
                continue

            print_youtube_info(youtube_info, args.media)
            if args.dry_run:
                finish_source(url, 1, 0)
                continue

            youtube_title_text = str(youtube_info.get("title") or "YouTube audio")
            youtube_artist_text = str(youtube_info.get("uploader") or youtube_info.get("channel") or "").strip()
            emit_json_event(
                options.json_events,
                "track_progress",
                key=url,
                index=url_index if len(args.urls) > 1 else None,
                total=len(args.urls),
                label=youtube_label(youtube_info),
                title=youtube_title_text,
                artists=youtube_artist_text,
                progress=0.05,
                state="running",
                message="Downloading",
            )

            try:
                result = download_youtube_media(url, options)
            except KeyboardInterrupt:
                print("Cancelled.", flush=True)
                return 130

            if result.ok:
                print(f"Done: {result.label} ({result.detail})", flush=True)
                emit_json_event(
                    options.json_events,
                    "track_progress",
                    key=url,
                    index=url_index if len(args.urls) > 1 else None,
                    total=len(args.urls),
                    label=result.label,
                    title=youtube_title_text,
                    artists=youtube_artist_text,
                    progress=1.0,
                    state="succeeded",
                    message=result.detail,
                    path=result.path,
                    created_this_run=result.created_this_run,
                )
            else:
                total_failures += 1
                print(f"Failed: {result.detail}", flush=True)
                emit_json_event(
                    options.json_events,
                    "track_progress",
                    key=url,
                    index=url_index if len(args.urls) > 1 else None,
                    total=len(args.urls),
                    label=result.label,
                    title=youtube_title_text,
                    artists=youtube_artist_text,
                    progress=1.0,
                    state="failed",
                    message=result.detail,
                )
            append_history(
                {
                    "source_url": url,
                    "media": args.media,
                    "format": options.fmt if args.media == "audio" else "mp4",
                    "bitrate": options.bitrate,
                    "output_folder": str(Path(args.output_dir).expanduser()),
                    "ok_count": 1 if result.ok else 0,
                    "failed_count": 0 if result.ok else 1,
                    "failed": [] if result.ok else [result.detail],
                }
            )
            finish_source(url, 1 if result.ok else 0, 0 if result.ok else 1)
            continue

        expected = "Spotify or YouTube URL" if args.media == "audio" else "YouTube URL"
        print(f"Unsupported URL, expected a {expected}: {url}", file=sys.stderr, flush=True)
        total_failures += 1
        finish_source(url, 0, 1)

    return 1 if total_failures else 0


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    args = parse_args(argv)
    log_path = setup_logging(getattr(args, "debug_log", False))

    if args.command == "doctor":
        print(f"Logs: {log_path.parent}", flush=True)
        return doctor()

    if args.command == "ffmpeg-install":
        return install_ffmpeg(getattr(args, "json_events", False))

    if args.command == "preview":
        items, errors = preview_sources(args.urls, media=args.media, output_dir=args.output_dir)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sunnify_parity": SUNNIFY_PARITY,
            "items": items,
            "errors": errors,
        }
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0

    if args.command == "health":
        payload = health_diagnostics(output_dir=args.output_dir, probe_network=getattr(args, "probe_network", True))
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0 if payload["ok"] else 1

    if args.command == "library":
        try:
            return repair_library(args)
        except KeyboardInterrupt:
            print("Cancelled.", flush=True)
            return 130

    if args.command == "clean-lyrics":
        try:
            return clean_lyrics_timestamps(args)
        except KeyboardInterrupt:
            print("Cancelled.", flush=True)
            return 130

    if args.command == "embed-lrc":
        try:
            return embed_lrc_sidecars(args)
        except KeyboardInterrupt:
            print("Cancelled.", flush=True)
            return 130

    if args.command == "download":
        return run_download(args)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

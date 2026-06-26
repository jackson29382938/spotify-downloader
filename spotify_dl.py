#!/usr/bin/env python3
"""Download Spotify audio and YouTube media through yt-dlp.

This intentionally does not use spotDL or Spotify API credentials. It reads the
public Spotify embed metadata, searches YouTube with yt-dlp, extracts audio, and
optionally tags MP3 output. Direct YouTube URLs can be downloaded as audio or
full videos.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse
import unicodedata

import requests as req
from yt_dlp import YoutubeDL

try:
    from mutagen.easyid3 import EasyID3
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3, ID3NoHeaderError
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis

    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False


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

RUNNING_PROCESSES: set[subprocess.Popen[str]] = set()
RUNNING_LOCK = threading.Lock()
STOP_EVENT = threading.Event()
MANIFEST_LOCK = threading.Lock()
STEM_LOCK = threading.Lock()
IN_FLIGHT_STEMS: set[str] = set()
MANIFEST_FILENAME = ".spotify-downloader-manifest.jsonl"
LOG = logging.getLogger("spotify_downloader")
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
    r"(?:official\s+)?(?:audio|video|lyrics?|visualizer|remaster(?:ed)?|"
    r"mono|stereo|live|sped\s+up|slowed|nightcore|clean|explicit)"
    r"(?:\s+\d{4})?\s*[)]?\s*$",
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
class SpotifyCollection:
    name: str
    tracks: list[Track]
    use_subfolder: bool
    cover_url: str | None = None


@dataclass(frozen=True)
class DownloadResult:
    ok: bool
    label: str
    detail: str = ""
    path: str | None = None
    skipped: bool = False


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


def parse_spotify_url(url: str) -> tuple[str, str]:
    match = SPOTIFY_RE.search(url)
    if not match:
        raise ValueError(f"not a supported Spotify track, playlist, or album URL: {url}")
    return (match.group("kind") or match.group("uri_kind")), match.group("id")


def is_spotify_url(url: str) -> bool:
    return SPOTIFY_RE.search(url) is not None


def is_youtube_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and (
        host in YOUTUBE_HOSTS
        or host.endswith(".youtube.com")
        or host.endswith(".youtube-nocookie.com")
    )


def spotify_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 20) -> req.Response:
    request_headers = {"User-Agent": "Mozilla/5.0", **(headers or {})}
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


def fetch_embed_page(kind: str, spotify_id: str) -> tuple[dict, str | None]:
    url = f"https://open.spotify.com/embed/{kind}/{spotify_id}"
    response = spotify_get(url, timeout=20)

    match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    if not match:
        raise ValueError("Spotify embed metadata was not found.")

    data = json.loads(match.group(1))
    return data["props"]["pageProps"]["state"]["data"]["entity"], session_token_from(data)


def fetch_embed_entity(kind: str, spotify_id: str) -> dict:
    entity, _ = fetch_embed_page(kind, spotify_id)
    return entity


def best_image(entity: dict) -> str | None:
    candidates = []
    visual_images = entity.get("visualIdentity", {}).get("image", [])
    cover_sources = entity.get("coverArt", {}).get("sources", [])
    candidates.extend(visual_images)
    candidates.extend(cover_sources)
    candidates = [item for item in candidates if item.get("url")]
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
        cover_url=best_image(item),
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


def complete_playlist_tracks(playlist_id: str, token: str, embed_tracks: list[Track]) -> list[Track]:
    try:
        ordered_ids = fetch_spclient_track_ids(playlist_id, token)
    except Exception as exc:
        LOG.info("full playlist lookup failed for %s: %s", playlist_id, exc)
        return embed_tracks

    if len(ordered_ids) <= len(embed_tracks):
        return embed_tracks

    tracks_by_id = {track.spotify_id: track for track in embed_tracks if track.spotify_id}
    missing_ids = [spotify_id for spotify_id in ordered_ids if spotify_id not in tracks_by_id]
    print(
        f"Spotify playlist has {len(ordered_ids)} tracks; fetching {len(missing_ids)} more.",
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

    ordered_tracks = [tracks_by_id[spotify_id] for spotify_id in ordered_ids if spotify_id in tracks_by_id]
    return ordered_tracks or embed_tracks


def fetch_spotify(url: str) -> SpotifyCollection:
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
        )

    cover_url = best_image(entity)
    raw_tracks = entity.get("trackList") or []
    album_name = name if kind == "album" else None
    tracks = [
        track_from_collection_item(item, cover_url, album=album_name)
        for item in raw_tracks
        if (item.get("entityType") in (None, "track"))
    ]

    if not tracks:
        raise ValueError(f"No playable tracks found in Spotify {kind}: {name}")

    if kind == "playlist" and token:
        tracks = complete_playlist_tracks(spotify_id, token, tracks)

    return SpotifyCollection(name=name, tracks=tracks, use_subfolder=True, cover_url=cover_url)


def find_ffmpeg_location() -> str | None:
    env_path = Path(value).expanduser() if (value := os_environ("SPOTIFY_DOWNLOADER_FFMPEG")) else None
    if env_path and env_path.exists():
        return str(env_path)

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


def os_environ(name: str) -> str | None:
    import os

    value = os.environ.get(name)
    return value if value else None


def normalized_audio_quality(value: str) -> str:
    if re.fullmatch(r"\d+k", value, re.IGNORECASE):
        return value[:-1]
    if value in {"auto", "disable"}:
        return "0"
    return value


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


def image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


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


def write_mp3_tags(path: Path, track: Track, pos: int | None, cover: tuple[bytes, str] | None) -> None:
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
        data, mime = cover
        try:
            id3 = ID3(str(path))
        except ID3NoHeaderError:
            id3 = ID3()
        id3.delall("APIC")
        id3.add(APIC(encoding=1, mime=mime, type=3, desc="Cover", data=data))
        id3.update_to_v23()
        id3.save(str(path), v2_version=3)


def write_m4a_tags(path: Path, track: Track, pos: int | None, cover: tuple[bytes, str] | None) -> None:
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


def write_flac_tags(path: Path, track: Track, pos: int | None, cover: tuple[bytes, str] | None) -> None:
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


def tag(path: Path, track: Track, pos: int | None) -> None:
    if not HAS_MUTAGEN:
        return

    try:
        suffix = path.suffix.lower()
        cover = cover_bytes(path, track) if suffix in {".mp3", ".m4a", ".flac"} else None
        if suffix == ".mp3":
            write_mp3_tags(path, track, pos, cover)
        elif suffix == ".m4a":
            write_m4a_tags(path, track, pos, cover)
        elif suffix == ".flac":
            write_flac_tags(path, track, pos, cover)
        elif suffix in {".opus", ".ogg"}:
            write_ogg_tags(path, track, pos)
    except Exception as exc:
        LOG.warning("tagging failed for %s: %s", path, exc)
        print(f"  Warning: tagging failed for {path.name}: {exc}", flush=True)


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
        return f"spotify:{track.spotify_id}"
    duration = track.duration_ms or 0
    return f"{pos or 0}:{track.artists.casefold()}:{track.name.casefold()}:{duration}"


def load_manifest(output_dir: Path) -> dict[str, Path]:
    manifest = output_dir / MANIFEST_FILENAME
    completed: dict[str, Path] = {}
    if not manifest.exists():
        return completed

    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            key = item.get("key")
            path = output_dir / str(item.get("file", ""))
            if key and path.exists():
                completed[str(key)] = path
    except Exception as exc:
        LOG.warning("manifest read failed for %s: %s", manifest, exc)
    return completed


def append_manifest(output_dir: Path, key: str, path: Path) -> None:
    entry = {"key": key, "file": path.name}
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


def duration_seconds(track: Track) -> float | None:
    return track.duration_ms / 1000 if track.duration_ms else None


def youtube_candidates(track: Track, limit: int = 5) -> list[dict]:
    query = f"ytsearch{limit}:{track.artists} - {track.name} official audio"
    ydl_opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "noplaylist": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)

    if not isinstance(info, dict):
        return []
    entries = info.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict)]


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
    allow_closest: bool,
) -> tuple[dict | None, str]:
    if not candidates:
        return None, "no YouTube results"

    expected_duration = duration_seconds(track)
    title = normalize_match_text(track.name)
    artists = artist_tokens(track.artists)

    def title_ok(candidate: dict) -> bool:
        candidate_text = normalize_match_text(str(candidate.get("title") or ""))
        return bool(title and title in candidate_text)

    def artist_ok(candidate: dict) -> bool:
        combined = " ".join(
            normalize_match_text(str(candidate.get(key) or ""))
            for key in ("title", "uploader", "channel")
        )
        return not artists or any(artist and artist in combined for artist in artists)

    strict_pool = [candidate for candidate in candidates if title_ok(candidate) and artist_ok(candidate)]
    if strict_pool:
        if expected_duration:
            timed = [candidate for candidate in strict_pool if candidate.get("duration")]
            if timed:
                chosen = min(timed, key=lambda item: abs(float(item["duration"]) - expected_duration))
                diff = abs(float(chosen["duration"]) - expected_duration)
                if diff <= 30:
                    return chosen, "title, artist, and duration matched"
                return None, f"closest title match was {diff:.0f}s off"
        return strict_pool[0], "title and artist matched"

    title_pool = [candidate for candidate in candidates if title_ok(candidate)]
    if title_pool and expected_duration:
        timed = [candidate for candidate in title_pool if candidate.get("duration")]
        if timed:
            chosen = min(timed, key=lambda item: abs(float(item["duration"]) - expected_duration))
            diff = abs(float(chosen["duration"]) - expected_duration)
            if diff <= 30:
                return chosen, "title and duration matched"

    if allow_closest and expected_duration:
        timed = [candidate for candidate in candidates if candidate.get("duration")]
        if timed:
            chosen = min(timed, key=lambda item: abs(float(item["duration"]) - expected_duration))
            diff = abs(float(chosen["duration"]) - expected_duration)
            return chosen, f"closest result selected ({diff:.0f}s off)"
    if allow_closest:
        return candidates[0], "closest result selected"

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


def fetch_youtube_info(url: str) -> dict:
    ydl_opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
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


def youtube_common_options(output_dir: Path, overwrite: str) -> dict[str, object]:
    return {
        "outtmpl": youtube_output_template(output_dir),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "overwrites": overwrite == "force",
        "continuedl": overwrite != "force",
    }


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


def download_youtube_media(url: str, args: argparse.Namespace) -> DownloadResult:
    if STOP_EVENT.is_set():
        return DownloadResult(False, url, "cancelled")

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_location = find_ffmpeg_location()

    media_label = "video" if args.media == "video" else "audio"
    print(f"Downloading YouTube {media_label} to: {output_dir}", flush=True)

    ydl_opts = youtube_common_options(output_dir, args.overwrite)
    preferred_ext: str | None

    if args.media == "video":
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
                        "preferredcodec": args.fmt,
                        "preferredquality": normalized_audio_quality(args.bitrate),
                    }
                ],
            }
        )
        preferred_ext = args.fmt

    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = first_youtube_info(ydl.extract_info(url, download=True))
            return DownloadResult(True, youtube_label(info), downloaded_file_detail(info, ydl, preferred_ext))
    except Exception as exc:
        return DownloadResult(False, url, str(exc).strip()[:700])


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


def download_track(
    track: Track,
    output_dir: Path,
    pos: int | None,
    total: int,
    ffmpeg_location: str | None,
    bitrate: str,
    fmt: str,
    overwrite: str,
    fallback_cover_url: str | None,
    manifest_done: dict[str, Path],
    track_number_prefix: bool,
    allow_closest_match: bool,
) -> DownloadResult:
    if STOP_EVENT.is_set():
        return DownloadResult(False, f"{track.artists} - {track.name}", "cancelled")

    key = track_key(track, pos)
    label = f"{track.artists} - {track.name}"
    if key in manifest_done and overwrite == "skip":
        return DownloadResult(True, label, f"resume skip: {manifest_done[key].name}", str(manifest_done[key]), True)

    width = max(2, len(str(total)))
    prefix = f"{pos:0{width}d}. " if track_number_prefix and pos is not None and total > 1 else ""
    stem = safe(f"{prefix}{track.name} - {track.artists}")
    label = f"{track.artists} - {track.name}"

    existing = existing_output(output_dir, stem, fmt)
    if existing and overwrite == "skip":
        append_manifest(output_dir, key, existing)
        return DownloadResult(True, label, f"skip exists: {existing.name}", str(existing), True)
    if existing and overwrite == "metadata":
        tag(existing, enriched_track(track, fallback_cover_url), pos)
        append_manifest(output_dir, key, existing)
        return DownloadResult(True, label, f"metadata refreshed: {existing.name}", str(existing), True)
    if existing and overwrite == "force":
        existing.unlink(missing_ok=True)

    working_track = enriched_track(track, fallback_cover_url)

    try:
        candidates = youtube_candidates(working_track)
        chosen, reason = choose_youtube_candidate(candidates, working_track, allow_closest_match)
    except Exception as exc:
        LOG.warning("youtube search failed for %s: %s", label, exc)
        return DownloadResult(False, label, f"YouTube search failed: {str(exc).strip()[:700]}")

    if not chosen:
        LOG.info("youtube match rejected for %s: %s", label, reason)
        return DownloadResult(False, label, reason)

    video_url = candidate_url(chosen)
    if not video_url:
        return DownloadResult(False, label, "YouTube result did not include a playable URL")

    LOG.info("selected %s for %s (%s)", chosen.get("id"), label, reason)
    reserved_stem = reserve_output_stem(output_dir, stem, fmt, working_track.spotify_id)
    ydl_opts: dict[str, object] = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / f"{reserved_stem}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
                "preferredquality": normalized_audio_quality(bitrate),
            }
        ],
    }
    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location

    attempts = [
        ("default", ydl_opts),
        (
            "alternate YouTube clients",
            {
                **ydl_opts,
                "extractor_args": {
                    "youtube": {"player_client": ["android", "ios", "tv", "web_safari"]}
                },
            },
        ),
    ]
    error_detail = ""
    for attempt_label, options in attempts:
        try:
            with YoutubeDL(options) as ydl:
                ydl.download([video_url])
            final = existing_output(output_dir, reserved_stem, fmt)
            if final:
                tag(final, working_track, pos)
                append_manifest(output_dir, key, final)
                detail = final.name if attempt_label == "default" else f"{final.name} via {attempt_label}"
                release_output_stem(output_dir, reserved_stem, fmt)
                return DownloadResult(True, label, detail, str(final))
            error_detail = f"{attempt_label} produced no output file"
        except Exception as exc:
            error_detail = str(exc).strip()
            LOG.warning("%s download failed for %s: %s", attempt_label, label, error_detail[:300])

    release_output_stem(output_dir, reserved_stem, fmt)
    return DownloadResult(False, label, (error_detail or "yt-dlp did not produce an output file")[:700])


def print_track_list(collection: SpotifyCollection) -> None:
    print(f"Found {len(collection.tracks)} track(s) in \"{collection.name}\"", flush=True)
    for index, track in enumerate(collection.tracks, 1):
        seconds = f" ({track.duration_ms // 1000}s)" if track.duration_ms else ""
        print(f"  {index:3d}. {track.artists} - {track.name}{seconds}", flush=True)


def download_collection(collection: SpotifyCollection, args: argparse.Namespace) -> tuple[int, int]:
    output_dir = Path(args.output_dir).expanduser()
    if collection.use_subfolder:
        output_dir = output_dir / safe(collection.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_tracks = [
        (index, track)
        for index, track in enumerate(collection.tracks, 1)
        if index >= args.start
    ]
    if not selected_tracks:
        return 0, 0

    ffmpeg_location = find_ffmpeg_location()
    manifest_done = load_manifest(output_dir)
    print(f"Downloading to: {output_dir}", flush=True)
    print(f"Using {max(1, args.threads)} worker(s)", flush=True)
    if manifest_done and args.overwrite == "skip":
        print(f"Resume manifest: {len(manifest_done)} completed track(s)", flush=True)

    ok = 0
    failed: list[str] = []

    if args.threads <= 1:
        for index, track in selected_tracks:
            print(f"  [{index}/{len(collection.tracks)}] {track.artists} - {track.name}", flush=True)
            result = download_track(
                track,
                output_dir,
                index if collection.use_subfolder else None,
                len(collection.tracks),
                ffmpeg_location,
                args.bitrate,
                args.fmt,
                args.overwrite,
                collection.cover_url,
                manifest_done,
                args.track_number_prefix,
                args.allow_closest_match,
            )
            if result.ok:
                ok += 1
                print(f"       Done: {result.detail}", flush=True)
            else:
                failed.append(f"{index}. {result.label}: {result.detail}")
                print(f"       Failed: {result.detail}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.threads)) as executor:
            futures = {}
            for index, track in selected_tracks:
                print(f"  [{index}/{len(collection.tracks)}] queued {track.artists} - {track.name}", flush=True)
                future = executor.submit(
                    download_track,
                    track,
                    output_dir,
                    index if collection.use_subfolder else None,
                    len(collection.tracks),
                    ffmpeg_location,
                    args.bitrate,
                    args.fmt,
                    args.overwrite,
                    collection.cover_url,
                    manifest_done,
                    args.track_number_prefix,
                    args.allow_closest_match,
                )
                futures[future] = (index, track)

            for future in as_completed(futures):
                index, track = futures[future]
                result = future.result()
                if result.ok:
                    ok += 1
                    print(f"  [{index}/{len(collection.tracks)}] Done: {result.label} ({result.detail})", flush=True)
                else:
                    failed.append(f"{index}. {result.label}: {result.detail}")
                    print(f"  [{index}/{len(collection.tracks)}] Failed: {result.label}", flush=True)

    fail_count = len(failed)
    print(f"Downloaded: {ok}/{len(selected_tracks)}", flush=True)
    if failed:
        print(f"Failed ({fail_count}):", flush=True)
        for item in failed:
            print(f"  {item}", flush=True)

    return ok, fail_count


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
        return 1

    from yt_dlp.version import __version__ as yt_dlp_version

    version = yt_dlp_version
    print(f"yt-dlp {version}; ffmpeg ready", flush=True)
    if not HAS_MUTAGEN:
        print("Warning: mutagen is missing, so MP3 tags will not be written.", flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Spotify audio and YouTube audio/video with yt-dlp."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check yt-dlp and ffmpeg dependencies.")

    download = subparsers.add_parser("download", help="Download Spotify or YouTube URLs.")
    download.add_argument("urls", nargs="+", help="Spotify track/playlist/album URLs or YouTube video URLs.")
    download.add_argument("-o", "--output-dir", default="downloads", help="Base download folder.")
    download.add_argument(
        "--media",
        choices=("audio", "video"),
        default="audio",
        help="Download audio, or full videos for direct YouTube URLs.",
    )
    download.add_argument(
        "-f",
        "--format",
        default="mp3",
        dest="fmt",
        choices=("mp3", "m4a", "flac", "opus", "ogg", "wav"),
        help="Audio output format.",
    )
    download.add_argument("-b", "--bitrate", default="192k", help="Audio quality, e.g. 192k, 320k, 0.")
    download.add_argument("--threads", type=int, default=4, help="Parallel downloads per playlist.")
    download.add_argument(
        "--overwrite",
        choices=("skip", "metadata", "force"),
        default="skip",
        help="How to handle files that already exist.",
    )
    download.add_argument(
        "--track-number-prefix",
        dest="track_number_prefix",
        action="store_true",
        default=True,
        help="Prefix playlist and album files with their track number.",
    )
    download.add_argument(
        "--no-track-number-prefix",
        dest="track_number_prefix",
        action="store_false",
        help="Do not prefix playlist and album files with their track number.",
    )
    download.add_argument(
        "--allow-closest-match",
        action="store_true",
        help="If no title/artist match is found, use the closest duration match.",
    )
    download.add_argument(
        "--debug-log",
        action="store_true",
        help="Write verbose diagnostics to the rotating log file.",
    )
    download.add_argument("--start", type=int, default=1, help="Start from track N in playlists.")
    download.add_argument("--dry-run", action="store_true", help="List tracks without downloading.")
    return parser.parse_args()


def main() -> int:
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    args = parse_args()
    log_path = setup_logging(getattr(args, "debug_log", False))
    if args.command == "doctor":
        print(f"Logs: {log_path.parent}", flush=True)
        return doctor()

    total_failures = 0
    for url in args.urls:
        if is_spotify_url(url):
            if args.media == "video":
                print("Spotify links can only be downloaded as audio.", file=sys.stderr, flush=True)
                total_failures += 1
                continue

            print(f"Fetching Spotify metadata: {url}", flush=True)
            try:
                collection = fetch_spotify(url)
            except Exception as exc:
                print(f"Failed to fetch Spotify metadata: {exc}", file=sys.stderr, flush=True)
                total_failures += 1
                continue

            print_track_list(collection)
            if args.dry_run:
                continue

            try:
                _, failures = download_collection(collection, args)
            except KeyboardInterrupt:
                print("Cancelled.", flush=True)
                return 130
            total_failures += failures
            continue

        if is_youtube_url(url):
            print(f"Fetching YouTube metadata: {url}", flush=True)
            try:
                youtube_info = fetch_youtube_info(url)
            except Exception as exc:
                print(f"Failed to fetch YouTube metadata: {exc}", file=sys.stderr, flush=True)
                total_failures += 1
                continue

            print_youtube_info(youtube_info, args.media)
            if args.dry_run:
                continue

            try:
                result = download_youtube_media(url, args)
            except KeyboardInterrupt:
                print("Cancelled.", flush=True)
                return 130

            if result.ok:
                print(f"Done: {result.label} ({result.detail})", flush=True)
            else:
                total_failures += 1
                print(f"Failed: {result.detail}", flush=True)
            continue

        expected = "Spotify or YouTube URL" if args.media == "audio" else "YouTube URL"
        print(f"Unsupported URL, expected a {expected}: {url}", file=sys.stderr, flush=True)
        total_failures += 1
        continue

    return 1 if total_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

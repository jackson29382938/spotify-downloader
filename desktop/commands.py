"""Validated argument construction; user text never passes through a shell."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import re


def parse_urls(text: str, media: str = "audio") -> list[str]:
    urls = list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))
    if not urls:
        raise ValueError("Paste at least one Spotify or YouTube link, one per line.")
    for url in urls:
        spotify = bool(re.fullmatch(
            r"(?:https?://open\.spotify\.com/(?:intl-[a-z]{2,}(?:-[a-z]{2,})?/)?"
            r"(?:track|album|playlist)/|spotify:(?:track|album|playlist):)"
            r"[A-Za-z0-9]+(?:[/?#]\S*)?", url))
        parsed = urlparse(url)
        youtube = parsed.scheme in {"https", "http"} and parsed.netloc.lower() in {
            "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
            "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
        }
        if not (spotify or youtube):
            raise ValueError(f"Unsupported link: {url}")
        if media == "video" and spotify:
            raise ValueError("Spotify links support audio only. Choose Audio or use a YouTube link.")
    return urls


@dataclass(frozen=True)
class DownloadOptions:
    output: str
    media: str = "audio"
    fmt: str = "mp3"
    bitrate: str = "192k"
    threads: int = 4
    retries: int = 2
    overwrite: str = "skip"
    lyrics: bool = True
    cookies: str = ""

    def arguments(self, urls: list[str], preview: bool = False) -> list[str]:
        parse_urls("\n".join(urls), self.media)
        if not self.output.strip():
            raise ValueError("Choose an output folder.")
        if self.media not in {"audio", "video"} or self.fmt not in {"mp3", "m4a", "flac", "opus", "ogg", "wav"}:
            raise ValueError("Invalid media or audio format.")
        if self.bitrate not in {"128k", "192k", "256k", "320k", "0"}:
            raise ValueError("Invalid audio quality.")
        if not 1 <= self.threads <= 16 or not 0 <= self.retries <= 5:
            raise ValueError("Invalid worker or retry count.")
        if self.overwrite not in {"skip", "metadata", "force"}:
            raise ValueError("Invalid existing-file behavior.")
        if self.cookies not in {"", "chrome", "firefox", "chromium", "edge", "opera", "brave", "safari"}:
            raise ValueError("Invalid browser cookie setting.")
        output = str(Path(self.output).expanduser().absolute())
        args = ["preview" if preview else "download", "--media", self.media, "--output-dir", output]
        if preview:
            args += ["--json"]
        else:
            args += ["--json-events", "--format", self.fmt, "--bitrate", self.bitrate,
                     "--threads", str(self.threads), "--retries", str(self.retries), "--overwrite", self.overwrite]
            if not self.lyrics:
                args.append("--no-lyrics")
            if self.cookies:
                args += ["--cookies-browser", self.cookies]
        return args + ["--"] + urls

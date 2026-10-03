"""Real download/conversion/tagging with generated media, without external services."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import math
from pathlib import Path
import struct
import threading
from unittest.mock import patch
import wave

from mutagen.mp3 import MP3
import spotify_dl as dl


def test_generated_media_download_conversion_tags_and_resume(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with wave.open(str(source / "tone.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b"".join(struct.pack("<h", int(10000 * math.sin(2 * math.pi * 440 * n / 22050)))
                                   for n in range(22050)))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(source)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "output"
    output.mkdir()
    url = f"http://127.0.0.1:{server.server_port}/tone.wav"
    candidate = {"id": "generated", "title": "Generated tone", "duration": 1, "webpage_url": url}
    track = dl.Track(name="Generated tone", artists="Test fixture", album="Owned synthetic audio", duration_ms=1000)
    options = dl.RunOptions(lyrics=False, retries=0, json_events=True, ffmpeg_location=dl.find_ffmpeg_location())
    try:
        with patch.object(dl, "find_youtube_candidate", return_value=(candidate, "controlled fixture")), \
             patch.object(dl, "YOUTUBE_GATE", dl.YouTubeGate(min_spacing=0)), \
             patch.object(dl, "emit_json_event") as events:
            dl.STOP_EVENT.clear()
            result = dl.download_track(track, output, None, 1, options, None, {})
            assert result.ok, result.detail
            path = Path(result.path)
            media = MP3(path)
            assert 0.9 <= media.info.length <= 1.5
            assert media.tags["TIT2"].text == ["Generated tone"]
            assert media.tags["TPE1"].text == ["Test fixture"]
            assert media.tags["TALB"].text == ["Owned synthetic audio"]
            selected = [call for call in events.call_args_list if call.args[1] == "match_selected"]
            assert selected[0].kwargs["candidate_url"] == url
            assert selected[0].kwargs["reason"] == "controlled fixture"
            original = path.read_bytes()
            resumed = dl.download_track(track, output, None, 1, options, None, {})
            assert resumed.ok and resumed.skipped
            assert path.read_bytes() == original
            assert (output / dl.MANIFEST_FILENAME).exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

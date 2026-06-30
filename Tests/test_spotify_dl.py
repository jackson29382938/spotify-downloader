import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import spotify_dl as dl


class SpotifyParsingTests(unittest.TestCase):
    def test_parse_spotify_url_supports_locale_urls_and_uris(self):
        self.assertEqual(
            dl.parse_spotify_url("https://open.spotify.com/intl-de/album/abc123?si=xyz"),
            ("album", "abc123"),
        )
        self.assertEqual(dl.parse_spotify_url("spotify:playlist:def456"), ("playlist", "def456"))

    def test_extract_spotify_entity_accepts_alternate_page_props_path(self):
        data = {"props": {"pageProps": {"data": {"entity": {"name": "Alternate"}}}}}
        self.assertEqual(dl.extract_spotify_entity(data)["name"], "Alternate")

    def test_extract_spotify_entity_uses_recursive_fallback(self):
        data = {"props": {"pageProps": {"experiment": {"nested": {"trackList": []}}}}}
        self.assertIn("trackList", dl.extract_spotify_entity(data))

    def test_extract_spotify_entity_skips_unrelated_type_keys(self):
        data = {
            "props": {
                "pageProps": {
                    "shell": {"type": "experiment"},
                    "nested": {"entity": {"type": "track", "name": "Song"}},
                }
            }
        }
        self.assertEqual(dl.extract_spotify_entity(data)["name"], "Song")

    def test_best_image_ignores_malformed_entries(self):
        entity = {
            "visualIdentity": {"image": [None, {"url": "small", "maxWidth": 64}]},
            "coverArt": {"sources": [{"url": "large", "width": 640}]},
        }
        self.assertEqual(dl.best_image(entity), "large")

    def test_album_from_social_preview_handles_attribute_order_and_entities(self):
        html = '<meta content="Artist &amp; Friend · Album Name · Song · 2026" property="og:description">'
        self.assertEqual(dl.parse_track_album_from_page(html), "Album Name")

    def test_playlist_tracks_do_not_fallback_to_playlist_cover(self):
        entity = {
            "title": "Playlist",
            "visualIdentity": {"image": [{"url": "https://example.com/playlist.jpg", "maxWidth": 640}]},
            "trackList": [
                {
                    "entityType": "track",
                    "title": "Song",
                    "artists": [{"name": "Artist"}],
                    "uri": "spotify:track:abc123",
                }
            ],
        }
        with patch.object(dl, "fetch_embed_page", return_value=(entity, None)):
            collection = dl.fetch_spotify("https://open.spotify.com/playlist/pl123")

        self.assertEqual(collection.cover_url, "https://example.com/playlist.jpg")
        self.assertIsNone(collection.track_cover_fallback_url)
        self.assertIsNone(collection.tracks[0].cover_url)

    def test_album_tracks_can_use_album_cover_as_track_artwork(self):
        entity = {
            "title": "Album",
            "coverArt": {"sources": [{"url": "https://example.com/album.jpg", "width": 640}]},
            "trackList": [
                {
                    "entityType": "track",
                    "title": "Song",
                    "artists": [{"name": "Artist"}],
                    "uri": "spotify:track:abc123",
                }
            ],
        }
        with patch.object(dl, "fetch_embed_page", return_value=(entity, None)):
            collection = dl.fetch_spotify("https://open.spotify.com/album/al123")

        self.assertEqual(collection.track_cover_fallback_url, "https://example.com/album.jpg")
        self.assertEqual(collection.tracks[0].cover_url, "https://example.com/album.jpg")


class YoutubeMatchingTests(unittest.TestCase):
    def test_rejects_title_match_with_wrong_artist_by_default(self):
        track = dl.Track(name="Mi Gente", artists="DJ Goja", duration_ms=115_000)
        candidates = [
            {
                "id": "wrong",
                "title": "SkywiinPROD - Mi Gente Remix",
                "duration": 115,
                "uploader": "Other Channel",
            }
        ]

        chosen, reason = dl.choose_youtube_candidate(candidates, track, allow_closest=False)

        self.assertIsNone(chosen)
        self.assertIn("artist", reason)

    def test_accepts_artist_from_uploader_or_channel(self):
        track = dl.Track(name="Mi Gente", artists="DJ Goja", duration_ms=115_000)
        candidates = [
            {
                "id": "right",
                "title": "Mi Gente",
                "duration": 116,
                "uploader": "DJ Goja - Topic",
            }
        ]

        chosen, reason = dl.choose_youtube_candidate(candidates, track, allow_closest=False)

        self.assertEqual(chosen["id"], "right")
        self.assertIn("matched", reason)

    def test_closest_match_can_opt_into_artist_mismatch(self):
        track = dl.Track(name="Mi Gente", artists="DJ Goja", duration_ms=115_000)
        candidates = [
            {
                "id": "fallback",
                "title": "Mi Gente",
                "duration": 115,
                "uploader": "Unrelated",
            }
        ]

        chosen, reason = dl.choose_youtube_candidate(candidates, track, allow_closest=True)

        self.assertEqual(chosen["id"], "fallback")
        self.assertIn("artist unmatched", reason)

    def test_exact_title_and_close_duration_can_pass_when_artist_unavailable(self):
        track = dl.Track(name="I Don't Know - Sped Up", artists="Veylow", duration_ms=176_000)
        candidates = [
            {
                "id": "extra",
                "title": "erika - I don’t know (sped up + bitcrushed)",
                "duration": 165,
                "uploader": "konnektom",
            },
            {
                "id": "right",
                "title": "erika - I don’t know ( sped up )",
                "duration": 175,
                "uploader": "Stay ok",
            },
            {
                "id": "wrong-variant",
                "title": "erika - I don’t know ( Nightcore )",
                "duration": 176,
                "uploader": "NAOMI",
            },
        ]

        chosen, reason = dl.choose_youtube_candidate(candidates, track, allow_closest=False)

        self.assertEqual(chosen["id"], "right")
        self.assertIn("artist unavailable", reason)


class LyricsTests(unittest.TestCase):
    def setUp(self):
        with dl.LYRICS_CACHE_LOCK:
            dl.LYRICS_CACHE.clear()

    def test_lrc_timestamps_are_stripped_for_plain_metadata(self):
        synced = "[00:01.00]First line\n[00:02.50][00:03.00]Second line"
        self.assertEqual(dl.strip_lrc_timestamps(synced), "First line\nSecond line")

    def test_lyrics_from_record_prefers_plain_lyrics(self):
        record = {
            "plainLyrics": "Plain words",
            "syncedLyrics": "[00:01.00]Timed words",
        }
        self.assertEqual(dl.lyrics_from_record(record), "Plain words")

    def test_fetch_lyrics_uses_exact_lookup(self):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {"plainLyrics": "Found lyrics"}

        track = dl.Track(name="Song", artists="Artist", album="Album", duration_ms=123_000)
        with patch.object(dl.req, "get", return_value=FakeResponse()) as get:
            self.assertEqual(dl.fetch_lyrics(track), "Found lyrics")

        params = get.call_args.kwargs["params"]
        self.assertEqual(params["track_name"], "Song")
        self.assertEqual(params["artist_name"], "Artist")
        self.assertEqual(params["album_name"], "Album")
        self.assertEqual(params["duration"], "123")


class LibraryRepairTests(unittest.TestCase):
    def test_filename_pairs_support_app_and_common_orders(self):
        pairs = dl.filename_title_artist_pairs(Path("01. Song Name - Artist Name.mp3"))
        self.assertEqual(pairs[0], ("Song Name", "Artist Name"))
        self.assertEqual(pairs[1], ("Artist Name", "Song Name"))

    def test_identify_library_metadata_selects_confident_candidate(self):
        guess = dl.LibraryTrackGuess(
            path=Path("Song - Artist.mp3"),
            title="Song",
            artist="Artist",
            duration_ms=180_000,
            from_filename=True,
        )
        candidate = dl.LibraryMetadata(
            title="Song",
            artist="Artist",
            album="Album",
            genre="Pop",
            duration_ms=181_000,
            source="Apple Music",
            confidence=0,
        )
        with (
            patch.object(dl, "itunes_search_candidates", return_value=[candidate]),
            patch.object(dl, "musicbrainz_search_candidates", return_value=[]),
        ):
            match = dl.identify_library_metadata(guess)

        self.assertIsNotNone(match)
        self.assertEqual(match.title, "Song")
        self.assertGreater(match.confidence, 0.9)

    def test_low_confidence_library_match_is_rejected(self):
        guess = dl.LibraryTrackGuess(
            path=Path("Song - Artist.mp3"),
            title="Song",
            artist="Artist",
            duration_ms=180_000,
        )
        candidate = dl.LibraryMetadata(
            title="Different",
            artist="Someone Else",
            duration_ms=220_000,
            source="Apple Music",
        )
        with (
            patch.object(dl, "itunes_search_candidates", return_value=[candidate]),
            patch.object(dl, "musicbrainz_search_candidates", return_value=[]),
        ):
            self.assertIsNone(dl.identify_library_metadata(guess))


class ResumeMetadataTests(unittest.TestCase):
    def test_manifest_spotify_ids_only_returns_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "done.mp3").write_bytes(b"x")
            (folder / dl.MANIFEST_FILENAME).write_text(
                "\n".join(
                    [
                        json.dumps({"key": "spotify:done", "file": "done.mp3"}),
                        json.dumps({"key": "spotify:missing", "file": "missing.mp3"}),
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(dl.manifest_spotify_ids(folder), {"done"})

    def test_complete_playlist_tracks_skips_metadata_for_manifested_ids(self):
        fetched: list[str] = []

        def fake_fetch_track_by_id(spotify_id: str) -> dl.Track:
            fetched.append(spotify_id)
            return dl.Track(name=f"Track {spotify_id}", artists="Artist", spotify_id=spotify_id)

        with (
            patch.object(dl, "fetch_spclient_track_ids", return_value=["id1", "id2", "id3"]),
            patch.object(dl, "fetch_track_by_id", side_effect=fake_fetch_track_by_id),
        ):
            tracks = dl.complete_playlist_tracks(
                "playlist",
                "token",
                [dl.Track(name="Track id1", artists="Artist", spotify_id="id1")],
                skip_ids={"id2"},
            )

        self.assertEqual(fetched, ["id3"])
        self.assertEqual([track.spotify_id for track in tracks], ["id1", "id3"])


class TieredSearchTests(unittest.TestCase):
    def test_ytmusic_search_is_tried_first(self):
        track = dl.Track(name="Song", artists="Artist")
        queries = dl.youtube_search_queries(track, limit=5)
        self.assertTrue(queries[0].startswith("ytmsearch5:"))
        self.assertTrue(queries[1].startswith("ytsearch5:"))

    def test_ytmusic_fallback_to_ytsearch(self):
        track = dl.Track(name="Song", artists="Artist")
        candidate = {"id": "abc", "title": "Artist - Song"}
        with patch.object(
            dl,
            "youtube_candidates_for_query",
            side_effect=[[], [candidate]],
        ) as search:
            results = dl.gather_youtube_candidates(track)

        self.assertEqual(results, [candidate])
        self.assertEqual(search.call_count, 2)


class FFmpegInstallTests(unittest.TestCase):
    def test_ffmpeg_install_command_exists(self):
        import argparse

        parser = dl.create_parser()
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        self.assertIn("ffmpeg-install", subparsers.choices)


class SidecarAndRenameTests(unittest.TestCase):
    def setUp(self):
        with dl.LYRICS_CACHE_LOCK:
            dl.LYRICS_CACHE.clear()

    def test_lrc_sidecar_written_on_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "song.mp3"
            audio.write_bytes(b"audio")
            track = dl.Track(name="Song", artists="Artist", duration_ms=123_000)
            options = dl.RunOptions(lyrics=True, write_lrc=True)
            record = {"plainLyrics": "Plain", "syncedLyrics": "[00:01.00]Synced line"}
            with patch.object(dl, "_lyrics_record", return_value=record):
                plain = dl.apply_track_lyrics(audio, track, options)

            self.assertEqual(plain, "Plain")
            sidecar = audio.with_suffix(".lrc")
            self.assertTrue(sidecar.exists())
            self.assertEqual(sidecar.read_text(encoding="utf-8"), "[00:01.00]Synced line")

    def test_library_rename_applies_pattern(self):
        metadata = dl.LibraryMetadata(
            title="Song",
            artist="Artist",
            album="Album",
            genre="Pop",
            year="2026",
            source="Apple Music",
        )
        stem = dl.render_rename_pattern("{track_number}. {title} - {artist}", metadata, track_number=3)
        self.assertEqual(stem, "03. Song - Artist")


class PreviewHealthHistoryTests(unittest.TestCase):
    def test_preview_sources_returns_spotify_collection_payload(self):
        collection = dl.SpotifyCollection(
            name="Playlist",
            tracks=[dl.Track(name="Song", artists="Artist", spotify_id="abc", duration_ms=123_000)],
            use_subfolder=True,
            cover_url="https://example.com/cover.jpg",
        )
        with patch.object(dl, "fetch_spotify", return_value=collection):
            items, errors = dl.preview_sources(
                ["https://open.spotify.com/playlist/abc"],
                media="audio",
                output_dir="/tmp/Music",
            )

        self.assertEqual(errors, [])
        self.assertEqual(items[0]["title"], "Playlist")
        self.assertEqual(items[0]["track_count"], 1)
        self.assertEqual(items[0]["tracks"][0]["title"], "Song")

    def test_health_diagnostics_reports_required_local_checks(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dl, "find_ffmpeg_location", return_value="/usr/local/bin/ffmpeg"),
        ):
            payload = dl.health_diagnostics(output_dir=tmp, probe_network=False)

        self.assertTrue(payload["ok"])
        check_names = {check["name"] for check in payload["checks"]}
        self.assertIn("yt-dlp", check_names)
        self.assertIn("ffmpeg", check_names)
        self.assertIn("output folder", check_names)

    def test_emit_json_event_writes_json_line_when_enabled(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            dl.emit_json_event(True, "sample", value=42)

        record = json.loads(output.getvalue())
        self.assertEqual(record["event"], "sample")
        self.assertEqual(record["value"], 42)
        self.assertIn("timestamp", record)

    def test_append_history_writes_jsonl_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "history.jsonl"
            with patch.object(dl, "history_path", return_value=target):
                dl.append_history({"source_url": "https://example.com", "ok_count": 1})

            lines = target.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["ok_count"], 1)


if __name__ == "__main__":
    unittest.main()

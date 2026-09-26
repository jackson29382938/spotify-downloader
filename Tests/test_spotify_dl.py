import contextlib
import io
import json
import tempfile
import unittest
from concurrent.futures import wait as real_wait
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

    def test_spotify_links_must_be_the_whole_input(self):
        self.assertTrue(dl.is_spotify_url("  https://open.spotify.com/track/abc123?si=xyz  "))
        self.assertTrue(dl.is_spotify_url("https://open.spotify.com/track/abc123/"))
        self.assertFalse(dl.is_spotify_url("see https://open.spotify.com/track/abc123"))
        self.assertFalse(dl.is_spotify_url("https://open.spotify.com/track/abc123 extra words"))
        self.assertFalse(dl.is_spotify_url("https://evil.example/?next=https://open.spotify.com/track/abc123"))
        with self.assertRaises(ValueError):
            dl.parse_spotify_url("prefix spotify:album:abc123")

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
    def test_strict_match_never_borrows_artist_from_another_result(self):
        track = dl.Track(name="Song", artists="Correct Artist", duration_ms=180_000)
        candidates = [
            {"id": "artist-only", "title": "Other Track", "uploader": "Correct Artist", "duration": 180},
            {"id": "wrong-artist", "title": "Song", "uploader": "Wrong Artist", "duration": 180},
        ]

        chosen, _ = dl.choose_youtube_candidate(candidates, track, allow_closest=False)

        self.assertIsNone(chosen)

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
    def test_title_alone_is_not_confident_enough_to_repair_metadata(self):
        guess = dl.LibraryTrackGuess(path=Path("Song.mp3"), title="Song", artist="")
        candidate = dl.LibraryMetadata(title="Song", artist="Wrong Artist", source="Apple Music")
        with (
            patch.object(dl, "itunes_search_candidates", return_value=[candidate]),
            patch.object(dl, "musicbrainz_search_candidates", return_value=[]),
        ):
            self.assertIsNone(dl.identify_library_metadata(guess))

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
    def test_duplicate_playlist_positions_have_distinct_manifest_keys(self):
        track = dl.Track(name="Song", artists="Artist", spotify_id="same")
        self.assertNotEqual(dl.track_key(track, 1), dl.track_key(track, 2))

    def test_corrupt_manifest_line_does_not_hide_later_completed_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "done.mp3").write_bytes(b"x")
            (folder / dl.MANIFEST_FILENAME).write_text(
                "not-json\n" + json.dumps({"key": "spotify:done:1", "file": "done.mp3"}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(dl.load_manifest(folder)["spotify:done:1"], folder / "done.mp3")

    def test_cached_manifest_tracks_only_returns_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "done.mp3").write_bytes(b"x")
            (folder / dl.MANIFEST_FILENAME).write_text(
                "\n".join(
                    [
                        json.dumps({"key": "spotify:done:1", "file": "done.mp3", "track": {"name": "Done", "artists": "Artist"}}),
                        json.dumps({"key": "spotify:missing:2", "file": "missing.mp3", "track": {"name": "Missing", "artists": "Artist"}}),
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(list(dl.load_manifest_tracks(folder, "mp3")), [("done", 1)])

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
                cached_tracks={("id2", 2): dl.Track(name="Track id2", artists="Artist", spotify_id="id2")},
            )

        self.assertEqual(fetched, ["id3"])
        self.assertEqual([track.spotify_id for track in tracks], ["id1", "id2", "id3"])

    def test_fetch_spotify_uses_completed_track_metadata_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "Playlist"
            folder.mkdir()
            (folder / "02. Done - Artist.mp3").write_bytes(b"audio")
            (folder / dl.MANIFEST_FILENAME).write_text(json.dumps({
                "key": "spotify:done:2",
                "file": "02. Done - Artist.mp3",
                "track": {"name": "Done", "artists": "Artist", "spotify_id": "done"},
            }) + "\n", encoding="utf-8")
            entity = {"title": "Playlist", "trackList": [
                {"title": "First", "artists": [{"name": "Artist"}], "uri": "spotify:track:first"},
            ]}
            with (
                patch.object(dl, "fetch_embed_page", return_value=(entity, "token")),
                patch.object(dl, "fetch_spclient_track_ids", return_value=["first", "done"]),
                patch.object(dl, "fetch_track_by_id") as fetch,
            ):
                collection = dl.fetch_spotify("https://open.spotify.com/playlist/abc", resume_output_root=tmp, resume_format="mp3")

            fetch.assert_not_called()
            self.assertEqual([track.name for track in collection.tracks], ["First", "Done"])


class TieredSearchTests(unittest.TestCase):
    def test_playlist_submits_bounded_work(self):
        collection = dl.SpotifyCollection(
            name="Many", use_subfolder=True,
            tracks=[dl.Track(name=f"Song {index}", artists="Artist") for index in range(30)],
        )
        peak_pending = 0

        def measure_pending(futures, **kwargs):
            nonlocal peak_pending
            peak_pending = max(peak_pending, len(futures))
            return real_wait(futures, **kwargs)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dl, "download_track", side_effect=lambda track, *_: dl.DownloadResult(True, track.name)),
            patch.object(dl, "wait", side_effect=measure_pending),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ok, failed, _, _, _ = dl.download_collection(collection, dl.RunOptions(), tmp, threads=4, start=1)

        self.assertEqual((ok, failed), (30, 0))
        self.assertLessEqual(peak_pending, 8)

    def test_failed_forced_replacement_keeps_existing_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "Song - Artist.mp3"
            original.write_bytes(b"original")
            with patch.object(dl, "youtube_candidates_for_query", return_value=[]):
                result = dl.download_track(
                    dl.Track(name="Song", artists="Artist"),
                    Path(tmp), None, 1,
                    dl.RunOptions(overwrite="force", retries=0, lyrics=False), None, {},
                )

            self.assertFalse(result.ok)
            self.assertEqual(original.read_bytes(), b"original")

    def test_successful_forced_replacement_reuses_original_path(self):
        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def download(self, urls):
                Path(self.options["outtmpl"].replace("%(ext)s", "mp3")).write_bytes(b"replacement")

        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "Song - Artist.mp3"
            original.write_bytes(b"original")
            candidate = {"id": "video", "title": "Artist - Song", "uploader": "Artist"}
            with (
                patch.object(dl, "youtube_candidates_for_query", return_value=[candidate]),
                patch.object(dl, "YoutubeDL", FakeYoutubeDL),
                patch.object(dl, "tag", return_value="metadata tagging failed: bad tags"),
            ):
                result = dl.download_track(
                    dl.Track(name="Song", artists="Artist"),
                    Path(tmp), None, 1,
                    dl.RunOptions(overwrite="force", retries=0, lyrics=False), None, {},
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.path, str(original))
            self.assertEqual(original.read_bytes(), b"replacement")
            self.assertFalse(result.created_this_run)
            self.assertIn("metadata tagging failed", result.detail)
            self.assertEqual(result.warning, "metadata tagging failed: bad tags")

    def test_plain_search_is_tried_first_and_ytmusic_stays_a_fallback(self):
        track = dl.Track(name="Song - 2015 Remaster", artists="Artist, Guest")
        queries = dl.youtube_search_queries(track, limit=5)
        self.assertEqual(queries[0], "ytsearch5:Artist, Guest - Song")
        ytmusic = [query for query in queries if query.startswith("https://music.youtube.com/search?")]
        self.assertEqual(len(ytmusic), 1)
        self.assertIn("Artist+-+Song", ytmusic[0])
        self.assertNotIn("#songs", ytmusic[0])

    def test_search_is_flat_so_results_do_not_load_video_pages(self):
        options = dl.youtube_search_options()
        self.assertEqual(options["extract_flat"], "in_playlist")
        self.assertTrue(options["ignoreerrors"])

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

    def test_failed_search_tier_does_not_abort_fallbacks(self):
        track = dl.Track(name="Song", artists="Artist")
        candidate = {"id": "abc", "title": "Artist - Song", "uploader": "Artist"}
        with patch.object(
            dl,
            "youtube_candidates_for_query",
            side_effect=[RuntimeError("unsupported search"), [candidate]],
        ) as search:
            chosen, reason = dl.find_youtube_candidate(track)

        self.assertEqual(chosen, candidate)
        self.assertIn("matched", reason)
        self.assertEqual(search.call_count, 2)

    def test_retry_attempts_change_clients_and_audio_format(self):
        base = {"format": "bestaudio/best", "quiet": True}
        initial = dl.youtube_attempt_options(base, attempt=0, audio=True)
        retry = dl.youtube_attempt_options(base, attempt=1, audio=True)

        self.assertNotIn("extractor_args", initial)
        self.assertIn("extractor_args", retry)
        self.assertNotEqual(initial["format"], retry["format"])

    def test_retry_clients_never_need_po_tokens(self):
        token_clients = {"android", "ios", "mweb", "web_safari", "android_vr", "web", "web_music"}
        for _, clients, _ in dl.YOUTUBE_DOWNLOAD_STRATEGIES:
            self.assertFalse(token_clients & set(clients or []), clients)
        self.assertEqual(len(dl.YOUTUBE_RETRY_METHODS), 6)

    def test_js_runtimes_are_passed_to_yt_dlp_when_found(self):
        runtimes = {"node": {"path": "/opt/homebrew/bin/node"}}
        with patch.object(dl, "find_js_runtimes", return_value=runtimes):
            options = dl.youtube_attempt_options({"quiet": True}, attempt=0, audio=True)
        self.assertEqual(options["js_runtimes"], runtimes)

    def test_friendly_errors_explain_bot_checks_and_403s(self):
        bot = "ERROR: [youtube] ZxgMGk9JPVA: Sign in to confirm you\u2019re not a bot. Use --cookies-from-browser"
        self.assertIn("Browser cookies", dl.friendly_error(bot))
        forbidden = "ERROR: unable to download video data: HTTP Error 403: Forbidden"
        with patch.object(dl, "find_js_runtimes", return_value={}):
            self.assertIn("brew install deno", dl.friendly_error(forbidden))
        self.assertEqual(dl.friendly_error("something else"), "something else")

    def test_download_retries_default_to_two_and_are_customizable(self):
        default_args = dl.parse_args(["download", "https://youtu.be/example"])
        custom_args = dl.parse_args(["download", "--retries", "4", "https://youtu.be/example"])

        self.assertEqual(dl.RunOptions.from_args(default_args).retries, 2)
        self.assertEqual(dl.RunOptions.from_args(custom_args).retries, 4)

    def _fake_youtube_dl(self, used_options, failures):
        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options
                used_options.append(options)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def download(self, urls):
                if failures:
                    raise RuntimeError(failures.pop(0))
                output = Path(str(self.options["outtmpl"]).replace("%(ext)s", "mp3"))
                output.write_bytes(b"audio")

        return FakeYoutubeDL

    def _download(self, track, retries, search_results, failures):
        used_options = []
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dl, "youtube_candidates_for_query", side_effect=search_results) as search,
            patch.object(dl, "YoutubeDL", self._fake_youtube_dl(used_options, failures)),
            patch.object(dl, "apply_track_lyrics", return_value=None),
            patch.object(dl, "tag", return_value=None),
            patch.object(dl.STOP_EVENT, "wait", return_value=False),
        ):
            result = dl.download_track(
                track,
                Path(tmp),
                None,
                1,
                dl.RunOptions(retries=retries, lyrics=False),
                None,
                {},
            )
        return result, search, used_options

    def test_track_search_tries_every_route_before_downloading(self):
        track = dl.Track(name="Song", artists="Artist", duration_ms=120_000)
        candidate = {"id": "abc", "title": "Artist - Song", "uploader": "Artist", "duration": 120}

        result, search, used_options = self._download(track, 0, [[], [candidate]], [])

        self.assertTrue(result.ok)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(len(used_options), 1)
        self.assertNotIn("extractor_args", used_options[0])

    def test_forbidden_download_retries_same_video_with_other_clients(self):
        track = dl.Track(name="Song", artists="Artist", duration_ms=120_000)
        candidate = {"id": "abc", "title": "Artist - Song", "uploader": "Artist", "duration": 120}

        result, search, used_options = self._download(
            track, 1, [[candidate]], ["unable to download video data: HTTP Error 403: Forbidden"]
        )

        self.assertTrue(result.ok)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(len(used_options), 2)
        self.assertIn("extractor_args", used_options[1])
        self.assertIn("TV client", result.detail)

    def test_unavailable_video_is_replaced_by_the_next_match(self):
        track = dl.Track(name="Song", artists="Artist", duration_ms=120_000)
        first = {"id": "gone", "title": "Artist - Song", "uploader": "Artist", "duration": 120}
        second = {"id": "good", "title": "Artist - Song (Audio)", "uploader": "Artist", "duration": 121}

        result, search, used_options = self._download(
            track, 1, [[first, second], [first, second]], ["ERROR: [youtube] gone: Video unavailable"]
        )

        self.assertTrue(result.ok)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(len(used_options), 2)

    def test_no_confident_match_does_not_repeat_every_search(self):
        track = dl.Track(name="Song", artists="Artist", duration_ms=120_000)
        wrong = {"id": "x", "title": "Other Band - Other Song", "uploader": "Other", "duration": 120}
        routes = len(dl.youtube_search_queries(track))

        result, search, used_options = self._download(track, 2, [[wrong]] * routes, [])

        self.assertFalse(result.ok)
        self.assertEqual(search.call_count, routes)
        self.assertEqual(used_options, [])
        self.assertIn("no confident", result.detail)


class FFmpegInstallTests(unittest.TestCase):
    def test_installer_uses_homebrew_and_checks_the_result(self):
        class FakeProcess:
            stdout = io.StringIO("Installed ffmpeg\n")

            def wait(self):
                return 0

        with (
            patch.object(dl.sys, "platform", "darwin"),
            patch.object(dl.shutil, "which", side_effect=lambda name: f"/opt/homebrew/bin/{name}"),
            patch.object(dl.subprocess, "Popen", return_value=FakeProcess()) as install,
            patch.object(dl.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()) as check,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(dl.install_ffmpeg(), 0)

        self.assertEqual(install.call_args.args[0], ["/opt/homebrew/bin/brew", "install", "ffmpeg"])
        self.assertEqual(check.call_args.args[0], ["/opt/homebrew/bin/ffmpeg", "-version"])

    def test_installer_refuses_unverified_download_when_homebrew_is_missing(self):
        with (
            patch.object(dl.sys, "platform", "darwin"),
            patch.object(dl.shutil, "which", return_value=None),
            patch.object(dl.req, "get") as download,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(dl.install_ffmpeg(), 1)
        download.assert_not_called()

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
    def test_tagging_failure_is_returned_to_the_download_flow(self):
        with (
            patch.object(dl, "HAS_MUTAGEN", True),
            patch.object(dl, "cover_bytes", return_value=None),
            patch.object(dl, "write_mp3_tags", side_effect=ValueError("bad tags")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            warning = dl.tag(Path("Song.mp3"), dl.Track(name="Song", artists="Artist"), None)

        self.assertIn("bad tags", warning)

    def setUp(self):
        with dl.LYRICS_CACHE_LOCK:
            dl.LYRICS_CACHE.clear()

    def test_lrc_sidecar_written_only_when_requested(self):
        record = {"plainLyrics": "Plain", "syncedLyrics": "[00:01.00]Synced line"}
        track = dl.Track(name="Song", artists="Artist", duration_ms=123_000)
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "song.mp3"
            audio.write_bytes(b"audio")
            with patch.object(dl, "_lyrics_record", return_value=record):
                default_lyrics = dl.apply_track_lyrics(audio, track, dl.RunOptions(lyrics=True))
            self.assertFalse(audio.with_suffix(".lrc").exists())
            self.assertEqual(default_lyrics.plain, "Plain")
            self.assertEqual(default_lyrics.synced, "[00:01.00]Synced line")

            with patch.object(dl, "_lyrics_record", return_value=record):
                dl.apply_track_lyrics(audio, track, dl.RunOptions(lyrics=True, write_lrc=True))
            sidecar = audio.with_suffix(".lrc")
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
    def test_large_playlist_preview_emits_only_json_on_stdout(self):
        entity = {
            "title": "Playlist",
            "trackList": [{"title": "One", "artists": [{"name": "Artist"}], "uri": "spotify:track:id1"}],
        }
        output = io.StringIO()
        with (
            patch.object(dl, "fetch_embed_page", return_value=(entity, "token")),
            patch.object(dl, "fetch_spclient_track_ids", return_value=["id1", "id2"]),
            patch.object(dl, "fetch_track_by_id", return_value=dl.Track(name="Two", artists="Artist", spotify_id="id2")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(dl.main(["preview", "--json", "https://open.spotify.com/playlist/abc"]), 0)

        self.assertEqual(len(json.loads(output.getvalue())["items"][0]["tracks"]), 2)

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

    def test_youtube_download_json_event_includes_completed_file_path(self):
        url = "https://www.youtube.com/watch?v=video123"
        args = dl.parse_args(["download", "--json-events", "--output-dir", "/tmp/music", url])
        output = io.StringIO()
        result = dl.DownloadResult(True, "Channel - Song", "Song.mp3", "/tmp/music/Song.mp3", created_this_run=True)
        with (
            patch.object(
                dl,
                "fetch_youtube_info",
                return_value={"title": "Song", "uploader": "Channel", "duration": 120},
            ),
            patch.object(dl, "download_youtube_media", return_value=result),
            patch.object(dl, "find_ffmpeg_location", return_value=None),
            patch.object(dl, "append_history"),
            contextlib.redirect_stdout(output),
        ):
            exit_code = dl.run_download(args)

        events = [
            json.loads(line)
            for line in output.getvalue().splitlines()
            if line.startswith("{")
        ]
        self.assertEqual(exit_code, 0)
        completed = next(event for event in events if event.get("state") == "succeeded")
        self.assertEqual(completed["path"], "/tmp/music/Song.mp3")
        self.assertTrue(completed["created_this_run"])
        self.assertEqual(events[-1]["event"], "source_finished")
        self.assertEqual(events[-1]["source_url"], url)
        self.assertEqual(events[-1]["failed_count"], 0)

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


class TitleCleanupTests(unittest.TestCase):
    def test_edition_tails_are_removed(self):
        cases = {
            "Run to the Hills - 2015 Remaster": "Run to the Hills",
            "Paint It, Black - Remastered 2011": "Paint It, Black",
            "Song - 2009 Remastered Version": "Song",
            "Song (Mono Version)": "Song",
            "Song - Radio Edit": "Song",
            "Song (feat. Someone Else)": "Song",
            "Song - From \"Top Gun\" Original Motion Picture Soundtrack": "Song",
            "Song [40th Anniversary Edition]": "Song",
        }
        for raw, expected in cases.items():
            self.assertEqual(dl.clean_track_title(raw), expected, raw)

    def test_real_version_tails_are_kept(self):
        for raw in ("Song - Live at Wembley", "Song - Acoustic", "Song (Remix)", "Song - Sped Up", "Remaster"):
            self.assertEqual(dl.clean_track_title(raw), raw)

    def test_remastered_spotify_title_matches_plain_youtube_uploads(self):
        track = dl.Track(name="Run to the Hills - 2015 Remaster", artists="Iron Maiden", duration_ms=233_000)
        candidates = [
            {"id": "a", "title": "Iron Maiden - Run To The Hills - Remastered", "channel": "Fan", "duration": 234},
            {"id": "b", "title": "Iron Maiden - Run To The Hills (Official Video)", "channel": "Iron Maiden", "duration": 232},
            {"id": "c", "title": "Iron Maiden - Run to the Hills [Original 1982 Studio Recording]", "channel": "Fan", "duration": 234},
        ]
        chosen, reason = dl.choose_youtube_candidate(candidates, track)
        self.assertIsNotNone(chosen, reason)

    def test_studio_track_prefers_studio_upload_over_live_one(self):
        track = dl.Track(name="Cum on Feel the Noize", artists="Quiet Riot", duration_ms=289_000)
        candidates = [
            {"id": "live", "title": "Quiet Riot - Cum On Feel The Noize (Live 1983)", "channel": "Quiet Riot", "duration": 289},
            {"id": "studio", "title": "Quiet Riot - Cum On Feel The Noize (Official Video)", "channel": "QuietRiotVEVO", "duration": 307},
        ]
        chosen, _ = dl.choose_youtube_candidate(candidates, track)
        self.assertEqual(chosen["id"], "studio")


class EmbeddedLyricsTests(unittest.TestCase):
    SYNCED = "[ar: Artist]\n[00:01.50]First line\n[00:03.00][00:10.25]Chorus\n"

    def setUp(self):
        with dl.LYRICS_CACHE_LOCK:
            dl.LYRICS_CACHE.clear()

    def test_parse_lrc_expands_repeated_timestamps_and_skips_metadata(self):
        self.assertEqual(
            dl.parse_lrc(self.SYNCED),
            [("First line", 1500), ("Chorus", 3000), ("Chorus", 10250)],
        )
        self.assertEqual(dl.strip_lrc_timestamps(self.SYNCED), "First line\nChorus")

    def test_lyrics_style_controls_standard_tag_text(self):
        lyrics = dl.Lyrics(plain=None, synced=self.SYNCED)
        self.assertEqual(lyrics.text("plain"), "First line\nChorus")
        self.assertEqual(lyrics.text("synced"), self.SYNCED)

    def test_mp3_gets_plain_lyrics_and_sylt_timing_inside_the_file(self):
        from mutagen.id3 import ID3

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "song.mp3"
            audio.write_bytes(b"\x00" * 512)
            self.assertTrue(dl.embed_lyrics(audio, dl.Lyrics(plain="First line\nChorus", synced=self.SYNCED)))

            tags = ID3(str(audio))
            self.assertEqual(tags.getall("USLT")[0].text, "First line\nChorus")
            self.assertEqual(tags.getall("SYLT")[0].text[0], ("First line", 1500))
            self.assertEqual(tags.version[:2], (2, 3))

    def test_embed_lrc_command_moves_sidecars_into_audio_files(self):
        from mutagen.id3 import ID3

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "Album" / "01. Song - Artist.mp3"
            audio.parent.mkdir()
            audio.write_bytes(b"\x00" * 512)
            audio.with_suffix(".lrc").write_text(self.SYNCED, encoding="utf-8")

            code = dl.main(["embed-lrc", tmp])

            self.assertEqual(code, 0)
            self.assertFalse(audio.with_suffix(".lrc").exists())
            self.assertEqual(ID3(str(audio)).getall("USLT")[0].text, "First line\nChorus")

    def test_lyrics_lookup_falls_back_to_search(self):
        track = dl.Track(name="Run to the Hills - 2015 Remaster", artists="Iron Maiden", duration_ms=233_000)

        class Response:
            def __init__(self, status, payload):
                self.status_code = status
                self._payload = payload

            def json(self):
                return self._payload

        results = [
            {"trackName": "Run to the Hills (Live)", "duration": 233, "plainLyrics": "wrong"},
            {"trackName": "Run to the Hills", "duration": 250, "plainLyrics": "too long"},
            {"trackName": "Run to the Hills (2015 Remaster)", "duration": 234, "plainLyrics": "right", "syncedLyrics": "[00:01.00]right"},
        ]
        with patch.object(dl.req, "get", side_effect=[Response(404, {}), Response(200, results)]):
            lyrics = dl.fetch_lyrics_payload(track)

        self.assertEqual(lyrics.plain, "right")
        self.assertEqual(lyrics.synced, "[00:01.00]right")


class MatchingReliabilityTests(unittest.TestCase):
    def test_search_queries_drop_youtube_operators(self):
        track = dl.Track(name='Someone To Follow', artists="-Prey, Nateki, leah julia, Bodycam")
        queries = dl.youtube_search_queries(track, limit=10)
        self.assertEqual(queries[0], "ytsearch10:Prey, Nateki, leah julia, Bodycam - Someone To Follow")
        self.assertEqual(dl.search_safe('+Artist "Quoted" ~Song - Title'), "Artist Quoted Song - Title")

    def test_hyphen_prefixed_artist_still_matches(self):
        track = dl.Track(name="Someone To Follow", artists="-Prey, Nateki, leah julia, Bodycam", duration_ms=132_000)
        candidate = {
            "id": "right",
            "title": "-Prey, Nateki & leah julia - Someone To Follow (Official Bodycam Soundtrack)",
            "channel": "Aurorian Records",
            "duration": 132,
        }
        chosen, _ = dl.choose_youtube_candidate([candidate], track)
        self.assertEqual(chosen["id"], "right")

    def test_flexibility_widens_duration_window(self):
        track = dl.Track(name="Song", artists="Artist", duration_ms=200_000)
        candidate = {"id": "long", "title": "Artist - Song", "channel": "Artist", "duration": 245}
        self.assertIsNone(dl.choose_youtube_candidate([candidate], track)[0])
        self.assertEqual(dl.choose_youtube_candidate([candidate], track, flexibility=0.8)[0]["id"], "long")

    def test_flexibility_allows_partial_titles_and_unlisted_artists(self):
        track = dl.Track(name="Midnight City Lights", artists="Somebody", duration_ms=180_000)
        partial = {"id": "partial", "title": "Somebody - Midnight City (Lights)", "channel": "Somebody", "duration": 181}
        unlisted = {"id": "unlisted", "title": "Midnight City Lights", "channel": "Uploads", "duration": 181}
        self.assertIsNone(dl.choose_youtube_candidate([unlisted], track)[0])
        self.assertEqual(dl.choose_youtube_candidate([partial], track, flexibility=0.5)[0]["id"], "partial")
        self.assertEqual(dl.choose_youtube_candidate([unlisted], track, flexibility=0.7)[0]["id"], "unlisted")

    def test_match_flexibility_flag_is_clamped(self):
        args = dl.parse_args(["download", "--match-flexibility", "4", "https://youtu.be/example"])
        self.assertEqual(dl.RunOptions.from_args(args).match_flexibility, 1.0)
        default = dl.parse_args(["download", "https://youtu.be/example"])
        self.assertEqual(dl.RunOptions.from_args(default).match_flexibility, dl.DEFAULT_MATCH_FLEXIBILITY)

    def test_threaded_output_keeps_every_json_event_whole(self):
        import threading

        buffer = io.StringIO()

        def work(worker):
            for index in range(300):
                dl.emit_json_event(True, "track_progress", key=f"{worker}-{index}", message="x" * 100)
                dl.print(f"  [{worker}] Done {index}", flush=True)

        with contextlib.redirect_stdout(buffer):
            threads = [threading.Thread(target=work, args=(worker,)) for worker in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        events = [line for line in buffer.getvalue().splitlines() if line.startswith("{")]
        self.assertEqual(len(events), 1800)
        for line in events:
            json.loads(line)

    def test_one_track_error_does_not_stop_the_playlist(self):
        collection = dl.SpotifyCollection(
            name="Mix", use_subfolder=True,
            tracks=[dl.Track(name="Boom", artists="A"), dl.Track(name="Fine", artists="B")],
        )

        def fake_download(track, *_):
            if track.name == "Boom":
                raise RuntimeError("surprise")
            return dl.DownloadResult(True, track.name)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dl, "download_track", side_effect=fake_download),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ok, failed, _, failures, _ = dl.download_collection(collection, dl.RunOptions(), tmp, threads=2, start=1)

        self.assertEqual((ok, failed), (1, 1))
        self.assertIn("unexpected error: surprise", failures[0])


class CleanLyricsTests(unittest.TestCase):
    def test_timestamped_lyrics_become_plain_text_with_mp3_timing_kept(self):
        from mutagen.id3 import ID3

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "song.mp3"
            audio.write_bytes(b"\x00" * 512)
            synced = "[00:42.92] Ooh yeah, ooh yeah\n[00:48.01] Rat-tailed Jimmy is a second-hand hood\n"
            dl.embed_lyrics(audio, dl.Lyrics(synced=synced), "synced")
            self.assertIn("[00:42.92]", ID3(str(audio)).getall("USLT")[0].text)

            with contextlib.redirect_stdout(io.StringIO()):
                code = dl.main(["clean-lyrics", tmp])

            tags = ID3(str(audio))
            self.assertEqual(code, 0)
            self.assertEqual(tags.getall("USLT")[0].text, "Ooh yeah, ooh yeah\nRat-tailed Jimmy is a second-hand hood")
            self.assertEqual(tags.getall("SYLT")[0].text[0], ("Ooh yeah, ooh yeah", 42920))

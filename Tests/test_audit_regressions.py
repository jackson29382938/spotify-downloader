import json
from pathlib import Path
from unittest.mock import patch

import pytest
import spotify_dl as dl


def test_unicode_filename_fits_filesystem_component(tmp_path):
    name = dl.safe("音楽🎶" * 200)
    assert len(name.encode("utf-8")) <= 200
    (tmp_path / f"{name}.mp3").touch()


def test_collision_suffix_survives_maximum_length_name(tmp_path):
    stem = "a" * 200
    (tmp_path / f"{stem}.mp3").touch()
    reserved = dl.reserve_output_stem(tmp_path, stem, "mp3", None)
    try:
        assert reserved.endswith(" (2)")
        assert len(reserved.encode()) <= 200
        assert reserved != stem
    finally:
        dl.release_output_stem(tmp_path, reserved, "mp3")


def test_existing_output_does_not_treat_title_as_glob(tmp_path):
    (tmp_path / "Song 1.mp3").touch()
    assert dl.existing_output(tmp_path, "Song [1]", "mp3") is None
    expected = tmp_path / "Song [1].MP3"
    expected.touch()
    assert dl.existing_output(tmp_path, "Song [1]", "mp3") == expected


@pytest.mark.parametrize("file_name", ["../outside.mp3", "/tmp/outside.mp3", "..\\outside.mp3", "C:\\outside.mp3", "\x00bad.mp3"])
def test_manifest_rejects_paths_outside_collection(tmp_path, file_name):
    (tmp_path / dl.MANIFEST_FILENAME).write_text(json.dumps({"key": "track", "file": file_name}))
    with patch.object(dl, "is_complete_audio", return_value=True):
        assert dl.load_manifest(tmp_path) == {}


def test_manifest_rejects_external_symlink(tmp_path):
    folder = tmp_path / "collection"
    folder.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.touch()
    try:
        (folder / "linked.mp3").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks require additional Windows privileges")
    assert dl.manifest_audio_path(folder, "linked.mp3") is None


def test_manifest_accepts_direct_file(tmp_path):
    expected = tmp_path / "track.mp3"
    expected.touch()
    assert dl.manifest_audio_path(tmp_path, "track.mp3") == expected


def test_diagnostics_do_not_overwrite_existing_probe_file(tmp_path):
    existing = tmp_path / ".spotify-downloader-write-test"
    existing.write_text("User data")
    report = dl.health_diagnostics(str(tmp_path), probe_network=False)
    assert report["ok"]
    assert existing.read_text() == "User data"
    assert not list(tmp_path.glob(".spotify-downloader-write-test-*"))

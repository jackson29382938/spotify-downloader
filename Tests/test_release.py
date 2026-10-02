import importlib.util
import json
from pathlib import Path
import plistlib
import zipfile

import pytest


spec = importlib.util.spec_from_file_location("publish_release", Path(__file__).resolve().parents[1] / "script" / "publish_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
SHA = "a" * 40


def build_api(monkeypatch, *, conclusion="success", tag_sha=SHA, jobs=None):
    def api(endpoint):
        if "/git/ref/" in endpoint:
            return {"object": {"type": "commit", "sha": tag_sha}}
        if endpoint.endswith("/jobs?per_page=100"):
            names = release.REQUIRED_JOBS if jobs is None else jobs
            return {"jobs": [{"name": name, "conclusion": "success"} for name in names]}
        if endpoint.endswith("/artifacts?per_page=100"):
            return {"artifacts": [{"name": name, "expired": False} for name in release.REQUIRED_ARTIFACTS]}
        return {"repository": {"full_name": "owner/repo"}, "path": ".github/workflows/desktop.yml",
                "status": "completed", "conclusion": conclusion, "head_sha": SHA}
    monkeypatch.setattr(release, "api", api)
    monkeypatch.setattr(release, "contents", lambda *args: "1.1.0\n")


def test_release_refuses_failed_native_build(monkeypatch):
    build_api(monkeypatch, conclusion="failure")
    with pytest.raises(ValueError, match="completed successfully"):
        release.verify_build("owner/repo", "v1.1.0", 123)


def test_release_refuses_tag_from_different_commit(monkeypatch):
    build_api(monkeypatch, tag_sha="b" * 40)
    with pytest.raises(ValueError, match="do not match"):
        release.verify_build("owner/repo", "v1.1.0", 123)


def test_release_requires_mac_windows_and_linux_jobs(monkeypatch):
    build_api(monkeypatch, jobs=release.REQUIRED_JOBS - {"macos"})
    with pytest.raises(ValueError, match="three native platform jobs"):
        release.verify_build("owner/repo", "v1.1.0", 123)


def test_release_accepts_exact_successful_native_build(monkeypatch):
    build_api(monkeypatch)
    assert release.verify_build("owner/repo", "v1.1.0", 123) == (SHA, "1.1.0")


def archives(folder, embedded_version="1.1.0"):
    for platform in ("Linux-x86_64", "Windows-AMD64", "macOS-arm64"):
        name = ("Spotify-Downloader-" if platform.startswith("macOS") else "SpotifyDownloader-") + "1.1.0-" + platform + ".zip"
        with zipfile.ZipFile(folder / name, "w") as zipped:
            if platform.startswith("macOS"):
                zipped.writestr("Spotify Downloader.app/Contents/Info.plist", plistlib.dumps({"CFBundleShortVersionString": embedded_version}))
                names = ["Spotify Downloader.app/Contents/MacOS/SpotDLDownloader", "Spotify Downloader.app/Contents/Resources/downloader/spotify_dl"]
            else:
                zipped.writestr("SpotifyDownloader/build-info.json", json.dumps({"version": embedded_version}))
                ext = ".exe" if platform.startswith("Windows") else ""
                names = ["SpotifyDownloader/SpotifyDownloader" + ext, "SpotifyDownloader/helper/spotify-helper" + ext]
            for executable in names:
                info = zipfile.ZipInfo(executable)
                info.external_attr = 0o100755 << 16
                zipped.writestr(info, b"placeholder binary")


def test_release_requires_matching_archive_versions(tmp_path):
    archives(tmp_path, embedded_version="1.0.0")
    with pytest.raises(ValueError, match="version mismatch"):
        release.verify_archives(tmp_path, "1.1.0")


def test_release_rejects_unsafe_paths_even_with_valid_metadata(tmp_path):
    archives(tmp_path)
    file = next(tmp_path.glob("*Linux*.zip"))
    with zipfile.ZipFile(file, "a") as zipped:
        zipped.writestr("../outside", "unexpected")
    with pytest.raises(ValueError, match="Unsafe archive path"):
        release.verify_archives(tmp_path, "1.1.0")


def test_release_checks_uploaded_content_digest():
    expected = {"app.zip": (100, "a" * 64)}
    item = {"name": "app.zip", "size": 100, "state": "uploaded", "digest": "sha256:" + "b" * 64}
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        release.verify_uploaded({"assets": [item]}, expected)
    item["digest"] = "sha256:" + "a" * 64
    release.verify_uploaded({"assets": [item]}, expected)

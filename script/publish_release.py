#!/usr/bin/env python3
"""Publish only native artifacts from successful CI for the exact version tag."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile
import zipfile


REQUIRED_JOBS = {"macos", "desktop (windows-latest)", "desktop (ubuntu-24.04)"}
REQUIRED_ARTIFACTS = {"desktop-macOS", "desktop-Windows", "desktop-Linux"}


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def api(endpoint):
    return json.loads(gh("api", endpoint))


def contents(repo, commit, name):
    item = api(f"repos/{repo}/contents/{name}?ref={commit}")
    return base64.b64decode(item["content"]).decode("utf-8")


def verify_build(repo, tag, run_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or run_id <= 0:
        raise ValueError("Use a numeric version tag and positive run ID")
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    if run["repository"]["full_name"].casefold() != repo.casefold():
        raise ValueError("Build belongs to a different repository")
    if run["path"] != ".github/workflows/desktop.yml" or run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError("Desktop build must have completed successfully")
    obj = api(f"repos/{repo}/git/ref/tags/{tag}")["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            break
        if obj["type"] != "tag":
            raise ValueError("Release tag must resolve to a commit")
        obj = api(f"repos/{repo}/git/tags/{obj['sha']}")["object"]
    if obj["type"] != "commit" or obj["sha"] != run["head_sha"]:
        raise ValueError("Release tag and tested build commit do not match")
    jobs = api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    if {job["name"] for job in jobs} != REQUIRED_JOBS or any(job["conclusion"] != "success" for job in jobs):
        raise ValueError("All three native platform jobs must pass")
    artifacts = api(f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    if {item["name"] for item in artifacts} != REQUIRED_ARTIFACTS or any(item["expired"] for item in artifacts):
        raise ValueError("All three native build artifacts must be available")
    version = contents(repo, obj["sha"], "VERSION").strip()
    if tag != f"v{version}":
        raise ValueError("VERSION does not match release tag")
    return obj["sha"], version


def verify_archives(folder, version):
    files = sorted(Path(folder).rglob("*.zip"))
    expected = {
        f"SpotifyDownloader-{version}-Linux-x86_64.zip",
        f"SpotifyDownloader-{version}-Windows-AMD64.zip",
        f"Spotify-Downloader-{version}-macOS-arm64.zip",
    }
    if len(files) != 3 or {file.name for file in files} != expected:
        raise ValueError("Expected exactly the versioned Linux, Windows and Apple Silicon ZIPs")
    for file in files:
        with zipfile.ZipFile(file) as zipped:
            if zipped.testzip() is not None:
                raise ValueError(f"Archive checksum failed: {file.name}")
            names = set(zipped.namelist())
            if any(name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") for name in names):
                raise ValueError(f"Unsafe archive path: {file.name}")
            if "-macOS-" in file.name:
                info = plistlib.loads(zipped.read("Spotify Downloader.app/Contents/Info.plist"))
                if info["CFBundleShortVersionString"] != version:
                    raise ValueError("Mac bundle version mismatch")
                required = {"Spotify Downloader.app/Contents/MacOS/SpotDLDownloader",
                            "Spotify Downloader.app/Contents/Resources/downloader/spotify_dl"}
            else:
                info = json.loads(zipped.read("SpotifyDownloader/build-info.json"))
                if info["version"] != version:
                    raise ValueError("Desktop bundle version mismatch")
                extension = ".exe" if "-Windows-" in file.name else ""
                required = {f"SpotifyDownloader/SpotifyDownloader{extension}",
                            f"SpotifyDownloader/helper/spotify-helper{extension}"}
                if not extension and any(not (zipped.getinfo(name).external_attr >> 16) & 0o111 for name in required):
                    raise ValueError("Linux executables lost their execute permissions")
            if not required.issubset(names):
                raise ValueError(f"Missing launcher/helper in {file.name}")
    return files


def verify_uploaded(release, expected):
    assets = release["assets"]
    if len(assets) != len(expected) or {asset["name"] for asset in assets} != set(expected):
        raise ValueError("Uploaded release asset set differs from verified files")
    for asset in assets:
        size, digest = expected[asset["name"]]
        if asset["state"] != "uploaded" or asset["size"] != size or asset.get("digest") != f"sha256:{digest}":
            raise ValueError(f"Uploaded size or SHA-256 mismatch: {asset['name']}")


def publish(repo, tag, run_id, folder):
    commit, version = verify_build(repo, tag, run_id)
    files = verify_archives(folder, version)
    expected = {}
    for file in files:
        with file.open("rb") as stream:
            expected[file.name] = (file.stat().st_size, hashlib.file_digest(stream, "sha256").hexdigest())
    with tempfile.TemporaryDirectory(prefix="verified-release-") as work:
        checksum = Path(work) / "SHA256SUMS"
        checksum.write_text("".join(f"{expected[file.name][1]}  {file.name}\n" for file in files), encoding="utf-8")
        data = checksum.read_bytes()
        expected[checksum.name] = (len(data), hashlib.sha256(data).hexdigest())
        notes = Path(work) / "release-notes.md"
        body = contents(repo, commit, "RELEASE_NOTES.md")
        body += f"\n## Build provenance\n\nAll native jobs passed for `{commit}`.\n\nCI: https://github.com/{repo}/actions/runs/{run_id}\n\nAssets: Linux x86_64, Windows AMD64, native macOS Apple Silicon (arm64). Intel Macs can build from source. Download checksums are attached in `SHA256SUMS`.\n"
        notes.write_text(body, encoding="utf-8")
        releases = api(f"repos/{repo}/releases?per_page=100")
        release = next((item for item in releases if item["tag_name"] == tag), None)
        if release and not release["draft"]:
            verify_uploaded(release, expected)
            print(f"Already published and verified: {release['html_url']}")
            return
        if release is None:
            # Use the creation response directly: list endpoints can lag behind
            # a newly created draft. The tag was already verified above.
            request = Path(work) / "create-release.json"
            request.write_text(json.dumps({"tag_name": tag, "target_commitish": commit,
                                          "name": f"Spotify Downloader {version}",
                                          "body": body, "draft": True}), encoding="utf-8")
            release = json.loads(gh("api", f"repos/{repo}/releases", "--method", "POST",
                                    "--input", str(request)))
            if release.get("tag_name") != tag or not release.get("draft") or not release.get("id"):
                raise ValueError("Release creation did not return the expected draft")
        for file in [*files, checksum]:
            if not api(f"repos/{repo}/releases/{release['id']}")["draft"]:
                raise ValueError("Release was published during upload; refusing to modify it")
            gh("release", "upload", tag, str(file), "--repo", repo, "--clobber")
        verify_uploaded(api(f"repos/{repo}/releases/{release['id']}"), expected)
        gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest",
           "--title", f"Spotify Downloader {version}", "--notes-file", str(notes))
        result = api(f"repos/{repo}/releases/{release['id']}")
        if result["draft"]:
            raise ValueError("Publication was not confirmed")
        verify_uploaded(result, expected)
        print(f"Published and verified: {result['html_url']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify", "publish"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--artifacts", default="release-assets")
    args = parser.parse_args()
    if args.mode == "verify":
        commit, version = verify_build(args.repo, args.tag, args.run_id)
        print(f"Verified native build: {args.tag}, {commit}, version {version}")
    else:
        publish(args.repo, args.tag, args.run_id, args.artifacts)


if __name__ == "__main__":
    main()

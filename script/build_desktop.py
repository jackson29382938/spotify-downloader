#!/usr/bin/env python3
"""Build portable native-platform Qt + helper bundles (no cross-compilation)."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="store_true", help="Create a portable ZIP")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("VERSION must contain a numeric major.minor.patch version")
    work = root / ".build" / "desktop"
    dist = root / "dist"
    gui = dist / "SpotifyDownloader"
    # All removal/build destinations are fixed generated paths inside this checkout.
    def build(name, entry, output, extras):
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
                        "--name", name, "--distpath", str(output), "--workpath", str(work / name),
                        "--specpath", str(work), *extras, str(root / entry)], cwd=root, check=True)

    build("spotify-helper", "desktop_helper.py", work / "helper-dist",
          ["--console", "--collect-all", "yt_dlp", "--collect-all", "yt_dlp_ejs"])
    build("SpotifyDownloader", "desktop_app.py", dist, ["--windowed"])
    # On macOS the Qt executable also lives here; this portable folder is the
    # supported output, while the existing SwiftUI build retains its own app bundle.
    shutil.copytree(work / "helper-dist" / "spotify-helper", gui / "helper", dirs_exist_ok=True)
    for name in ("DISCLAIMER.md", "DESKTOP.md", "VERSION"):
        shutil.copy2(root / name, gui / name)
    versions = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    (gui / "build-info.json").write_text(json.dumps({"version": version, "platform": platform.platform(),
        "python": platform.python_version(), "dependencies": versions.splitlines()}, indent=2), encoding="utf-8")
    executable = gui / ("SpotifyDownloader.exe" if os.name == "nt" else "SpotifyDownloader")
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    subprocess.run([str(executable), "--smoke-test"], env=environment, cwd=gui, check=True, timeout=60)
    if args.package:
        archive = shutil.make_archive(str(dist / f"SpotifyDownloader-{version}-{platform.system()}-{platform.machine()}"),
                                      "zip", dist, gui.name)
        print(f"Package: {archive}")
    print(f"Verified application: {executable}")


if __name__ == "__main__":
    main()

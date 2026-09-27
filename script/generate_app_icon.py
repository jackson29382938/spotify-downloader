#!/usr/bin/env python3
"""Package the checked-in AppIconSource.png master into the macOS icon sizes.

The master was created with the built-in image generator. Keep it as the source
of truth; logo.svg and AppLogoMark provide a matching flat vector fallback.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Resources" / "AppIconSource.png"
ICONSET = ROOT / "Resources" / "AppIcon.iconset"
OUTPUT = ROOT / "Resources" / "AppIcon.icns"

SIZES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]


def main() -> int:
    with Image.open(SOURCE) as source:
        if source.width != source.height or source.width < 1024:
            raise ValueError("AppIconSource.png must be square and at least 1024px")
        # Premultiplied alpha avoids dark fringes around the transparent tile.
        master = source.convert("RGBA").convert("RGBa")
    ICONSET.mkdir(parents=True, exist_ok=True)
    for pixel_size, filename in SIZES:
        icon = master.resize((pixel_size, pixel_size), Image.Resampling.LANCZOS)
        icon.convert("RGBA").save(ICONSET / filename)

    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(OUTPUT)], check=True)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

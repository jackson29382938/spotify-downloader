#!/usr/bin/env python3
"""Generate AppIcon.icns from the same vector mark as Resources/logo.svg."""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
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


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def draw_logo(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = size * 0.0625
    tile = (inset, inset, size - inset, size - inset)
    corner = int((tile[2] - tile[0]) * 0.21875)

    for y in range(size):
        for x in range(size):
            left, top, right, bottom = tile
            if not (left <= x < right and top <= y < bottom):
                continue
            local_x = (x - left) / (right - left)
            local_y = (y - top) / (bottom - top)
            if local_x < corner / (right - left):
                dx = corner / (right - left) - local_x
                dy = local_y
                if math.hypot(dx, dy) > corner / (right - left):
                    continue
            if local_x > 1 - corner / (right - left):
                dx = local_x - (1 - corner / (right - left))
                dy = local_y
                if math.hypot(dx, dy) > corner / (right - left):
                    continue
            if local_y < corner / (bottom - top):
                dx = local_x
                dy = corner / (bottom - top) - local_y
                if math.hypot(dx, dy) > corner / (bottom - top):
                    continue
            if local_y > 1 - corner / (bottom - top):
                dx = local_x
                dy = local_y - (1 - corner / (bottom - top))
                if math.hypot(dx, dy) > corner / (bottom - top):
                    continue
            r = int(lerp(30, 22, local_x))
            g = int(lerp(215, 156, local_x))
            b = int(lerp(96, 70, local_x))
            image.putpixel((x, y), (r, g, b, 255))

    stroke = max(2, int(size * 0.055))
    center_x = size / 2
    top = size * 0.234375
    stem_bottom = size * 0.515625
    wing_y = size * 0.40625
    wing_x = size * 0.09375
    white = (255, 255, 255, 255)

    draw.line([(center_x, top), (center_x, stem_bottom)], fill=white, width=stroke)
    draw.line([(center_x - wing_x, wing_y), (center_x, stem_bottom), (center_x + wing_x, wing_y)], fill=white, width=stroke)

    def wave(base_y: float, amplitude: float) -> list[tuple[float, float]]:
        left = size * 0.265625
        right = size * 0.734375
        mid = size / 2
        return [
            (left, base_y),
            (left + size * 0.125, base_y - amplitude * 0.35),
            (mid, base_y + amplitude),
            (right - size * 0.125, base_y + amplitude * 1.35),
            (right, base_y),
        ]

    for base, amp, alpha in (
        (size * 0.609375, size * 0.0625, 255),
        (size * 0.71875, size * 0.078125, 220),
    ):
        draw.line(wave(base, amp), fill=(255, 255, 255, alpha), width=max(2, int(size * 0.04)))

    return image


def main() -> int:
    ICONSET.mkdir(parents=True, exist_ok=True)
    for pixel_size, filename in SIZES:
        draw_logo(pixel_size).save(ICONSET / filename)

    if OUTPUT.exists():
        OUTPUT.unlink()
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(OUTPUT)], check=True)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

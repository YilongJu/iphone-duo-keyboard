"""Turns one candidate of generate.ps1 into the template images of the Select All key.

The candidate is black on white. The key tints its icon with the text color, so the image keeps
only the shape: black pixels whose opacity is the darkness of the candidate. The shape is cut to
its bounds, centered in a square of 24 points, and written at 2 and 3 pixels per point.

Usage, from the repository root:
    python scripts/select-all-icon/make_icon.py a
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops

POINTS = 24          # the square of the icon in the key, in points
MARGIN = 1           # empty points at each side of the shape
HERE = Path(__file__).resolve().parent
SHARED = HERE.parents[1] / "Shared"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_icon.py CANDIDATE")
    source = HERE / "candidates" / f"{sys.argv[1]}.png"
    darkness = ImageChops.invert(Image.open(source).convert("L"))
    # A pixel darker than 10% belongs to the shape. The paper of a candidate is not always pure white.
    bounds = darkness.point(lambda value: 255 if value > 25 else 0).getbbox()
    if bounds is None:
        raise SystemExit(f"{source} holds no dark shape")
    shape = darkness.crop(bounds)
    for scale in (2, 3):
        side = POINTS * scale
        room = side - 2 * MARGIN * scale
        factor = room / max(shape.size)
        size = (max(1, round(shape.width * factor)), max(1, round(shape.height * factor)))
        alpha = Image.new("L", (side, side), 0)
        alpha.paste(shape.resize(size, Image.LANCZOS), ((side - size[0]) // 2, (side - size[1]) // 2))
        image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        image.putalpha(alpha)
        target = SHARED / f"select-all@{scale}x.png"
        image.save(target, optimize=True)
        print(f"wrote {target.name}: {side}x{side} pixels, {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()

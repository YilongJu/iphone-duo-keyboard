"""Draws the 1024 x 1024 app icon: a small keyboard with a wide space bar on a dark background.

Usage: uv run --with pillow scripts/app-icon/make_icon.py App/Assets.xcassets/AppIcon.appiconset/icon-1024.png
App Store Connect rejects an icon with an alpha channel, so the image is saved as RGB.
"""
import sys

from PIL import Image, ImageDraw

SIZE = 1024
image = Image.new("RGB", (SIZE, SIZE), (28, 30, 38))
draw = ImageDraw.Draw(image)

rows = [14, 14, 13, 12]
margin = 110
gap = 12
key_width = (SIZE - 2 * margin - 13 * gap) / 14
key_height = 96
top = 250
for row_index, count in enumerate(rows):
    row_width = count * key_width + (count - 1) * gap
    x = (SIZE - row_width) / 2
    y = top + row_index * (key_height + gap)
    for _ in range(count):
        draw.rounded_rectangle([x, y, x + key_width, y + key_height], radius=12, fill=(235, 237, 242))
        x += key_width + gap

y = top + len(rows) * (key_height + gap)
draw.rounded_rectangle([margin, y, margin + 130, y + key_height], radius=12, fill=(120, 126, 140))
draw.rounded_rectangle([margin + 142, y, SIZE - margin - 142, y + key_height], radius=12, fill=(64, 156, 255))
draw.rounded_rectangle([SIZE - margin - 130, y, SIZE - margin, y + key_height], radius=12, fill=(120, 126, 140))

image.save(sys.argv[1], "PNG")

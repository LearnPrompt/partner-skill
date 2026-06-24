#!/usr/bin/env python3
"""Generate the README showcase GIF for Partner.

The animation intentionally uses only geometric shapes. That keeps the asset
reproducible on machines where font libraries are unavailable or blocked.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "showcase.gif"
SIZE = (720, 405)

BG = "#101418"
PANEL = "#172025"
BORDER = "#2b383d"
CLAUDE = "#f3c969"
CODEX = "#7cc7b2"
MUTED = "#334047"
TEXTURE = "#223038"


def draw_node(draw: ImageDraw.ImageDraw, center: tuple[int, int], color: str, active: bool) -> None:
    x, y = center
    radius = 42 if active else 34
    halo = 58 if active else 0
    if active:
        draw.ellipse((x - halo, y - halo, x + halo, y + halo), fill="#26353a")
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    inner = 18 if active else 13
    draw.ellipse((x - inner, y - inner, x + inner, y + inner), fill=PANEL)


def draw_badges(draw: ImageDraw.ImageDraw, active: int) -> None:
    for index, x in enumerate([110, 260, 410, 560]):
        fill = CODEX if index == active else MUTED
        draw.rounded_rectangle((x, 304, x + 72, 338), radius=14, fill=fill)
        draw.rectangle((x + 24, 314, x + 48, 328), fill=PANEL)


def render_frame(active: int) -> Image.Image:
    image = Image.new("RGB", SIZE, BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((40, 36, 680, 366), radius=22, fill=PANEL, outline=BORDER, width=2)
    for offset in range(0, 600, 48):
        draw.line((70 + offset, 70, 20 + offset, 332), fill=TEXTURE, width=1)

    centers = [(150, 176), (300, 176), (450, 176), (600, 176)]
    for start, end in zip(centers, centers[1:]):
        draw.line((start[0] + 42, start[1], end[0] - 42, end[1]), fill=BORDER, width=10)
    for index in range(active):
        start, end = centers[index], centers[index + 1]
        draw.line((start[0] + 42, start[1], end[0] - 42, end[1]), fill=CODEX, width=10)

    for index, center in enumerate(centers):
        color = CLAUDE if index in (0, 2) else CODEX
        draw_node(draw, center, color, index == active)

    # Two small side rails: Claude on top for judgment, Codex below for evidence.
    draw.rounded_rectangle((104, 82, 616, 104), radius=11, fill="#2d2b24")
    draw.rounded_rectangle((104, 248, 616, 270), radius=11, fill="#20332f")
    draw.rectangle((104, 82, 232 + active * 128, 104), fill=CLAUDE)
    draw.rectangle((104, 248, 232 + active * 128, 270), fill=CODEX)

    draw_badges(draw, active)
    return image


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [render_frame(index).convert("P", palette=Image.Palette.ADAPTIVE, colors=96) for index in range(4)]
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=900,
        loop=0,
        optimize=False,
    )
    print(OUT)


if __name__ == "__main__":
    main()

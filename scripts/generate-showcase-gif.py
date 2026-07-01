#!/usr/bin/env python3
"""Generate the README showcase GIF for Partner.

The visual direction is inspired by MotionSites-style cinematic hero previews:
dark stage, glow, depth, and one obvious before/after transformation. It does
not copy third-party imagery.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "showcase.gif"
W, H = 960, 540
SEED = 2077


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size=size, index=0)
    return ImageFont.load_default()


F_HERO = font(48, True)
F_TITLE = font(34, True)
F_BODY = font(22)
F_SMALL = font(17)
F_MONO = font(18)
F_BADGE = font(16, True)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], body: str, fill: str, face: ImageFont.ImageFont, width: int | None = None, gap: int = 6) -> int:
    if width is None:
        draw.text(xy, body, fill=fill, font=face)
        return xy[1] + draw.textbbox(xy, body, font=face)[3]

    words = body.split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textbbox((0, 0), trial, font=face)[2] <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)

    x, y = xy
    line_height = draw.textbbox((0, 0), "Ag", font=face)[3] + gap
    for line in lines:
        draw.text((x, y), line, fill=fill, font=face)
        y += line_height
    return y


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, width: int = 1, radius: int = 18) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def stage() -> Image.Image:
    img = Image.new("RGB", (W, H), "#07111f")
    px = img.load()
    for y in range(H):
        for x in range(W):
            t = y / H
            cx = abs(x - W * 0.62) / W
            r = int(7 + 9 * (1 - t) + 16 * max(0, 0.4 - cx))
            g = int(14 + 20 * (1 - t))
            b = int(31 + 50 * (1 - t) + 30 * max(0, 0.45 - cx))
            px[x, y] = (r, g, b)

    rng = random.Random(SEED)
    draw = ImageDraw.Draw(img)
    for _ in range(120):
        x = rng.randrange(0, W)
        y = rng.randrange(0, H - 70)
        a = rng.randrange(90, 210)
        draw.point((x, y), fill=(a, a, min(255, a + 35)))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for radius, alpha in [(300, 35), (210, 50), (120, 70)]:
        g.ellipse((W // 2 - radius, 185 - radius, W // 2 + radius, 185 + radius), fill=(103, 91, 255, alpha))
    for radius, alpha in [(240, 34), (150, 54)]:
        g.ellipse((W - 260 - radius, 280 - radius, W - 260 + radius, 280 + radius), fill=(255, 190, 85, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(28))).convert("RGB")
    return img


def boring_stage() -> Image.Image:
    img = Image.new("RGB", (W, H), "#eef2f7")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, H), fill="#eef2f7")
    draw.text((54, 48), "Codex-only first pass", fill="#202833", font=F_HERO)
    text(draw, (58, 112), "Technically correct. No motion, no story, no reason to share.", "#667085", F_BODY, 690)

    rounded(draw, (74, 170, 430, 458), "#ffffff", "#d9e1ee", 2, 10)
    draw.text((104, 205), "Partner Receipt", fill="#202833", font=F_TITLE)
    for i, label in enumerate(["Session", "Claude session", "Codex passes", "Checks"]):
        y = 268 + i * 42
        draw.text((104, y), label.upper(), fill="#8a94a6", font=F_SMALL)
        draw.rectangle((260, y + 2, 390, y + 16), fill="#e5eaf2")

    rounded(draw, (506, 170, 842, 458), "#f8fafc", "#d9e1ee", 2, 10)
    draw.text((540, 216), "Result", fill="#202833", font=F_TITLE)
    text(draw, (542, 270), "Readable, but flat. Claude Code has not yet added product taste.", "#667085", F_BODY, 240)
    draw.rectangle((542, 372, 806, 410), fill="#e5eaf2")
    return img


def badge(draw: ImageDraw.ImageDraw, x: int, y: int, body: str, fill: str) -> None:
    rounded(draw, (x, y, x + 168, y + 34), fill, radius=17)
    draw.text((x + 18, y + 9), body, fill="#ffffff", font=F_BADGE)


def receipt_card(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    rounded(draw, (x, y, x + 380, y + 250), "#fbfdff", "#a9c5ff", 2, 18)
    draw.text((x + 26, y + 28), "Partner Session Receipt", fill="#101828", font=font(27, True))
    rows = [
        ("claude_session_reused", "yes"),
        ("new_claude_p_sessions", "0"),
        ("codex_passes", "2"),
        ("checks", "passed"),
    ]
    yy = y + 84
    for key, value in rows:
        draw.text((x + 28, yy), key, fill="#667085", font=F_SMALL)
        draw.text((x + 270, yy), value, fill="#087443", font=font(18, True))
        yy += 36


def frame_partner_prompt() -> Image.Image:
    img = stage()
    draw = ImageDraw.Draw(img)
    badge(draw, 58, 52, "TRIGGER", "#6d5dfc")
    draw.text((58, 104), "One prompt becomes a protocol", fill="#f8fbff", font=F_HERO)
    text(draw, (62, 170), "Partner: Claude plans, Codex implements, same-session review, then receipt.", "#cbd7ff", F_BODY, 760)

    rounded(draw, (86, 268, 874, 398), "#0d1728", "#4856ff", 2, 26)
    draw.text((122, 312), "Claude Code", fill="#ffd27a", font=font(30, True))
    draw.line((330, 333, 450, 333), fill="#6d5dfc", width=5)
    draw.polygon([(450, 333), (430, 322), (430, 344)], fill="#6d5dfc")
    draw.text((486, 312), "Codex", fill="#8df3dc", font=font(30, True))
    draw.line((630, 333, 748, 333), fill="#6d5dfc", width=5)
    draw.polygon([(748, 333), (728, 322), (728, 344)], fill="#6d5dfc")
    draw.text((777, 312), "Receipt", fill="#ffffff", font=font(30, True))
    return img


def frame_shiny_result() -> Image.Image:
    img = stage()
    draw = ImageDraw.Draw(img)
    badge(draw, 58, 52, "AFTER", "#0f8b63")
    draw.text((58, 104), "Claude Code adds the sparkle", fill="#f8fbff", font=F_HERO)
    text(draw, (62, 166), "Same session gives UI taste, motion direction, edge-state review, and final /codex:review.", "#cbd7ff", F_BODY, 750)

    # Laptop / stage base
    rounded(draw, (76, 412, 884, 458), "#101828", "#31415d", 2, 18)
    draw.rectangle((138, 430, 822, 436), fill="#27364f")

    receipt_card(draw, 304, 210)

    # Light beams from Claude and Codex to the receipt.
    for offset in range(0, 16, 4):
        draw.line((112, 388 - offset, 320, 332 - offset), fill="#ffd27a", width=2)
        draw.line((848, 388 - offset, 668, 332 - offset), fill="#8df3dc", width=2)
    rounded(draw, (78, 330, 230, 386), "#171f33", "#ffd27a", 2, 18)
    draw.text((104, 350), "Claude", fill="#ffd27a", font=font(24, True))
    rounded(draw, (730, 330, 882, 386), "#171f33", "#8df3dc", 2, 18)
    draw.text((766, 350), "Codex", fill="#8df3dc", font=font(24, True))
    return img


def frame_cost() -> Image.Image:
    img = stage()
    draw = ImageDraw.Draw(img)
    badge(draw, 58, 52, "PROOF", "#0f8b63")
    draw.text((58, 104), "Cost pressure shifts away from Claude", fill="#f8fbff", font=F_HERO)
    text(draw, (62, 166), "Showcase accounting model: Codex carries implementation; Claude stays focused on plan, polish, and review.", "#cbd7ff", F_BODY, 760)

    rounded(draw, (86, 248, 874, 408), "#0d1728", "#31415d", 2, 24)
    draw.text((126, 282), "Pure Claude Code", fill="#ffd27a", font=font(24, True))
    draw.rectangle((126, 326, 778, 354), fill="#533f1b")
    draw.rectangle((126, 326, 778, 354), fill="#f0bd4f")
    draw.text((790, 323), "100%", fill="#f8fbff", font=font(22, True))

    draw.text((126, 378), "Partner split", fill="#8df3dc", font=font(24, True))
    draw.rectangle((312, 382, 778, 410), fill="#1f2a44")
    draw.rectangle((312, 382, 602, 410), fill="#68d8c0")
    draw.rectangle((602, 382, 720, 410), fill="#f0bd4f")
    draw.text((732, 379), "Claude focused", fill="#f8fbff", font=F_SMALL)

    rounded(draw, (126, 438, 778, 492), "#111a2c", "#31415d", 2, 18)
    draw.text((152, 455), "Example split: Codex carries implementation; Claude stays on taste and judgment.", fill="#cbd7ff", font=F_SMALL)
    return img.crop((0, 0, W, H))


def frame_receipt() -> Image.Image:
    img = stage()
    draw = ImageDraw.Draw(img)
    badge(draw, 58, 52, "RECEIPT", "#6d5dfc")
    draw.text((58, 104), "No vague savings claims", fill="#f8fbff", font=F_HERO)
    text(draw, (62, 166), "Partner reports verifiable behavior first. Exact token numbers require telemetry.", "#cbd7ff", F_BODY, 740)
    receipt_card(draw, 284, 234)
    rounded(draw, (112, 430, 848, 486), "#0d1728", "#31415d", 2, 20)
    draw.text((140, 448), "new_claude_p_sessions: 0  |  same session reused: yes", fill="#8df3dc", font=font(23, True))
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        boring_stage(),
        frame_partner_prompt(),
        frame_shiny_result(),
        frame_cost(),
        frame_receipt(),
    ]
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=[1350, 1300, 1700, 1700, 1800],
        loop=0,
        optimize=True,
    )
    print(OUT)


if __name__ == "__main__":
    main()

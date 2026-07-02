#!/usr/bin/env python3
"""Generate the README showcase GIF for Partner.

The visual direction is inspired by MotionSites-style cinematic hero previews:
black stage, tilted product surfaces, neon glow, and a high-contrast before /
after transformation. The artwork is generated locally and does not copy
third-party imagery.
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


F_HERO = font(52, True)
F_TITLE = font(32, True)
F_BODY = font(21)
F_SMALL = font(16)
F_MONO = font(18)
F_BADGE = font(15, True)


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    body: str,
    fill: str,
    face: ImageFont.ImageFont,
    width: int,
    gap: int = 6,
) -> int:
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


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str | None = None,
    width: int = 1,
    radius: int = 18,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def stage() -> Image.Image:
    img = Image.new("RGB", (W, H), "#03050c")
    px = img.load()
    for y in range(H):
        for x in range(W):
            nx = x / W
            ny = y / H
            center = max(0.0, 1.0 - math.hypot(nx - 0.56, ny - 0.46) * 1.65)
            r = int(5 + 27 * center + 24 * max(0, 1 - ny))
            g = int(8 + 12 * center + 7 * max(0, 1 - ny))
            b = int(17 + 68 * center + 30 * max(0, 1 - ny))
            px[x, y] = (r, g, b)

    rng = random.Random(SEED)
    draw = ImageDraw.Draw(img)
    for _ in range(180):
        x = rng.randrange(0, W)
        y = rng.randrange(0, H - 78)
        a = rng.randrange(110, 245)
        draw.point((x, y), fill=(a, a, min(255, a + 40)))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for radius, alpha, color in [
        (320, 52, (119, 67, 255)),
        (230, 72, (228, 47, 255)),
        (145, 70, (255, 151, 80)),
    ]:
        g.ellipse((W // 2 - radius, 276 - radius, W // 2 + radius, 276 + radius), fill=(*color, alpha))
    for radius, alpha in [(210, 50), (140, 62)]:
        g.ellipse((W - 130 - radius, 150 - radius, W - 130 + radius, 150 + radius), fill=(91, 233, 255, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(34))).convert("RGB")

    draw = ImageDraw.Draw(img)
    horizon = 418
    for i in range(10):
        y = horizon + i * 18
        draw.line((0, y, W, y), fill=(52, 36, 93), width=1)
    for x in range(-120, W + 120, 70):
        draw.line((W // 2, horizon, x, H), fill=(42, 33, 86), width=1)
    return img


def glow_paste(base: Image.Image, item: Image.Image, xy: tuple[int, int], glow_color: tuple[int, int, int], blur: int = 22) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    mask = item.split()[-1]
    glow = Image.new("RGBA", item.size, (*glow_color, 0))
    glow.putalpha(mask)
    layer.alpha_composite(glow, xy)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(layer)
    base.alpha_composite(item, xy)


def glass_panel(size: tuple[int, int], title: str, subtitle: str, mode: str) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rounded(draw, (4, 4, w - 4, h - 4), "#0b1020ee", "#7c8cff", 2, 28)

    for y in range(36, h - 18):
        t = (y - 36) / max(1, h - 54)
        color = (
            int(95 + 125 * t),
            int(62 + 18 * (1 - t)),
            int(255 - 85 * t),
            124,
        )
        draw.line((34, y, w - 34, y), fill=color, width=1)

    draw.text((40, 34), title, fill="#ffffff", font=font(34, True))
    draw_wrapped(draw, (42, 82), subtitle, "#cad6ff", F_BODY, w - 84)

    if mode == "studio":
        rounded(draw, (58, 166, w - 58, 318), "#11182dd8", "#ff63e8", 2, 26)
        draw.ellipse((w // 2 - 48, 202, w // 2 + 48, 298), fill="#201044", outline="#ff63e8", width=3)
        draw.ellipse((w // 2 - 18, 232, w // 2 + 18, 268), fill="#fff1a8")
        for x, label, fill in [(92, "PLAN", "#ffd06f"), (w - 222, "REVIEW", "#7fffee")]:
            rounded(draw, (x, 204, x + 150, 276), "#0b1020", fill, 2, 18)
            draw.text((x + 36, 229), label, fill=fill, font=font(19, True))
        for i in range(4):
            x = 74 + i * 112
            rounded(draw, (x, 348, x + 90, 410), "#151d33", "#3d4d7e", 1, 16)
            draw.rectangle((x + 18, 374, x + 72, 382), fill=["#ff63e8", "#ffd06f", "#7fffee", "#87a6ff"][i])
    elif mode == "receipt":
        rows = [
            ("claude_session_reused", "yes"),
            ("new_claude_p_sessions", "0"),
            ("codex_passes", "2"),
            ("checks", "passed"),
        ]
        yy = 168
        for key, value in rows:
            rounded(draw, (58, yy, w - 58, yy + 46), "#f8fbffe8", "#9dc3ff", 1, 13)
            draw.text((78, yy + 14), key, fill="#344054", font=F_SMALL)
            draw.text((w - 150, yy + 12), value, fill="#087443", font=font(18, True))
            yy += 58
    elif mode == "bars":
        labels = [("Codex work", 0.70, "#7fffee"), ("Claude taste", 0.30, "#ffd06f")]
        yy = 170
        for label, pct, color in labels:
            draw.text((62, yy), label, fill="#ffffff", font=font(22, True))
            rounded(draw, (62, yy + 40, w - 82, yy + 72), "#151d33", "#36466c", 1, 16)
            rounded(draw, (62, yy + 40, 62 + int((w - 144) * pct), yy + 72), color, radius=16)
            draw.text((w - 68, yy + 38), f"{int(pct * 100)}%", fill="#ffffff", font=font(20, True))
            yy += 112
    return img


def tilted_panel(size: tuple[int, int], title: str, subtitle: str, mode: str, angle: float = -7) -> Image.Image:
    panel = glass_panel(size, title, subtitle, mode)
    return panel.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def badge(draw: ImageDraw.ImageDraw, x: int, y: int, body: str, fill: str) -> None:
    rounded(draw, (x, y, x + 156, y + 34), fill, radius=17)
    draw.text((x + 17, y + 9), body, fill="#ffffff", font=F_BADGE)


def hero_copy(draw: ImageDraw.ImageDraw, badge_text: str, badge_fill: str, title: str, body: str) -> None:
    badge(draw, 50, 42, badge_text, badge_fill)
    draw.text((50, 92), title, fill="#ffffff", font=F_HERO)
    draw_wrapped(draw, (54, 156), body, "#cbd7ff", F_BODY, 790)


def opener_frame() -> Image.Image:
    img = stage().convert("RGBA")
    draw = ImageDraw.Draw(img)
    hero_copy(
        draw,
        "SHOWCASE",
        "#8b5cf6",
        "From plain Codex to Partner sparkle",
        "A boring first pass becomes a shareable interface after Claude Code plans and polishes in the same session.",
    )

    left = boring_stage().resize((360, 204))
    left_card = Image.new("RGBA", (388, 244), (0, 0, 0, 0))
    ld = ImageDraw.Draw(left_card)
    rounded(ld, (0, 0, 388, 244), "#f8fafc", "#e4e7ec", 2, 22)
    ld.text((24, 18), "BEFORE", fill="#344054", font=font(20, True))
    left_card.alpha_composite(left.convert("RGBA"), (14, 48))
    img.alpha_composite(left_card, (74, 252))

    right = tilted_panel(
        (470, 332),
        "Partner Receipt Studio",
        "Motion, depth, glow, and a proof layer that explains the collaboration.",
        "studio",
        -7,
    )
    glow_paste(img, right, (438, 196), (255, 67, 231), 30)

    rounded(draw, (424, 334, 540, 382), "#0b1020ee", "#7fffee", 2, 24)
    draw.text((452, 348), "AFTER", fill="#7fffee", font=font(19, True))
    draw.line((386, 370, 454, 370), fill="#7fffee", width=5)
    draw.polygon([(454, 370), (436, 358), (436, 382)], fill="#7fffee")
    return img.convert("RGB")


def boring_stage() -> Image.Image:
    img = Image.new("RGB", (W, H), "#eef2f7")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, H), fill="#eef2f7")
    draw.text((54, 44), "Codex-only first pass", fill="#202833", font=F_HERO)
    draw_wrapped(draw, (58, 108), "Technically correct. No motion, no story, no reason to share.", "#667085", F_BODY, 720)

    rounded(draw, (72, 174, 424, 458), "#ffffff", "#d9e1ee", 2, 10)
    draw.text((104, 206), "Partner Receipt", fill="#202833", font=F_TITLE)
    for i, label in enumerate(["Session", "Claude session", "Codex passes", "Checks"]):
        y = 268 + i * 42
        draw.text((104, y), label.upper(), fill="#8a94a6", font=F_SMALL)
        draw.rectangle((260, y + 2, 390, y + 16), fill="#e5eaf2")

    rounded(draw, (504, 174, 842, 458), "#f8fafc", "#d9e1ee", 2, 10)
    draw.text((540, 216), "Result", fill="#202833", font=F_TITLE)
    draw_wrapped(draw, (542, 270), "Readable, but flat. Claude Code has not yet added product taste.", "#667085", F_BODY, 236)
    draw.rectangle((542, 378, 806, 414), fill="#e5eaf2")
    return img


def inspiration_frame() -> Image.Image:
    img = stage().convert("RGBA")
    draw = ImageDraw.Draw(img)
    hero_copy(
        draw,
        "CASE PICKED",
        "#8b5cf6",
        "MotionSites-style hero energy",
        "Borrow the pattern, not the pixels: tilted product screens, dark depth, neon gradients, obvious visual payoff.",
    )
    p1 = tilted_panel((520, 360), "Dark Product Stage", "Big surface, one vivid focal glow, tiny proof cards orbiting the center.", "studio", -10)
    p2 = tilted_panel((320, 290), "Receipt Layer", "The collaboration remains auditable.", "receipt", 8)
    glow_paste(img, p1, (354, 176), (255, 69, 230), 28)
    glow_paste(img, p2, (76, 252), (91, 233, 255), 20)
    return img.convert("RGB")


def partner_transform_frame() -> Image.Image:
    img = stage().convert("RGBA")
    draw = ImageDraw.Draw(img)
    hero_copy(
        draw,
        "AFTER",
        "#0f8b63",
        "Claude Code adds the sparkle",
        "Same session gives UI taste, motion direction, edge-state review, and final /codex:review.",
    )
    main = tilted_panel((590, 390), "Partner Receipt Studio", "A dull receipt turns into a product demo with depth, glow, and a readable proof layer.", "studio", -8)
    side = tilted_panel((300, 330), "Session Proof", "same session reused · new p sessions: 0 · checks passed", "receipt", 9)
    glow_paste(img, main, (294, 154), (255, 67, 231), 30)
    glow_paste(img, side, (64, 228), (102, 243, 220), 22)
    draw.line((166, 390, 322, 334), fill="#7fffee", width=4)
    draw.line((784, 402, 698, 318), fill="#ffd06f", width=4)
    return img.convert("RGB")


def cost_frame() -> Image.Image:
    img = stage().convert("RGBA")
    draw = ImageDraw.Draw(img)
    hero_copy(
        draw,
        "PROOF",
        "#0f8b63",
        "Cost pressure shifts away from Claude",
        "Showcase accounting model: Codex carries implementation; Claude stays focused on plan, polish, and review.",
    )
    bars = tilted_panel((620, 370), "Workload Split", "This is a reproducible workload model, not provider billing telemetry.", "bars", -5)
    receipt = tilted_panel((250, 292), "No vague claims", "Exact token numbers require telemetry.", "receipt", 8)
    glow_paste(img, bars, (84, 216), (126, 255, 238), 24)
    glow_paste(img, receipt, (668, 210), (255, 208, 111), 20)
    rounded(draw, (680, 88, 884, 190), "#0b1020dd", "#ffd06f", 2, 24)
    draw.text((706, 92), "70%", fill="#fff1a8", font=font(66, True))
    draw.text((708, 156), "less Claude pressure", fill="#ffffff", font=font(18, True))
    return img.convert("RGB")


def receipt_frame() -> Image.Image:
    img = stage().convert("RGBA")
    draw = ImageDraw.Draw(img)
    hero_copy(
        draw,
        "RECEIPT",
        "#8b5cf6",
        "Readable proof, cinematic enough to share",
        "Partner reports session reuse, changed files, checks, remaining issues, and clear cost-claim boundaries.",
    )
    receipt = tilted_panel((540, 380), "Partner Session Receipt", "The handoff ends with evidence, not vibes.", "receipt", -3)
    glow_paste(img, receipt, (214, 184), (138, 92, 246), 24)
    rounded(draw, (98, 442, 862, 498), "#0b1020ee", "#7fffee", 2, 20)
    draw.text((128, 460), "new_claude_p_sessions: 0  |  same session reused: yes  |  checks: passed", fill="#7fffee", font=font(22, True))
    return img.convert("RGB")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        opener_frame(),
        boring_stage(),
        partner_transform_frame(),
        cost_frame(),
        receipt_frame(),
    ]
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=[1550, 1100, 1750, 1650, 1850],
        loop=0,
        optimize=True,
    )
    print(OUT)


if __name__ == "__main__":
    main()

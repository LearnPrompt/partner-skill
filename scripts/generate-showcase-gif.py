#!/usr/bin/env python3
"""Generate the README budget/receipt GIF for Partner.

The generated GIF is intentionally text-heavy: it must explain the budget
difference at GitHub README scale, not merely decorate the page.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "showcase.gif"
FONT = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
SIZE = "960x540"

BG = "#f7f3ea"
INK = "#172025"
MUTED = "#5f6c67"
LINE = "#d9d2c3"
CLAUDE = "#f0bd4f"
CODEX = "#63bda8"
BAD = "#e36f5c"
GOOD = "#257e68"
PANEL = "#ffffff"


def magick_bin() -> str:
    tool = shutil.which("magick") or shutil.which("convert")
    if not tool:
        raise SystemExit("ImageMagick is required to rebuild assets/showcase.gif")
    if not FONT.exists():
        raise SystemExit(f"Required font not found: {FONT}")
    return tool


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def base_cmd(tool: str, title: str, subtitle: str) -> list[str]:
    return [
        tool,
        "-size",
        SIZE,
        f"xc:{BG}",
        "-font",
        str(FONT),
        "-fill",
        INK,
        "-pointsize",
        "42",
        "-annotate",
        "+54+72",
        title,
        "-fill",
        MUTED,
        "-pointsize",
        "23",
        "-annotate",
        "+56+112",
        subtitle,
        "-fill",
        "none",
        "-stroke",
        LINE,
        "-strokewidth",
        "2",
        "-draw",
        "roundrectangle 44,34 916,500 24,24",
        "-stroke",
        "none",
    ]


def draw_card(cmd: list[str], x: int, y: int, w: int, h: int, color: str, title: str, body: str) -> None:
    cmd.extend(
        [
            "-fill",
            PANEL,
            "-stroke",
            color,
            "-strokewidth",
            "4",
            "-draw",
            f"roundrectangle {x},{y} {x + w},{y + h} 16,16",
            "-stroke",
            "none",
            "-fill",
            color,
            "-pointsize",
            "26",
            "-annotate",
            f"+{x + 24}+{y + 44}",
            title,
            "-fill",
            INK,
            "-pointsize",
            "21",
            "-annotate",
            f"+{x + 24}+{y + 82}",
            body,
        ]
    )


def draw_bar(cmd: list[str], x: int, y: int, width: int, fill_width: int, color: str, label: str) -> None:
    cmd.extend(
        [
            "-fill",
            "#e6dfd0",
            "-draw",
            f"roundrectangle {x},{y} {x + width},{y + 34} 14,14",
            "-fill",
            color,
            "-draw",
            f"roundrectangle {x},{y} {x + fill_width},{y + 34} 14,14",
            "-fill",
            INK,
            "-pointsize",
            "22",
            "-annotate",
            f"+{x}+{y + 70}",
            label,
        ]
    )


def frame_without(tool: str, path: Path) -> None:
    cmd = base_cmd(tool, "Without Partner", "Claude loses context after Codex implements")
    draw_card(cmd, 70, 168, 250, 130, CLAUDE, "Claude plan", "$$$ context load")
    draw_card(cmd, 355, 168, 250, 130, CODEX, "Codex build", "$ long edit loop")
    draw_card(cmd, 640, 168, 250, 130, BAD, "New Claude review", "$$$ cold start again")
    draw_bar(cmd, 70, 360, 820, 760, BAD, "Budget shape: 2 Claude starts + repeated repo explanation")
    cmd.append(str(path))
    run(cmd)


def frame_with(tool: str, path: Path) -> None:
    cmd = base_cmd(tool, "With Partner", "One Claude Code session carries plan, polish, and review")
    draw_card(cmd, 70, 168, 250, 130, CLAUDE, "Claude plan", "keep session open")
    draw_card(cmd, 355, 168, 250, 130, CODEX, "Codex build", "implement + checks")
    draw_card(cmd, 640, 168, 250, 130, GOOD, "Same-session review", "no fresh claude -p")
    draw_bar(cmd, 70, 360, 820, 455, GOOD, "Budget shape: 1 Claude session + bounded handoff")
    cmd.append(str(path))
    run(cmd)


def frame_handoff(tool: str, path: Path) -> None:
    cmd = base_cmd(tool, "Bounded Handoff", "Codex sends only the context Claude needs")
    draw_card(cmd, 80, 160, 240, 150, CODEX, "Diff stat", "changed files + why")
    draw_card(cmd, 360, 160, 240, 150, CODEX, "Checks", "tests, build, risks")
    draw_card(cmd, 640, 160, 240, 150, CLAUDE, "Ask", "polish or review")
    draw_bar(cmd, 80, 360, 800, 330, GOOD, "No whole-repo paste. No fresh review session by default.")
    cmd.append(str(path))
    run(cmd)


def frame_receipt(tool: str, path: Path) -> None:
    cmd = base_cmd(tool, "Partner Session Receipt", "The saving becomes a visible artifact")
    lines = [
        "[Partner session receipt]",
        "claude_session_reused: yes",
        "new_claude_p_sessions: 0",
        "codex_passes: 2",
        "checks: package check + schema + diff",
        "anomalies: none",
    ]
    y = 170
    for index, line in enumerate(lines):
        color = GOOD if index in (1, 2) else INK
        cmd.extend(["-fill", color, "-pointsize", "28", "-annotate", f"+92+{y}", line])
        y += 46
    draw_bar(cmd, 92, 394, 760, 760, GOOD, "Report verifiable behavior. Do not invent token numbers.")
    cmd.append(str(path))
    run(cmd)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tool = magick_bin()
    with tempfile.TemporaryDirectory(prefix="partner-showcase-") as tmp:
        tmpdir = Path(tmp)
        frames = [tmpdir / f"frame-{index}.png" for index in range(4)]
        frame_without(tool, frames[0])
        frame_with(tool, frames[1])
        frame_handoff(tool, frames[2])
        frame_receipt(tool, frames[3])
        run([tool, "-delay", "135", *map(str, frames), "-loop", "0", str(OUT)])
    print(OUT)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check that Chinese and English READMEs stay structurally aligned."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZH = ROOT / "README.md"
EN = ROOT / "README.en.md"

EXPECTED_HEADINGS = [
    ("## 30 秒装上", "## Install"),
    ("## 一句话用起来", "## Use It"),
    ("## 主 Showcase", "## Main Showcase"),
    ("## 成本压力模型", "## Cost Pressure Model"),
    ("## 它解决什么", "## What It Solves"),
    ("## 触发方式", "## Trigger Prompts"),
    ("## 它会交付什么", "## What It Delivers"),
    ("## 文件结构", "## File Map"),
    ("## 安全边界", "## Safety"),
    ("## 验证", "## Verify"),
    ("## License", "## License"),
]

REQUIRED_MARKERS = [
    "assets/showcase.gif",
    "examples/showcase-cost-ledger.json",
    "docs/showcase-cost-model.md",
    "Partner Session Receipt",
    "new_claude_p_sessions",
    "scripts/generate-showcase-gif.py",
    "scripts/showcase-cost-ledger.py",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def headings(markdown: str) -> list[str]:
    return [line.strip() for line in markdown.splitlines() if line.startswith("## ")]


def anchors(markdown: str) -> set[str]:
    return set(re.findall(r"\]\(#([^)]+)\)", markdown))


def main() -> int:
    zh = read(ZH)
    en = read(EN)
    failures: list[str] = []

    zh_headings = headings(zh)
    en_headings = headings(en)
    expected_zh = [pair[0] for pair in EXPECTED_HEADINGS]
    expected_en = [pair[1] for pair in EXPECTED_HEADINGS]

    if zh_headings != expected_zh:
        failures.append(f"README.md headings mismatch: {zh_headings!r}")
    if en_headings != expected_en:
        failures.append(f"README.en.md headings mismatch: {en_headings!r}")

    if "README.en.md" not in zh:
        failures.append("README.md must link to README.en.md")
    if "README.md" not in en:
        failures.append("README.en.md must link to README.md")

    for marker in REQUIRED_MARKERS:
        if marker not in zh:
            failures.append(f"README.md missing marker: {marker}")
        if marker not in en:
            failures.append(f"README.en.md missing marker: {marker}")

    zh_anchor_count = len(anchors(zh))
    en_anchor_count = len(anchors(en))
    if zh_anchor_count != en_anchor_count:
        failures.append(f"README anchor count differs: zh={zh_anchor_count}, en={en_anchor_count}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print("PASS README parity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    ("## Showcase", "## Showcase"),
    ("## 一句话用起来", "## Use It"),
    ("## 分宿主用法", "## Per-Host Usage"),
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
    "examples/showcase-cost-ledger.json",
    "docs/showcase-cost-model.md",
    "assets/config-switch-demo.mp4",
    "assets/config-switch-demo.gif",
    "assets/v2.0.1-conversation-cost-receipt.png",
    "Partner Session Receipt",
    "new_claude_p_sessions",
    "monitoring_level",
    "scripts/showcase-cost-ledger.py",
]

FILE_MAP_ENTRIES = [
    "SKILL.md",
    "README.md",
    "README.en.md",
    "install.sh",
    "test-prompts.json",
    "docs/showcase-cost-model.md",
    "docs/receipt-schema.json",
    "docs/config-schema.md",
    "examples/session-receipt.md",
    "examples/v2.0.0-conversation-cost-receipt.md",
    "examples/v2.0.1-conversation-cost-receipt.md",
    "examples/showcase-cost-ledger.json",
    "references/monitoring.md",
    "references/handoff-template.md",
    "references/failure-playbook.md",
    "references/scenarios.md",
    "references/darwin-ratchet.md",
    "references/codex-driven.md",
    "references/claude-driven.md",
    "references/setup.md",
    "references/tryout.md",
    "references/goal-to-pr.md",
    "references/goal-template.md",
    "references/fable5-principles.md",
    "references/bounded-planning.md",
    "references/memory-protocol.md",
    "scripts/showcase-cost-ledger.py",
    "scripts/check-readme-parity.py",
    "scripts/check-skill-repo.sh",
    "scripts/check-claude-cli.sh",
    "scripts/make-handoff.sh",
    "scripts/make-receipt.py",
    "scripts/session-snapshot.sh",
    "scripts/validate-receipt.py",
    "scripts/run-test-prompts.py",
    "scripts/run-claude-plan.py",
    "scripts/delegate-codex.sh",
    "scripts/partner-config.py",
    "scripts/partner_runtime.py",
    "scripts/partner-setup.py",
    "scripts/partner-setup-ui.py",
    "scripts/goal-sync.py",
    "tests/test_partner_config.py",
    "tests/test_partner_setup.py",
    "tests/test_partner_setup_ui.py",
    "tests/test_delegate_role.py",
    "tests/test_goal_sync.py",
    "tests/test_run_claude_plan.py",
    "idea-king/SKILL.md",
    "idea-king/README.md",
]


CURLY_QUOTES = "“”‘’"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def slugify(heading: str) -> str:
    text = heading.removeprefix("## ").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


def check_anchors_resolve(markdown: str, label: str, failures: list[str]) -> None:
    slugs = {slugify(heading) for heading in headings(markdown)}
    for anchor in sorted(anchors(markdown)):
        if anchor not in slugs:
            failures.append(f"{label} anchor #{anchor} does not match any heading")


def check_html_tags_ascii_quotes(markdown: str, label: str, failures: list[str]) -> None:
    for match in re.finditer(r"<[^<>\n]+>", markdown):
        tag = match.group(0)
        if any(quote in tag for quote in CURLY_QUOTES):
            failures.append(f"{label} HTML tag contains curly quotes: {tag}")


def headings(markdown: str) -> list[str]:
    return [line.strip() for line in markdown.splitlines() if line.startswith("## ")]


def anchors(markdown: str) -> set[str]:
    return set(re.findall(r"\]\(#([^)]+)\)", markdown))


def section(markdown: str, heading: str) -> str:
    start = markdown.find(heading)
    if start < 0:
        return ""
    next_heading = markdown.find("\n## ", start + len(heading))
    if next_heading < 0:
        return markdown[start:]
    return markdown[start:next_heading]


def assert_order(markdown: str, entries: list[str], label: str, failures: list[str]) -> None:
    positions = []
    for entry in entries:
        index = markdown.find(entry)
        if index < 0:
            failures.append(f"{label} File Map missing: {entry}")
        positions.append(index)
    present_positions = [index for index in positions if index >= 0]
    if present_positions != sorted(present_positions):
        failures.append(f"{label} File Map entries are not in the expected order")


def main() -> int:
    zh = read(ZH)
    en = read(EN)
    skill = read(ROOT / "SKILL.md")
    failures: list[str] = []

    version_match = re.search(r"(?m)^version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", skill)
    if version_match is None:
        failures.append("SKILL.md is missing a semantic version")
    else:
        expected_badge = f"[![Version: {version_match.group(1)}]"
        if expected_badge not in zh:
            failures.append(
                f"README.md version badge does not match SKILL.md {version_match.group(1)}"
            )
        if expected_badge not in en:
            failures.append(
                f"README.en.md version badge does not match SKILL.md {version_match.group(1)}"
            )

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

    assert_order(section(zh, "## 文件结构"), FILE_MAP_ENTRIES, "README.md", failures)
    assert_order(section(en, "## File Map"), FILE_MAP_ENTRIES, "README.en.md", failures)

    zh_anchor_count = len(anchors(zh))
    en_anchor_count = len(anchors(en))
    if zh_anchor_count != en_anchor_count:
        failures.append(f"README anchor count differs: zh={zh_anchor_count}, en={en_anchor_count}")

    check_anchors_resolve(zh, "README.md", failures)
    check_anchors_resolve(en, "README.en.md", failures)
    check_html_tags_ascii_quotes(zh, "README.md", failures)
    check_html_tags_ascii_quotes(en, "README.en.md", failures)

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print("PASS README parity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

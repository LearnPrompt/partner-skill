#!/usr/bin/env python3
"""Hash-checked read/write for .partner/goal.md.

goal.md has no lock (see docs/config-schema.md's neighbor design in
references/goal-to-pr.md): write frequency is low and usually one host
drives it. Instead, a write must state the sha256 it last read; if the
file changed since, the write aborts instead of silently clobbering the
other host's update.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_SCRIPT = SCRIPT_DIR / "partner-config.py"
SPEC = importlib.util.spec_from_file_location("partner_config", CONFIG_SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - installation failure
    raise RuntimeError(f"cannot load {CONFIG_SCRIPT}")
partner_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = partner_config
SPEC.loader.exec_module(partner_config)


class GoalSyncError(Exception):
    """A user-actionable goal.md read/write failure."""


def goal_path(repo: Path) -> Path:
    return repo.resolve() / ".partner" / "goal.md"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_goal(repo: Path) -> str:
    path = goal_path(repo)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_goal(repo: Path, new_text: str, expect_sha256: Optional[str]) -> str:
    """Write new_text if the file still matches expect_sha256; else abort."""

    path = goal_path(repo)
    current = read_goal(repo)
    current_hash = sha256(current)
    if expect_sha256 is None:
        if current:
            raise GoalSyncError(
                f"goal.md already exists (sha256={current_hash}); pass "
                f"--expect-sha256 {current_hash} to write over the current content, "
                "or re-read it first"
            )
    elif expect_sha256 != current_hash:
        raise GoalSyncError(
            "goal.md has been modified by another process since you last read it "
            f"(expected sha256={expect_sha256}, found {current_hash}); re-read and retry"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    partner_config.atomic_write(path, new_text)
    return sha256(new_text)


def cmd_read(args: argparse.Namespace) -> int:
    text = read_goal(args.repo)
    print(f"sha256={sha256(text)}")
    if text:
        print(text, end="" if text.endswith("\n") else "\n")
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    new_text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    new_hash = write_goal(args.repo, new_text, args.expect_sha256)
    print(f"sha256={new_hash}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hash-checked read/write for .partner/goal.md.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root (default: current directory).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("read", help="Print sha256 then the current goal.md content.")

    write_parser = subparsers.add_parser("write", help="Write goal.md if it still matches --expect-sha256.")
    write_parser.add_argument("--file", help="Read new content from this path instead of stdin.")
    write_parser.add_argument(
        "--expect-sha256",
        help="sha256 last read via 'read'; omit only when creating goal.md for the first time.",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.repo = args.repo.resolve()
    try:
        if args.command == "read":
            return cmd_read(args)
        return cmd_write(args)
    except (GoalSyncError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate a valid Partner Session Receipt.

Receipts written by hand drift in format and invite optimistic guesses.
This tool builds the receipt from arguments, auto-fills monitoring_level by
running scripts/check-claude-cli.sh, validates the result with
scripts/validate-receipt.py logic before printing, and can persist it under
the target repo's .partner/receipts/.

Usage:
    python3 make-receipt.py --phase "final fix" --claude-session abc123 \
        --reused yes --new-claude-p 0 --codex-passes 2 \
        --checks "npm test; bash lint.sh" [--anomalies none] [--save] [--repo PATH]

Tip: get a verifiable --new-claude-p value from
`bash session-snapshot.sh diff` instead of estimating it.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_receipt", SCRIPT_DIR / "validate-receipt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe_monitoring_level() -> str:
    probe = SCRIPT_DIR / "check-claude-cli.sh"
    try:
        result = subprocess.run(
            ["bash", str(probe)], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    for line in result.stdout.splitlines():
        if line.startswith("MONITORING_LEVEL="):
            return line.split("=", 1)[1].strip()
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a valid Partner Session Receipt.")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--claude-session", required=True, help="Session id, or 'none'.")
    parser.add_argument("--reused", required=True, help="yes | no | n/a")
    parser.add_argument("--new-claude-p", required=True, help="Count or 'unknown'; prefer session-snapshot.sh diff.")
    parser.add_argument("--codex-passes", required=True)
    parser.add_argument("--checks", required=True)
    parser.add_argument("--anomalies", default="none")
    parser.add_argument("--monitoring-level", default="", help="Override; default runs check-claude-cli.sh.")
    parser.add_argument("--save", action="store_true", help="Also write to <repo>/.partner/receipts/.")
    parser.add_argument("--repo", default=".", help="Target repo for --save (default: current directory).")
    args = parser.parse_args()

    fields = {
        "phase": args.phase,
        "claude_session": args.claude_session,
        "claude_session_reused": args.reused,
        "new_claude_p_sessions": args.new_claude_p,
        "codex_passes": args.codex_passes,
        "checks": args.checks,
        "anomalies": args.anomalies,
        "monitoring_level": args.monitoring_level or probe_monitoring_level(),
    }

    validator = load_validator()
    failures = validator.validate(dict(fields))
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    lines = ["[Partner session receipt]"]
    lines.extend(f"{key}: {value}" for key, value in fields.items())
    receipt = "\n".join(lines)
    print(receipt)

    if args.save:
        save_dir = Path(args.repo).resolve() / ".partner" / "receipts"
        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        save_path = save_dir / f"receipt-{stamp}.md"
        save_path.write_text(receipt + "\n", encoding="utf-8")
        print(f"saved: {save_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

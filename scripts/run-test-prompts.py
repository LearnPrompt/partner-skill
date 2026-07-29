#!/usr/bin/env python3
"""Run the Partner behavior regression prompts.

Two modes:

Static (default, CI-safe, no agent needed):
    python3 scripts/run-test-prompts.py
  Validates every entry in test-prompts.json structurally: unique ids,
  non-empty prompt, expected_behavior and must_not lists, risky command
  text confined to must_not, and receipt-contract coverage.

Live (experimental, needs a real agent):
    PARTNER_AGENT_CMD='<command>' python3 scripts/run-test-prompts.py --live
  Runs each prompt through the agent command (prompt appended as the last
  argument) and checks the output for a Partner Session Receipt block,
  which is then validated with scripts/validate-receipt.py. Live mode is
  a smoke signal, not proof: it checks the output contract, not judgment
  quality.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "test-prompts.json"
VALIDATOR = ROOT / "scripts" / "validate-receipt.py"

RISKY = re.compile(r"git reset --hard|rm -rf|force push|--force")  # risk-ok: detection pattern, not a command
REQUIRED_KEYS = {"id", "prompt", "expected_behavior", "must_not"}
RECEIPT_HEADER = "[Partner session receipt]"


def static_check(entries: list[dict]) -> list[str]:
    failures: list[str] = []

    if len(entries) < 4:
        failures.append(f"expected at least 4 cases, found {len(entries)}")

    ids = [entry.get("id") for entry in entries]
    duplicated = {case_id for case_id in ids if ids.count(case_id) > 1}
    if duplicated:
        failures.append(f"duplicate ids: {sorted(duplicated)}")

    for entry in entries:
        case_id = entry.get("id", "<missing id>")
        missing = REQUIRED_KEYS - set(entry)
        if missing:
            failures.append(f"{case_id}: missing keys {sorted(missing)}")
            continue
        if not str(entry["prompt"]).strip():
            failures.append(f"{case_id}: empty prompt")
        for list_key in ("expected_behavior", "must_not"):
            value = entry[list_key]
            if not isinstance(value, list) or not value:
                failures.append(f"{case_id}: {list_key} must be a non-empty list")
                continue
            if any(not str(item).strip() for item in value):
                failures.append(f"{case_id}: {list_key} contains an empty item")
        for text in [entry["prompt"], *entry.get("expected_behavior", [])]:
            if RISKY.search(str(text)):
                failures.append(f"{case_id}: risky command text outside must_not: {text!r}")
        if entry.get("should_trigger") not in (True, False):
            failures.append(f"{case_id}: should_trigger must be true or false")

    if not any("receipt" in str(entry.get("id", "")) for entry in entries):
        failures.append("no receipt-contract case found (expected an id containing 'receipt')")

    return failures


def live_check(entries: list[dict], agent_cmd: str) -> list[str]:
    failures: list[str] = []
    base = shlex.split(agent_cmd)
    for entry in entries:
        case_id = entry["id"]
        try:
            result = subprocess.run(
                [*base, entry["prompt"]],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append(f"{case_id}: agent command failed: {error}")
            continue
        output = result.stdout + result.stderr
        should_trigger = entry.get("should_trigger", True)
        if not should_trigger:
            if RECEIPT_HEADER in output:
                failures.append(f"{case_id}: expected no trigger, but a receipt was emitted")
            else:
                print(f"PASS live {case_id} (correctly did not trigger)")
            continue
        if RECEIPT_HEADER not in output:
            failures.append(f"{case_id}: no Partner Session Receipt in output")
            continue
        validation = subprocess.run(
            [sys.executable, str(VALIDATOR), "-"],
            input=output,
            capture_output=True,
            text=True,
        )
        if validation.returncode != 0:
            failures.append(f"{case_id}: receipt invalid: {validation.stdout.strip()}")
        else:
            print(f"PASS live {case_id}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Partner test prompts.")
    parser.add_argument("--live", action="store_true", help="Run prompts through PARTNER_AGENT_CMD.")
    args = parser.parse_args()

    entries = json.loads(PROMPTS.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        print("FAIL test-prompts.json must be a JSON array")
        return 1

    failures = static_check(entries)
    if not failures:
        print(f"PASS static checks ({len(entries)} cases)")

    if args.live and not failures:
        agent_cmd = os.environ.get("PARTNER_AGENT_CMD", "")
        if not agent_cmd:
            print("FAIL --live requires PARTNER_AGENT_CMD")
            return 1
        failures.extend(live_check(entries, agent_cmd))

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

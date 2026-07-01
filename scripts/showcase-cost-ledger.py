#!/usr/bin/env python3
"""Generate the Partner showcase cost-pressure ledger.

The default ledger uses workload units, not provider billing telemetry. If a
future run has exact token counts, pass them as JSON with --measured-json and
the script will keep measured values separate from the illustrative model.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "examples" / "showcase-cost-ledger.json"

MODEL = {
    "codex_only": {
        "label": "Codex-only",
        "codex_workload_units": 100,
        "claude_code_workload_units": 0,
        "best_for": "Low-risk tasks with no UI taste requirement",
    },
    "partner": {
        "label": "Partner",
        "codex_workload_units": 70,
        "claude_code_workload_units": 30,
        "best_for": "UI-heavy or feature-heavy tasks where Claude API cost matters",
    },
    "pure_claude_code": {
        "label": "Pure Claude Code",
        "codex_workload_units": 0,
        "claude_code_workload_units": 100,
        "best_for": "Tiny tasks or when the user explicitly wants Claude to do everything",
    },
}


def load_measured(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit("--measured-json must contain a JSON object")
    return data


def mode_row(key: str, measured: dict[str, Any]) -> dict[str, Any]:
    row = dict(MODEL[key])
    total = row["codex_workload_units"] + row["claude_code_workload_units"]
    row["claude_pressure_vs_pure_claude"] = round(row["claude_code_workload_units"] / MODEL["pure_claude_code"]["claude_code_workload_units"], 2)
    row["codex_share_of_workload"] = round(row["codex_workload_units"] / total, 2) if total else 0
    row["claude_code_share_of_workload"] = round(row["claude_code_workload_units"] / total, 2) if total else 0

    measured_mode = measured.get(key, {})
    row["measured_tokens"] = {
        "codex_input_tokens": measured_mode.get("codex_input_tokens", "unknown"),
        "codex_output_tokens": measured_mode.get("codex_output_tokens", "unknown"),
        "claude_input_tokens": measured_mode.get("claude_input_tokens", "unknown"),
        "claude_output_tokens": measured_mode.get("claude_output_tokens", "unknown"),
        "source": measured_mode.get("source", "not captured"),
    }
    return row


def build_ledger(measured: dict[str, Any]) -> dict[str, Any]:
    modes = {key: mode_row(key, measured) for key in MODEL}
    partner = modes["partner"]
    pure = modes["pure_claude_code"]
    claude_pressure_reduction = 1 - partner["claude_pressure_vs_pure_claude"]
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        generated_at = datetime.fromtimestamp(int(source_date_epoch), timezone.utc).replace(microsecond=0).isoformat()
    else:
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    return {
        "schema": "partner.showcase_cost_ledger.v1",
        "generated_at": generated_at,
        "claim_boundary": "Workload units are illustrative. Exact token-savings claims require measured token telemetry.",
        "session_receipt_fields": [
            "claude_session",
            "claude_session_reused",
            "new_claude_p_sessions",
            "codex_passes",
            "checks",
            "anomalies",
        ],
        "modes": modes,
        "comparison": {
            "partner_vs_pure_claude": {
                "claude_pressure_reduction": round(claude_pressure_reduction, 2),
                "plain_english": "In the showcase model, Partner shifts implementation and verification to Codex, leaving Claude Code focused on plan, polish, and review.",
            },
            "partner_vs_codex_only": {
                "tradeoff": "Partner spends focused Claude Code judgment to gain planning, UI polish, and review quality that Codex-only may miss.",
            },
        },
    }


def markdown_summary(ledger: dict[str, Any]) -> str:
    lines = [
        "| Mode | Codex workload | Claude Code workload | Claude pressure | Measured tokens |",
        "|---|---:|---:|---:|---|",
    ]
    for key in ["codex_only", "partner", "pure_claude_code"]:
        row = ledger["modes"][key]
        measured = row["measured_tokens"]
        measured_text = measured["source"] if measured["source"] != "not captured" else "not captured"
        lines.append(
            f"| {row['label']} | {row['codex_workload_units']} | {row['claude_code_workload_units']} | {row['claude_pressure_vs_pure_claude']}x | {measured_text} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Partner showcase cost-pressure ledger.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path.")
    parser.add_argument("--measured-json", help="Optional measured token JSON keyed by mode.")
    parser.add_argument("--markdown", action="store_true", help="Print a README-ready markdown table.")
    args = parser.parse_args()

    measured = load_measured(args.measured_json)
    ledger = build_ledger(measured)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    if args.markdown:
        print(markdown_summary(ledger))


if __name__ == "__main__":
    main()

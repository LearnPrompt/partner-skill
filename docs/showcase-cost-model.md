# Partner Showcase Cost Model

Updated: 2026-07-29

This document backs the README showcase. It separates verified behavior from illustrative cost modeling.

## What Is Verified

The Partner workflow can verify these facts without billing telemetry:

- whether one Claude Code session was reused;
- whether a fresh `claude -p` review session was opened;
- whether Codex sent a bounded handoff instead of asking Claude to rediscover the repo;
- which checks passed;
- which anomalies occurred.

These facts belong in the Partner Session Receipt.

## What Is A Model

The current showcase uses workload units, not exact API token counts:

| Mode | Codex workload | Claude Code workload | Claude pressure |
|---|---:|---:|---:|
| Codex-only | 100 | 0 | 0.0x |
| Partner | 70 | 30 | 0.3x |
| Pure Claude Code | 0 | 100 | 1.0x |

Interpretation:

- Codex-only is cheapest for Claude but may miss UI taste and a second review perspective.
- Partner keeps Claude focused on planning, UI polish, and review while Codex carries implementation and verification.
- Pure Claude Code spends Claude capacity on planning, implementation, fixes, checks, and review.

Do not present this model as measured token savings.

## Observed v2.0.1 Bounded-Planning Evidence

Partner 2.0.1 also has real cost evidence for one narrow workflow: bounded
repository planning with the configured Fable 5/xhigh identity. This evidence
does **not** replace the workload model above and does not measure the whole
Partner development loop.

| Run | Session mode | Outcome | Cost returned by Claude CLI |
|---|---|---|---:|
| v2.0.0 repository planning | fresh, unbounded | stream idle after three subagents; no plan | `$6.57` |
| `fable-candidate-r2` | fresh, bounded | local `idle_timeout`; no plan | `unknown` |
| `fable-candidate-r2-resume` | exact same session | valid eight-section plan | `$0.382695` |
| `fable-candidate-final` | fresh, bounded | valid plan; exact model/session/hashes | `$0.45282` |

The failed bounded attempt has `unknown` cost because Claude CLI did not emit a
final result/cost event before the runner's 180-second accepted-event timeout.
Partner does not estimate the missing value. The runner retained failure
metadata and recovery, the exact same session resumed successfully, and a
separate fresh candidate later passed the release gate.

See `docs/releases/v2.0.1.md` for the release boundary and
`references/bounded-planning.md` for the runtime and artifact contracts.

## How To Record A Real Showcase Run

For a measured end-to-end run, record one row per phase:

| Field | Meaning |
|---|---|
| `phase` | `claude_plan`, `codex_implementation`, `claude_polish`, `codex_fix`, `claude_review`, `codex_verify` |
| `agent` | `Claude Code` or `Codex` |
| `session_id` | Claude Code session id when applicable |
| `fresh_claude_p_sessions` | Number of one-off `claude -p` calls opened during the phase |
| `input_tokens` | Exact provider/API count if available |
| `output_tokens` | Exact provider/API count if available |
| `changed_files` | Diff scope for the phase |
| `checks` | Commands run and result |
| `receipt_evidence` | Evidence copied into the Partner Session Receipt |

When exact token fields are missing, report `unknown` and keep the workload model separate.

## README Claim Boundary

Allowed:

```text
Partner reduced Claude pressure in the showcase model by keeping Claude to plan/polish/review while Codex handled implementation.
```

Not allowed:

```text
Partner saved 70% of Claude tokens.
```

That claim requires exact Claude and Codex token telemetry from the run.

## Rebuild The Ledger

```bash
SOURCE_DATE_EPOCH=1782921600 python3 scripts/showcase-cost-ledger.py --markdown
```

Default output:

```text
examples/showcase-cost-ledger.json
```

To attach measured token telemetry later:

```bash
python3 scripts/showcase-cost-ledger.py \
  --measured-json path/to/measured-tokens.json \
  --out examples/showcase-cost-ledger.json
```

The measured JSON is keyed by mode:

```json
{
  "partner": {
    "codex_input_tokens": 120000,
    "codex_output_tokens": 8000,
    "claude_input_tokens": 30000,
    "claude_output_tokens": 5000,
    "source": "provider telemetry export"
  }
}
```

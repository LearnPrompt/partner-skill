# Claude Code Refinement Brief

Date: 2026-06-30

Purpose: give Claude Code a small, bounded code/function refinement task for Partner Skill.

## One-Line Goal

Make Partner better at reusing one Claude Code conversation instead of accidentally opening fresh Claude sessions that waste front-loaded context tokens.

## Why This Matters

Partner's promise is not "call Claude more." Partner's promise is:

```text
Claude Code: plan -> polish -> /codex:review
Codex: implement -> monitor -> verify -> receipt
```

The current docs already say this. The missing piece is operational reliability. Codex needs a small, repeatable way to track and reuse the active Claude session for a repo, then prove it in the Partner Session Receipt.

## Current Assets

- `SKILL.md` — runtime workflow and output contract.
- `references/monitoring.md` — how to inspect Claude Code sessions with PTY, `claude agents --json`, transcripts, task files, and repo evidence.
- `references/handoff-template.md` — bounded handoff shape.
- `examples/session-receipt.md` — receipt example.
- `test-prompts.json` — behavior prompts, including `session-receipt-required` and `avoid-fresh-claude-review`.
- `scripts/check-skill-repo.sh` — package readiness check.

## Problem To Refine

As of 2026-06-30, same-session reuse is a policy, not a convenience:

1. Codex starts Claude Code manually.
2. Codex must remember the session name/id.
3. If the session stalls or exits, Codex has to decide whether to resume or open a new one.
4. The final receipt depends on manual accounting: session reused, fresh `claude -p` sessions, anomalies.

This makes the expensive failure easy:

```text
Codex finishes implementation -> opens a fresh Claude review-only session -> Claude rebuilds context -> token waste
```

## Candidate Implementation

Prefer one small helper over a large framework:

```text
scripts/partner-session.sh
```

Suggested commands:

```bash
scripts/partner-session.sh start --repo . --name <task-name>
scripts/partner-session.sh status --repo .
scripts/partner-session.sh receipt --repo . --phase review --checks "bash scripts/check-skill-repo.sh ."
```

Suggested state file:

```text
.partner/session.json
```

Suggested fields:

```json
{
  "repo": "/absolute/repo/path",
  "name": "partner-task-name",
  "sessionId": "Claude session id when known",
  "pid": 12345,
  "startedAt": "2026-06-30T00:00:00Z",
  "resumeCommand": "claude --resume \"partner-task-name\"",
  "freshClaudePSessions": 0,
  "codexPasses": 0,
  "anomalies": []
}
```

Keep `.partner/session.json` local-only. Add `.partner/` to `.gitignore` if this helper is implemented.

## Acceptance Criteria

- `scripts/partner-session.sh status --repo .` can show whether a Claude Code session is currently active for this repo using `claude agents --json --cwd <repo>`.
- `receipt` prints the exact `Partner Session Receipt` format already documented in `SKILL.md`.
- The helper never starts `claude -p` for review.
- The helper records a fresh-session anomaly if no existing session is reusable.
- The helper does not commit, push, publish, deploy, or touch secrets.
- `bash scripts/check-skill-repo.sh .` remains `fail=0`.
- Add at least one test prompt or example showing the helper-driven receipt.

## Non-Goals

- Do not build a full TUI.
- Do not add telemetry or external network calls.
- Do not create release tags.
- Do not publish to a registry.
- Do not make the skill Claude-only; Partner must remain useful from Codex.

## Suggested Claude Code Prompt

```text
Read docs/current-progress.md and docs/claude-code-refinement-brief.md.

Task: propose and implement the smallest code/function refinement that makes Partner reuse one Claude Code session more reliably and produce a Partner Session Receipt.

Constraints:
- Keep the change small and reviewable.
- Prefer one helper script plus docs/tests over a framework.
- Do not use claude -p as the default review path.
- Do not commit, push, tag, release, publish, deploy, or send external messages.
- Run bash scripts/check-skill-repo.sh . and report the result.
```

## Handoff Summary For Claude

Current best next change:

```text
Implement a local session helper that tracks the active Claude Code session for a repo and prints the documented Partner Session Receipt.
```

Reason:

```text
This turns "reuse the same Claude session" from a written rule into an executable workflow, reducing accidental cold-start token waste.
```

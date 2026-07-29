---
name: partner-skill
version: 2.0.1
description: |
  搭子.skill / Partner — two-direction cost-split workflow between Claude Code and Codex. Direction A (Codex-driven): Codex orchestrates and implements; Claude Code plans (/goal), polishes UI/interaction, and runs final /codex:review in one reused session. Direction B (Claude-driven): Claude plans and splits the work, runs the idea-king adversarial gate, delegates to Codex background jobs, monitors, and full-reviews before accepting. Use on "搭子" / "双向搭子" / "搭子，恢复" (resume from .partner/), "搭子，配置" (first-run setup wizard), "搭子，试跑" (identity tryout report), 分工给 codex / 让 codex 做 / codex 后台跑 / Claude 计划 Codex 实现 / 让 Claude skip 做完, or any request to split coding work between Claude Code and Codex to save quota. Not for ordinary code review without Claude Code; do not trigger on the bare English word "partner" in unrelated contexts.
---

# 搭子.skill (Partner)

> 我的 Claude Code 和 Codex 天下第一好。

## Overview

Use this skill to run a two-agent coding workflow: Claude Code is the high-value planning, polish, and review agent; Codex is the outer orchestrator and main implementer. Keep Claude Code usage focused because it may be billed through API.

Prefer one long-lived Claude Code session for small and medium tasks: ask Claude for the plan, let Codex implement, then return the diff summary and key files to the same Claude session for UI/interaction polish and final `/codex:review`. This avoids paying Claude to rebuild the same project context and gives Claude enough continuity to improve the work.

Partner is not a delegation excuse. The user remains the owner, Codex remains accountable for repository evidence, and Claude Code is treated as a high-value collaborator whose output must be verified.

## Host Detection

Partner is one Core (this file) plus one host adapter. Decide the host once at the start and say which direction you are in:

- **The host is the runtime that actually loaded this SKILL.md.** Self-identification wins: a prompt that merely mentions the other agent ("让 codex 做", "ask Claude") never switches your identity.
- The `host=codex|claude|generic` marker in `.install-meta` (written by install.sh) is a tiebreaker only, for copies whose load path is ambiguous. It never overrides self-identification.
- A generic install (`~/.agents`) runs Core-only: state up front that adapter primitives (delegate-codex.sh background jobs, Claude session monitoring) are unavailable instead of pretending they work.
- Probing the peer CLI (`codex --version`, `check-claude-cli.sh`) only tells you what the other side can do; it never decides which adapter you load.

Then load the matching adapter:

- **Direction A — Codex-driven**: this file is loaded by Codex; Codex orchestrates and Claude Code is the high-value planning/polish/review agent. Read `references/codex-driven.md` and follow its Default Flow, Session Strategy, and Permission Policy.
- **Direction B — Claude-driven**: this file is loaded inside Claude Code and the user asks to delegate work to Codex ("双向搭子", "分工给 codex", "让 codex 做", "codex 后台跑"). Claude plans and splits the work, delegates to Codex via `bash "$PARTNER_DIR/scripts/delegate-codex.sh"` background jobs, monitors with a loop, and full-reviews the result before accepting. Read `references/claude-driven.md` and follow its five phases; the shared prompting rules live in `references/fable5-principles.md` and the wrap-up memory rules in `references/memory-protocol.md`.

Both directions end with the same Partner Session Receipt; `direction` records which flow ran.

## Configuration

On "搭子，配置", or when a Partner flow needs an identity with no
configuration yet, run the local setup UI in `references/setup.md` with
`python3 "$PARTNER_DIR/scripts/partner-setup-ui.py" --host <host> --repo <repo>`.
Do not collect the matrix through repeated chat questions when a browser is
available. The single page shows every backend, concrete model, and effort,
then delegates every preview/write to `partner-setup.py` (preview → atomic
apply → automatic smoke test). It uses beginner-safe project defaults instead
of asking scope/Git/routing questions in chat; the terminal engine remains
available for explicit advanced overrides. Three identities — deep_reasoner, fast_worker, and
arbiter (the blind second solver for contentious calls) — each carry their
own backend (which CLI executes: claude or codex), model, and effort,
freely mixed across vendors. Their values live only in
`.partner/config.toml` (project) or `~/.config/partner/config.toml`
(global) — schema in `docs/config-schema.md`; never duplicate them into
prompts or docs. On "搭子，试跑", run the identity tryout in
`references/tryout.md`: each identity executes one micro-task and the
report proves they are live on the configured models.

## Tool Location

The helper scripts referenced below live in this skill's install directory (the directory containing this SKILL.md), not in the target repo. Resolve it once as `$PARTNER_DIR` — you know it from wherever this file was loaded; otherwise probe `~/.codex/skills/partner-skill`, `~/.claude/skills/partner-skill`, `~/.agents/skills/partner-skill`, or the local clone. All scripts accept running from any cwd; repo-dependent ones take `--repo`.

## Routing Rules

- Route to Claude Code: architecture planning, implementation strategy, UI/interaction critique, final Codex Review, difficult product tradeoffs.
- Route to Codex: scaffolding, implementation, long-context code edits, tests, build fixes, repository inspection, monitoring, summaries.
- Route back to the same Claude Code session when UI quality matters or the first implementation passes technically but still needs product polish.
- Keep Kimi Work/Kimi Code Goal separate from Claude Code `/goal`; prior "Goal mode" context may refer to Kimi, not Claude.

## Bounded Claude Planning

For repository-heavy planning through a Claude-backed `deep_reasoner`,
especially at `xhigh`, use `references/bounded-planning.md` and
`scripts/run-claude-plan.py`. The outer host prepares the required
24,000-character-max evidence packet; Claude runs in safe mode with no tools or
subagents, explicit wall/valid-event idle limits, bounded stream/output/log
sizes, process-group termination, and a Claude-CLI-enforced API budget.
Model and effort come only from `.partner/config.toml`. Failure preserves a
checkpoint, sanitized events, cost metadata, and a same-session recovery
command; Partner never substitutes another model silently.

## Validation Gate

Use the Darwin-style ratchet in `references/darwin-ratchet.md` when improving this workflow or applying it to a substantial task:

- Change one workflow dimension at a time: planning, implementation, UI polish, review, monitoring, permissions, or reporting.
- Run test prompts or a real miniloop before calling an improvement better.
- Do not let the same agent be the only maker and only judge for high-risk changes.
- Keep the change only when repo evidence improves. If it regresses, use a reviewable revert, not `git reset --hard`.
- Stop when another prompt loop produces low signal or <1 point expected improvement.

## Monitoring

For active Claude Code sessions, read `references/monitoring.md`. Prefer five signals instead of trusting chat text alone:

1. PTY output from the running Claude Code session.
2. `claude agents --json --cwd <repo>` session status.
3. Claude JSONL transcript structure, without dumping full message bodies by default.
4. Optional task files under `~/.claude/tasks/<sessionId>/`.
5. Repo evidence: `git status --short`, `git diff --stat`, and relevant test/build checks.

Signals 2-4 depend on Claude Code CLI internals that can drift between versions. Probe them with `bash "$PARTNER_DIR/scripts/check-claude-cli.sh"` and report the resulting `monitoring_level` (`full`, `degraded`, or `none`) in the receipt. Never claim a signal the probe says is unavailable. When an anomaly occurs, follow the fixed recovery path in `references/failure-playbook.md`.

## Output Contract

When reporting back to the user, include:

- Current phase: planning, Codex implementation, Claude polish, review, or final fix.
- Claude Code session id when one exists.
- Files changed and checks run.
- Review findings fixed or still open.
- Whether the work is ready to commit; do not commit by default.
- Any monitoring anomaly such as idle session, permission wait, empty review output, no diff, or failed check.
- A Partner Session Receipt for non-trivial Claude Code workflows:

```text
[Partner session receipt]
phase: <planning | codex implementation | claude polish | review | final fix>
claude_session: <sessionId or none>
claude_session_reused: <yes | no | n/a>
new_claude_p_sessions: <0 | count | unknown>
codex_passes: <number of implementation/fix passes>
checks: <commands run or not run>
anomalies: <none | permission wait | idle | empty review | failed check | other>
monitoring_level: <full | degraded | none | unknown>
direction: <codex-driven | claude-driven>
codex_jobs: <0 | count>
host: <claude_code | codex | generic>
scope: <project | global | n/a>
config_source: <session | project | global | default | n/a>
roles_used: <none | JSON array of {role, host, model, effort, verified}>
receipt_schema_version: 2
```

Generate the receipt with `python3 "$PARTNER_DIR/scripts/make-receipt.py"` — it auto-fills `monitoring_level` from the probe and refuses to emit an invalid receipt. Get `new_claude_p_sessions` from `bash "$PARTNER_DIR/scripts/session-snapshot.sh" diff` so the count is computed from transcript evidence. In Direction B, set `direction: claude-driven` and `codex_jobs` to the number of `delegate-codex.sh` jobs (including fix rounds); in Direction A they are `codex-driven` and `0` unless background jobs were used. A written receipt can be re-checked any time with `validate-receipt.py` against `docs/receipt-schema.json`.

`host` is the runtime that loaded this file (see Host Detection above); `scope`
and `config_source` come straight from `partner-setup.py --status` or a
`partner-config.py resolve` call (`n/a` when the run touched no configured
role). `roles_used` lists every role actually invoked this run, each entry's
`verified` taken from the config's `verified` field, not guessed — an
unconfigured or unverified role still gets an entry with `verified: false`,
it is never omitted to make the receipt look cleaner. `receipt_schema_version`
is always `2`; a receipt missing the four fields above is a schema v1
receipt from before this contract and will fail `validate-receipt.py`, which
is the intended signal to regenerate it with the current `make-receipt.py`.

Do not fabricate token savings. When exact token telemetry is unavailable, report verifiable behavior instead: same Claude Code session reused, no fresh `claude -p` session, bounded handoff used, checks passed.

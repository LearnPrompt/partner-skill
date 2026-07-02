---
name: partner-skill
version: 1.3.0
description: |
  搭子.skill / Partner coordinates a cost-efficient workflow where Claude Code handles planning, UI/interaction polish, and final Codex Review while Codex does most implementation, long-context edits, tests, and orchestration. Slogan: 我的 Claude Code 和 Codex 天下第一好。Use when the user says or implies "搭子", "搭子.skill", "用 Claude Code goal", "让 Claude skip 做完", "Claude 计划 Codex 实现", "Claude 优化 UI", "Claude 里跑 Codex Review", "同目录打开 Claude Code", "用 Claude Code 制定计划你来实现", "搭子，恢复" (resume the last Partner task from .partner/ state), "Partner skill", "Partner workflow", or asks to split work between Claude Code and Codex to save API cost. Do not use for ordinary code review with no Claude Code involvement, and do not trigger on the bare English word "partner" in unrelated contexts.
---

# 搭子.skill (Partner)

> 我的 Claude Code 和 Codex 天下第一好。

## Overview

Use this skill to run a two-agent coding workflow: Claude Code is the high-value planning, polish, and review agent; Codex is the outer orchestrator and main implementer. Keep Claude Code usage focused because it may be billed through API.

Prefer one long-lived Claude Code session for small and medium tasks: ask Claude for the plan, let Codex implement, then return the diff summary and key files to the same Claude session for UI/interaction polish and final `/codex:review`. This avoids paying Claude to rebuild the same project context and gives Claude enough continuity to improve the work.

Partner is not a delegation excuse. The user remains the owner, Codex remains accountable for repository evidence, and Claude Code is treated as a high-value collaborator whose output must be verified.

## Tool Location

The helper scripts referenced below live in this skill's install directory (the directory containing this SKILL.md), not in the target repo. Resolve it once as `$PARTNER_DIR` — you know it from wherever this file was loaded; otherwise probe `~/.codex/skills/partner-skill`, `~/.claude/skills/partner-skill`, `~/.agents/skills/partner-skill`, or the local clone. All scripts accept running from any cwd; repo-dependent ones take `--repo`.

## Default Flow

1. Ground in the target repo.
   - Enter the concrete project directory, not the `agent-workbench` root.
   - Run `git status --short` before starting Claude Code. For a non-git target, record a bounded file inventory instead (see `references/monitoring.md`).
   - Run `bash "$PARTNER_DIR/scripts/check-claude-cli.sh"` once to learn the available monitoring level; report it in the final receipt.
   - Run `bash "$PARTNER_DIR/scripts/session-snapshot.sh" start --repo <repo>` so the receipt's new-session count is computed, not guessed.
   - Identify whether the task is greenfield, feature-heavy, UI-heavy, review-only, or debugging. When the task does not fit the default profile (review-only, debugging, non-UI, non-git, monorepo, multi-day), apply the matching profile in `references/scenarios.md`.

2. Start one Claude Code session for the expensive thinking loop.
   - For planning: start Claude Code in a PTY and set a goal.
   - Use `claude --permission-mode plan --name <task-name>` by default.
   - In the interactive session, send `/goal <clear completion condition>`.
   - Ask Claude Code for a concrete implementation plan, acceptance criteria, and UI/interaction guidance.
   - Keep this same session open for the later polish and review passes when the task is not too large.
   - Do not start a separate `claude -p` review-only session just because Codex has finished implementation. That spends tokens on cold-start context and weakens Claude's continuity.

3. Implement primarily with Codex.
   - Convert Claude Code's plan into a short checklist.
   - Make the code changes directly in Codex, using existing repo patterns.
   - Run the fastest relevant check after risky edits.
   - Keep Claude Code out of mechanical bulk edits, repeated lint fixes, and long command loops unless the user asks.

4. Send the implemented state back to the same Claude Code session for polish.
   - Use this especially for frontend UI, interaction quality, product feel, accessibility, and edge states.
   - Send a bounded payload. Use `references/handoff-template.md` when possible: the original plan, changed-file list, `git diff --stat`, test/check output, risks, open questions, and only the key file snippets or full files Claude needs. `bash "$PARTNER_DIR/scripts/make-handoff.sh"` collects the evidence half automatically.
   - Ask for prioritized findings, not broad rewrites.
   - Codex applies accepted fixes and reruns checks.

5. Run final review from the same Claude Code session.
   - In Claude Code, use `/codex:review` when available.
   - Treat findings as bug/risk/test issues first, style suggestions second.
   - Codex fixes blocking findings, reruns checks, and reports final status.
   - End with a Partner Session Receipt so the user can verify whether Claude Code context was reused.

## Session Strategy

- Small or medium task: keep one Claude Code session open for `plan -> polish -> /codex:review`.
- Treat a new Claude Code session as expensive. Open one only when there is no reusable session, the prior session is unrecoverable, or the user explicitly asks for a fresh Claude pass.
- If the same Claude session gets stuck in a prompt, permission wait, or idle state, first try to continue or resume the same session with a bounded message. Do not cold-start a replacement review unless the value clearly beats the context cost.
- Large task or huge diff: split sessions only after Codex produces a compact handoff containing the plan, changed files, key decisions, known risks, and check results.
- For large or multi-day tasks, persist the loop state under `.partner/` in the target repo (plan, handoffs via `make-handoff.sh --save`, receipts) so a lost session restarts from the newest handoff, not from zero. See `references/failure-playbook.md`.
- When the user says `搭子，恢复` or asks to resume the last Partner task, load `.partner/plan.md` plus the newest file in `.partner/handoffs/` as the cold-start payload instead of rebuilding context.
- If the same Claude session gets slow, confused, or context-heavy, close it and restart with a bounded handoff only after reporting the token tradeoff.
- Do not skip the Claude polish phase for UI/frontend work unless the user explicitly asks for a faster minimal loop.
- If `/codex:review` hangs, times out, or gets stuck in a permission prompt, record that as a monitoring finding, stop the stuck subprocess/session, and continue with Codex-side verification.
- If Claude Code produces no actionable polish, do not keep prompting it blindly. Capture the empty/low-signal result, run Codex verification, and report the limitation.
- `claude -p` is not the default Partner path. Use it only for cheap one-off questions where losing prior session context is acceptable.

## Permission Policy

- Default to `--permission-mode plan` for planning and normal permissions for implementation review.
- Use skip/bypass only when the user explicitly asks for `skip`, `最高权限`, `全部允许`, `bypass`, or when the work is inside an intentionally isolated worktree.
- Treat `skip` as a permission escalation only when it clearly refers to Claude Code's permission mode (for example `让 Claude skip 做完`). When `skip` could mean skipping a workflow step (for example `skip the polish`, `跳过这一步`), ask one clarifying question instead of launching bypassPermissions.
- For skip mode, start Claude Code with `claude --permission-mode bypassPermissions --name <task-name>` or `claude --dangerously-skip-permissions --name <task-name>`.
- Before any skip session, state the repo path, current git status, intended scope, and stop condition.
- Never let skip mode commit, push, deploy, send messages, publish, or touch secrets unless the user gives a separate explicit instruction.
- Never treat `skip` as permission to ignore repo evidence. `skip` changes Claude Code permissions, not Partner's verification duty.
- Keep repository visibility changes, release tags, registry publication, and external announcements behind a separate explicit publish instruction.

## Routing Rules

- Route to Claude Code: architecture planning, implementation strategy, UI/interaction critique, final Codex Review, difficult product tradeoffs.
- Route to Codex: scaffolding, implementation, long-context code edits, tests, build fixes, repository inspection, monitoring, summaries.
- Route back to the same Claude Code session when UI quality matters or the first implementation passes technically but still needs product polish.
- Keep Kimi Work/Kimi Code Goal separate from Claude Code `/goal`; prior "Goal mode" context may refer to Kimi, not Claude.

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
```

Generate the receipt with `python3 "$PARTNER_DIR/scripts/make-receipt.py"` — it auto-fills `monitoring_level` from the probe and refuses to emit an invalid receipt. Get `new_claude_p_sessions` from `bash "$PARTNER_DIR/scripts/session-snapshot.sh" diff` so the count is computed from transcript evidence. A written receipt can be re-checked any time with `validate-receipt.py` against `docs/receipt-schema.json`.

Do not fabricate token savings. When exact token telemetry is unavailable, report verifiable behavior instead: same Claude Code session reused, no fresh `claude -p` session, bounded handoff used, checks passed.

---
name: claude-codex-relay
description: |
  Coordinate a cost-efficient workflow where Claude Code handles planning, UI/interaction polish, and final Codex Review while Codex does most implementation, long-context edits, tests, and orchestration. Use when the user says or implies "用 Claude Code goal", "让 Claude skip 做完", "Claude 计划 Codex 实现", "Claude 优化 UI", "Claude 里跑 Codex Review", "同目录打开 Claude Code", "用 Claude Code 制定计划你来实现", or asks to split work between Claude Code and Codex to save API cost.
---

# Claude-Codex 双擎接力

## Overview

Use this skill to run a two-agent coding workflow: Claude Code is the high-value planning, polish, and review agent; Codex is the outer orchestrator and main implementer. Keep Claude Code usage focused because it may be billed through API.

Prefer a single Claude Code session for small and medium tasks: ask Claude for the plan, let Codex implement, then return the diff summary and key files to the same Claude session for UI/interaction polish and final `/codex:review`. This usually avoids paying Claude to rebuild the same project context multiple times.

## Default Flow

1. Ground in the target repo.
   - Enter the concrete project directory, not the `agent-workbench` root.
   - Run `git status --short` before starting Claude Code.
   - Identify whether the task is greenfield, feature-heavy, UI-heavy, review-only, or debugging.

2. Start one Claude Code session for the expensive thinking loop.
   - For planning: start Claude Code in a PTY and set a goal.
   - Use `claude --permission-mode plan --name <task-name>` by default.
   - In the interactive session, send `/goal <clear completion condition>`.
   - Ask Claude Code for a concrete implementation plan, acceptance criteria, and UI/interaction guidance.
   - Keep this same session open for the later polish and review passes when the task is not too large.

3. Implement primarily with Codex.
   - Convert Claude Code's plan into a short checklist.
   - Make the code changes directly in Codex, using existing repo patterns.
   - Run the fastest relevant check after risky edits.
   - Keep Claude Code out of mechanical bulk edits, repeated lint fixes, and long command loops unless the user asks.

4. Send the implemented state back to the same Claude Code session for polish.
   - Use this especially for frontend UI, interaction quality, product feel, accessibility, and edge states.
   - Send a bounded payload: the original plan, changed-file list, `git diff --stat`, test/check output, and only the key file snippets or full files Claude needs.
   - Ask for prioritized findings, not broad rewrites.
   - Codex applies accepted fixes and reruns checks.

5. Run final review from the same Claude Code session.
   - In Claude Code, use `/codex:review` when available.
   - Treat findings as bug/risk/test issues first, style suggestions second.
   - Codex fixes blocking findings, reruns checks, and reports final status.

## Session Strategy

- Small or medium task: keep one Claude Code session open for `plan -> polish -> /codex:review`.
- Large task or huge diff: split sessions only after Codex produces a compact handoff containing the plan, changed files, key decisions, known risks, and check results.
- If the same Claude session gets slow, confused, or context-heavy, close it and restart with a bounded handoff instead of pasting the whole repo state.
- Do not skip the Claude polish phase for UI/frontend work unless the user explicitly asks for a faster minimal loop.
- If `/codex:review` hangs, times out, or gets stuck in a permission prompt, record that as a monitoring finding, stop the stuck subprocess/session, and continue with Codex-side verification.

## Permission Policy

- Default to `--permission-mode plan` for planning and normal permissions for implementation review.
- Use skip/bypass only when the user explicitly asks for `skip`, `最高权限`, `全部允许`, `bypass`, or when the work is inside an intentionally isolated worktree.
- For skip mode, start Claude Code with `claude --permission-mode bypassPermissions --name <task-name>` or `claude --dangerously-skip-permissions --name <task-name>`.
- Before any skip session, state the repo path, current git status, intended scope, and stop condition.
- Never let skip mode commit, push, deploy, send messages, publish, or touch secrets unless the user gives a separate explicit instruction.

## Routing Rules

- Route to Claude Code: architecture planning, implementation strategy, UI/interaction critique, final Codex Review, difficult product tradeoffs.
- Route to Codex: scaffolding, implementation, long-context code edits, tests, build fixes, repository inspection, monitoring, summaries.
- Route back to the same Claude Code session when UI quality matters or the first implementation passes technically but still needs product polish.
- Keep Kimi Work/Kimi Code Goal separate from Claude Code `/goal`; prior "Goal mode" context may refer to Kimi, not Claude.

## Monitoring

For active Claude Code sessions, read `references/monitoring.md`. Prefer five signals instead of trusting chat text alone:

1. PTY output from the running Claude Code session.
2. `claude agents --json --cwd <repo>` session status.
3. Claude JSONL transcript structure, without dumping full message bodies by default.
4. Optional task files under `~/.claude/tasks/<sessionId>/`.
5. Repo evidence: `git status --short`, `git diff --stat`, and relevant test/build checks.

## Output Contract

When reporting back to the user, include:

- Current phase: planning, Codex implementation, Claude polish, review, or final fix.
- Claude Code session id when one exists.
- Files changed and checks run.
- Review findings fixed or still open.
- Whether the work is ready to commit; do not commit by default.

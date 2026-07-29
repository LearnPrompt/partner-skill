# Codex-Driven Partner Flow (Direction A)

Use this flow when the skill is loaded by Codex: Codex is the outer
orchestrator and main implementer, and Claude Code is the high-value
planning, polish, and review agent reached through one long-lived session.
Host detection, shared routing rules, the validation gate, monitoring
signals, and the Partner Session Receipt contract live in `SKILL.md`;
this file holds only the Codex-driven flow itself.

All helper scripts live in `$PARTNER_DIR` (see Tool Location in `SKILL.md`).

## Default Flow

1. Ground in the target repo.
   - Enter the concrete project directory, not the `agent-workbench` root.
   - Run `git status --short` before starting Claude Code. For a non-git target, record a bounded file inventory instead (see `references/monitoring.md`).
   - Run `bash "$PARTNER_DIR/scripts/check-claude-cli.sh"` once to learn the available monitoring level; report it in the final receipt.
   - Run `bash "$PARTNER_DIR/scripts/session-snapshot.sh" start --repo <repo>` so the receipt's new-session count is computed, not guessed.
   - Identify whether the task is greenfield, feature-heavy, UI-heavy, review-only, or debugging. When the task does not fit the default profile (review-only, debugging, non-UI, non-git, monorepo, multi-day), apply the matching profile in `references/scenarios.md`.

2. Start one Claude Code session for the expensive thinking loop.
   - For repository-heavy planning through a Claude-backed `deep_reasoner`,
     especially at `xhigh`, follow `references/bounded-planning.md`: Codex
     prepares the contract packet and invokes
     `python3 "$PARTNER_DIR/scripts/run-claude-plan.py"`. The runner preserves a
     resumable session id while disabling tools and subagents.
   - For small interactive planning, or when the user explicitly asks for
     Claude Code `/goal`, start Claude Code in a PTY with
     `claude --permission-mode plan --name <task-name>` and send
     `/goal <clear completion condition>`.
   - Ask Claude Code for a concrete implementation plan, acceptance criteria, and UI/interaction guidance.
   - Reuse the bounded runner's session id or the interactive session for later
     polish and review when it remains healthy.
   - Do not start a separate cold review session just because Codex has finished
     implementation. That spends tokens on rediscovery and weakens continuity.

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
- Raw `claude -p` is not the default Partner path. The bounded runner is the
  only default print-mode exception: it supplies limits, artifacts, config-only
  model resolution, and a resumable session id. Use raw print mode only for a
  cheap one-off where losing prior context is acceptable.

## Permission Policy

- Default to `--permission-mode plan` for planning and normal permissions for implementation review.
- Use skip/bypass only when the user explicitly asks for `skip`, `最高权限`, `全部允许`, `bypass`, or when the work is inside an intentionally isolated worktree.
- Treat `skip` as a permission escalation only when it clearly refers to Claude Code's permission mode (for example `让 Claude skip 做完`). When `skip` could mean skipping a workflow step (for example `skip the polish`, `跳过这一步`), ask one clarifying question instead of launching bypassPermissions.
- For skip mode, start Claude Code with `claude --permission-mode bypassPermissions --name <task-name>` or `claude --dangerously-skip-permissions --name <task-name>`.
- Before any skip session, state the repo path, current git status, intended scope, and stop condition.
- Never let skip mode commit, push, deploy, send messages, publish, or touch secrets unless the user gives a separate explicit instruction.
- Never treat `skip` as permission to ignore repo evidence. `skip` changes Claude Code permissions, not Partner's verification duty.
- Keep repository visibility changes, release tags, registry publication, and external announcements behind a separate explicit publish instruction.

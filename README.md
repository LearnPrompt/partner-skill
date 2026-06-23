# Claude-Codex 双擎接力

> Let Claude Code spend on judgment, and let Codex spend time on implementation.

English name: `Claude Codex Relay`

Skill id / repo name: `claude-codex-relay`

This is a private Codex skill for coordinating a cost-efficient two-agent coding workflow: Claude Code plans, polishes UI/interaction details, and runs final Codex Review; Codex implements, monitors, fixes, verifies, and reports.

For small and medium tasks, keep Claude Code in one conversation: plan first, let Codex implement, then send a bounded diff summary back to the same Claude session for polish and `/codex:review`. Split sessions only when the diff or conversation becomes too large.

## Quick Start

Use one of these prompts:

```text
用 Claude Code goal 先规划，你 Codex 来实现。
同一个 Claude Code 对话里先出 plan，你实现后再让它 polish 和 /codex:review。
让 Claude skip 做完这个 UI 交互优化，你监控它。
Claude 里跑 Codex Review 验收当前 diff，发现问题你来修。
```

## What It Delivers

- A clear routing rule for Claude Code vs Codex work.
- A single-session default for lower-token Claude plan, polish, and review loops.
- A safer permission policy for `skip` / `bypassPermissions`.
- A monitoring checklist for Claude Code PTY sessions, `claude agents --json`, JSONL transcripts, optional task files, and repo evidence.
- A final report format with phase, session id, changed files, checks, open findings, and ready-to-commit status.

## Safety Boundaries

- Do not use `claude -p` to send `/goal`; `/goal` is an interactive Claude Code command.
- Do not let skip mode commit, push, deploy, publish, send external messages, or touch secrets without a separate explicit instruction.
- Do not trust Claude Code completion text without checking repository evidence.
- Keep Kimi Work / Kimi Code Goal separate from Claude Code `/goal`.

## Local Test Prompt Examples

See `test-prompts.json` for dry-run examples covering same-session planning/polish/review, explicit skip mode, and Claude Code `/codex:review` handoff.

Validate the prompt list locally:

```bash
jq -r '.[].id' test-prompts.json
```

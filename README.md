# 搭子.skill (Partner)

> 我的 Claude Code 和 Codex 天下第一好。

Give Codex a Claude Code partner. Claude thinks, critiques, and reviews; Codex implements, monitors, fixes, and proves the work is ready.

`partner-skill` is a workflow skill for cost-aware multi-agent coding. It keeps Claude Code focused on high-leverage judgment, UI/interaction polish, and final review while Codex carries the long-context implementation loop.

## Why Install It

Use Partner when one agent alone is the wrong shape for the job:

- You want Claude Code's planning, taste, and review without paying it to do every mechanical edit.
- You want Codex to implement, test, and monitor Claude Code sessions from the outside.
- You want a repeatable handoff protocol instead of ad hoc "ask Claude, then ask Codex" switching.
- You need a safety policy for `skip` / `bypassPermissions` before letting Claude Code touch a repo.

## Install

Install into Codex:

```bash
git clone https://github.com/LearnPrompt/partner-skill.git
cd partner-skill
bash install.sh --target codex
```

Install into Claude Code too:

```bash
bash install.sh --target claude
```

Validate the package:

```bash
bash scripts/check-skill-repo.sh .
jq -r '.[].id' test-prompts.json
```

## Trigger Partner

Use one of these prompts:

```text
用 Claude Code goal 先规划，你 Codex 来实现。
同一个 Claude Code 对话里先出 plan，你实现后再让它 polish 和 /codex:review。
让 Claude skip 做完这个 UI 交互优化，你监控它。
Claude 里跑 Codex Review 验收当前 diff，发现问题你来修。
```

Expected loop:

```text
Claude Code same session:
  plan -> polish -> /codex:review

Codex:
  implement -> verify -> monitor -> fix -> report
```

## What It Delivers

- A clear routing rule for Claude Code vs Codex work.
- A single-session default for lower-token Claude plan, polish, and review loops.
- A safer permission policy for `skip` / `bypassPermissions`.
- A monitoring checklist for Claude Code PTY sessions, `claude agents --json`, JSONL transcripts, optional task files, and repo evidence.
- A bounded handoff template so Claude gets the useful context, not the whole repo pasted back at it.
- A Darwin-style validation gate: one improvement dimension at a time, test prompts required, keep changes only when they improve the package.
- A final report format with phase, session id, changed files, checks, open findings, and ready-to-commit status.

## Example: Skill Inventory Mini-Loop

The first live Partner run built `skill-inventory`, a local dashboard that scans installed agent skills and flags duplicates, risky keywords, and missing metadata.

The useful evidence was not "Claude said done." The useful evidence was:

- Claude Code produced an implementation plan.
- Codex implemented the app and tests.
- Claude Code `/codex:review` got stuck in a background companion process.
- Partner's monitoring contract caught the busy session and empty review output.
- Codex stopped the stuck subprocess, verified the repo, and reported the residual review risk.

See [examples/skill-inventory-miniloop.md](examples/skill-inventory-miniloop.md).

## Safety Boundaries

- Do not use `claude -p` to send `/goal`; `/goal` is an interactive Claude Code command.
- Do not let skip mode commit, push, deploy, publish, send external messages, or touch secrets without a separate explicit instruction.
- Do not trust Claude Code completion text without checking repository evidence.
- Keep Kimi Work / Kimi Code Goal separate from Claude Code `/goal`.
- Do not use `git reset --hard` as the default rollback path. Prefer a reviewable diff or `git revert`.
- Do not let the same agent both make a high-risk change and be the only reviewer.

## File Map

```text
SKILL.md                         Runtime instructions for Codex/Claude-compatible agents
README.md                        Human-facing install, value, examples, and safety boundaries
install.sh                       Local installer for Codex, Claude Code, Agents, or all targets
test-prompts.json                Trigger and behavior regression prompts
references/monitoring.md         How Codex monitors Claude Code progress
references/handoff-template.md   Bounded context packet for Claude Code polish/review
references/darwin-ratchet.md     Validation-gated improvement rules
scripts/check-skill-repo.sh      Publish readiness smoke check
examples/skill-inventory-miniloop.md
```

## Local Test Prompt Examples

See `test-prompts.json` for dry-run examples covering same-session planning/polish/review, explicit skip mode, and Claude Code `/codex:review` handoff.

Validate the prompt list locally:

```bash
jq -r '.[].id' test-prompts.json
```

## Release Checklist

- [ ] `bash scripts/check-skill-repo.sh .`
- [ ] `jq -r '.[].id' test-prompts.json`
- [ ] No secrets, tokens, cookies, private keys, or `.env` values in tracked files.
- [ ] README explains who should install it, when to trigger it, and what output proves success.
- [ ] `references/handoff-template.md` and `references/monitoring.md` still match the real workflow.
- [ ] At least one real miniloop example is present under `examples/`.

<sub>🌐 <a href="README.md">中文</a> · <b>English</b></sub>

<div align="center">

# Partner Skill

> My Claude Code and Codex are the best coding partners.

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-partner--skill-blueviolet)](SKILL.md)
[![GitHub stars](https://img.shields.io/github/stars/LearnPrompt/partner-skill?style=flat-square&color=f5c542)](https://github.com/LearnPrompt/partner-skill/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Let Claude Code handle high-value planning, polish, and review. Let Codex implement, monitor, and verify. End with a Session Receipt that proves whether you avoided fresh Claude cold starts.**

[Install](#install) · [Use It](#use-it) · [Budget Demo](#budget-demo) · [What It Solves](#what-it-solves) · [Safety](#safety) · [Verify](#verify)

</div>

---

## Install

Ask your agent to install from GitHub:

```text
Please install Partner Skill: https://github.com/LearnPrompt/partner-skill
```

Or install with `npx`:

```bash
npx skills add LearnPrompt/partner-skill -g
```

Manual local install:

```bash
git clone https://github.com/LearnPrompt/partner-skill.git
cd partner-skill
bash install.sh --target codex
bash install.sh --target claude
```

## Use It

```text
Partner, use the same Claude Code session for planning first.
After Codex implements, send the diff back to that same session for UI polish
and /codex:review. End with a Partner Session Receipt showing whether
any fresh claude -p session was opened.
```

Short version:

```text
Partner: Claude plans, Codex implements, same-session review, then receipt.
```

## Budget Demo

![Partner session budget demo](assets/showcase.gif)

Partner is not "call Claude more." Partner is **avoid repeated Claude cold starts**.

| Without Partner | With Partner |
|---|---|
| Claude plans once, then a fresh Claude review session starts after Codex edits | One Claude Code session keeps the plan context |
| Each review re-explains the repo, goal, and diff | Codex sends a bounded handoff back to the same session |
| Token savings stay hand-wavy | The receipt says `new_claude_p_sessions: 0` |

Receipt example:

```text
[Partner session receipt]
phase: final fix
claude_session: 9836fe7e-4aca-47a6-83b5-69086b8db275
claude_session_reused: yes
new_claude_p_sessions: 0
codex_passes: 2
checks: bash scripts/check-skill-repo.sh .; jq schema check; git diff --check
anomalies: none
```

When exact token telemetry is unavailable, Partner does not invent savings. It reports verifiable behavior: same Claude Code session reused, no fresh `claude -p`, checks passed, anomalies captured.

## What It Solves

You may already switch between Codex and Claude Code. The pain is not whether they can collaborate. The pain is context waste:

- Claude Code is valuable for planning, UI taste, and review, but expensive for every mechanical edit.
- Codex is strong at implementation, long-context fixes, and running checks, but benefits from a second review perspective.
- The expensive failure mode is opening a new Claude session after Codex edits, forcing Claude to rediscover the repo.
- Users hear "I used Claude" but cannot see whether the workflow saved money.

Partner turns this into a protocol:

```text
Claude Code same session:
  plan -> polish -> /codex:review

Codex:
  implement -> verify -> monitor -> fix -> receipt
```

## Trigger Prompts

```text
Partner
Use Claude Code goal for the plan, then Codex implements.
Use the same Claude Code chat for plan, polish, and /codex:review.
Let Claude skip this UI polish task, and Codex monitors it.
Run Codex Review inside Claude Code, then Codex fixes the findings.
```

Chinese triggers such as `搭子` and `搭子.skill` are also first-class triggers.

## What It Delivers

- Clear routing: Claude Code plans, polishes, and reviews; Codex implements, monitors, verifies, and fixes.
- A cost-aware default: keep one Claude Code session for small and medium tasks.
- A bounded handoff: plan, changed files, diff stat, checks, risks, and only the snippets Claude needs.
- Monitoring evidence: PTY output, `claude agents --json`, transcript structure, optional task files, and repo checks.
- A Session Receipt: proof of session reuse, fresh `claude -p` count, checks, and anomalies.
- A Darwin-style ratchet: improve one workflow dimension at a time and keep only verified gains.

## Safety

- Do not send `/goal` through `claude -p`; `/goal` is an interactive Claude Code command.
- Use `skip` / `bypassPermissions` only when the user explicitly asks or when the worktree is isolated.
- Skip mode does not allow commit, push, deploy, publish, external messages, or secrets access by default.
- Do not use a fresh `claude -p` final review by default. Continue or resume the same Claude Code session first.
- Do not change repo visibility, tag releases, publish to registries, or announce externally without explicit permission.
- Do not use `git reset --hard` as the default rollback path. Prefer reviewable diffs or reverts.

## Verify

```bash
bash scripts/check-skill-repo.sh .
jq -r '.[].id' test-prompts.json
python3 scripts/generate-showcase-gif.py
```

Passing evidence:

- `SKILL.md` includes the bare `搭子` trigger.
- README explains "fewer Claude cold starts" within 10 seconds.
- `assets/showcase.gif` makes the budget difference readable.
- `Partner Session Receipt` appears in `SKILL.md`, README, and test prompts.
- Local check returns `fail=0`; the only allowed warning is the safety text that explicitly forbids high-risk commands.

## License

MIT

# Partner Skill Current Progress

Created: 2026-06-30

Last checked: 2026-07-01

Repo: https://github.com/LearnPrompt/partner-skill

Local path: `/Users/carl/projects/partner-skill`

## Current State

- GitHub visibility is public.
- Default branch is `main`.
- The public README is Chinese-first and links to `README.en.md`.
- The English README links back to `README.md`.
- `assets/showcase.gif` is now the primary cinematic showcase: boring Codex-only first pass -> Partner trigger -> Claude Code polish -> cost-pressure model -> Session Receipt.
- The showcase was rebuilt on 2026-07-01 with a MotionSites-style visual mechanism: dark stage, tilted product surfaces, violet-magenta glow, and obvious before/after contrast. It uses generated local artwork only.
- `Partner Session Receipt` is part of the runtime contract, README proof, test prompts, example, and package check.
- `examples/skill-inventory-miniloop.md` is the one retained previous safety-skill mini-loop example; it is not the main public showcase.
- The Claude Code refinement task is documented but not implemented in code.
- No `scripts/partner-session.sh` helper exists as of 2026-07-01.

## Important Commits

- `258779f` — Add Partner session receipt for public release.
- `2eac3c1` — Split README languages and rebuild budget showcase.
- `ad19e6c` — Upgrade Partner showcase and release docs.
- `efed0d8` — Add reproducible Partner cost ledger.
- `8ebb5cf` — Add README parity release gate.
- `3418b60` — Make showcase visually obvious.

## Verification Already Passing

```bash
bash scripts/check-skill-repo.sh .
jq -e 'type == "array" and length == 9 and all(.[]; has("id") and has("prompt") and has("expected_behavior") and has("must_not"))' test-prompts.json
bash install.sh --target codex --dry-run
bash install.sh --target claude --dry-run
python3 scripts/generate-showcase-gif.py
SOURCE_DATE_EPOCH=1782921600 python3 scripts/showcase-cost-ledger.py
git diff --check
```

Known warning:

```text
WARN high-risk command text found
```

This is expected because safety docs explicitly forbid `git reset --hard`.

## 2026-07-01 Claude Code Follow-Up Check

Codex checked whether Claude Code had implemented the refinement brief. Result:

- No new commit exists after `2eac3c1` on `main`.
- `git status --short --branch` shows only the handoff docs, README entries, and readiness check updates.
- `find . -maxdepth 3 -type f -name '*partner*' -o -name '*session*'` finds only `examples/session-receipt.md`.
- `claude agents --json --cwd /Users/carl/projects/partner-skill` returns `[]` when no active Claude Code session is attached.
- There is no `scripts/partner-session.sh` and no `.partner/session.json`.

Conclusion: the handoff package is ready, but the helper implementation has not landed in this repo.

## Current Problem

Partner's product promise depends on reusing one Claude Code conversation:

```text
Claude Code same session:
  plan -> polish -> /codex:review

Codex:
  implement -> verify -> monitor -> fix -> receipt
```

The current workflow is still too manual. Codex can launch Claude Code in a PTY, but keeping that same conversation stable across planning, handoff, polish, and review is fragile. If Codex opens a fresh Claude conversation for review, Claude pays the same expensive project-context cold start again.

The next refinement should make same-session reuse more reliable and visible.

## Next Best Work

Hand this to Claude Code as a focused code/function refinement task:

```text
Read Claude Code Refinement Brief at docs/claude-code-refinement-brief.md and propose one small implementation plan.
Do not rewrite the skill. Focus only on making same-session Claude Code reuse easier to execute and easier to verify.
```

The target is not another long methodology section. The target is a small, testable helper or workflow adjustment that reduces accidental fresh Claude sessions.

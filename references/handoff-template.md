# Partner Handoff Template

Use this packet when Codex sends the implemented state back to the same Claude Code session for polish or final review. Keep it bounded. Do not paste the whole repo unless the repo is tiny.

```markdown
# Partner Handoff

## Task
[One sentence: what the user asked for.]

## Claude Plan
[The plan Claude already gave, or a 5-bullet summary.]

## Codex Implementation
- Changed files:
  - ...
- Key decisions:
  - ...
- Known tradeoffs:
  - ...

## Repo Evidence
```bash
git status --short
git diff --stat
[fastest relevant check command and output summary]
```

## What I Need From Claude
Choose exactly one:

1. UI/interaction polish: return prioritized findings only.
2. Architecture/product critique: return blocking risks only.
3. `/codex:review`: review the current diff for bugs, regressions, missing tests, and unsafe behavior.

## Scope Boundary
- Do not commit, push, deploy, publish, or send external messages.
- Do not touch secrets or `.env` files.
- If you need more context, ask for the smallest file or snippet that unblocks the review.

## Partner Session Receipt
Fill this at the end of the loop:

```text
[Partner session receipt]
phase: <planning | codex implementation | claude polish | review | final fix>
claude_session: <sessionId or none>
claude_session_reused: <yes | no | n/a>
new_claude_p_sessions: <0 | count | unknown>
codex_passes: <number>
checks: <commands run or not run>
anomalies: <none | permission wait | idle | empty review | failed check | other>
```
```

## Good Handoff Rules

- Include `git diff --stat`; include full diffs only for small files.
- Include check output summaries, not entire noisy logs.
- Name the exact phase: `plan`, `polish`, `review`, or `fix`.
- Ask for prioritized findings. Do not ask for a broad rewrite unless the user requested one.
- If Claude Code returns style-only ideas after the app already works, Codex decides whether they are worth applying.
- Include a Partner Session Receipt whenever Claude Code was involved.

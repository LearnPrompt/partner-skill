# Monitoring Claude Code From Codex

Use these checks when Codex launches or supervises a Claude Code session.

## Session Status

List Claude Code sessions for the target repo:

```bash
claude agents --json --cwd "$REPO"
```

Useful fields:

- `sessionId`: use this to locate transcripts and task files.
- `status`: watch for `idle`, active/running states, or missing sessions.
- `pid`: confirm the process still exists.
- `cwd`: verify Claude is operating in the intended repo.

If there are multiple sessions, prefer the one with the target `cwd`, latest `startedAt`, and matching `--name` from the launch command.

## Transcript Structure

Find the transcript by session id:

```bash
TRANSCRIPT="$(find "$HOME/.claude/projects" -name "$SESSION_ID.jsonl" -print -quit)"
```

Inspect structure without dumping full message bodies:

```bash
tail -n 30 "$TRANSCRIPT" \
  | jq -r '[.timestamp, .type, .subtype, .message.role, .stopReason, .toolUseID, .hasOutput] | @tsv'
```

Only read full text when it is necessary to recover a plan, error, or review finding. Do not paste secrets, credentials, `.env` values, or private keys from transcripts into chat or files.

## Task Files

Claude task files may exist at:

```bash
$HOME/.claude/tasks/$SESSION_ID/
```

Summarize task status:

```bash
if [ -d "$HOME/.claude/tasks/$SESSION_ID" ]; then
  find "$HOME/.claude/tasks/$SESSION_ID" -maxdepth 1 -type f -name '*.json' -print \
    | sort \
    | xargs -I{} jq -r '[input_filename | split("/")[-1], .status, .subject, (.blockedBy // "")] | @tsv' {}
fi
```

Treat tasks as advisory. Repo state and checks are the source of truth.

## Repo Evidence

Run these from the target repo only after confirming it is a Git repository:

```bash
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git status --short
  git diff --stat
  git diff --name-only
else
  echo "NOT_GIT_REPO: skip git status/diff; record a bounded file inventory instead"
  find . -maxdepth 2 -type f -not -path '*/.DS_Store' | sort | sed 's#^\./##' | head -80
fi
```

Then run the fastest relevant verification command for the project, such as a targeted test, typecheck, lint, or build. Prefer existing scripts from `package.json`, `pyproject.toml`, `Makefile`, or repo docs.

## Progress Interpretation

- `idle` plus no diff usually means Claude stopped before doing useful work.
- `idle` plus meaningful diff means inspect and verify the changes.
- Active session plus growing transcript means wait and poll again.
- Active session plus no transcript/diff growth for several polls means check PTY output for prompts, permission waits, or crashes.
- Non-Git target plus a bounded file inventory is acceptable for local skill folders, handoff packs, or scratch prototypes.
- Any check failure becomes a Codex implementation task unless the failure is caused by missing external credentials or user-only context.

## Token-Aware Recovery

When Claude Code stalls, preserve continuity before opening a new session:

1. Capture the current `sessionId`, `pid`, PTY state, and last useful output.
2. If the process is waiting for approval, answer or cancel inside the same PTY when safe.
3. If the session exits, resume it with the printed `claude --resume <name-or-id>` command when available.
4. If resume is unavailable, start a fresh session only with a bounded handoff and state that this is a token tradeoff.
5. Do not use `claude -p` as a replacement for final review after a rich interactive planning session unless the user explicitly asks for that cheap one-off path.

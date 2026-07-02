#!/usr/bin/env bash
# Generate a bounded Partner handoff from live repo evidence.
#
# Automates the evidence half of references/handoff-template.md so the
# handoff Codex sends back to the same Claude Code session never forgets
# git status, diff stat, or check output. Judgment fields (plan summary,
# key decisions, tradeoffs) stay as explicit TODO markers for the agent.
#
# Usage:
#   bash scripts/make-handoff.sh [options]
#
# Options:
#   --task "..."      One-sentence task description
#   --phase X         polish | review | fix (default: polish)
#   --repo PATH       Target repo (default: current directory)
#   --check "cmd"     Check command to run; its tail is embedded as evidence
#   --save            Also write the handoff to .partner/handoffs/ in the repo
#
# Prints the handoff markdown to stdout. With --save, the saved path is
# printed to stderr so stdout stays clean for piping.
set -euo pipefail

TASK="[TODO: one sentence — what the user asked for]"
PHASE="polish"
REPO="$(pwd)"
CHECK_CMD=""
SAVE="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --task) TASK="${2:?--task needs a value}"; shift 2 ;;
    --phase) PHASE="${2:?--phase needs a value}"; shift 2 ;;
    --repo) REPO="${2:?--repo needs a value}"; shift 2 ;;
    --check) CHECK_CMD="${2:?--check needs a value}"; shift 2 ;;
    --save) SAVE="true"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$PHASE" in
  polish|review|fix) ;;
  *) echo "ERROR: --phase must be polish, review, or fix." >&2; exit 2 ;;
esac

cd "$REPO"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_STATUS="$(git status --short || true)"
  DIFF_STAT="$(git diff --stat || true)"
  CHANGED_FILES="$(git diff --name-only || true)"
  [ -n "$GIT_STATUS" ] || GIT_STATUS="(clean working tree)"
  [ -n "$DIFF_STAT" ] || DIFF_STAT="(no unstaged diff)"
  [ -n "$CHANGED_FILES" ] || CHANGED_FILES="(none)"
else
  GIT_STATUS="NOT_GIT_REPO: bounded file inventory instead"
  DIFF_STAT="(not a git repository)"
  CHANGED_FILES="$(find . -maxdepth 2 -type f -not -name '.DS_Store' | sort | sed 's#^\./##' | head -40)"
fi

CHECK_EVIDENCE="[TODO: fastest relevant check command and output summary]"
if [ -n "$CHECK_CMD" ]; then
  set +e
  CHECK_OUTPUT="$(eval "$CHECK_CMD" 2>&1 | tail -n 20)"
  CHECK_EXIT=$?
  set -e
  CHECK_EVIDENCE="\$ $CHECK_CMD (exit $CHECK_EXIT)
$CHECK_OUTPUT"
fi

HANDOFF="$(cat <<HANDOFF
# Partner Handoff

## Task
$TASK

## Claude Plan
[TODO: the plan Claude already gave, or a 5-bullet summary]

## Codex Implementation
- Changed files:
$(printf '%s\n' "$CHANGED_FILES" | sed 's/^/  - /')
- Key decisions:
  - [TODO]
- Known tradeoffs:
  - [TODO]

## Repo Evidence
\`\`\`text
\$ git status --short
$GIT_STATUS

\$ git diff --stat
$DIFF_STAT

$CHECK_EVIDENCE
\`\`\`

## What I Need From Claude
[TODO: choose exactly one]
1. UI/interaction polish: return prioritized findings only.
2. Architecture/product critique: return blocking risks only.
3. /codex:review: review the current diff for bugs, regressions, missing tests, and unsafe behavior.

## Scope Boundary
- Do not commit, push, deploy, publish, or send external messages.
- Do not touch secrets or .env files.
- If you need more context, ask for the smallest file or snippet that unblocks the review.

<!-- phase: $PHASE | generated: $(date -u +%Y-%m-%dT%H:%M:%SZ) | by scripts/make-handoff.sh -->
HANDOFF
)"

printf '%s\n' "$HANDOFF"

if [ "$SAVE" = "true" ]; then
  SAVE_DIR="$REPO/.partner/handoffs"
  mkdir -p "$SAVE_DIR"
  SAVE_PATH="$SAVE_DIR/handoff-$(date -u +%Y%m%dT%H%M%SZ)-$PHASE.md"
  printf '%s\n' "$HANDOFF" >"$SAVE_PATH"
  echo "saved: $SAVE_PATH" >&2
fi

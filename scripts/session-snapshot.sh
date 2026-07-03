#!/usr/bin/env bash
# Make new_claude_p_sessions a computed fact instead of a self-reported claim.
#
# Every Claude Code session — including one-off `claude -p` runs — writes a
# transcript file under ~/.claude/projects/<munged-repo-path>/. Snapshot the
# transcript list when the Partner run starts; at receipt time, diff it. New
# transcript files are new sessions, so the receipt number is verifiable.
#
# Usage:
#   bash session-snapshot.sh start [--repo PATH]
#       Save the current transcript list to .partner/session-baseline.txt
#   bash session-snapshot.sh diff [--repo PATH]
#       Print each new transcript since the baseline, then NEW_SESSIONS=<n>
#
# Exit codes: 0 on success (any count), 2 on usage error, 3 when no baseline
# exists for diff. Missing transcript dir is treated as an empty list so the
# tool degrades cleanly when monitoring is degraded.
set -euo pipefail

MODE="${1:-}"
shift || true
REPO="$(pwd)"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a value}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$MODE" in
  start|diff) ;;
  *) echo "Usage: bash session-snapshot.sh start|diff [--repo PATH]" >&2; exit 2 ;;
esac

REPO="$(cd "$REPO" && pwd)"
MUNGED="$(printf '%s' "$REPO" | sed 's/[^A-Za-z0-9]/-/g')"
TRANSCRIPT_DIR="$HOME/.claude/projects/$MUNGED"
BASELINE="$REPO/.partner/session-baseline.txt"

list_transcripts() {
  if [ -d "$TRANSCRIPT_DIR" ]; then
    find "$TRANSCRIPT_DIR" -maxdepth 1 -name '*.jsonl' -exec basename {} .jsonl \; | sort
  fi
}

case "$MODE" in
  start)
    mkdir -p "$REPO/.partner"
    list_transcripts >"$BASELINE"
    echo "baseline: $BASELINE ($(wc -l <"$BASELINE" | tr -d ' ') sessions)"
    ;;
  diff)
    if [ ! -f "$BASELINE" ]; then
      echo "ERROR: no baseline at $BASELINE; run 'session-snapshot.sh start' first." >&2
      exit 3
    fi
    current="$(list_transcripts)"
    new_sessions="$(printf '%s\n' "$current" | grep -vxF -f "$BASELINE" || true)"
    new_sessions="$(printf '%s\n' "$new_sessions" | sed '/^$/d')"
    if [ -n "$new_sessions" ]; then
      printf '%s\n' "$new_sessions" | sed 's/^/new: /'
    fi
    count=0
    [ -n "$new_sessions" ] && count="$(printf '%s\n' "$new_sessions" | wc -l | tr -d ' ')"
    echo "NEW_SESSIONS=$count"
    ;;
esac

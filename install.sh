#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Partner installer

Usage:
  bash install.sh [--target codex|claude|agents|all] [--dry-run]

Targets:
  codex   -> ~/.codex/skills/partner-skill
  claude  -> ~/.claude/skills/partner-skill
  agents  -> ~/.agents/skills/partner-skill
  all     -> all of the above
USAGE
}

TARGET="codex"
DRY_RUN="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --target=*)
      TARGET="${1#--target=}"
      shift
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$ROOT/SKILL.md" ]; then
  echo "ERROR: install.sh must run from the partner-skill repository." >&2
  exit 1
fi

case "$TARGET" in
  codex) DESTS=("$HOME/.codex/skills/partner-skill") ;;
  claude) DESTS=("$HOME/.claude/skills/partner-skill") ;;
  agents) DESTS=("$HOME/.agents/skills/partner-skill") ;;
  all) DESTS=("$HOME/.codex/skills/partner-skill" "$HOME/.claude/skills/partner-skill" "$HOME/.agents/skills/partner-skill") ;;
  *)
    echo "ERROR: unsupported target '$TARGET'." >&2
    usage
    exit 2
    ;;
esac

for dest in "${DESTS[@]}"; do
  if [ "$ROOT" = "$dest" ]; then
    echo "Already installed at $dest"
    continue
  fi

  echo "Install Partner -> $dest"
  if [ "$DRY_RUN" = "true" ]; then
    continue
  fi

  mkdir -p "$(dirname "$dest")"
  if [ -e "$dest" ]; then
    backup="$dest.backup.$(date +%Y%m%d%H%M%S)"
    echo "Existing install found. Moving it to $backup"
    mv "$dest" "$backup"
  fi

  mkdir -p "$dest"
  rsync -a \
    --exclude='.git' \
    --exclude='.DS_Store' \
    "$ROOT/" "$dest/"
done

echo "Done. Try: 用 Claude Code goal 先规划，你 Codex 来实现。"

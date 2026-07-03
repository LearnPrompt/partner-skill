#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Partner installer

Usage:
  bash install.sh [--target codex|claude|agents|all] [--dry-run]
  bash install.sh --status

Targets:
  codex   -> ~/.codex/skills/partner-skill  (+ ~/.codex/prompts/idea-king.md)
  claude  -> ~/.claude/skills/partner-skill (+ ~/.claude/skills/idea-king)
  agents  -> ~/.agents/skills/partner-skill (+ ~/.agents/skills/idea-king)
  all     -> all of the above

The idea-king (点子王) companion skill ships with Partner: first-principles
decomposition plus adversarial review, used by Direction B on every work
split. It installs as its own skill directory so both agents can call it.

--status compares every installed copy's .install-meta commit against this
repository's HEAD so stale copies are visible before they cause confusion.
USAGE
}

TARGET="codex"
DRY_RUN="false"
STATUS="false"
BACKUP_KEEP=3

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
    --status)
      STATUS="true"
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

if [ "$STATUS" = "true" ]; then
  head_commit="(not a git repository)"
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    head_commit="$(git -C "$ROOT" rev-parse HEAD)"
  fi
  echo "repo HEAD: $head_commit"
  for dest in "$HOME/.codex/skills/partner-skill" "$HOME/.claude/skills/partner-skill" "$HOME/.agents/skills/partner-skill"; do
    if [ ! -d "$dest" ]; then
      echo "MISSING  $dest"
    elif [ ! -f "$dest/.install-meta" ]; then
      echo "UNKNOWN  $dest (no .install-meta; installed before v1.1.0?)"
    else
      installed_commit="$(sed -n 's/^source_commit=//p' "$dest/.install-meta")"
      if [ "$installed_commit" = "$head_commit" ]; then
        echo "CURRENT  $dest ($installed_commit)"
      else
        echo "STALE    $dest (installed $installed_commit, repo at $head_commit)"
      fi
    fi
  done
  exit 0
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

copy_payload() {
  # Package only the skill payload. Tracked files when git is available, so
  # local scratch files and logs never ship into the user's skills directory.
  local dest="$1"
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$ROOT" ls-files -z -- . ':!:.github' ':!:docs/TEST.md' \
      | (cd "$ROOT" && tar -cf - --null -T -) \
      | tar -xf - -C "$dest"
    {
      printf 'source_commit=%s\n' "$(git -C "$ROOT" rev-parse HEAD)"
      printf 'installed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } >"$dest/.install-meta"
  else
    (cd "$ROOT" && find . -type f \
      ! -path './.git/*' \
      ! -path './.github/*' \
      ! -path './docs/TEST.md' \
      ! -name '.DS_Store' \
      -print0 | tar -cf - --null -T -) \
      | tar -xf - -C "$dest"
  fi
}

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
    ls -dt "$dest".backup.* 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" \
      | while IFS= read -r old_backup; do
          rm -rf "$old_backup" # risk-ok: prunes only our own timestamped backups beyond BACKUP_KEEP
        done
  fi

  mkdir -p "$dest"
  copy_payload "$dest"
done

install_idea_king_skill() {
  # Installs idea-king as a sibling skill directory (Claude Code and agents
  # discover skills at <root>/<name>/SKILL.md, so it cannot stay nested
  # inside the partner-skill copy).
  local dest="$1"
  echo "Install idea-king -> $dest"
  if [ "$DRY_RUN" = "true" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  if [ -e "$dest" ]; then
    local backup="$dest.backup.$(date +%Y%m%d%H%M%S)"
    echo "Existing idea-king install found. Moving it to $backup"
    mv "$dest" "$backup"
    ls -dt "$dest".backup.* 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" \
      | while IFS= read -r old_backup; do
          rm -rf "$old_backup" # risk-ok: prunes only our own timestamped backups beyond BACKUP_KEEP
        done
  fi
  mkdir -p "$dest"
  (cd "$ROOT/idea-king" && find . -type f ! -name '.DS_Store' ! -name 'codex-prompt.md' -print0 \
    | tar -cf - --null -T -) | tar -xf - -C "$dest"
}

install_idea_king_codex_prompt() {
  local dest="$HOME/.codex/prompts/idea-king.md"
  echo "Install idea-king codex prompt -> $dest"
  if [ "$DRY_RUN" = "true" ]; then
    return 0
  fi
  mkdir -p "$HOME/.codex/prompts"
  cp "$ROOT/idea-king/codex-prompt.md" "$dest"
}

for dest in "${DESTS[@]}"; do
  case "$dest" in
    "$HOME/.claude/skills/partner-skill") install_idea_king_skill "$HOME/.claude/skills/idea-king" ;;
    "$HOME/.agents/skills/partner-skill") install_idea_king_skill "$HOME/.agents/skills/idea-king" ;;
    "$HOME/.codex/skills/partner-skill") install_idea_king_codex_prompt ;;
  esac
done

echo "Done. Try: 用 Claude Code goal 先规划，你 Codex 来实现。或在 Claude Code 里说：搭子，分工给 codex。"

#!/usr/bin/env bash
# Probe which Claude Code monitoring layers are available in this environment.
#
# references/monitoring.md describes five monitoring signals. Three of them
# depend on Claude Code CLI internals that may change between versions:
# `claude agents --json`, `~/.claude/projects` transcripts, and
# `~/.claude/tasks` task files. Run this probe before a Partner session and
# record the resulting MONITORING_LEVEL in the Partner Session Receipt so a
# CLI drift becomes an explicit fact instead of a silent monitoring gap.
#
# Output contract (stdout):
#   PROBE pass|warn|fail <name> [detail]   one line per probe
#   MONITORING_LEVEL=full|degraded|none    always the last line
#
# Levels:
#   full     -> claude binary + agents command + transcript dir all available
#   degraded -> claude binary exists but agents command or transcript dir is
#               missing; fall back to PTY output + repo evidence
#   none     -> no claude binary; Codex-only monitoring (repo evidence)
#
# Exit code is always 0; the level is data, not a failure.
set -uo pipefail

level="full"

if command -v claude >/dev/null 2>&1; then
  version="$(claude --version 2>/dev/null | head -n 1 || true)"
  echo "PROBE pass claude binary (${version:-version unknown})"
else
  echo "PROBE fail claude binary not found in PATH"
  echo "MONITORING_LEVEL=none"
  exit 0
fi

if claude agents --help >/dev/null 2>&1; then
  echo "PROBE pass agents command"
else
  echo "PROBE fail agents command (claude agents --help failed)"
  level="degraded"
fi

if [ -d "$HOME/.claude/projects" ]; then
  echo "PROBE pass transcript dir $HOME/.claude/projects"
else
  echo "PROBE fail transcript dir $HOME/.claude/projects missing"
  level="degraded"
fi

# Task files are documented as optional; absence does not degrade monitoring.
if [ -d "$HOME/.claude/tasks" ]; then
  echo "PROBE pass task dir $HOME/.claude/tasks"
else
  echo "PROBE warn task dir $HOME/.claude/tasks missing (optional signal)"
fi

echo "MONITORING_LEVEL=$level"

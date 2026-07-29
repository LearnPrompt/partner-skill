# Partner Session Receipt Example

This is the minimal public proof that Partner reused Claude Code context instead of spawning a fresh cold-start review session.

```text
[Partner session receipt]
phase: final fix
claude_session: 9836fe7e-4aca-47a6-83b5-69086b8db275
claude_session_reused: yes
new_claude_p_sessions: 0
codex_passes: 2
checks: bash scripts/check-skill-repo.sh .; jq schema check; git diff --check
anomalies: none
monitoring_level: full
direction: codex-driven
codex_jobs: 0
host: codex
scope: n/a
config_source: n/a
roles_used: none
receipt_schema_version: 2
```

This example is validated in CI: `python3 scripts/validate-receipt.py examples/session-receipt.md`.

Use exact token counts only when reliable telemetry is available. Without telemetry, report behavior that can be verified from PTY output, `claude agents --json`, transcripts, and repo evidence.

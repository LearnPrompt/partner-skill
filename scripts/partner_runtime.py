"""Shared subprocess boundaries for Partner helper scripts."""

from __future__ import annotations

from typing import Dict, Mapping


def clean_claude_env(env: Mapping[str, str]) -> Dict[str, str]:
    """Remove host-injected Claude variables before starting a child CLI.

    Nested Claude Code hosts can inject provider URLs, credentials, and
    session markers that override the user's normal first-party CLI login.
    Partner child processes must resolve authentication exactly as a fresh
    terminal invocation would.
    """

    cleaned = {
        key: value
        for key, value in env.items()
        if not key.startswith("ANTHROPIC_") and not key.startswith("CLAUDE_CODE_")
    }
    cleaned["CLAUDECODE"] = ""
    return cleaned

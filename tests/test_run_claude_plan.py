from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-claude-plan.py"


class RunClaudePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.packet = self.root / "packet.md"
        self.packet.write_text(self.packet_text(), encoding="utf-8")
        self.args_log = self.root / "args.json"
        self.stdin_log = self.root / "stdin.txt"
        self.fake_claude = self.root / "claude"
        self.fake_claude.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import signal
                import subprocess
                import sys
                import time
                from pathlib import Path

                arguments = sys.argv[1:]
                Path(os.environ["FAKE_ARGS_LOG"]).write_text(
                    json.dumps(arguments), encoding="utf-8"
                )
                mode = os.environ.get("FAKE_MODE", "success")
                if mode == "stdin_stall":
                    Path(os.environ["FAKE_STDIN_LOG"]).write_text(
                        "", encoding="utf-8"
                    )
                    time.sleep(5)
                    sys.exit(0)
                Path(os.environ["FAKE_STDIN_LOG"]).write_text(
                    sys.stdin.read(), encoding="utf-8"
                )
                if "--resume" in arguments:
                    session_id = arguments[arguments.index("--resume") + 1]
                else:
                    session_id = arguments[arguments.index("--session-id") + 1]
                if mode == "wrong_session":
                    session_id = "11111111-1111-4111-8111-111111111111"
                emitted_model = (
                    "claude-sonnet-5"
                    if mode == "wrong_model"
                    else "claude-fable-5"
                )
                valid_plan = (
                    "# Plan Checkpoint\\n\\n"
                    "## Goal\\nShip the bounded change.\\n"
                    "## Non-goals\\nDo not change delegation.\\n"
                    "## Current-State Evidence\\nThe packet names the current files.\\n"
                    "## File Scope\\nOnly the bounded runner.\\n"
                    "## Steps\\n1. Make the small change.\\n"
                    "## Risks\\nThe CLI can fail upstream.\\n"
                    "## Acceptance Checks (binary)\\n- [ ] Unit tests pass.\\n"
                    "## Rollback\\nRevert the runner change."
                )

                def emit(value):
                    print(json.dumps(value), flush=True)

                if mode != "no_session":
                    emit({
                        "type": "system",
                        "subtype": "init",
                        "session_id": session_id,
                        "model": emitted_model,
                        "tools": [],
                    })
                if mode == "slow_success":
                    time.sleep(0.5)
                    mode = "success"
                if mode == "no_session":
                    print("Authentication failed before session init", file=sys.stderr)
                    sys.exit(1)
                elif mode == "idle":
                    time.sleep(5)
                elif mode == "partial_line":
                    os.write(
                        sys.stdout.fileno(),
                        b'{"type":"stream_event","event":{"type":"content_block_delta"',
                    )
                    time.sleep(5)
                elif mode == "partial_trickle":
                    for _ in range(100):
                        os.write(sys.stdout.fileno(), b"x")
                        time.sleep(0.05)
                elif mode == "json_scalar":
                    print("null", flush=True)
                    time.sleep(5)
                elif mode == "unknown_event_trickle":
                    while True:
                        emit({})
                        time.sleep(0.05)
                elif mode == "oversized_line":
                    os.write(sys.stdout.fileno(), b"x" * 1_100_000)
                    time.sleep(5)
                elif mode == "oversized_visible":
                    emit({
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {
                                "type": "text_delta",
                                "text": "x" * 100_001,
                            },
                        },
                    })
                    time.sleep(5)
                elif mode == "heartbeat":
                    while True:
                        emit({
                            "type": "stream_event",
                            "event": {
                                "type": "content_block_delta",
                                "delta": {"type": "thinking_delta", "thinking": "secret"},
                            },
                        })
                        time.sleep(0.05)
                elif mode == "tool":
                    emit({
                        "type": "assistant",
                        "message": {
                            "model": "claude-fable-5",
                            "stop_reason": "tool_use",
                            "content": [{"type": "tool_use", "name": "Read"}],
                        },
                    })
                    time.sleep(5)
                elif mode == "tool_ignore":
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    emit({
                        "type": "assistant",
                        "message": {
                            "model": "claude-fable-5",
                            "stop_reason": "tool_use",
                            "content": [{"type": "tool_use", "name": "Read"}],
                        },
                    })
                    time.sleep(5)
                elif mode == "descendant_ignore":
                    child_code = (
                        "import os, signal, time\\n"
                        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
                        "with open(os.environ['FAKE_CHILD_PID_LOG'], 'w') as handle:\\n"
                        "    handle.write(str(os.getpid()))\\n"
                        "while True:\\n"
                        "    with open(os.environ['FAKE_CHILD_HEARTBEAT_LOG'], 'a') as handle:\\n"
                        "        handle.write('x')\\n"
                        "    time.sleep(0.05)\\n"
                    )
                    subprocess.Popen([sys.executable, "-c", child_code])
                    time.sleep(5)
                elif mode == "burst":
                    values = [
                        {
                            "type": "stream_event",
                            "event": {
                                "type": "content_block_delta",
                                "delta": {
                                    "type": "text_delta",
                                    "text": f"step {index}\\n",
                                },
                            },
                        }
                        for index in range(25)
                    ]
                    values.append({
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "session_id": session_id,
                        "result": valid_plan,
                        "total_cost_usd": 0.25,
                        "num_turns": 1,
                        "terminal_reason": "completed",
                    })
                    os.write(
                        sys.stdout.fileno(),
                        "".join(json.dumps(value) + "\\n" for value in values).encode(),
                    )
                elif mode == "budget":
                    emit({
                        "type": "result",
                        "subtype": "error_max_budget_usd",
                        "is_error": True,
                        "session_id": session_id,
                        "total_cost_usd": 2.0,
                        "terminal_reason": "max_budget_usd",
                    })
                    sys.exit(1)
                elif mode == "auth":
                    print("Authentication failed: please login", file=sys.stderr)
                    sys.exit(1)
                elif mode == "auth_secret":
                    print(
                        "Authentication failed token=github_pat_"
                        + "a" * 24
                        + " Authorization: Bearer eyJ"
                        + "a" * 20
                        + "."
                        + "b" * 20
                        + "."
                        + "c" * 20
                        + " password=hunter2 glpat-"
                        + "d" * 24,
                        file=sys.stderr,
                    )
                    sys.exit(1)
                elif mode == "event_secret":
                    emit({
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {
                                "type": "text_delta",
                                "text": "Authorization: Bearer eyJ"
                                + "a" * 20
                                + "."
                                + "b" * 20
                                + "."
                                + "c" * 20,
                            },
                        },
                    })
                    sys.exit(1)
                elif mode == "empty_success":
                    emit({
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "session_id": session_id,
                        "result": "",
                        "total_cost_usd": 0.1,
                        "num_turns": 1,
                        "terminal_reason": "completed",
                    })
                elif mode == "malformed_success":
                    emit({
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "session_id": session_id,
                        "result": "I will write the plan file next.",
                        "total_cost_usd": 0.1,
                        "num_turns": 1,
                        "terminal_reason": "completed",
                    })
                elif mode == "upstream_idle":
                    emit({
                        "type": "assistant",
                        "message": {
                            "model": "<synthetic>",
                            "stop_reason": "stop_sequence",
                            "content": [{
                                "type": "text",
                                "text": "API Error: Stream idle timeout - no chunks received",
                            }],
                        },
                    })
                    emit({
                        "type": "result",
                        "subtype": "success",
                        "is_error": True,
                        "session_id": session_id,
                        "result": "",
                        "total_cost_usd": 0,
                        "num_turns": 1,
                        "terminal_reason": "api_error",
                    })
                    sys.exit(1)
                else:
                    emit({
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {"type": "thinking_delta", "thinking": "secret"},
                        },
                    })
                    emit({
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "# Plan Checkpoint\\n"},
                        },
                    })
                    emit({
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "session_id": session_id,
                        "result": valid_plan,
                        "total_cost_usd": 0.25,
                        "num_turns": 1,
                        "usage": {
                            "input_tokens": 100,
                            "cache_creation_input_tokens": 50,
                            "cache_read_input_tokens": 0,
                            "output_tokens": 20,
                        },
                        "terminal_reason": "completed",
                    })
                    if mode == "nonzero_success":
                        sys.exit(23)
                """
            ),
            encoding="utf-8",
        )
        self.fake_claude.chmod(0o755)
        self.write_config()

    @staticmethod
    def packet_text(evidence: str = "`src/app.py:1` — current behavior.\n") -> str:
        return (
            "# Partner Bounded Planning Packet\n"
            "## Goal\nShip a reliable bounded planner.\n"
            "## Non-goals\nDo not change delegation.\n"
            "## Current-State Evidence\n"
            f"{evidence}"
            "## Constraints\nNo tools or model substitution.\n"
            "## Acceptance\nTests and real miniloops pass.\n"
            "## Open Decisions\nNone.\n"
            "## Truncation\nnone\n"
        )

    def write_config(
        self,
        *,
        backend: str = "claude",
        verified: bool = True,
        include_role: bool = True,
    ) -> None:
        config = self.repo / ".partner" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        role = ""
        if include_role:
            role = (
                "[hosts.codex.identities.deep_reasoner]\n"
                f'backend = "{backend}"\n'
                'model = "claude-fable-5"\n'
                'effort = "xhigh"\n'
                f"verified = {'true' if verified else 'false'}\n"
                'verified_at = "2026-07-29T00:00:00Z"\n'
            )
        config.write_text(
            "schema_version = 2\nrevision = 1\n\n" + role,
            encoding="utf-8",
        )

    def run_cli(
        self,
        *extra: str,
        mode: str = "success",
        packet: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PARTNER_CLAUDE_BIN": str(self.fake_claude),
                "FAKE_ARGS_LOG": str(self.args_log),
                "FAKE_STDIN_LOG": str(self.stdin_log),
                "FAKE_CHILD_PID_LOG": str(self.root / "child.pid"),
                "FAKE_CHILD_HEARTBEAT_LOG": str(self.root / "child.heartbeat"),
                "FAKE_MODE": mode,
                "HOME": str(self.root / "home"),
                "XDG_CONFIG_HOME": str(self.root / "xdg"),
            }
        )
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--repo",
                str(self.repo),
                "--host",
                "codex",
                "--packet",
                str(packet or self.packet),
                "--run-id",
                "test-run",
                *extra,
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def metadata(self) -> dict:
        return json.loads(
            (
                self.repo / ".partner" / "runs" / "test-run" / "metadata.json"
            ).read_text(encoding="utf-8")
        )

    def test_success_uses_exact_config_and_lockdown_flags(self) -> None:
        result = self.run_cli()
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        arguments = json.loads(self.args_log.read_text(encoding="utf-8"))
        self.assertEqual("claude-fable-5", arguments[arguments.index("--model") + 1])
        self.assertEqual("xhigh", arguments[arguments.index("--effort") + 1])
        self.assertEqual("", arguments[arguments.index("--tools") + 1])
        self.assertIn("--safe-mode", arguments)
        self.assertIn("--no-chrome", arguments)
        self.assertNotIn(self.packet_text(), " ".join(arguments))
        stdin_text = self.stdin_log.read_text(encoding="utf-8")
        self.assertIn("You are Partner's bounded Deep Reasoner", stdin_text)
        self.assertIn(self.packet_text(), stdin_text)
        self.assertEqual(
            "2.0", arguments[arguments.index("--max-budget-usd") + 1]
        )
        plan = self.repo / ".partner" / "plans" / "test-run.md"
        self.assertIn("Ship the bounded change", plan.read_text(encoding="utf-8"))
        checkpoint = (
            self.repo / ".partner" / "runs" / "test-run" / "checkpoint.md"
        )
        self.assertEqual(
            plan.read_text(encoding="utf-8"),
            checkpoint.read_text(encoding="utf-8"),
        )
        events = (
            self.repo / ".partner" / "runs" / "test-run" / "events.jsonl"
        ).read_text(encoding="utf-8")
        self.assertNotIn("secret", events)
        self.assertEqual("success", self.metadata()["status"])
        self.assertEqual("claude_cli", self.metadata()["budget_enforced_by"])
        self.assertTrue(self.metadata()["session_observed"])
        self.assertFalse(self.metadata()["allow_unverified"])
        self.assertEqual(
            self.metadata()["requested_session_id"],
            self.metadata()["observed_session_ids"][0],
        )
        self.assertEqual(["claude-fable-5"], self.metadata()["observed_models"])
        self.assertEqual(
            hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            self.metadata()["runner_sha256"],
        )
        self.assertEqual(1_048_576, self.metadata()["max_stream_buffer_bytes"])
        self.assertEqual(100_000, self.metadata()["max_visible_output_chars"])
        self.assertEqual(10_000_000, self.metadata()["max_event_log_bytes"])
        self.assertLessEqual(
            self.metadata()["event_log_bytes"],
            self.metadata()["max_event_log_bytes"],
        )

    def test_missing_or_non_claude_role_fails_without_spawn(self) -> None:
        self.write_config(include_role=False)
        missing = self.run_cli()
        self.assertEqual(2, missing.returncode)
        self.assertIn("is not configured", missing.stderr)
        self.assertFalse(self.args_log.exists())

        self.write_config(backend="codex")
        backend = self.run_cli()
        self.assertEqual(2, backend.returncode)
        self.assertIn("never substitutes", backend.stderr)
        self.assertFalse(self.args_log.exists())

    def test_unverified_role_requires_explicit_override(self) -> None:
        self.write_config(verified=False)
        refused = self.run_cli("--dry-run")
        self.assertEqual(2, refused.returncode)
        self.assertIn("unverified", refused.stderr)
        allowed = self.run_cli("--dry-run", "--allow-unverified")
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        self.assertIn("verified=false", allowed.stdout)
        actual = self.run_cli("--allow-unverified")
        self.assertEqual(0, actual.returncode, actual.stderr)
        self.assertTrue(self.metadata()["allow_unverified"])

    def test_higher_layer_model_cannot_inherit_verified_true(self) -> None:
        global_config = self.root / "xdg" / "partner" / "config.toml"
        global_config.parent.mkdir(parents=True)
        global_config.write_text(
            "schema_version = 2\nrevision = 1\n\n"
            "[hosts.codex.identities.deep_reasoner]\n"
            'backend = "claude"\n'
            'model = "verified-old"\n'
            'effort = "high"\n'
            "verified = true\n"
            'verified_at = "2026-07-29T00:00:00Z"\n',
            encoding="utf-8",
        )
        (self.repo / ".partner" / "config.toml").write_text(
            "schema_version = 2\nrevision = 1\n\n"
            "[hosts.codex.identities.deep_reasoner]\n"
            'backend = "claude"\n'
            'model = "unverified-new"\n'
            'effort = "xhigh"\n',
            encoding="utf-8",
        )
        result = self.run_cli("--dry-run")
        self.assertEqual(2, result.returncode)
        self.assertIn("unverified", result.stderr)
        self.assertFalse(self.args_log.exists())

    def test_packet_limit_accepts_24000_and_rejects_24001(self) -> None:
        base = self.packet_text(evidence="\n")
        accepted_packet = self.root / "accepted.md"
        accepted_packet.write_text(
            self.packet_text(evidence="x" * (24_000 - len(base)) + "\n"),
            encoding="utf-8",
        )
        self.assertEqual(24_000, len(accepted_packet.read_text(encoding="utf-8")))
        accepted = self.run_cli("--dry-run", packet=accepted_packet)
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        rejected_packet = self.root / "rejected.md"
        rejected_packet.write_text(
            accepted_packet.read_text(encoding="utf-8") + "x", encoding="utf-8"
        )
        rejected = self.run_cli("--dry-run", packet=rejected_packet)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("24001 characters", rejected.stderr)
        self.assertFalse(self.args_log.exists())

    def test_packet_contract_and_secret_scan_fail_before_spawn(self) -> None:
        malformed = self.root / "malformed.md"
        malformed.write_text("# Partner Bounded Planning Packet\n## Goal\nx\n", encoding="utf-8")
        result = self.run_cli("--dry-run", packet=malformed)
        self.assertEqual(2, result.returncode)
        self.assertIn("sections must appear exactly", result.stderr)

        secret = self.root / "secret.md"
        secret.write_text(
            self.packet_text(evidence="github_pat_" + "a" * 24 + "\n"),
            encoding="utf-8",
        )
        result = self.run_cli("--dry-run", packet=secret)
        self.assertEqual(2, result.returncode)
        self.assertIn("secret-like", result.stderr)
        self.assertFalse(self.args_log.exists())

        for index, value in enumerate(
            (
                "AWS_SECRET_ACCESS_KEY=" + "a" * 40,
                "token=" + "b" * 32,
                "ya29." + "c" * 32,
            )
        ):
            secret = self.root / f"secret-{index}.md"
            secret.write_text(
                self.packet_text(evidence=value + "\n"),
                encoding="utf-8",
            )
            result = self.run_cli("--dry-run", packet=secret)
            self.assertEqual(2, result.returncode)
            self.assertIn("secret-like", result.stderr)

    def test_idle_timeout_preserves_failure_artifacts(self) -> None:
        result = self.run_cli(
            "--idle-timeout-seconds",
            "0.2",
            "--wall-timeout-seconds",
            "2",
            mode="idle",
        )
        self.assertEqual(4, result.returncode)
        metadata = self.metadata()
        self.assertEqual("idle_timeout", metadata["failure_kind"])
        for name in ("events.jsonl", "checkpoint.md", "metadata.json", "recovery.md"):
            self.assertTrue(
                (self.repo / ".partner" / "runs" / "test-run" / name).is_file()
            )
        recovery = (
            self.repo / ".partner" / "runs" / "test-run" / "recovery.md"
        ).read_text(encoding="utf-8")
        self.assertIn("automatic model fallback: disabled", recovery)
        self.assertIn("--resume-session", recovery)

    def test_wall_timeout_wins_while_stream_is_active(self) -> None:
        result = self.run_cli(
            "--idle-timeout-seconds",
            "1",
            "--wall-timeout-seconds",
            "0.3",
            mode="heartbeat",
        )
        self.assertEqual(4, result.returncode)
        self.assertEqual("wall_timeout", self.metadata()["failure_kind"])
        events = (
            self.repo / ".partner" / "runs" / "test-run" / "events.jsonl"
        ).read_text(encoding="utf-8")
        self.assertNotIn("secret", events)

    def test_partial_json_line_cannot_block_idle_watchdog(self) -> None:
        started = time.monotonic()
        result = self.run_cli(
            "--idle-timeout-seconds",
            "0.2",
            "--wall-timeout-seconds",
            "2",
            mode="partial_line",
        )
        self.assertEqual(4, result.returncode)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual("idle_timeout", self.metadata()["failure_kind"])

    def test_partial_byte_trickle_does_not_reset_valid_event_idle_timer(self) -> None:
        started = time.monotonic()
        result = self.run_cli(
            "--idle-timeout-seconds",
            "2",
            "--wall-timeout-seconds",
            "6",
            mode="partial_trickle",
        )
        self.assertEqual(4, result.returncode, result.stderr)
        self.assertLess(time.monotonic() - started, 5.5)
        self.assertEqual("idle_timeout", self.metadata()["failure_kind"])

    def test_json_scalar_and_unknown_event_fail_with_complete_artifacts(self) -> None:
        scalar = self.run_cli(mode="json_scalar")
        self.assertEqual(4, scalar.returncode, scalar.stderr)
        metadata = self.metadata()
        self.assertEqual("protocol_error", metadata["failure_kind"])
        self.assertIn("JSON object", metadata["failure_detail"])
        self.assertTrue(
            (self.repo / ".partner" / "runs" / "test-run" / "recovery.md").is_file()
        )

        self.repo = self.root / "unknown-event"
        self.repo.mkdir()
        self.write_config()
        started = time.monotonic()
        unknown = self.run_cli(
            "--idle-timeout-seconds",
            "1",
            "--wall-timeout-seconds",
            "3",
            mode="unknown_event_trickle",
        )
        self.assertEqual(4, unknown.returncode, unknown.stderr)
        self.assertLess(time.monotonic() - started, 2)
        metadata = self.metadata()
        self.assertEqual("protocol_error", metadata["failure_kind"])
        self.assertIn("unsupported type", metadata["failure_detail"])

    def test_stream_line_and_visible_output_caps_fail_closed(self) -> None:
        oversized_line = self.run_cli(
            "--idle-timeout-seconds",
            "5",
            "--wall-timeout-seconds",
            "8",
            mode="oversized_line",
        )
        self.assertEqual(4, oversized_line.returncode)
        self.assertEqual("protocol_error", self.metadata()["failure_kind"])
        self.assertIn("line exceeded", self.metadata()["failure_detail"])

        self.repo = self.root / "oversized-visible"
        self.repo.mkdir()
        self.write_config()
        oversized_visible = self.run_cli(
            "--idle-timeout-seconds",
            "5",
            "--wall-timeout-seconds",
            "8",
            mode="oversized_visible",
        )
        self.assertEqual(4, oversized_visible.returncode)
        self.assertEqual("protocol_error", self.metadata()["failure_kind"])
        self.assertIn("checkpoint exceeded", self.metadata()["failure_detail"])
        self.assertLessEqual(
            (self.repo / ".partner" / "runs" / "test-run" / "events.jsonl").stat().st_size,
            10_000_000,
        )

    def test_child_that_never_reads_max_packet_cannot_block_watchdog(self) -> None:
        base = self.packet_text(evidence="\n")
        max_packet = self.root / "max-packet.md"
        max_packet.write_text(
            self.packet_text(evidence="x" * (24_000 - len(base)) + "\n"),
            encoding="utf-8",
        )
        started = time.monotonic()
        result = self.run_cli(
            "--idle-timeout-seconds",
            "0.2",
            "--wall-timeout-seconds",
            "2",
            mode="stdin_stall",
            packet=max_packet,
        )
        self.assertEqual(4, result.returncode)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual("idle_timeout", self.metadata()["failure_kind"])

    def test_burst_lines_are_drained_without_false_idle(self) -> None:
        result = self.run_cli(
            "--idle-timeout-seconds",
            "1",
            "--wall-timeout-seconds",
            "3",
            mode="burst",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        events = (
            self.repo / ".partner" / "runs" / "test-run" / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(events), 28)
        self.assertEqual("success", self.metadata()["status"])

    def test_tool_use_is_a_protocol_failure(self) -> None:
        result = self.run_cli(
            "--idle-timeout-seconds",
            "1",
            "--wall-timeout-seconds",
            "2",
            mode="tool",
        )
        self.assertEqual(4, result.returncode)
        self.assertEqual("tool_use_violation", self.metadata()["failure_kind"])

    def test_first_failure_wins_when_child_ignores_sigterm(self) -> None:
        started = time.monotonic()
        result = self.run_cli(
            "--idle-timeout-seconds",
            "5",
            "--wall-timeout-seconds",
            "2",
            mode="tool_ignore",
        )
        self.assertEqual(4, result.returncode)
        self.assertLess(time.monotonic() - started, 5.5)
        self.assertEqual("tool_use_violation", self.metadata()["failure_kind"])

    def test_timeout_kills_descendant_that_inherits_pipes_and_ignores_sigterm(self) -> None:
        started = time.monotonic()
        result = self.run_cli(
            "--idle-timeout-seconds",
            "1",
            "--wall-timeout-seconds",
            "5",
            mode="descendant_ignore",
        )
        self.assertEqual(4, result.returncode)
        self.assertLess(time.monotonic() - started, 5.5)
        self.assertEqual("idle_timeout", self.metadata()["failure_kind"])
        child_pid = int((self.root / "child.pid").read_text(encoding="utf-8"))
        heartbeat = self.root / "child.heartbeat"
        before = heartbeat.stat().st_size
        time.sleep(0.2)
        self.assertEqual(
            before,
            heartbeat.stat().st_size,
            f"descendant process {child_pid} survived process-group kill",
        )

    def test_budget_and_auth_failures_are_classified(self) -> None:
        budget = self.run_cli(mode="budget")
        self.assertEqual(4, budget.returncode)
        self.assertEqual("budget_exceeded", self.metadata()["failure_kind"])
        self.assertEqual(2.0, self.metadata()["total_cost_usd"])

        other_repo = self.root / "other"
        other_repo.mkdir()
        self.repo = other_repo
        self.write_config()
        auth = self.run_cli(mode="auth")
        self.assertEqual(4, auth.returncode)
        self.assertEqual("authentication", self.metadata()["failure_kind"])

    def test_nonzero_exit_cannot_be_success_even_with_valid_result(self) -> None:
        result = self.run_cli(mode="nonzero_success")
        self.assertEqual(4, result.returncode)
        metadata = self.metadata()
        self.assertEqual("protocol_error", metadata["failure_kind"])
        self.assertIn("exited 23", metadata["failure_detail"])
        self.assertFalse((self.repo / ".partner" / "plans" / "test-run.md").exists())

    def test_synthetic_stream_idle_text_is_classified_as_upstream_idle(self) -> None:
        result = self.run_cli(mode="upstream_idle")
        self.assertEqual(4, result.returncode)
        metadata = self.metadata()
        self.assertEqual("upstream_idle", metadata["failure_kind"])
        checkpoint = (
            self.repo / ".partner" / "runs" / "test-run" / "checkpoint.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Stream idle timeout", checkpoint)

    def test_empty_success_result_is_a_consistent_protocol_failure(self) -> None:
        result = self.run_cli(mode="empty_success")
        self.assertEqual(4, result.returncode)
        metadata = self.metadata()
        self.assertEqual("failed", metadata["status"])
        self.assertEqual("protocol_error", metadata["failure_kind"])

    def test_conversational_success_result_does_not_create_plan(self) -> None:
        result = self.run_cli(mode="malformed_success")
        self.assertEqual(4, result.returncode)
        metadata = self.metadata()
        self.assertEqual("protocol_error", metadata["failure_kind"])
        self.assertIn("must start", metadata["failure_detail"])
        self.assertFalse((self.repo / ".partner" / "plans" / "test-run.md").exists())
        checkpoint = (
            self.repo / ".partner" / "runs" / "test-run" / "checkpoint.md"
        ).read_text(encoding="utf-8")
        self.assertIn("write the plan file next", checkpoint)

    def test_output_created_during_paid_run_is_never_overwritten(self) -> None:
        output = self.root / "shared-plan.md"
        timer = threading.Timer(
            0.2, output.write_text, args=("first-writer\n",), kwargs={"encoding": "utf-8"}
        )
        timer.start()
        try:
            result = self.run_cli(
                "--output",
                str(output),
                mode="slow_success",
            )
        finally:
            timer.cancel()
        self.assertEqual(4, result.returncode)
        self.assertEqual("first-writer\n", output.read_text(encoding="utf-8"))
        metadata = self.metadata()
        self.assertEqual("protocol_error", metadata["failure_kind"])
        self.assertIn("refusing to overwrite", metadata["failure_detail"])
        self.assertIsNone(metadata["plan_path"])

    def test_success_requires_exact_observed_model_and_session(self) -> None:
        wrong_model = self.run_cli(mode="wrong_model")
        self.assertEqual(4, wrong_model.returncode)
        self.assertEqual("protocol_error", self.metadata()["failure_kind"])
        self.assertIn("configured model", self.metadata()["failure_detail"])

        self.repo = self.root / "wrong-session"
        self.repo.mkdir()
        self.write_config()
        wrong_session = self.run_cli(mode="wrong_session")
        self.assertEqual(4, wrong_session.returncode)
        self.assertEqual("protocol_error", self.metadata()["failure_kind"])
        self.assertIn("session id", self.metadata()["failure_detail"])

    def test_stderr_secret_is_redacted_from_artifacts_and_console(self) -> None:
        result = self.run_cli(mode="auth_secret")
        self.assertEqual(4, result.returncode)
        metadata_text = (
            self.repo / ".partner" / "runs" / "test-run" / "metadata.json"
        ).read_text(encoding="utf-8")
        secrets = (
            "github_pat_" + "a" * 24,
            "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20,
            "hunter2",
            "glpat-" + "d" * 24,
        )
        for secret in secrets:
            self.assertNotIn(secret, metadata_text)
            self.assertNotIn(secret, result.stderr)
        self.assertIn("[REDACTED]", metadata_text)

    def test_visible_event_secret_is_redacted_from_event_log(self) -> None:
        result = self.run_cli(mode="event_secret")
        self.assertEqual(4, result.returncode)
        events = (
            self.repo / ".partner" / "runs" / "test-run" / "events.jsonl"
        ).read_text(encoding="utf-8")
        self.assertNotIn("eyJ" + "a" * 20, events)
        self.assertIn("[REDACTED]", events)

    def test_resume_prompt_requires_plan_checkpoint_title(self) -> None:
        session_id = "11111111-1111-4111-8111-111111111111"
        result = self.run_cli("--resume-session", session_id)
        self.assertEqual(0, result.returncode, result.stderr)
        arguments = json.loads(self.args_log.read_text(encoding="utf-8"))
        self.assertEqual(session_id, arguments[arguments.index("--resume") + 1])
        prompt = self.stdin_log.read_text(encoding="utf-8")
        self.assertIn("# Plan Checkpoint", prompt)

    def test_recovery_warns_when_session_was_not_observed(self) -> None:
        result = self.run_cli(mode="no_session")
        self.assertEqual(4, result.returncode)
        metadata = self.metadata()
        self.assertFalse(metadata["session_observed"])
        recovery = (
            self.repo / ".partner" / "runs" / "test-run" / "recovery.md"
        ).read_text(encoding="utf-8")
        self.assertIn("may not have been persisted", recovery)


if __name__ == "__main__":
    unittest.main()

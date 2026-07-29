from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "partner-config.py"
SPEC = importlib.util.spec_from_file_location("partner_config", SCRIPT)
partner_config = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = partner_config
SPEC.loader.exec_module(partner_config)


def document(claude_model: str = "opus", codex_model: str = "gpt-test") -> str:
    return (
        "# keep this top comment\r\n"
        "schema_version = 2\r\n"
        "revision = 7\r\n"
        "\r\n"
        "[hosts.claude_code.identities.deep_reasoner]\r\n"
        'backend = "claude"\r\n'
        f'model = "{claude_model}" # claude comment\r\n'
        'effort = "high"\r\n'
        "\r\n"
        "[hosts.claude_code.identities.fast_worker]\r\n"
        'backend = "codex"\r\n'
        'model = "sonnet"\r\n'
        'effort = "medium"\r\n'
        "\r\n"
        "# codex prefix comment must survive\r\n"
        "[hosts.codex.identities.deep_reasoner]\r\n"
        'backend = "codex"\r\n'
        f'model = "{codex_model}" # untouched inline\r\n'
        'effort = "xhigh"\r\n'
        "\r\n"
        "[hosts.codex.identities.fast_worker]\r\n"
        'backend = "claude"\r\n'
        'model = "gpt-fast"\r\n'
        'effort = "medium"\r\n'
        "\r\n"
        "[routing]\r\n"
        "always_on_host_rules = false # routing comment\r\n"
        "\r\n"
        "[future]\r\n"
        'opaque = "preserve me" # exact\r\n'
    )


def legacy_document() -> str:
    return (
        "schema_version = 1\n"
        "revision = 4\n"
        "\n"
        "[hosts.codex.roles.deep_reasoner]\n"
        'model = "gpt-legacy"\n'
        'effort = "xhigh"\n'
        "verified = true\n"
        "\n"
        "[hosts.codex.roles.fast_worker]\n"
        'model = "gpt-legacy-fast"\n'
        'effort = "medium"\n'
    )


class ConfigRoundTripTests(unittest.TestCase):
    def test_unowned_host_routing_and_comments_are_byte_preserved(self):
        original = document()
        before_chunks = {
            chunk.name: chunk.text
            for chunk in partner_config.split_sections(original)
            if chunk.name and not chunk.name.startswith("hosts.claude_code.identities.")
        }
        identities = {
            "deep_reasoner": {"backend": "claude", "model": "new-opus", "effort": "high"},
            "fast_worker": {"backend": "codex", "model": "new-sonnet", "effort": "low"},
        }
        updated = partner_config.update_host(original, "claude_code", identities)
        after_chunks = {
            chunk.name: chunk.text
            for chunk in partner_config.split_sections(updated)
            if chunk.name and not chunk.name.startswith("hosts.claude_code.identities.")
        }
        self.assertEqual(before_chunks, after_chunks)
        self.assertIn("# keep this top comment\r\n", updated)

    def test_dual_host_merge_only_changes_self(self):
        original = document()
        claude_bytes = "".join(
            chunk.text for chunk in partner_config.split_sections(original)
            if chunk.name and chunk.name.startswith("hosts.claude_code.identities.")
        )
        parsed = partner_config.validate_config(original, "codex")
        identities = parsed["hosts"]["codex"]["identities"]
        identities["fast_worker"]["effort"] = "low"
        updated = partner_config.update_host(original, "codex", identities)
        updated_claude_bytes = "".join(
            chunk.text for chunk in partner_config.split_sections(updated)
            if chunk.name and chunk.name.startswith("hosts.claude_code.identities.")
        )
        self.assertEqual(claude_bytes, updated_claude_bytes)
        self.assertIn('effort = "low"', updated)

    def test_emitter_is_idempotent(self):
        parsed = partner_config.validate_config(document(), "claude_code")
        identities = parsed["hosts"]["claude_code"]["identities"]
        once = partner_config.update_host(document(), "claude_code", identities)
        twice = partner_config.update_host(once, "claude_code", identities)
        self.assertEqual(once, twice)
        self.assertLess(once.index("backend ="), once.index("model ="))
        self.assertLess(once.index("model ="), once.index("effort ="))


class UnsupportedSyntaxTests(unittest.TestCase):
    def assert_parse_error(self, assignment: str):
        text = (
            "schema_version = 2\n"
            "revision = 0\n"
            "[hosts.codex.identities.deep_reasoner]\n"
            'backend = "codex"\n'
            f"{assignment}\n"
            'effort = "high"\n'
        )
        with self.assertRaises(partner_config.ConfigParseError) as raised:
            partner_config.validate_config(text, "codex")
        message = str(raised.exception)
        self.assertRegex(message, r"line \d+, column \d+")
        self.assertIn("docs/config-schema.md", message)

    def test_inline_table_fails_closed(self):
        self.assert_parse_error("model = { name = \"x\" }")

    def test_multiline_string_fails_closed(self):
        self.assert_parse_error('model = """x"""')

    def test_datetime_fails_closed(self):
        self.assert_parse_error("model = 2026-07-19T10:00:00Z")

    def test_array_of_tables_fails_closed(self):
        text = "schema_version = 2\n[[hosts.codex.identities]]\nmodel = \"x\"\n"
        with self.assertRaises(partner_config.ConfigParseError) as raised:
            partner_config.validate_config(text, "codex")
        self.assertIn("line 2, column 1", str(raised.exception))

    def test_dotted_key_assignment_fails_closed(self):
        self.assert_parse_error('settings.model = "x"')


class BackendValidationTests(unittest.TestCase):
    def identity_document(self, backend: str = "") -> str:
        return (
            "schema_version = 2\n"
            "revision = 0\n"
            "[hosts.codex.identities.deep_reasoner]\n"
            f"{backend}"
            'model = "gpt-test"\n'
            'effort = "high"\n'
        )

    def test_missing_backend_fails_validation(self):
        with self.assertRaises(partner_config.ConfigValidationError) as raised:
            partner_config.validate_config(self.identity_document(), "codex")
        self.assertIn("backend must be one of claude, codex", str(raised.exception))

    def test_invalid_backend_fails_validation(self):
        with self.assertRaises(partner_config.ConfigValidationError) as raised:
            partner_config.validate_config(
                self.identity_document('backend = "local"\n'), "codex"
            )
        self.assertIn("backend must be one of claude, codex", str(raised.exception))


class LegacyMigrationTests(unittest.TestCase):
    def run_cli(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = partner_config.main(list(arguments))
        return status, stdout.getvalue(), stderr.getvalue()

    def assert_upgrade_error(self, message: str, path: Path):
        self.assertIn(partner_config.V1_UPGRADE_MESSAGE, message)
        self.assertIn(str(path), message)

    def test_resolve_v1_file_reports_upgrade_guide_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            path = repo / ".partner" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text(legacy_document(), encoding="utf-8")
            env = {"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "xdg")}
            with self.assertRaises(partner_config.ConfigValidationError) as raised:
                partner_config.resolve_config(repo, "codex", env=env)
            self.assert_upgrade_error(str(raised.exception), path)

    def test_validate_v1_file_reports_upgrade_guide_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".partner" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text(legacy_document(), encoding="utf-8")
            status, _, error = self.run_cli(
                "--host", "codex", "--repo", directory, "validate"
            )
            self.assertEqual(2, status)
            self.assert_upgrade_error(error, path)

    def test_set_v1_file_reports_upgrade_guide_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".partner" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text(legacy_document(), encoding="utf-8")
            before = path.read_bytes()
            status, _, error = self.run_cli(
                "--host", "codex", "--repo", directory, "set",
                "--role", "deep_reasoner", "--backend", "codex",
                "--model", "new-model", "--effort", "high",
            )
            self.assertEqual(2, status)
            self.assert_upgrade_error(error, path)
            self.assertEqual(before, path.read_bytes())

    def test_schema_v2_with_legacy_role_section_fails_closed(self):
        text = legacy_document().replace("schema_version = 1", "schema_version = 2")
        path = Path("/tmp/schema-v2-with-roles.toml")
        with self.assertRaises(partner_config.ConfigValidationError) as raised:
            partner_config.validate_config(text, "codex", path=path)
        self.assert_upgrade_error(str(raised.exception), path)

    def test_read_legacy_v1_extracts_only_model_and_effort_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(legacy_document(), encoding="utf-8")
            before = path.read_bytes()
            extracted = partner_config.read_legacy_v1(
                path.read_text(encoding="utf-8"), "codex"
            )
            self.assertEqual(
                {
                    "deep_reasoner": {"model": "gpt-legacy", "effort": "xhigh"},
                    "fast_worker": {"model": "gpt-legacy-fast", "effort": "medium"},
                },
                extracted,
            )
            self.assertEqual(before, path.read_bytes())


class ResolveTests(unittest.TestCase):
    def test_priority_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            xdg = root / "xdg"
            global_path = xdg / "partner" / "config.toml"
            project_path = repo / ".partner" / "config.toml"
            global_path.parent.mkdir(parents=True)
            project_path.parent.mkdir(parents=True)
            global_path.write_text(
                partner_config.update_host("", "codex", {
                    "deep_reasoner": {"backend": "codex", "model": "global", "effort": "high"},
                    "fast_worker": {"backend": "claude", "model": "global-fast", "effort": "low"},
                }), encoding="utf-8"
            )
            project_path.write_text(
                partner_config.update_host("", "codex", {
                    "deep_reasoner": {"backend": "codex", "model": "project", "effort": "xhigh"},
                    "fast_worker": {"backend": "claude", "model": "project-fast", "effort": "medium"},
                }), encoding="utf-8"
            )
            env = {"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(xdg)}
            resolved = partner_config.resolve_config(repo, "codex", env=env)
            self.assertEqual("project", resolved["source"])
            self.assertEqual("project", resolved["hosts"]["codex"]["identities"]["deep_reasoner"]["model"])
            self.assertEqual("codex", resolved["hosts"]["codex"]["identities"]["deep_reasoner"]["backend"])
            override = {"hosts": {"codex": {"identities": {"deep_reasoner": {"model": "session"}}}}}
            resolved = partner_config.resolve_config(repo, "codex", override, env=env)
            self.assertEqual("session", resolved["source"])
            self.assertEqual("session", resolved["hosts"]["codex"]["identities"]["deep_reasoner"]["model"])
            project_path.unlink()
            resolved = partner_config.resolve_config(repo, "codex", env=env)
            self.assertEqual("global", resolved["source"])
            global_path.unlink()
            resolved = partner_config.resolve_config(repo, "codex", env=env)
            self.assertEqual("default", resolved["source"])
            self.assertEqual({}, resolved["hosts"]["codex"]["identities"])

    def test_higher_layer_identity_change_invalidates_inherited_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            xdg = root / "xdg"
            global_path = xdg / "partner" / "config.toml"
            project_path = repo / ".partner" / "config.toml"
            global_path.parent.mkdir(parents=True)
            project_path.parent.mkdir(parents=True)
            global_path.write_text(
                partner_config.update_host(
                    "",
                    "codex",
                    {
                        "deep_reasoner": {
                            "backend": "claude",
                            "model": "verified-old",
                            "effort": "high",
                            "verified": True,
                            "verified_at": "2026-07-29T00:00:00Z",
                        }
                    },
                ),
                encoding="utf-8",
            )
            project_path.write_text(
                partner_config.update_host(
                    "",
                    "codex",
                    {
                        "deep_reasoner": {
                            "backend": "claude",
                            "model": "unverified-new",
                            "effort": "xhigh",
                        }
                    },
                ),
                encoding="utf-8",
            )
            env = {"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(xdg)}
            resolved = partner_config.resolve_config(repo, "codex", env=env)
            identity = resolved["hosts"]["codex"]["identities"]["deep_reasoner"]
            self.assertEqual("unverified-new", identity["model"])
            self.assertFalse(identity["verified"])
            self.assertNotIn("verified_at", identity)

            override = {
                "hosts": {
                    "codex": {
                        "identities": {
                            "deep_reasoner": {"model": "session-model"}
                        }
                    }
                }
            }
            resolved = partner_config.resolve_config(
                repo, "codex", override, env=env
            )
            identity = resolved["hosts"]["codex"]["identities"]["deep_reasoner"]
            self.assertEqual("session-model", identity["model"])
            self.assertFalse(identity["verified"])


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_leaves_no_tempfile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            partner_config.atomic_write(path, "one\n")
            partner_config.atomic_write(path, "two\n")
            self.assertEqual("two\n", path.read_text(encoding="utf-8"))
            self.assertEqual(["config.toml"], sorted(item.name for item in path.parent.iterdir()))


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = partner_config.main(list(arguments))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_init_set_get_validate_and_idempotent_init(self):
        with tempfile.TemporaryDirectory() as directory:
            base = ("--host", "codex", "--repo", directory)
            self.assertEqual(0, self.run_cli(*base, "init")[0])
            status, _, error = self.run_cli(
                *base, "set", "--role", "deep_reasoner",
                "--backend", "codex", "--model", "chosen-model", "--effort", "high",
            )
            self.assertEqual((0, ""), (status, error))
            self.assertEqual(0, self.run_cli(*base, "validate")[0])
            status, output, error = self.run_cli(
                *base, "get", "hosts.codex.identities.deep_reasoner.model"
            )
            self.assertEqual((0, "chosen-model\n", ""), (status, output, error))
            status, _, error = self.run_cli(
                *base, "set", "--role", "deep_reasoner", "--effort", "xhigh"
            )
            self.assertEqual((0, ""), (status, error))
            status, output, error = self.run_cli(
                *base, "get", "hosts.codex.identities.deep_reasoner.backend"
            )
            self.assertEqual((0, "codex\n", ""), (status, output, error))
            path = Path(directory) / ".partner" / "config.toml"
            self.assertIn("schema_version = 2", path.read_text(encoding="utf-8"))
            before = path.read_bytes()
            self.assertEqual(0, self.run_cli(*base, "init")[0])
            self.assertEqual(before, path.read_bytes())

    def test_invalid_new_role_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            base = ("--host", "codex", "--repo", directory)
            self.assertEqual(0, self.run_cli(*base, "init")[0])
            path = Path(directory) / ".partner" / "config.toml"
            before = path.read_bytes()
            status, _, error = self.run_cli(
                *base, "set", "--role", "fast_worker", "--backend", "claude",
                "--model", "model-only"
            )
            self.assertEqual(2, status)
            self.assertIn("effort must be a non-empty string", error)
            self.assertEqual(before, path.read_bytes())

    def test_new_identity_requires_backend_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = ("--host", "codex", "--repo", directory)
            self.assertEqual(0, self.run_cli(*base, "init")[0])
            path = Path(directory) / ".partner" / "config.toml"
            before = path.read_bytes()
            status, _, error = self.run_cli(
                *base, "set", "--role", "fast_worker",
                "--model", "gpt-fast", "--effort", "medium",
            )
            self.assertEqual(2, status)
            self.assertIn("backend must be one of claude, codex", error)
            self.assertEqual(before, path.read_bytes())

    def test_arbiter_full_read_write_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            base = ("--host", "claude_code", "--repo", directory)
            self.assertEqual(0, self.run_cli(*base, "init")[0])
            status, _, error = self.run_cli(
                *base, "set", "--role", "arbiter", "--backend", "codex",
                "--model", "gpt-arbiter", "--effort", "xhigh", "--verified",
            )
            self.assertEqual((0, ""), (status, error))
            status, output, error = self.run_cli(
                *base, "get", "hosts.claude_code.identities.arbiter"
            )
            self.assertEqual((0, ""), (status, error))
            self.assertEqual(
                {"backend": "codex", "effort": "xhigh", "model": "gpt-arbiter", "verified": True},
                json.loads(output),
            )

    def test_identity_change_invalidates_existing_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            base = ("--host", "codex", "--repo", directory)
            self.assertEqual(0, self.run_cli(*base, "init")[0])
            self.assertEqual(
                0,
                self.run_cli(
                    *base,
                    "set",
                    "--role",
                    "deep_reasoner",
                    "--backend",
                    "claude",
                    "--model",
                    "verified-old",
                    "--effort",
                    "high",
                    "--verified",
                    "--verified-at",
                    "2026-07-29T00:00:00Z",
                )[0],
            )
            self.assertEqual(
                0,
                self.run_cli(
                    *base,
                    "set",
                    "--role",
                    "deep_reasoner",
                    "--model",
                    "unverified-new",
                )[0],
            )
            status, output, error = self.run_cli(
                *base, "get", "hosts.codex.identities.deep_reasoner"
            )
            self.assertEqual((0, ""), (status, error))
            identity = json.loads(output)
            self.assertEqual("unverified-new", identity["model"])
            self.assertFalse(identity["verified"])
            self.assertNotIn("verified_at", identity)


class LockTests(unittest.TestCase):
    def make_lock(self, root: Path, pid: int, timestamp: float):
        lock_path = root / ".config.lock"
        lock_path.mkdir()
        (lock_path / "info").write_text(
            json.dumps({"pid": pid, "ts": timestamp, "host": "test", "token": "old"}) + "\n",
            encoding="utf-8",
        )

    def test_dead_pid_is_reclaimed_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_lock(root, 123, 100.0)
            lock = partner_config.ConfigLock(
                root / "config.toml", clock=lambda: 101.0, sleep=lambda _: None,
                pid_alive=lambda _: False, retries=0,
            )
            with lock:
                owner = json.loads((root / ".config.lock" / "info").read_text(encoding="utf-8"))
                self.assertEqual(os.getpid(), owner["pid"])
                self.assertEqual("unknown", owner["host"])
            self.assertFalse((root / ".config.lock").exists())

    def test_live_but_timed_out_pid_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_lock(root, 456, 10.0)
            lock = partner_config.ConfigLock(
                root / "config.toml", clock=lambda: 30.0, stale_after=15.0,
                sleep=lambda _: None, pid_alive=lambda _: True, retries=0,
            )
            with lock:
                self.assertTrue((root / ".config.lock").is_dir())
            self.assertFalse((root / ".config.lock").exists())

    def test_live_owner_fails_after_bounded_backoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_lock(root, 789, 99.0)
            delays = []
            lock = partner_config.ConfigLock(
                root / "config.toml", clock=lambda: 100.0, stale_after=15.0,
                retries=3, base_delay=0.001, sleep=delays.append,
                pid_alive=lambda _: True,
            )
            with self.assertRaises(partner_config.ConfigLockError) as raised:
                lock.acquire()
            self.assertEqual([0.001, 0.002, 0.004], delays)
            message = str(raised.exception)
            self.assertIn("pid=789", message)
            self.assertIn("ts=99.0", message)
            self.assertIn(str(root / ".config.lock"), message)
            self.assertTrue((root / ".config.lock").exists())


if __name__ == "__main__":
    unittest.main()

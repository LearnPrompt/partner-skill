from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "partner-setup.py"
SPEC = importlib.util.spec_from_file_location("partner_setup", SCRIPT)
partner_setup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = partner_setup
SPEC.loader.exec_module(partner_setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.home = self.root / "home"
        self.xdg = self.root / "xdg"
        self.codex_home = self.root / "codex-home"
        self.repo.mkdir()
        self.home.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.xdg),
                "CODEX_HOME": str(self.codex_home),
            }
        )

    def run_cli(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = partner_setup.main(list(arguments), env=self.env)
        return status, stdout.getvalue(), stderr.getvalue()

    def claude_args(self, action="--apply", *extra):
        return (
            action,
            "--host",
            "claude_code",
            "--repo",
            str(self.repo),
            "--exclude-choice",
            "track",
            *extra,
        )

    def codex_args(self, action="--apply", *extra):
        return (
            action,
            "--host",
            "codex",
            "--repo",
            str(self.repo),
            "--exclude-choice",
            "track",
            *extra,
        )

    def write_codex_native(self, model="gpt-detected", effort="xhigh"):
        self.codex_home.mkdir(parents=True, exist_ok=True)
        (self.codex_home / "config.toml").write_text(
            f'model = "{model}"\nmodel_reasoning_effort = "{effort}"\n',
            encoding="utf-8",
        )

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_preview_is_zero_write_and_lists_every_target_with_diffs(self):
        before = self.snapshot()
        status, output, error = self.run_cli(
            *self.claude_args("--preview", "--routing-block")
        )
        self.assertEqual((0, ""), (status, error))
        self.assertEqual(before, self.snapshot())
        repo = self.repo.resolve()
        targets = (
            repo / ".partner" / "config.toml",
            repo / ".claude" / "agents" / "partner-deep-reasoner.md",
            repo / ".claude" / "agents" / "partner-fast-worker.md",
            repo / ".partner" / ".generated-manifest",
            repo / "CLAUDE.md",
        )
        for target in targets:
            self.assertIn(str(target), output)
            self.assertIn(f"Diff: {target}", output)
        self.assertGreaterEqual(output.count("--- /dev/null"), len(targets))

    def test_apply_is_idempotent_for_config_and_agents(self):
        self.assertEqual(0, self.run_cli(*self.claude_args())[0])
        config = self.repo / ".partner" / "config.toml"
        agents = sorted((self.repo / ".claude" / "agents").glob("*.md"))
        before = {path: path.read_bytes() for path in [config, *agents]}
        status, output, error = self.run_cli(*self.claude_args())
        self.assertEqual((0, ""), (status, error))
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertIn("UNCHANGED", output)

    def test_user_agent_is_refused_while_other_files_are_written(self):
        agent_dir = self.repo / ".claude" / "agents"
        agent_dir.mkdir(parents=True)
        protected = agent_dir / "partner-deep-reasoner.md"
        protected.write_text("user content\n", encoding="utf-8")
        status, _, error = self.run_cli(*self.claude_args())
        self.assertEqual(1, status)
        self.assertIn("REFUSED", error)
        self.assertIn("references/setup.md", error)
        self.assertEqual("user content\n", protected.read_text(encoding="utf-8"))
        self.assertTrue((agent_dir / "partner-fast-worker.md").is_file())
        self.assertTrue((self.repo / ".partner" / "config.toml").is_file())
        manifest = json.loads(
            (self.repo / ".partner" / ".generated-manifest").read_text(encoding="utf-8")
        )
        self.assertNotIn(str(protected), manifest)

    def test_second_host_apply_preserves_first_host_sections_byte_for_byte(self):
        self.write_codex_native()
        self.assertEqual(0, self.run_cli(*self.codex_args())[0])
        config = self.repo / ".partner" / "config.toml"
        before = partner_setup.read_text(config)
        codex_chunks = "".join(
            chunk.text
            for chunk in partner_setup.partner_config.split_sections(before)
            if chunk.name and chunk.name.startswith("hosts.codex.roles.")
        )
        self.assertEqual(0, self.run_cli(*self.claude_args())[0])
        after = partner_setup.read_text(config)
        after_codex_chunks = "".join(
            chunk.text
            for chunk in partner_setup.partner_config.split_sections(after)
            if chunk.name and chunk.name.startswith("hosts.codex.roles.")
        )
        self.assertEqual(codex_chunks, after_codex_chunks)

    def test_managed_block_apply_and_remove_restore_original_bytes(self):
        target = self.repo / "CLAUDE.md"
        original = "# User rules\n\nKeep this byte-for-byte.\n"
        target.write_text(original, encoding="utf-8")
        self.assertEqual(
            0,
            self.run_cli(
                *self.claude_args("--apply", "--no-write-agents", "--routing-block")
            )[0],
        )
        managed = target.read_text(encoding="utf-8")
        self.assertIn(partner_setup.BEGIN_MARKER, managed)
        self.assertNotIn("opus", managed)
        self.assertNotIn("high", managed)
        self.assertEqual(
            0,
            self.run_cli(
                *self.claude_args(
                    "--apply", "--no-write-agents", "--remove-routing-block"
                )
            )[0],
        )
        self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_managed_block_five_fail_closed_cases_and_force_boundary(self):
        valid = partner_setup.render_managed_block()
        digest_at = valid.index("sha256:") + len("sha256:")
        wrong_digit = "0" if valid[digest_at] != "0" else "1"
        hash_mismatch = valid[:digest_at] + wrong_digit + valid[digest_at + 1 :]
        malformed = {
            "missing_half": partner_setup.BEGIN_MARKER + "\n",
            "duplicate": (
                partner_setup.BEGIN_MARKER
                + "\n"
                + partner_setup.BEGIN_MARKER
                + "\n"
                + partner_setup.END_MARKER
                + "\n"
            ),
            "reversed": partner_setup.END_MARKER + "\n" + partner_setup.BEGIN_MARKER + "\n",
            "hash_mismatch": hash_mismatch,
            "hash_missing": (
                partner_setup.BEGIN_MARKER
                + "\nchanged policy\n"
                + partner_setup.END_MARKER
                + "\n"
            ),
        }
        for name, text in malformed.items():
            with self.subTest(name=name):
                with self.assertRaises(partner_setup.SetupError):
                    partner_setup.update_managed_block(text)
        self.assertIn(
            partner_setup.HASH_PREFIX,
            partner_setup.update_managed_block(malformed["hash_missing"], force=True),
        )
        with self.assertRaises(partner_setup.SetupError):
            partner_setup.update_managed_block(malformed["missing_half"], force=True)
        empty = partner_setup.BEGIN_MARKER + "\n" + partner_setup.END_MARKER + "\n"
        self.assertIn(partner_setup.HASH_PREFIX, partner_setup.update_managed_block(empty))

    def test_rollback_restores_latest_pre_apply_state_and_keeps_three_backups(self):
        modes = ("balanced", "quality", "cost", "balanced")
        previous = b""
        for index, mode in enumerate(modes, 1):
            config = self.repo / ".partner" / "config.toml"
            previous = config.read_bytes() if config.exists() else b""
            status, _, error = self.run_cli(
                *self.claude_args(
                    "--apply",
                    "--mode",
                    mode,
                    "--timestamp",
                    f"20260720T00000{index}Z",
                )
            )
            self.assertEqual((0, ""), (status, error))
        backups = sorted((self.repo / ".partner" / "backups").glob("*/manifest.json"))
        self.assertEqual(3, len(backups))
        status, _, error = self.run_cli(
            "--rollback",
            "--host",
            "claude_code",
            "--repo",
            str(self.repo),
        )
        self.assertEqual((0, ""), (status, error))
        self.assertEqual(previous, (self.repo / ".partner" / "config.toml").read_bytes())

    def test_git_exclude_is_added_once(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        arguments = (
            "--apply",
            "--host",
            "claude_code",
            "--repo",
            str(self.repo),
            "--no-write-agents",
        )
        self.assertEqual(0, self.run_cli(*arguments)[0])
        self.assertEqual(0, self.run_cli(*arguments)[0])
        exclude = self.repo / ".git" / "info" / "exclude"
        self.assertEqual(1, exclude.read_text(encoding="utf-8").splitlines().count(".partner/config.toml"))

    def test_codex_without_detected_or_explicit_model_fails_with_guidance(self):
        status, _, error = self.run_cli(*self.codex_args("--preview"))
        self.assertEqual(2, status)
        self.assertIn("CODEX_HOME", error)
        self.assertIn("--role-model deep_reasoner", error)
        self.assertFalse((self.repo / ".partner").exists())

    def test_codex_smoke_records_exact_timestamp(self):
        self.write_codex_native()
        self.assertEqual(0, self.run_cli(*self.codex_args())[0])
        timestamp = "2026-07-20T01:02:03Z"
        status, output, error = self.run_cli(
            "--smoke",
            "--host",
            "codex",
            "--repo",
            str(self.repo),
            "--timestamp",
            timestamp,
        )
        self.assertEqual((0, ""), (status, error))
        self.assertEqual(2, output.count("PASS"))
        parsed = partner_setup.partner_config.validate_config(
            partner_setup.read_text(self.repo / ".partner" / "config.toml"), "codex"
        )
        for role in partner_setup.ROLES:
            values = parsed["hosts"]["codex"]["roles"][role]
            self.assertTrue(values["verified"])
            self.assertEqual(timestamp, values["verified_at"])

        status, status_output, error = self.run_cli(
            "--status", "--host", "codex", "--repo", str(self.repo)
        )
        self.assertEqual((0, ""), (status, error))
        self.assertIn("config_source=project", status_output)
        self.assertIn("model=gpt-detected", status_output)
        self.assertIn("effort=high", status_output)
        self.assertIn("verified=true", status_output)
        self.assertIn(f"verified_at={timestamp}", status_output)

    def test_uninstall_removes_manifest_tracked_agents_and_updates_manifest(self):
        self.assertEqual(0, self.run_cli(*self.claude_args())[0])
        deep_agent = self.repo.resolve() / ".claude" / "agents" / "partner-deep-reasoner.md"
        fast_agent = self.repo.resolve() / ".claude" / "agents" / "partner-fast-worker.md"
        self.assertTrue(deep_agent.is_file())
        self.assertTrue(fast_agent.is_file())

        status, output, error = self.run_cli(
            "--uninstall", "--host", "claude_code", "--repo", str(self.repo)
        )
        self.assertEqual((0, ""), (status, error))
        self.assertIn(f"REMOVED {deep_agent}", output)
        self.assertIn(f"REMOVED {fast_agent}", output)
        self.assertFalse(deep_agent.exists())
        self.assertFalse(fast_agent.exists())
        manifest = json.loads(
            (self.repo / ".partner" / ".generated-manifest").read_text(encoding="utf-8")
        )
        self.assertNotIn(str(deep_agent), manifest)
        self.assertNotIn(str(fast_agent), manifest)
        # Config itself is untouched by a plain uninstall.
        self.assertTrue((self.repo / ".partner" / "config.toml").is_file())

    def test_uninstall_skips_agent_modified_since_generation(self):
        self.assertEqual(0, self.run_cli(*self.claude_args())[0])
        deep_agent = self.repo.resolve() / ".claude" / "agents" / "partner-deep-reasoner.md"
        deep_agent.write_text("hand-edited by the user\n", encoding="utf-8")

        status, _, error = self.run_cli(
            "--uninstall", "--host", "claude_code", "--repo", str(self.repo)
        )
        self.assertEqual(0, status)
        self.assertIn("modified since generation", error)
        self.assertEqual("hand-edited by the user\n", deep_agent.read_text(encoding="utf-8"))

    def test_uninstall_dry_run_removes_nothing(self):
        self.assertEqual(0, self.run_cli(*self.claude_args())[0])
        deep_agent = self.repo.resolve() / ".claude" / "agents" / "partner-deep-reasoner.md"
        before = deep_agent.read_bytes()

        status, output, error = self.run_cli(
            "--uninstall", "--host", "claude_code", "--repo", str(self.repo), "--dry-run"
        )
        self.assertEqual((0, ""), (status, error))
        self.assertIn(f"WOULD_REMOVE {deep_agent}", output)
        self.assertTrue(deep_agent.exists())
        self.assertEqual(before, deep_agent.read_bytes())

    def test_uninstall_removes_managed_block_and_restores_user_content(self):
        target = self.repo / "CLAUDE.md"
        original = "# User rules\n\nKeep this byte-for-byte.\n"
        target.write_text(original, encoding="utf-8")
        self.assertEqual(
            0,
            self.run_cli(*self.claude_args("--apply", "--no-write-agents", "--routing-block"))[0],
        )
        self.assertIn(partner_setup.BEGIN_MARKER, target.read_text(encoding="utf-8"))

        status, output, error = self.run_cli(
            "--uninstall", "--host", "claude_code", "--repo", str(self.repo)
        )
        self.assertEqual((0, ""), (status, error))
        self.assertIn("managed routing block", output)
        self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_uninstall_remove_config_clears_only_this_hosts_roles(self):
        self.write_codex_native()
        self.assertEqual(0, self.run_cli(*self.codex_args())[0])
        self.assertEqual(0, self.run_cli(*self.claude_args())[0])
        config = self.repo / ".partner" / "config.toml"
        codex_before = "".join(
            chunk.text
            for chunk in partner_setup.partner_config.split_sections(partner_setup.read_text(config))
            if chunk.name and chunk.name.startswith("hosts.codex.roles.")
        )

        status, output, error = self.run_cli(
            "--uninstall", "--host", "claude_code", "--repo", str(self.repo), "--remove-config"
        )
        self.assertEqual((0, ""), (status, error))
        self.assertIn("roles cleared", output)
        parsed = partner_setup.partner_config.validate_config(
            partner_setup.read_text(config), "claude_code"
        )
        self.assertEqual({}, parsed["hosts"]["claude_code"]["roles"])
        codex_after = "".join(
            chunk.text
            for chunk in partner_setup.partner_config.split_sections(partner_setup.read_text(config))
            if chunk.name and chunk.name.startswith("hosts.codex.roles.")
        )
        self.assertEqual(codex_before, codex_after)

    def test_claude_smoke_never_guesses_verified_true(self):
        self.assertEqual(0, self.run_cli(*self.claude_args())[0])
        status, output, error = self.run_cli(
            "--smoke",
            "--host",
            "claude_code",
            "--repo",
            str(self.repo),
            "--timestamp",
            "2026-07-20T01:02:03Z",
        )
        self.assertEqual((0, ""), (status, error))
        self.assertIn("needs_new_session", output)
        parsed = partner_setup.partner_config.validate_config(
            partner_setup.read_text(self.repo / ".partner" / "config.toml"),
            "claude_code",
        )
        for role in partner_setup.ROLES:
            self.assertFalse(parsed["hosts"]["claude_code"]["roles"][role]["verified"])


if __name__ == "__main__":
    unittest.main()

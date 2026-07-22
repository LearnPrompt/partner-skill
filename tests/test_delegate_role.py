from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path("scripts/delegate-codex.sh")


class DelegateRoleTests(unittest.TestCase):
    def run_submit(self, config: str | None, *arguments: str, init_git: bool = False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        repo = root / "repo"
        repo.mkdir()
        if init_git:
            subprocess.run(
                ["git", "init", "--quiet", str(repo)],
                check=True,
                capture_output=True,
                text=True,
            )
        prompt = root / "prompt.md"
        prompt.write_text("test prompt\n", encoding="utf-8")
        if config is not None:
            config_path = repo / ".partner" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text(config, encoding="utf-8")
        fake_codex = root / "codex"
        fake_codex.write_text(
            "#!/usr/bin/env bash\nprintf 'codex-cli test-version\\n'\n",
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(root / "home"),
                "XDG_CONFIG_HOME": str(root / "xdg"),
                "PARTNER_CODEX_BIN": str(fake_codex),
            }
        )
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "submit",
                "--repo",
                str(repo),
                "--prompt-file",
                str(prompt),
                "--dry-run",
                *arguments,
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return result, repo

    @staticmethod
    def config(
        *,
        include_deep_reasoner: bool = True,
        deep_reasoner_backend: str = "codex",
        include_arbiter: bool = False,
        include_claude_code: bool = False,
    ) -> str:
        deep_reasoner = ""
        if include_deep_reasoner:
            deep_reasoner = (
                "[hosts.codex.identities.deep_reasoner]\n"
                f'backend = "{deep_reasoner_backend}"\n'
                'model = "gpt-deep"\n'
                'effort = "xhigh"\n\n'
            )
        arbiter = ""
        if include_arbiter:
            arbiter = (
                "\n[hosts.codex.identities.arbiter]\n"
                'backend = "codex"\n'
                'model = "gpt-arbiter"\n'
                'effort = "high"\n'
            )
        claude_code = ""
        if include_claude_code:
            claude_code = (
                "\n[hosts.claude_code.identities.deep_reasoner]\n"
                'backend = "codex"\n'
                'model = "claude-driver-delegate"\n'
                'effort = "medium"\n'
            )
        return (
            "schema_version = 2\n"
            "revision = 0\n\n"
            f"{deep_reasoner}"
            "[hosts.codex.identities.fast_worker]\n"
            'backend = "codex"\n'
            'model = "gpt-fast"\n'
            'effort = "low"\n'
            f"{arbiter}"
            f"{claude_code}"
        )

    @staticmethod
    def parsed(output: str) -> dict[str, str]:
        return dict(line.split("=", 1) for line in output.splitlines())

    def test_deep_reasoner_uses_project_config(self):
        result, _ = self.run_submit(self.config(), "--role", "deep_reasoner")
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        expected = {
            "role": "deep_reasoner",
            "backend": "codex",
            "config_host": "codex",
            "model": "gpt-deep",
            "effort": "xhigh",
            "model_source": "config:project",
            "effort_source": "config:project",
        }
        self.assertEqual(expected, {key: parsed[key] for key in expected})

    def test_explicit_effort_overrides_fast_worker_config(self):
        result, _ = self.run_submit(
            self.config(), "--role", "fast_worker", "--effort", "xhigh"
        )
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        self.assertEqual("gpt-fast", parsed["model"])
        self.assertEqual("config:project", parsed["model_source"])
        self.assertEqual("xhigh", parsed["effort"])
        self.assertEqual("explicit", parsed["effort_source"])

    def test_missing_role_fails_with_setup_guidance(self):
        result, _ = self.run_submit(
            self.config(include_deep_reasoner=False), "--role", "deep_reasoner"
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "python3 scripts/partner-config.py --host codex init", result.stderr
        )
        self.assertIn("set --role deep_reasoner", result.stderr)

    def test_without_role_uses_default_effort(self):
        result, _ = self.run_submit(None)
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        self.assertEqual("none", parsed["role"])
        self.assertEqual("codex", parsed["backend"])
        self.assertEqual("codex", parsed["config_host"])
        self.assertEqual("default", parsed["model"])
        self.assertEqual("high", parsed["effort"])
        self.assertEqual("default", parsed["effort_source"])

    def test_dry_run_does_not_create_jobs_directory(self):
        result, repo = self.run_submit(self.config(), "--role", "deep_reasoner")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((repo / ".partner" / "jobs").exists())

    def test_dry_run_reports_selected_codex_binary(self):
        result, _ = self.run_submit(self.config(), "--role", "deep_reasoner")
        self.assertEqual(0, result.returncode, result.stderr)
        parsed = self.parsed(result.stdout)
        self.assertEqual("env", parsed["codex_bin_source"])
        self.assertEqual("codex-cli test-version", parsed["codex_version"])
        self.assertTrue(parsed["codex_bin"].endswith("/codex"))

    def test_arbiter_uses_codex_identity_config(self):
        result, _ = self.run_submit(
            self.config(include_arbiter=True), "--role", "arbiter"
        )
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        self.assertEqual("arbiter", parsed["role"])
        self.assertEqual("gpt-arbiter", parsed["model"])
        self.assertEqual("high", parsed["effort"])
        self.assertEqual("codex", parsed["backend"])

    def test_claude_code_host_uses_its_identity_namespace(self):
        result, _ = self.run_submit(
            self.config(include_claude_code=True),
            "--role",
            "deep_reasoner",
            "--host",
            "claude_code",
        )
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        self.assertEqual("claude-driver-delegate", parsed["model"])
        self.assertEqual("medium", parsed["effort"])
        self.assertEqual("codex", parsed["backend"])
        self.assertEqual("claude_code", parsed["config_host"])

    def test_claude_backend_fails_with_spawn_guidance(self):
        result, _ = self.run_submit(
            self.config(deep_reasoner_backend="claude"),
            "--role",
            "deep_reasoner",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("backend=claude", result.stderr)
        self.assertIn("spawn partner-deep_reasoner subagent", result.stderr)

    def test_default_host_uses_codex_namespace(self):
        result, _ = self.run_submit(
            self.config(include_claude_code=True), "--role", "deep_reasoner"
        )
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        self.assertEqual("gpt-deep", parsed["model"])
        self.assertEqual("codex", parsed["config_host"])

    def test_non_git_repo_appends_skip_git_repo_check(self):
        result, repo = self.run_submit(None)
        self.assertFalse((repo / ".git").exists())
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        self.assertIn("--skip-git-repo-check", result.stdout)
        self.assertEqual("--skip-git-repo-check", parsed["skip_git_repo_check"])

    def test_git_repo_omits_skip_git_repo_check(self):
        result, repo = self.run_submit(None, init_git=True)
        self.assertTrue((repo / ".git").exists())
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        parsed = self.parsed(result.stdout)
        self.assertNotIn("--skip-git-repo-check", result.stdout)
        self.assertEqual("", parsed["skip_git_repo_check"])


if __name__ == "__main__":
    unittest.main()

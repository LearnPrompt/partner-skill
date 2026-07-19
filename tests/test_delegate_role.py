from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path("scripts/delegate-codex.sh")


class DelegateRoleTests(unittest.TestCase):
    def run_submit(self, config: str | None, *arguments: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        repo = root / "repo"
        repo.mkdir()
        prompt = root / "prompt.md"
        prompt.write_text("test prompt\n", encoding="utf-8")
        if config is not None:
            config_path = repo / ".partner" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text(config, encoding="utf-8")
        env = os.environ.copy()
        env.update({"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "xdg")})
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
    def config(*, include_deep_reasoner: bool = True) -> str:
        deep_reasoner = ""
        if include_deep_reasoner:
            deep_reasoner = (
                "[hosts.codex.roles.deep_reasoner]\n"
                'model = "gpt-deep"\n'
                'effort = "xhigh"\n\n'
            )
        return (
            "schema_version = 1\n"
            "revision = 0\n\n"
            f"{deep_reasoner}"
            "[hosts.codex.roles.fast_worker]\n"
            'model = "gpt-fast"\n'
            'effort = "low"\n'
        )

    @staticmethod
    def parsed(output: str) -> dict[str, str]:
        return dict(line.split("=", 1) for line in output.splitlines())

    def test_deep_reasoner_uses_project_config(self):
        result, _ = self.run_submit(self.config(), "--role", "deep_reasoner")
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        self.assertEqual(
            {
                "role": "deep_reasoner",
                "model": "gpt-deep",
                "effort": "xhigh",
                "model_source": "config:project",
                "effort_source": "config:project",
            },
            self.parsed(result.stdout),
        )

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
        self.assertEqual("default", parsed["model"])
        self.assertEqual("high", parsed["effort"])
        self.assertEqual("default", parsed["effort_source"])

    def test_dry_run_does_not_create_jobs_directory(self):
        result, repo = self.run_submit(self.config(), "--role", "deep_reasoner")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((repo / ".partner" / "jobs").exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "goal-sync.py"
SPEC = importlib.util.spec_from_file_location("goal_sync", SCRIPT)
goal_sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = goal_sync
SPEC.loader.exec_module(goal_sync)


class GoalSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)

    def run_cli(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = goal_sync.main(["--repo", str(self.repo), *arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_first_write_needs_no_expected_hash(self):
        status, output, error = self.run_cli("write", "--file", self._write_tmp("# Goal\nhello\n"))
        self.assertEqual((0, ""), (status, error))
        self.assertIn("sha256=", output)
        self.assertEqual("# Goal\nhello\n", goal_sync.read_goal(self.repo))

    def test_write_over_existing_without_hash_is_refused(self):
        self.run_cli("write", "--file", self._write_tmp("v1\n"))
        status, _, error = self.run_cli("write", "--file", self._write_tmp("v2\n"))
        self.assertEqual(2, status)
        self.assertIn("already exists", error)
        self.assertEqual("v1\n", goal_sync.read_goal(self.repo))

    def test_stale_hash_write_is_rejected_and_file_unchanged(self):
        self.run_cli("write", "--file", self._write_tmp("v1\n"))
        _, read_output, _ = self.run_cli("read")
        stale_hash = read_output.splitlines()[0].split("=", 1)[1]

        # A second host writes concurrently, moving the file past that hash.
        status, _, _ = self.run_cli(
            "write", "--file", self._write_tmp("v2-from-other-host\n"), "--expect-sha256", stale_hash
        )
        self.assertEqual(0, status)

        # The first host retries its own write using the now-stale hash.
        status, _, error = self.run_cli(
            "write", "--file", self._write_tmp("v1-lost-update\n"), "--expect-sha256", stale_hash
        )
        self.assertEqual(2, status)
        self.assertIn("modified by another process", error)
        # No silent lost update: the second host's content survives untouched.
        self.assertEqual("v2-from-other-host\n", goal_sync.read_goal(self.repo))

    def test_matching_hash_write_succeeds(self):
        self.run_cli("write", "--file", self._write_tmp("v1\n"))
        _, read_output, _ = self.run_cli("read")
        current_hash = read_output.splitlines()[0].split("=", 1)[1]
        status, _, error = self.run_cli(
            "write", "--file", self._write_tmp("v2\n"), "--expect-sha256", current_hash
        )
        self.assertEqual((0, ""), (status, error))
        self.assertEqual("v2\n", goal_sync.read_goal(self.repo))

    def _write_tmp(self, content: str) -> str:
        handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".md")
        handle.write(content)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name


if __name__ == "__main__":
    unittest.main()

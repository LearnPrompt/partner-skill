from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "partner-setup-ui.py"
SPEC = importlib.util.spec_from_file_location("partner_setup_ui", SCRIPT)
partner_setup_ui = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = partner_setup_ui
SPEC.loader.exec_module(partner_setup_ui)


class SetupUITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.home = self.root / "home"
        self.codex_home = self.root / "codex-home"
        self.xdg = self.root / "xdg"
        self.bin = self.root / "bin"
        for path in (self.repo, self.home, self.codex_home, self.xdg, self.bin):
            path.mkdir()
        for name, version in (("claude", "Claude Code 9.9"), ("codex", "codex-cli 8.8")):
            executable = self.bin / name
            executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
            executable.chmod(0o755)
        (self.codex_home / "config.toml").write_text(
            'model = "gpt-detected"\nmodel_reasoning_effort = "xhigh"\n',
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "CODEX_HOME": str(self.codex_home),
                "XDG_CONFIG_HOME": str(self.xdg),
                "PATH": f"{self.bin}:/usr/bin:/bin",
                "PARTNER_CODEX_BIN": str(self.bin / "codex"),
            }
        )

    def payload(self, controller, mode="balanced"):
        state = controller.state()
        identities = {
            identity: {
                field: state["presets"][mode][identity][field]
                for field in ("backend", "model", "effort")
            }
            for identity in partner_setup_ui.engine.IDENTITIES
        }
        return {
            "mode": mode,
            "identities": identities,
            "scope": "project",
            "exclude_choice": "track",
            "routing_action": "none",
            "write_agents": False,
            "smoke": False,
        }

    def test_state_shows_exact_detected_models_and_full_presets(self):
        state = partner_setup_ui.build_state("codex", self.repo, self.env)
        self.assertEqual("default", state["config_source"])
        self.assertEqual("gpt-detected", state["detected"]["codex_model"])
        self.assertEqual("xhigh", state["detected"]["codex_effort"])
        self.assertEqual("Claude Code 9.9", state["clis"]["claude"]["version"])
        self.assertEqual(
            ("codex", "gpt-detected", "high", "detected"),
            tuple(
                state["presets"]["balanced"]["fast_worker"][field]
                for field in ("backend", "model", "effort", "model_source")
            ),
        )
        self.assertEqual(
            ("claude", "opus", "high"),
            tuple(
                state["presets"]["quality"]["fast_worker"][field]
                for field in ("backend", "model", "effort")
            ),
        )

    def test_preview_is_zero_write_and_apply_requires_the_same_payload(self):
        controller = partner_setup_ui.SetupController("codex", self.repo, self.env)
        payload = self.payload(controller)
        preview = controller.preview(payload)
        self.assertTrue(preview["ok"], preview)
        self.assertIn("fast_worker: backend=codex", preview["output"])
        config = self.repo / ".partner" / "config.toml"
        self.assertFalse(config.exists())

        changed = dict(payload)
        changed["scope"] = "global"
        with self.assertRaisesRegex(partner_setup_ui.UIError, "精确预览"):
            controller.apply(changed)

        applied = controller.apply(payload)
        self.assertTrue(applied["ok"], applied)
        self.assertTrue(config.is_file())
        status = partner_setup_ui.engine.partner_config.resolve_config(
            self.repo, "codex", env=self.env
        )
        self.assertEqual(
            "gpt-detected",
            status["hosts"]["codex"]["identities"]["fast_worker"]["model"],
        )

    def test_manual_matrix_requires_custom_mode(self):
        controller = partner_setup_ui.SetupController("codex", self.repo, self.env)
        payload = self.payload(controller)
        payload["identities"]["fast_worker"]["effort"] = "low"
        with self.assertRaisesRegex(partner_setup_ui.UIError, "自定义模式"):
            partner_setup_ui.normalize_payload(
                payload,
                host="codex",
                repo=self.repo,
                env=self.env,
            )
        payload["mode"] = "custom"
        normalized = partner_setup_ui.normalize_payload(
            payload,
            host="codex",
            repo=self.repo,
            env=self.env,
        )
        self.assertEqual("low", normalized["identities"]["fast_worker"]["effort"])

    def test_ui_keeps_the_taste_design_and_accessibility_contract(self):
        html = partner_setup_ui.HTML
        self.assertIn("Variance 8, motion 6, density 5", html)
        self.assertIn('class="hero-map"', html)
        self.assertIn('class="matrix" id="identities"', html)
        self.assertIn("@keyframes signal-run", html)
        self.assertIn("syncHeroMap()", html)
        self.assertIn("renderIdentities();\n      syncHeroMap();", html)
        self.assertIn("prefers-reduced-motion:no-preference", html)
        self.assertIn("prefers-reduced-motion:reduce", html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertIn('aria-describedby="${identity}-source"', html)
        for forbidden in ("backdrop-filter", "—", "–", " · "):
            self.assertNotIn(forbidden, html)


if __name__ == "__main__":
    unittest.main()

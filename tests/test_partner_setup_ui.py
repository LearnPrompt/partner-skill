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
        claude = self.bin / "claude"
        claude.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"--help\" ]; then\n"
            "  printf '%s\\n' '--effort <level>  Effort level for the current session'\n"
            "  printf '%s\\n' '                  (low, medium, high, xhigh, max)'\n"
            "  printf \"Provide\\n  an alias for the latest model (e.g.\\n  'fable', 'opus', or 'sonnet').\\n\"\n"
            "else\n"
            "  printf 'Claude Code 9.9\\n'\n"
            "fi\n",
            encoding="utf-8",
        )
        claude.chmod(0o755)
        codex = self.bin / "codex"
        codex.write_text(
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            "if '--version' in sys.argv:\n"
            "    print('codex-cli 8.8')\n"
            "elif len(sys.argv) > 1 and sys.argv[1] == 'app-server':\n"
            "    for line in sys.stdin:\n"
            "        message = json.loads(line)\n"
            "        if message.get('id') == 1:\n"
            "            print(json.dumps({'id': 1, 'result': {'userAgent': 'test'}}), flush=True)\n"
            "        elif message.get('id') == 2:\n"
            "            models = [\n"
            "                {'model': 'gpt-catalog', 'displayName': 'GPT Catalog', "
            "'description': 'Account model', 'isDefault': True, "
            "'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, "
            "{'reasoningEffort': 'high'}, {'reasoningEffort': 'ultra'}]},\n"
            "                {'model': 'gpt-catalog-fast', 'displayName': 'GPT Catalog Fast', "
            "'description': 'Fast model', 'isDefault': False, "
            "'supportedReasoningEfforts': [{'reasoningEffort': 'medium'}]},\n"
            "            ]\n"
            "            print(json.dumps({'id': 2, 'result': {'data': models, "
            "'nextCursor': None}}), flush=True)\n",
            encoding="utf-8",
        )
        codex.chmod(0o755)
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
        self.assertEqual(
            ["gpt-catalog", "gpt-catalog-fast", "gpt-detected"],
            [option["value"] for option in state["model_options"]["codex"]],
        )
        self.assertEqual(
            ["low", "high"], state["model_options"]["codex"][0]["efforts"]
        )
        self.assertEqual(
            ["fable", "opus", "sonnet", "haiku"],
            [option["value"] for option in state["model_options"]["claude"]],
        )
        self.assertEqual(
            ["low", "medium", "high", "xhigh", "max"],
            state["model_options"]["claude"][0]["efforts"],
        )
        self.assertEqual(
            {
                "claude": ["low", "medium", "high", "xhigh", "max"],
                "codex": ["minimal", "low", "medium", "high", "xhigh"],
            },
            state["efforts_by_backend"],
        )
        self.assertEqual("Codex CLI 自动获取", state["model_discovery"]["codex"])

    def test_claude_context_variants_are_normalized_and_deduplicated(self):
        options, _ = partner_setup_ui._claude_model_options(
            str(self.bin / "claude"),
            self.env,
            {
                "opus": "claude-opus-4-6[1m] 1M",
                "opus_duplicate": "claude-opus-4-6",
                "haiku": "haiku 1M",
            },
        )
        values = [option["value"] for option in options]
        self.assertEqual(1, values.count("haiku"))
        self.assertEqual(1, values.count("claude-opus-4-6"))
        self.assertNotIn("claude-opus-4-6[1m] 1M", values)

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

    def test_payload_rejects_effort_not_supported_by_backend_or_model(self):
        controller = partner_setup_ui.SetupController("codex", self.repo, self.env)
        payload = self.payload(controller)
        payload["mode"] = "custom"
        payload["identities"]["deep_reasoner"]["effort"] = "minimal"
        with self.assertRaisesRegex(partner_setup_ui.UIError, "claude/opus"):
            partner_setup_ui.normalize_payload(
                payload,
                host="codex",
                repo=self.repo,
                env=self.env,
                model_options=controller.initial_state["model_options"],
            )

        payload = self.payload(controller)
        payload["mode"] = "custom"
        payload["identities"]["fast_worker"]["model"] = "gpt-catalog-fast"
        payload["identities"]["fast_worker"]["effort"] = "high"
        with self.assertRaisesRegex(partner_setup_ui.UIError, "可选值：medium"):
            partner_setup_ui.normalize_payload(
                payload,
                host="codex",
                repo=self.repo,
                env=self.env,
                model_options=controller.initial_state["model_options"],
            )

    def test_ui_keeps_the_taste_design_and_accessibility_contract(self):
        html = partner_setup_ui.HTML
        self.assertIn("Variance 4, motion 5, density 4", html)
        self.assertIn('class="hero-map"', html)
        self.assertIn('class="matrix" id="identities"', html)
        self.assertIn(".main-heading,.settings-head", html)
        self.assertIn(".identity:nth-child(2) { --row:1; }", html)
        self.assertNotIn("margin-left:clamp", html)
        self.assertNotIn("margin-right:clamp", html)
        self.assertIn("@keyframes signal-run", html)
        self.assertIn("syncHeroMap()", html)
        self.assertIn("renderIdentities();\n      syncHeroMap();", html)
        self.assertIn("prefers-reduced-motion:no-preference", html)
        self.assertIn("prefers-reduced-motion:reduce", html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertIn('aria-describedby="${identity}-source"', html)
        self.assertIn('<select id="${identity}-model" data-field="model"', html)
        self.assertNotIn('type="text" data-field="model"', html)
        self.assertIn("Codex 模型从本机账户自动读取", html)
        self.assertIn('id="technicalDetails"', html)
        self.assertIn("查看完整路径和技术 diff", html)
        self.assertIn("我确认安装到当前项目", html)
        self.assertIn("scope: 'project'", html)
        self.assertIn("exclude_choice: 'git-exclude'", html)
        self.assertIn("function effortCatalog(backend, model)", html)
        self.assertIn("syncEffort(matrix[identity])", html)
        self.assertIn("安装完成，但自动检查未通过", html)
        for advanced_label in (
            "写入与验证",
            "写入范围",
            "所有项目",
            "项目配置的 Git 处理",
            "常驻路由块",
            "smoke test",
        ):
            self.assertNotIn(advanced_label, html)
        for forbidden in ("backdrop-filter", "—", "–", " · "):
            self.assertNotIn(forbidden, html)


if __name__ == "__main__":
    unittest.main()

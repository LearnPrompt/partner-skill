#!/usr/bin/env python3
"""Run the Partner setup wizard as a local, single-page web UI."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import selectors
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_PATH = SCRIPT_DIR / "partner-setup.py"
SPEC = importlib.util.spec_from_file_location("partner_setup_ui_engine", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - broken install
    raise RuntimeError(f"cannot load {ENGINE_PATH}")
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)

MODES = ("balanced", "quality", "cost", "custom")
SCOPES = ("project", "global")
EXCLUDE_CHOICES = ("git-exclude", "self", "track")
ROUTING_ACTIONS = ("none", "write", "remove")
CLAUDE_MODEL_ALIASES = ("fable", "opus", "sonnet", "haiku")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
IDENTITY_META = {
    "deep_reasoner": {
        "label": "深度推理",
        "hint": "架构、诊断与复杂取舍",
    },
    "fast_worker": {
        "label": "快速执行",
        "hint": "机械实现、测试与修复",
    },
    "arbiter": {
        "label": "独立仲裁",
        "hint": "争议结论的盲解复核",
    },
}


class UIError(Exception):
    """A user-actionable local UI error."""


def _binary_version(path: Optional[str], env: Mapping[str, str], source: str) -> Dict[str, Any]:
    if not path:
        return {"available": False, "path": None, "version": None, "source": source}
    try:
        result = subprocess.run(
            [path, "--version"],
            env=engine._nested_claude_env(env),
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        version = (result.stdout or result.stderr).strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired):
        version = "已找到，版本读取失败"
    return {"available": True, "path": path, "version": version, "source": source}


def _version(name: str, env: Mapping[str, str]) -> Dict[str, Any]:
    return _binary_version(shutil.which(name, path=env.get("PATH")), env, "PATH")


def _codex_path(env: Mapping[str, str]) -> Tuple[Optional[str], str]:
    configured = env.get("PARTNER_CODEX_BIN")
    if configured:
        path = configured if "/" in configured else shutil.which(configured, path=env.get("PATH"))
        return path, "PARTNER_CODEX_BIN"
    if sys.platform == "darwin":
        for candidate in (
            "/Applications/ChatGPT.app/Contents/Resources/codex",
            "/Applications/Codex.app/Contents/Resources/codex",
        ):
            if os.access(candidate, os.X_OK):
                return candidate, "app"
    return shutil.which("codex", path=env.get("PATH")), "PATH"


def _codex_version(env: Mapping[str, str]) -> Dict[str, Any]:
    path, source = _codex_path(env)
    return _binary_version(path, env, source)


def _send_json_line(process: subprocess.Popen[str], payload: Mapping[str, Any]) -> None:
    if process.stdin is None:
        raise OSError("Codex app-server stdin is unavailable")
    process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_json_response(
    process: subprocess.Popen[str], request_id: int, *, timeout: float
) -> Dict[str, Any]:
    if process.stdout is None:
        raise OSError("Codex app-server stdout is unavailable")
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise subprocess.TimeoutExpired(process.args, timeout)
            line = process.stdout.readline()
            if not line:
                raise OSError("Codex app-server closed before returning the model list")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise OSError(str(message["error"]))
                result = message.get("result")
                if not isinstance(result, dict):
                    raise OSError("Codex app-server returned an invalid response")
                return result
    finally:
        selector.close()


def _codex_model_options(
    path: Optional[str], env: Mapping[str, str]
) -> Tuple[List[Dict[str, Any]], str]:
    if not path:
        return [], "Codex CLI 未安装"
    process: Optional[subprocess.Popen[str]] = None
    try:
        process = subprocess.Popen(
            [path, "app-server", "--listen", "stdio://"],
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        _send_json_line(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "partner-setup", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        _read_json_response(process, 1, timeout=5)
        _send_json_line(process, {"method": "initialized", "params": {}})
        _send_json_line(
            process,
            {
                "id": 2,
                "method": "model/list",
                "params": {"includeHidden": False, "limit": 100},
            },
        )
        response = _read_json_response(process, 2, timeout=5)
        data = response.get("data")
        if not isinstance(data, list):
            raise OSError("Codex model/list did not return a list")
        options: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("model"), str):
                continue
            value = item["model"].strip()
            if not value:
                continue
            effort_items = item.get("supportedReasoningEfforts", [])
            efforts = [
                entry["reasoningEffort"]
                for entry in effort_items
                if isinstance(entry, dict)
                and entry.get("reasoningEffort") in CODEX_EFFORTS
            ]
            options.append(
                {
                    "value": value,
                    "label": item.get("displayName") or value,
                    "description": item.get("description") or "",
                    "source": "codex model/list",
                    "efforts": efforts,
                    "is_default": bool(item.get("isDefault")),
                }
            )
        return options, "Codex CLI 自动获取" if options else "Codex CLI 未返回可选模型"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return [], "Codex CLI 模型列表读取失败"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        if process is not None:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()


def _canonical_claude_model(value: str) -> str:
    """Collapse Claude context-window variants into one model choice."""
    normalized = re.sub(r"\[1m\]", "", value.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+1m$", "", normalized, flags=re.IGNORECASE).strip()


def _claude_model_options(
    path: Optional[str], env: Mapping[str, str], detected: Mapping[str, str]
) -> Tuple[List[Dict[str, Any]], str]:
    aliases: List[str] = []
    efforts = list(CLAUDE_EFFORTS)
    if path:
        try:
            result = subprocess.run(
                [path, "--help"],
                env=engine._nested_claude_env(env),
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
            help_text = result.stdout or result.stderr
            example = re.search(
                r"Provide\s+an\s+alias.*?\(e\.g\.(.*?)\)", help_text, flags=re.DOTALL
            )
            if example:
                aliases = re.findall(r"'([^']+)'", example.group(1))
            effort_help = re.search(
                r"--effort\s+<level>.*?\(([^)\n]+)\)", help_text, flags=re.DOTALL
            )
            if effort_help:
                detected_efforts = [
                    value.strip() for value in effort_help.group(1).split(",")
                ]
                if detected_efforts and all(
                    value in engine.CLAUDE_EFFORTS for value in detected_efforts
                ):
                    efforts = detected_efforts
        except (OSError, subprocess.TimeoutExpired):
            pass
    aliases = [
        normalized
        for alias in (*aliases, *CLAUDE_MODEL_ALIASES)
        if (normalized := _canonical_claude_model(alias))
    ]
    options = [
        {
            "value": alias,
            "label": alias.capitalize(),
            "description": "Claude Code 官方滚动别名",
            "source": "claude --help",
            "efforts": efforts,
            "is_default": alias == "opus",
        }
        for alias in dict.fromkeys(aliases)
    ]
    known = {option["value"] for option in options}
    for detected_value in detected.values():
        value = _canonical_claude_model(detected_value)
        if value and value not in known:
            options.append(
                {
                    "value": value,
                    "label": value,
                    "description": "本机 Claude 配置中已使用",
                    "source": "local claude config",
                    "efforts": efforts,
                    "is_default": False,
                }
            )
            known.add(value)
    source = "Claude CLI 官方别名" if path else "Claude 官方别名兜底"
    return options, source


def _ensure_model_option(
    options: List[Dict[str, Any]], value: str, source: str, backend: str
) -> None:
    if not value or any(option["value"] == value for option in options):
        return
    options.append(
        {
            "value": value,
            "label": value,
            "description": "当前配置中已使用",
            "source": source,
            "efforts": list(engine.BACKEND_EFFORTS[backend]),
            "is_default": False,
        }
    )


def _preset_matrices(env: Mapping[str, str]) -> Dict[str, Dict[str, Dict[str, str]]]:
    codex = engine.detect_codex(env)
    codex_model = codex.get("model", "")
    matrices: Dict[str, Dict[str, Dict[str, str]]] = {}
    for mode, preset in engine.PRESETS.items():
        matrix: Dict[str, Dict[str, str]] = {}
        for identity in engine.IDENTITIES:
            backend, configured_model, effort = preset[identity]
            if backend == "codex":
                model = configured_model or codex_model
                source = "detected" if model else "custom (required)"
            else:
                model = configured_model or ""
                source = "built-in alias"
            matrix[identity] = {
                "backend": backend,
                "model": model,
                "effort": effort,
                "model_source": source,
            }
        matrices[mode] = matrix
    return matrices


def build_state(host: str, repo: Path, env: Mapping[str, str]) -> Dict[str, Any]:
    repo = repo.resolve()
    presets = _preset_matrices(env)
    resolved = engine.partner_config.resolve_config(repo, host, env=env)
    identities = resolved["hosts"][host]["identities"]
    current = {
        identity: {
            "backend": values["backend"],
            "model": values["model"],
            "effort": values["effort"],
            "model_source": "existing config",
        }
        for identity, values in identities.items()
    }
    peer = "claude_code" if host == "codex" else "codex"
    peer_resolved = engine.partner_config.resolve_config(repo, peer, env=env)
    peer_identities = peer_resolved["hosts"][peer]["identities"]
    codex_detected = engine.detect_codex(env)
    claude_detected = engine.detect_claude(env)
    claude_cli = _version("claude", env)
    codex_cli = _codex_version(env)
    codex_options, codex_discovery = _codex_model_options(codex_cli["path"], env)
    claude_options, claude_discovery = _claude_model_options(
        claude_cli["path"], env, claude_detected
    )
    option_sets = {"claude": claude_options, "codex": codex_options}
    for matrix in (*presets.values(), current, peer_identities):
        for values in matrix.values():
            backend = values.get("backend")
            model = values.get("model")
            if backend in option_sets and isinstance(model, str):
                _ensure_model_option(
                    option_sets[backend],
                    model,
                    values.get("model_source", "existing config"),
                    backend,
                )
    initial_mode = "custom" if current else "balanced"
    initial_matrix = current or presets["balanced"]
    return {
        "host": host,
        "repo": str(repo),
        "config_source": resolved["source"],
        "clis": {
            "claude": claude_cli,
            "codex": codex_cli,
        },
        "detected": {
            "codex_model": codex_detected.get("model"),
            "codex_effort": codex_detected.get("model_reasoning_effort"),
            "claude_models": claude_detected,
        },
        "model_options": option_sets,
        "model_discovery": {
            "claude": claude_discovery,
            "codex": codex_discovery,
        },
        "presets": presets,
        "initial_mode": initial_mode,
        "initial_matrix": initial_matrix,
        "efforts_by_backend": {
            "claude": list(CLAUDE_EFFORTS),
            "codex": list(CODEX_EFFORTS),
        },
        "identity_meta": IDENTITY_META,
        "peer": {
            "host": peer,
            "source": peer_resolved["source"],
            "identities": peer_identities,
        },
        "write_agents_available": host == "claude_code",
    }


def _clean_string(value: Any, label: str, *, limit: int = 200) -> str:
    if not isinstance(value, str):
        raise UIError(f"{label} 必须是字符串")
    value = value.strip()
    if not value or len(value) > limit or any(ord(char) < 32 for char in value):
        raise UIError(f"{label} 不能为空、不能含控制字符，且最多 {limit} 个字符")
    return value


def normalize_payload(
    raw: Any,
    *,
    host: str,
    repo: Path,
    env: Mapping[str, str],
    model_options: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise UIError("请求必须是 JSON 对象")
    peer = "claude_code" if host == "codex" else "codex"
    peer_resolved = engine.partner_config.resolve_config(repo, peer, env=env)
    peer_identities = peer_resolved["hosts"][peer]["identities"]
    join_action = raw.get("join_action", "add")
    if peer_identities and join_action not in ("add", "shared", "cancel"):
        raise UIError("第二宿主接入方式无效")
    if peer_identities and join_action != "add":
        raise UIError("已选择不添加本宿主配置；没有文件需要预览或写入")
    mode = raw.get("mode")
    if mode not in MODES:
        raise UIError("工作模式无效")
    scope = raw.get("scope")
    if scope not in SCOPES:
        raise UIError("作用域无效")
    exclude_choice = raw.get("exclude_choice", "git-exclude")
    if exclude_choice not in EXCLUDE_CHOICES:
        raise UIError("Git 处理方式无效")
    routing_action = raw.get("routing_action", "none")
    if routing_action not in ROUTING_ACTIONS:
        raise UIError("常驻路由设置无效")
    supplied = raw.get("identities")
    if not isinstance(supplied, dict):
        raise UIError("缺少身份矩阵")
    identities: Dict[str, Dict[str, str]] = {}
    for identity in engine.IDENTITIES:
        values = supplied.get(identity)
        if not isinstance(values, dict):
            raise UIError(f"缺少 {identity} 设置")
        backend = values.get("backend")
        if backend not in engine.BACKENDS:
            raise UIError(f"{identity} 的 CLI 无效")
        model = _clean_string(values.get("model"), f"{identity} model")
        effort = values.get("effort")
        supported_efforts = engine.BACKEND_EFFORTS[backend]
        if model_options:
            option = next(
                (
                    candidate
                    for candidate in model_options.get(backend, ())
                    if candidate.get("value") == model
                ),
                None,
            )
            if option and option.get("efforts"):
                supported_efforts = tuple(option["efforts"])
        if effort not in supported_efforts:
            raise UIError(
                f"{identity} 的思考深度 {effort} 不受 {backend}/{model} 支持；"
                f"可选值：{', '.join(supported_efforts)}"
            )
        identities[identity] = {
            "backend": backend,
            "model": model,
            "effort": effort,
        }
    if mode != "custom":
        expected = _preset_matrices(env)[mode]
        comparable = {
            identity: {
                field: expected[identity][field]
                for field in ("backend", "model", "effort")
            }
            for identity in engine.IDENTITIES
        }
        if identities != comparable:
            raise UIError("身份设置已修改，请切换到自定义模式后重新预览")
    return {
        "host": host,
        "repo": str(repo.resolve()),
        "mode": mode,
        "scope": scope,
        "exclude_choice": exclude_choice,
        "routing_action": routing_action,
        "write_agents": bool(raw.get("write_agents")) and host == "claude_code",
        "smoke": bool(raw.get("smoke", True)),
        "identities": identities,
    }


def engine_arguments(payload: Mapping[str, Any], action: str) -> list[str]:
    args = [
        action,
        "--host",
        str(payload["host"]),
        "--repo",
        str(payload["repo"]),
        "--scope",
        str(payload["scope"]),
        "--mode",
        str(payload["mode"]),
        "--exclude-choice",
        str(payload["exclude_choice"]),
    ]
    if payload["mode"] == "custom":
        for identity in engine.IDENTITIES:
            values = payload["identities"][identity]
            args.extend(("--role-backend", f"{identity}={values['backend']}"))
            args.extend(("--role-model", f"{identity}={values['model']}"))
            args.extend(("--role-effort", f"{identity}={values['effort']}"))
    args.append("--write-agents" if payload["write_agents"] else "--no-write-agents")
    if payload["routing_action"] == "write":
        args.append("--routing-block")
    elif payload["routing_action"] == "remove":
        args.append("--remove-routing-block")
    return args


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SetupController:
    def __init__(self, host: str, repo: Path, env: Mapping[str, str]):
        self.host = host
        self.repo = repo.resolve()
        self.env = dict(env)
        self.initial_state = build_state(self.host, self.repo, self.env)
        self.lock = threading.Lock()
        self.preview_digest: Optional[str] = None
        self.preview_stdout = ""
        self.preview_stderr = ""
        self.preview_code: Optional[int] = None

    def state(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.initial_state, ensure_ascii=False))

    def _run(self, arguments: Sequence[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ENGINE_PATH), *arguments],
            cwd=self.repo,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )

    def preview(self, raw: Any) -> Dict[str, Any]:
        payload = normalize_payload(
            raw,
            host=self.host,
            repo=self.repo,
            env=self.env,
            model_options=self.initial_state["model_options"],
        )
        with self.lock:
            result = self._run(engine_arguments(payload, "--preview"))
            self.preview_digest = _digest(payload) if result.returncode == 0 else None
            self.preview_stdout = result.stdout
            self.preview_stderr = result.stderr
            self.preview_code = result.returncode
        return {
            "ok": result.returncode == 0,
            "code": result.returncode,
            "output": result.stdout,
            "error": result.stderr,
        }

    def apply(self, raw: Any) -> Dict[str, Any]:
        payload = normalize_payload(
            raw,
            host=self.host,
            repo=self.repo,
            env=self.env,
            model_options=self.initial_state["model_options"],
        )
        with self.lock:
            if self.preview_digest != _digest(payload) or self.preview_code != 0:
                raise UIError("当前选择还没有通过精确预览，请先点击“预览安装内容”")
            fresh = self._run(engine_arguments(payload, "--preview"))
            if (
                fresh.returncode != self.preview_code
                or fresh.stdout != self.preview_stdout
                or fresh.stderr != self.preview_stderr
            ):
                self.preview_digest = None
                raise UIError("文件状态在预览后发生变化，请重新生成预览再确认")
            applied = self._run(engine_arguments(payload, "--apply"), timeout=120)
            self.preview_digest = None
            smoke = None
            if applied.returncode == 0 and payload["smoke"]:
                smoke_args = [
                    "--smoke",
                    "--host",
                    self.host,
                    "--repo",
                    str(self.repo),
                    "--scope",
                    str(payload["scope"]),
                ]
                smoke = self._run(smoke_args, timeout=120)
        return {
            "ok": applied.returncode == 0,
            "code": applied.returncode,
            "output": applied.stdout,
            "error": applied.stderr,
            "smoke": None
            if smoke is None
            else {
                "ok": smoke.returncode == 0,
                "code": smoke.returncode,
                "output": smoke.stdout,
                "error": smoke.stderr,
            },
        }


HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>搭子配置</title>
  <style>
    /* Base structural styles. The taste-v2 layer below owns the visual direction. */
    :root {
      color-scheme:dark;
      --bg:#0b0d0f;
      --surface:#111417;
      --surface-raised:#171b1f;
      --surface-input:#0d1012;
      --line:#2a3035;
      --line-strong:#3a4249;
      --text:#f2f3ef;
      --muted:#9ba3a8;
      --quiet:#727b81;
      --accent:#9befbd;
      --accent-ink:#0b2415;
      --amber:#efc878;
      --red:#ff8d92;
      --panel-radius:16px;
      --control-radius:9px;
      --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;
      --mono:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
    }
    * { box-sizing:border-box; }
    html { background:var(--bg); }
    body { margin:0; min-width:320px; background:var(--bg); color:var(--text); font:15px/1.5 var(--sans); }
    button,select,input { font:inherit; }
    button { -webkit-tap-highlight-color:transparent; }
    .shell { width:min(1240px,calc(100% - 40px)); margin:0 auto 64px; }
    .topbar { display:flex; justify-content:space-between; gap:32px; align-items:flex-end; padding:42px 0 24px; border-bottom:1px solid var(--line); }
    .title-block { max-width:610px; }
    h1 { font-size:clamp(32px,4vw,52px); line-height:1.02; margin:0 0 12px; letter-spacing:-.055em; font-weight:720; }
    h2 { font-size:15px; line-height:1.3; margin:0; letter-spacing:-.01em; }
    h3 { margin:0; }
    p { margin:0; }
    .muted { color:var(--muted); }
    .subtitle { max-width:560px; color:var(--muted); font-size:16px; }
    .repo-block { width:min(390px,42vw); text-align:right; }
    .repo-block span { display:block; color:var(--quiet); font-size:11px; letter-spacing:.08em; margin-bottom:6px; text-transform:uppercase; }
    .repo-block code { display:block; color:#d9ddd9; font:12px/1.45 var(--mono); overflow-wrap:anywhere; }
    .detect { display:grid; grid-template-columns:.7fr .9fr 1fr 1fr 1.15fr; border-bottom:1px solid var(--line); }
    .detect .item { min-width:0; padding:15px 14px 16px; border-left:1px solid var(--line); }
    .detect .item:first-child { padding-left:0; border-left:0; }
    .k { color:var(--quiet); font-size:11px; letter-spacing:.035em; margin-bottom:4px; }
    .v { font-weight:620; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .ok { color:var(--accent); }
    .warn { color:var(--amber); }
    .bad { color:var(--red); }
    .workspace { display:grid; grid-template-columns:minmax(270px,340px) minmax(0,1fr); gap:18px; align-items:start; margin-top:18px; }
    .rail,.main-panel { border:1px solid var(--line); border-radius:var(--panel-radius); background:var(--surface); }
    .rail { overflow:hidden; }
    .rail-section { padding:19px; border-top:1px solid var(--line); }
    .rail-section:first-child { border-top:0; }
    .section-heading { margin-bottom:14px; }
    .section-heading p { margin-top:5px; color:var(--muted); font-size:12px; }
    .modes { display:grid; gap:2px; }
    .mode { appearance:none; width:100%; position:relative; display:grid; grid-template-columns:78px 1fr; gap:12px; text-align:left; color:var(--text); background:transparent; border:0; border-left:2px solid transparent; border-radius:0; padding:11px 10px 11px 12px; cursor:pointer; }
    .mode:hover { background:var(--surface-raised); }
    .mode:active { transform:translateY(1px); }
    .mode.active { border-left-color:var(--accent); background:var(--surface-raised); }
    .mode strong { display:block; font-size:14px; }
    .mode small { color:var(--muted); display:grid; gap:2px; font:10px/1.35 var(--mono); overflow-wrap:anywhere; }
    .mode-line b { color:var(--quiet); font:inherit; display:inline-block; width:30px; }
    .peer { display:none; border-top:1px solid rgba(239,200,120,.4); }
    .peer h2 { color:var(--amber); }
    .peer p { margin-top:7px; font-size:12px; overflow-wrap:anywhere; }
    .peer .field-stack { margin-top:13px; }
    .field-stack { display:grid; gap:13px; }
    .setting-block + .setting-block { margin-top:18px; padding-top:18px; border-top:1px solid var(--line); }
    label,.field-label { display:block; color:var(--muted); font-size:11px; letter-spacing:.02em; margin:0 0 6px; }
    select,input[type=text] { width:100%; min-height:42px; border:1px solid var(--line); border-radius:var(--control-radius); background:var(--surface-input); color:var(--text); padding:9px 10px; font:13px var(--mono); outline:none; }
    select:hover,input[type=text]:hover { border-color:var(--line-strong); }
    select:focus-visible,input:focus-visible,button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
    .choice-row { display:flex; gap:12px; flex-wrap:wrap; }
    .choice { display:flex; align-items:flex-start; gap:8px; color:var(--text); font-size:13px; line-height:1.35; cursor:pointer; }
    .choice input { margin:2px 0 0; accent-color:var(--accent); }
    .choice:has(input:disabled) { color:var(--quiet); cursor:not-allowed; }
    .main-panel { min-width:0; padding:22px; }
    .main-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; padding-bottom:18px; border-bottom:1px solid var(--line); }
    .main-heading h2 { font-size:20px; }
    .main-heading p { color:var(--muted); margin-top:5px; font-size:13px; }
    .current-mode { flex:0 0 auto; color:var(--accent); font:11px var(--mono); }
    .matrix { display:grid; }
    .identity { display:grid; grid-template-columns:minmax(155px,.85fr) minmax(130px,.7fr) minmax(210px,1.25fr) minmax(120px,.65fr); gap:12px; align-items:start; padding:17px 0; border-top:1px solid var(--line); }
    .identity:first-child { border-top:0; }
    .identity:hover { background:#13171a; box-shadow:18px 0 #13171a,-18px 0 #13171a; }
    .identity-head { min-width:0; padding-top:2px; }
    .identity h3 { font-size:15px; margin-bottom:4px; }
    .identity-head small { display:block; color:var(--muted); font-size:11px; line-height:1.35; }
    .identity-code { display:block; color:var(--quiet); margin-top:8px; font:10px var(--mono); overflow-wrap:anywhere; }
    .field { min-width:0; }
    .source { color:var(--quiet); font-size:10px; margin-top:5px; overflow-wrap:anywhere; }
    .output-section { display:none; margin-top:18px; padding-top:18px; border-top:1px solid var(--line); }
    .output-section h2 { margin-bottom:10px; }
    .output-section.has-error { border-left:2px solid var(--red); padding-left:14px; }
    pre { white-space:pre-wrap; overflow-wrap:anywhere; background:var(--surface-input); border:1px solid var(--line); border-radius:var(--control-radius); padding:15px; max-height:430px; overflow:auto; color:#d9ddd9; font:12px/1.55 var(--mono); }
    .confirm { display:none; align-items:center; justify-content:flex-end; gap:14px; margin-top:12px; }
    .confirm label { margin:0; color:var(--text); font-size:13px; }
    .result { border-left:2px solid var(--accent); padding-left:14px; }
    .actions { display:flex; gap:10px; align-items:center; padding:14px 0 0; margin-top:18px; border-top:1px solid var(--line); background:var(--surface); }
    button.primary,button.apply { min-height:42px; border:1px solid var(--accent); border-radius:var(--control-radius); padding:10px 15px; font-weight:720; cursor:pointer; }
    button.primary { background:var(--accent); color:var(--accent-ink); }
    button.apply { background:transparent; color:var(--accent); }
    button.primary:hover { filter:brightness(1.06); }
    button.apply:hover { background:rgba(155,239,189,.08); }
    button.primary:active,button.apply:active { transform:translateY(1px); }
    button:disabled { opacity:.38; cursor:not-allowed; transform:none; }
    .status { margin-left:auto; color:var(--muted); font-size:12px; text-align:right; }
    .loading-copy { color:var(--quiet); font-size:12px; padding:12px 0; }
    @media (max-width:980px) {
      .detect { grid-template-columns:repeat(3,1fr); }
      .detect .item:nth-child(4) { padding-left:0; border-left:0; border-top:1px solid var(--line); }
      .detect .item:nth-child(5) { border-top:1px solid var(--line); }
      .workspace { grid-template-columns:1fr; }
      .rail { display:grid; grid-template-columns:1fr 1fr; }
      .rail-section { border-top:0; border-left:1px solid var(--line); }
      .rail-section:first-child { border-left:0; }
      .peer { grid-column:1 / -1; border-left:0; }
    }
    @media (max-width:720px) {
      .shell { width:min(100% - 24px,1240px); margin-bottom:32px; }
      .topbar { display:block; padding-top:26px; }
      .repo-block { width:100%; text-align:left; margin-top:20px; }
      .detect { grid-template-columns:1fr 1fr; }
      .detect .item,.detect .item:first-child,.detect .item:nth-child(4) { padding:12px 10px; border-left:1px solid var(--line); border-top:1px solid var(--line); }
      .detect .item:nth-child(odd) { padding-left:0; border-left:0; }
      .detect .item:first-child,.detect .item:nth-child(2) { border-top:0; }
      .rail { display:block; }
      .rail-section { border-left:0; border-top:1px solid var(--line); }
      .rail-section:first-child { border-top:0; }
      .main-panel { padding:18px; }
      .identity { grid-template-columns:1fr 1fr; }
      .identity-head { grid-column:1 / -1; }
      .field.model-field { grid-column:1 / -1; grid-row:3; }
      .actions { flex-wrap:wrap; }
      .status { width:100%; margin:0; text-align:left; order:-1; }
      .confirm { align-items:flex-start; flex-direction:column; }
    }
    @media (max-width:480px) {
      .detect { grid-template-columns:1fr; }
      .detect .item,.detect .item:first-child,.detect .item:nth-child(2),.detect .item:nth-child(4) { padding:11px 0; border-left:0; border-top:1px solid var(--line); }
      .detect .item:first-child { border-top:0; }
      .main-heading { align-items:flex-start; flex-direction:column; gap:10px; }
      .identity { grid-template-columns:1fr; }
      .identity-head,.field.model-field { grid-column:1; grid-row:auto; }
      button.primary,button.apply { width:100%; }
    }
    @media (prefers-reduced-motion:reduce) {
      *,*::before,*::after { scroll-behavior:auto!important; transition:none!important; animation:none!important; }
    }
  </style>
  <style>
    /* Reading this as a calm local Agent installer for first-time users. Variance 4, motion 5, density 4. */
    :root {
      color-scheme:light;
      --canvas:#f0f1ec;
      --paper:#fafaf7;
      --paper-strong:#ffffff;
      --ink:#171915;
      --ink-soft:#343730;
      --muted-v2:#6b6f66;
      --line-v2:#d3d6cc;
      --accent-v2:#e75b38;
      --accent-deep:#8f2f19;
      --accent-soft:#f7d9d0;
      --shadow-v2:0 28px 70px rgba(66,54,43,.12);
      --display:"Avenir Next","SF Pro Display","PingFang SC",sans-serif;
      --body:"Avenir Next","SF Pro Text","PingFang SC",sans-serif;
      --mono-v2:"SFMono-Regular","JetBrains Mono",Consolas,monospace;
    }
    html { background:var(--canvas); scroll-behavior:smooth; }
    body { min-width:320px; background:
      radial-gradient(circle at 82% 4%,rgba(231,91,56,.15),transparent 30rem),
      var(--canvas); color:var(--ink); font:15px/1.5 var(--body); overflow-x:hidden; }
    body::before { content:""; position:fixed; inset:0; pointer-events:none; z-index:3; opacity:.13; background-image:radial-gradient(rgba(23,25,21,.42) .45px,transparent .55px); background-size:4px 4px; }
    .shell { width:min(1320px,calc(100% - 48px)); margin:0 auto 80px; }
    .masthead { height:68px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid rgba(23,25,21,.18); }
    .brand { display:flex; align-items:center; gap:11px; font-weight:680; letter-spacing:-.025em; }
    .brand-mark { width:32px; height:32px; display:grid; place-items:center; border-radius:10px; background:var(--ink); color:var(--paper); font-weight:760; }
    .brand small { display:block; color:var(--muted-v2); font:10px/1.2 var(--mono-v2); letter-spacing:.03em; }
    .local-state { color:var(--muted-v2); font:11px var(--mono-v2); }
    .hero { min-height:430px; display:grid; grid-template-columns:minmax(0,1fr) minmax(440px,.85fr); gap:clamp(36px,7vw,100px); align-items:center; padding:42px 0 54px; }
    .hero-copy { align-self:center; }
    .hero h1 { max-width:760px; margin:0; color:var(--ink); font:760 clamp(46px,6vw,78px)/.98 var(--display); letter-spacing:-.065em; text-wrap:balance; }
    .hero .subtitle { max-width:520px; margin-top:22px; color:var(--ink-soft); font-size:17px; line-height:1.65; text-wrap:pretty; }
    .repo-block { width:auto; margin-top:30px; text-align:left; }
    .repo-block span { color:var(--muted-v2); text-transform:none; letter-spacing:0; font-size:11px; }
    .repo-block code { display:inline-block; max-width:100%; padding:9px 12px; border:1px solid var(--line-v2); border-radius:10px; background:rgba(255,255,255,.5); color:var(--ink-soft); font:11px/1.4 var(--mono-v2); }
    .hero-map { position:relative; min-height:340px; overflow:hidden; border-radius:30px; background:var(--ink); color:var(--paper); box-shadow:0 35px 80px rgba(63,44,32,.22); isolation:isolate; }
    .hero-map::before { content:""; position:absolute; width:320px; height:320px; right:-100px; top:-130px; border-radius:50%; background:radial-gradient(circle,rgba(231,91,56,.72),rgba(231,91,56,0) 68%); opacity:.7; }
    .hero-map::after { content:""; position:absolute; inset:0; z-index:-1; opacity:.12; background-image:radial-gradient(rgba(250,250,247,.75) .55px,transparent .7px); background-size:7px 7px; }
    .map-caption { position:absolute; left:24px; top:22px; color:#aeb1a8; font:10px var(--mono-v2); }
    .agent-core { position:absolute; left:7%; top:50%; width:126px; height:126px; transform:translateY(-50%); display:grid; place-content:center; text-align:center; border:1px solid rgba(250,250,247,.28); border-radius:28px; background:#242720; box-shadow:inset 0 1px rgba(255,255,255,.09),0 18px 42px rgba(0,0,0,.28); }
    .agent-core strong { font:720 28px/1 var(--display); letter-spacing:-.05em; }
    .agent-core small { margin-top:8px; color:#aeb1a8; font:9px var(--mono-v2); }
    .agent-core::after { content:""; position:absolute; inset:-10px; border:1px solid rgba(231,91,56,.32); border-radius:36px; }
    .role-node { position:absolute; left:62%; width:31%; min-width:140px; padding:13px 15px; border:1px solid rgba(250,250,247,.18); border-radius:16px; background:rgba(41,44,36,.92); box-shadow:inset 0 1px rgba(255,255,255,.06); }
    .role-node.deep { top:10%; }
    .role-node.fast { top:40%; }
    .role-node.arbiter { top:70%; }
    .role-node span { display:block; color:#aeb1a8; font-size:10px; margin-bottom:3px; }
    .role-node strong { display:block; overflow:hidden; color:var(--paper); font:10px/1.45 var(--mono-v2); text-overflow:ellipsis; white-space:nowrap; }
    .route-line { position:absolute; left:31%; width:34%; height:1px; transform-origin:left center; background:linear-gradient(90deg,rgba(231,91,56,.18),rgba(231,91,56,.78)); }
    .route-line.deep { top:48%; transform:rotate(-28deg); }
    .route-line.fast { top:50%; }
    .route-line.arbiter { top:52%; transform:rotate(28deg); }
    .route-line i { position:absolute; left:0; top:-4px; width:9px; height:9px; border-radius:3px; background:var(--accent-v2); box-shadow:0 0 16px rgba(231,91,56,.7); }
    .detect { display:grid; grid-template-columns:.72fr .92fr 1fr 1fr 1.2fr; margin-bottom:0; overflow:hidden; border:1px solid var(--line-v2); border-radius:18px; background:rgba(250,250,247,.72); box-shadow:0 14px 35px rgba(66,54,43,.07); }
    .detect .item,.detect .item:first-child { min-width:0; padding:17px 18px; border:0; border-left:1px solid var(--line-v2); }
    .detect .item:first-child { border-left:0; }
    .detect .item:nth-child(1) { --i:0; }
    .detect .item:nth-child(2) { --i:1; }
    .detect .item:nth-child(3) { --i:2; }
    .detect .item:nth-child(4) { --i:3; }
    .detect .item:nth-child(5) { --i:4; }
    .k { color:var(--muted-v2); font-size:10px; letter-spacing:.02em; }
    .v { color:var(--ink); font:650 12px/1.4 var(--body); }
    .ok { color:var(--accent-deep); }
    .warn,.bad { color:var(--accent-deep); }
    .config-section { margin-top:70px; }
    .config-heading { max-width:680px; margin-bottom:24px; }
    .config-heading h2 { color:var(--ink); font:720 clamp(30px,4vw,48px)/1.05 var(--display); letter-spacing:-.045em; }
    .config-heading p { max-width:570px; margin-top:10px; color:var(--muted-v2); font-size:14px; }
    .modes { display:grid; grid-template-columns:repeat(3,1fr); gap:5px; padding:5px; border-radius:18px; background:var(--ink); box-shadow:0 20px 45px rgba(66,54,43,.14); }
    .mode { appearance:none; width:100%; min-height:86px; display:block; position:relative; overflow:hidden; padding:15px 16px; border:0; border-radius:13px; background:transparent; color:#b8bbb2; text-align:left; cursor:pointer; }
    .mode strong { position:relative; z-index:1; display:block; margin:0 0 6px; color:inherit; font:680 15px var(--body); }
    .mode small { position:relative; z-index:1; display:block; color:inherit; font:10px/1.45 var(--mono-v2); opacity:.75; }
    .mode::before { content:""; position:absolute; inset:0; border-radius:inherit; background:var(--accent-v2); transform:scale(.86); opacity:0; }
    .mode:hover { color:var(--paper); background:#252820; }
    .mode.active { color:var(--paper); background:transparent; }
    .mode.active::before { transform:scale(1); opacity:1; }
    .config-grid { display:grid; grid-template-columns:minmax(0,1.55fr) minmax(300px,.7fr); gap:22px; align-items:start; margin-top:22px; }
    .matrix-panel,.settings-panel { overflow:hidden; border:1px solid var(--line-v2); border-radius:24px; background:rgba(250,250,247,.82); box-shadow:var(--shadow-v2); }
    .matrix-panel { min-width:0; padding:0; }
    .main-heading,.settings-head { box-sizing:border-box; min-height:81px; padding:20px 22px 16px; border-bottom:1px solid var(--line-v2); }
    .main-heading { align-items:flex-start; }
    .main-heading h2 { color:var(--ink); font:700 23px/1.15 var(--display); letter-spacing:-.035em; }
    .main-heading p { max-width:530px; color:var(--muted-v2); font-size:12px; }
    .current-mode { color:var(--accent-deep); font:10px var(--mono-v2); }
    .matrix { display:grid; gap:12px; padding:18px 20px 20px; }
    .identity { display:grid; grid-template-columns:minmax(155px,.82fr) minmax(130px,.7fr) minmax(220px,1.2fr) minmax(120px,.62fr); gap:12px; align-items:start; position:relative; min-height:110px; overflow:hidden; padding:17px; border:1px solid var(--line-v2); border-radius:17px; background:var(--paper-strong); box-shadow:0 10px 26px rgba(66,54,43,.06); }
    .identity:first-child { border-top:1px solid var(--line-v2); }
    .identity:nth-child(1) { --row:0; }
    .identity:nth-child(2) { --row:1; }
    .identity:nth-child(3) { --row:2; }
    .identity::before { content:""; position:absolute; left:0; top:13px; bottom:13px; width:3px; border-radius:3px; background:var(--accent-v2); transform:scaleY(0); }
    .identity:hover { background:var(--paper-strong); box-shadow:0 18px 38px rgba(66,54,43,.12); }
    .identity:hover::before { transform:scaleY(1); }
    .identity-head { padding:1px 0 0; }
    .identity h3 { color:var(--ink); font:680 15px var(--body); }
    .identity-head small { color:var(--muted-v2); }
    .identity-code { color:#979b91; }
    label,.field-label { color:var(--muted-v2); font-size:10px; }
    select,input[type=text] { min-height:43px; border:1px solid var(--line-v2); border-radius:11px; background:#f3f4ef; color:var(--ink); font:12px var(--mono-v2); }
    select:hover,input[type=text]:hover { border-color:#aeb2a6; }
    select:focus-visible,input:focus-visible,button:focus-visible { outline:3px solid rgba(231,91,56,.3); outline-offset:2px; border-color:var(--accent-v2); }
    .source { color:#888d82; }
    .settings-panel { position:sticky; top:18px; overflow:hidden; }
    .settings-head { background:var(--accent-soft); }
    .settings-head h2 { color:var(--ink); font:700 21px/1.15 var(--display); letter-spacing:-.03em; }
    .settings-head p { margin-top:7px; color:#765c53; font-size:12px; }
    .settings-body { padding:8px 22px 4px; }
    .setup-summary { list-style:none; margin:0; padding:0; }
    .setup-item { display:grid; grid-template-columns:28px 1fr; gap:11px; padding:15px 0; border-bottom:1px solid var(--line-v2); }
    .setup-item:last-child { border-bottom:0; }
    .setup-check { width:28px; height:28px; display:grid; place-items:center; border-radius:9px; background:var(--ink); color:var(--paper); font:700 13px var(--body); }
    .setup-item strong { display:block; color:var(--ink); font-size:13px; }
    .setup-item small { display:block; margin-top:3px; color:var(--muted-v2); font-size:11px; line-height:1.45; }
    .choice { color:var(--ink-soft); }
    .choice input { accent-color:var(--accent-v2); }
    .choice:has(input:disabled) { color:#9a9d95; }
    .peer { margin:0; padding:18px 22px; border:0; border-bottom:1px solid var(--line-v2); border-radius:0; background:#fff5e3; box-shadow:none; }
    .peer h2 { color:#7d5617; }
    .actions { display:grid; gap:10px; margin:12px 22px 18px; padding:14px 0 0; border-top:1px solid var(--line-v2); background:transparent; }
    .status { width:100%; margin:0; color:var(--muted-v2); text-align:left; font-size:11px; }
    button.primary,button.apply { min-height:48px; border:1px solid var(--ink); border-radius:13px; padding:11px 17px; background:var(--ink); color:var(--paper); font-weight:700; }
    button.primary { width:100%; position:relative; overflow:hidden; }
    button.primary::after { content:""; position:absolute; inset:-80% -35%; background:linear-gradient(90deg,transparent,rgba(255,255,255,.22),transparent); transform:translateX(-70%) rotate(12deg); }
    button.primary:hover { filter:none; background:var(--accent-v2); border-color:var(--accent-v2); }
    button.apply { background:var(--accent-v2); border-color:var(--accent-v2); color:var(--paper); }
    button.apply:hover { background:var(--accent-deep); }
    button:disabled { opacity:.38; }
    .output-section { display:none; margin-top:22px; padding:24px; border:1px solid var(--line-v2); border-radius:24px; background:rgba(250,250,247,.9); box-shadow:var(--shadow-v2); }
    .output-section h2 { color:var(--ink); font:700 22px var(--display); }
    .output-section.stale { opacity:.5; transform:scale(.99); }
    .output-section.has-error { border-left:4px solid var(--accent-v2); padding-left:24px; }
    .preview-plan { margin:15px 0; padding:4px 18px; border:1px solid var(--line-v2); border-radius:16px; background:var(--paper-strong); }
    .preview-plan .setup-item { grid-template-columns:24px 1fr; padding:12px 0; }
    .preview-plan .setup-check { width:24px; height:24px; border-radius:8px; font-size:12px; }
    .technical-details { margin-top:12px; }
    .technical-details summary { width:max-content; max-width:100%; color:var(--accent-deep); font-size:12px; font-weight:650; cursor:pointer; }
    .technical-details pre { margin-top:12px; }
    pre { border:0; border-radius:16px; background:var(--ink); color:#e8eadf; box-shadow:inset 0 1px rgba(255,255,255,.08); }
    .confirm { justify-content:flex-end; }
    .confirm label { color:var(--ink); }
    .result { border-left:4px solid var(--accent-v2); }
    .loading-copy { color:var(--muted-v2); }
    @media (prefers-reduced-motion:no-preference) {
      .hero-copy { animation:rise-in .72s cubic-bezier(.16,1,.3,1) both; }
      .hero-map { animation:map-in .82s .08s cubic-bezier(.16,1,.3,1) both; }
      .detect { animation:rise-in .65s .18s cubic-bezier(.16,1,.3,1) both; }
      .detect .item { animation:rise-in .48s cubic-bezier(.16,1,.3,1) both; animation-delay:calc(.22s + var(--i,0) * .055s); }
      .agent-core::after { animation:core-breathe 2.8s ease-in-out infinite; }
      .route-line i { animation:signal-run 2.2s cubic-bezier(.4,0,.2,1) infinite; }
      .route-line.fast i { animation-delay:.55s; }
      .route-line.arbiter i { animation-delay:1.1s; }
      .mode,.mode::before,.identity,.identity::before,button,select,input { transition:transform .28s cubic-bezier(.16,1,.3,1),opacity .28s ease,background-color .28s ease,border-color .28s ease,box-shadow .28s ease,color .28s ease; }
      .mode:active,button:active { transform:scale(.98); }
      .identity { animation:row-enter .48s cubic-bezier(.16,1,.3,1) both; animation-delay:calc(var(--row,0) * .07s); }
      .identity:hover { transform:translateY(-3px); }
      .output-section[style*="block"] { animation:output-enter .5s cubic-bezier(.16,1,.3,1) both; }
      [aria-busy="true"] button.primary::after { animation:button-scan 1.3s ease-in-out infinite; }
    }
    @keyframes rise-in { from { opacity:0; transform:translateY(22px); } to { opacity:1; transform:translateY(0); } }
    @keyframes map-in { from { opacity:0; transform:translateY(28px) rotate(1.5deg) scale(.96); } to { opacity:1; transform:none; } }
    @keyframes row-enter { from { opacity:0; transform:translateX(18px); } to { opacity:1; transform:translateX(0); } }
    @keyframes output-enter { from { opacity:0; transform:translateY(18px) scale(.985); } to { opacity:1; transform:none; } }
    @keyframes signal-run { 0% { opacity:0; transform:translateX(0) scale(.75); } 18% { opacity:1; } 80% { opacity:1; } 100% { opacity:0; transform:translateX(150px) scale(1); } }
    @keyframes core-breathe { 0%,100% { opacity:.35; transform:scale(.96); } 50% { opacity:1; transform:scale(1.04); } }
    @keyframes button-scan { from { transform:translateX(-70%) rotate(12deg); } to { transform:translateX(70%) rotate(12deg); } }
    @media (max-width:1040px) {
      .hero { grid-template-columns:1fr 1fr; gap:34px; }
      .config-grid { grid-template-columns:1fr; }
      .settings-panel { position:static; }
      .actions { grid-template-columns:1fr auto; align-items:center; }
      .status { width:auto; }
      button.primary { width:auto; }
    }
    @media (max-width:780px) {
      .shell { width:min(100% - 28px,1320px); }
      .hero { min-height:auto; grid-template-columns:1fr; padding:38px 0 42px; }
      .hero h1 { font-size:clamp(44px,13vw,66px); }
      .hero-map { min-height:320px; }
      .detect { grid-template-columns:1fr 1fr; }
      .detect .item,.detect .item:first-child { padding:13px 12px; border-top:1px solid var(--line-v2); border-left:1px solid var(--line-v2); }
      .detect .item:nth-child(odd) { border-left:0; }
      .detect .item:first-child,.detect .item:nth-child(2) { border-top:0; }
      .modes { grid-template-columns:1fr 1fr; }
      .identity { grid-template-columns:1fr 1fr; }
      .identity-head,.field.model-field { grid-column:1 / -1; }
      .actions { grid-template-columns:1fr; }
      button.primary { width:100%; }
      .confirm { align-items:stretch; }
    }
    @media (max-width:500px) {
      .masthead { height:60px; }
      .brand small { display:none; }
      .hero-map { min-height:380px; }
      .agent-core { left:50%; top:43%; transform:translate(-50%,-50%); }
      .role-node { left:7%; width:86%; display:grid; grid-template-columns:90px 1fr; gap:8px; align-items:center; }
      .role-node.deep { top:63%; }
      .role-node.fast { top:74%; }
      .role-node.arbiter { top:85%; }
      .route-line { display:none; }
      .modes { grid-template-columns:1fr; }
      .mode { min-height:70px; }
      .identity { grid-template-columns:1fr; }
      .identity-head,.field.model-field { grid-column:1; }
      .main-heading { display:block; }
      .current-mode { display:block; margin-top:10px; }
      .matrix-panel { padding:0; }
      .main-heading { min-height:auto; padding:18px; }
      .matrix { padding:14px; }
      .output-section { padding:18px; }
    }
    @media (prefers-reduced-motion:reduce) {
      html { scroll-behavior:auto; }
      *,*::before,*::after { animation:none!important; transition:none!important; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <nav class="masthead" aria-label="搭子配置">
      <div class="brand"><span class="brand-mark">搭</span><span>Partner Setup<small>本地 Agent 配置台</small></span></div>
      <div class="local-state">仅在本机运行</div>
    </nav>

    <header class="hero">
      <div class="hero-copy">
        <h1>配置你的搭子</h1>
        <p class="subtitle">把推理、执行和仲裁一次分配清楚。先看真实模型与精确 diff，确认后才写入。</p>
        <div class="repo-block"><span>当前项目</span><code id="repo"></code></div>
      </div>
      <div class="hero-map" aria-label="当前角色路由预览">
        <span class="map-caption">真实配置预览</span>
        <div class="agent-core"><strong>搭子</strong><small>orchestrator</small></div>
        <div class="route-line deep" aria-hidden="true"><i></i></div>
        <div class="route-line fast" aria-hidden="true"><i></i></div>
        <div class="route-line arbiter" aria-hidden="true"><i></i></div>
        <div class="role-node deep"><span>深度推理</span><strong id="heroDeep">正在检测</strong></div>
        <div class="role-node fast"><span>快速执行</span><strong id="heroFast">正在检测</strong></div>
        <div class="role-node arbiter"><span>独立仲裁</span><strong id="heroArbiter">正在检测</strong></div>
      </div>
    </header>

    <section class="detect" id="detect" aria-label="本机环境检测">
      <p class="loading-copy">正在读取本机环境...</p>
    </section>

    <section class="config-section" id="configWorkspace" aria-busy="true">
      <div class="config-heading"><h2>先选工作模式</h2><p>先选一个推荐组合，也可以直接调整每个角色使用的 CLI、模型和思考深度。</p></div>
      <div class="modes" id="modes"><p class="loading-copy">正在生成模式...</p></div>

      <div class="config-grid">
        <section class="matrix-panel" aria-labelledby="matrixTitle">
          <div class="main-heading">
            <div><h2 id="matrixTitle">三个搭子角色</h2><p>Codex 模型从本机账户自动读取，Claude 模型使用 CLI 官方别名。</p></div>
            <span class="current-mode" id="currentMode">当前模式：读取中</span>
          </div>
          <div class="matrix" id="identities"><p class="loading-copy">正在读取具体模型...</p></div>
        </section>

        <aside class="settings-panel" aria-label="安装前确认">
          <div class="settings-head"><h2>准备安装</h2><p>这里不用再选，搭子会按安全默认值处理。</p></div>

          <section class="peer" id="peerWrap">
            <h2>会保留另一端的搭子配置</h2>
            <p class="muted" id="peerSummary"></p>
          </section>

          <div class="settings-body">
            <ul class="setup-summary">
              <li class="setup-item"><span class="setup-check" aria-hidden="true">✓</span><span><strong>只配置当前项目</strong><small>不会影响你电脑上的其他项目。</small></span></li>
              <li class="setup-item"><span class="setup-check" aria-hidden="true">✓</span><span><strong>配置只保留在本机</strong><small>不会把个人模型设置提交到 Git。</small></span></li>
              <li class="setup-item"><span class="setup-check" aria-hidden="true">✓</span><span><strong>安装完成后自动检查</strong><small>确认搭子能读取新配置，失败会显示原因。</small></span></li>
            </ul>
          </div>
          <div class="actions">
            <span class="status" id="status" role="status" aria-live="polite">还没有修改任何文件</span>
            <button class="primary" id="previewBtn">预览安装内容</button>
          </div>
        </aside>
      </div>

      <div class="output-section" id="previewWrap" aria-live="polite">
        <h2>将要修改的文件</h2>
        <ul class="preview-plan" id="previewPlan">
          <li class="setup-item"><span class="setup-check" aria-hidden="true">1</span><span><strong>保存三个角色的模型设置</strong><small>写入当前项目的 .partner/config.toml。</small></span></li>
          <li class="setup-item"><span class="setup-check" aria-hidden="true">2</span><span><strong>让配置只留在本机</strong><small>把配置加入这个仓库的本机 Git 忽略列表。</small></span></li>
          <li class="setup-item"><span class="setup-check" aria-hidden="true">3</span><span><strong>安装后自动检查</strong><small>确认搭子能读取刚写入的设置。</small></span></li>
        </ul>
        <details class="technical-details" id="technicalDetails">
          <summary id="technicalSummary">查看完整路径和技术 diff</summary>
          <pre id="preview"></pre>
        </details>
        <div class="confirm" id="confirm">
          <label class="choice"><input type="checkbox" id="confirmed"> 我确认安装到当前项目</label>
          <button class="apply" id="apply" disabled>安装并自动检查</button>
        </div>
      </div>

      <div class="output-section result" id="resultWrap" aria-live="polite">
        <h2>执行结果</h2>
        <pre id="result"></pre>
      </div>
    </section>
  </main>
  <script>
    const token = new URLSearchParams(location.search).get('token');
    let state;
    let mode = 'balanced';
    let matrix = {};
    let previewValid = false;
    const MODE_LABELS = {balanced:'均衡',quality:'质量',cost:'成本',custom:'自定义'};
    const PRESET_MODES = ['balanced','quality','cost'];
    const MODE_DESCRIPTIONS = {
      balanced:'Claude 主理，Codex 执行',
      quality:'更多任务交给 Claude',
      cost:'Codex 主跑，Claude 兜底',
      custom:'逐个角色手动设置',
    };
    const EFFORT_LABELS = {
      minimal:'最少 (minimal)',
      low:'低 (low)',
      medium:'中 (medium)',
      high:'高 (high)',
      xhigh:'极高 (xhigh)',
      max:'最高 (max)',
    };
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const $ = (id) => document.getElementById(id);
    const clone = (value) => JSON.parse(JSON.stringify(value));

    function esc(value) {
      return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    }
    function modeSummary(name) {
      return esc(MODE_DESCRIPTIONS[name]);
    }
    function sourceLabel(source) {
      return ({
        'detected':'本机检测',
        'built-in alias':'内置别名',
        'existing config':'现有配置',
        'codex model/list':'Codex CLI 自动获取',
        'claude --help':'Claude CLI 官方别名',
        'local claude config':'本机 Claude 配置',
        'custom (required)':'尚未读取到',
        'built-in':'内置值',
      })[source] || source;
    }
    function modelCatalog(backend, current, source) {
      const options = clone(state.model_options[backend] || []);
      if (current && !options.some(option => option.value === current)) {
        options.unshift({value:current,label:current,source:source || 'existing config'});
      }
      return options;
    }
    function modelOption(backend, value) {
      return modelCatalog(backend, value, 'existing config').find(option => option.value === value);
    }
    function modelOptionLabel(option) {
      return option.label === option.value ? option.label : `${option.label} (${option.value})`;
    }
    function effortCatalog(backend, model) {
      const option = modelOption(backend, model);
      if (option && option.efforts && option.efforts.length) return option.efforts;
      return state.efforts_by_backend[backend] || [];
    }
    function syncEffort(values) {
      const efforts = effortCatalog(values.backend, values.model);
      if (!efforts.includes(values.effort)) {
        values.effort = efforts.includes('high') ? 'high' : (efforts[0] || '');
      }
      return efforts;
    }
    function syncReadiness() {
      const ready = Object.values(matrix).every(values => values.model);
      $('previewBtn').disabled = !ready;
      if (!ready) $('status').textContent = '没有读取到可用模型，请检查 CLI 登录状态后刷新';
    }
    function syncModeControls() {
      document.querySelectorAll('.mode').forEach(el => {
        const active = el.dataset.mode === mode;
        el.classList.toggle('active', active);
        el.setAttribute('aria-pressed', String(active));
      });
      $('currentMode').textContent = `当前模式：${MODE_LABELS[mode]}`;
    }
    function syncHeroMap() {
      const targets = {
        deep_reasoner:'heroDeep',
        fast_worker:'heroFast',
        arbiter:'heroArbiter',
      };
      for (const [identity, target] of Object.entries(targets)) {
        const values = matrix[identity];
        if (!values) continue;
        const backend = values.backend === 'claude' ? 'Claude Code' : 'Codex';
        $(target).textContent = `${backend} / ${values.model || '需填写'} / ${values.effort}`;
      }
    }
    function invalidate() {
      previewValid = false;
      $('confirmed').checked = false;
      $('apply').disabled = true;
      $('confirm').style.display = 'none';
      if ($('previewWrap').style.display === 'block') $('previewWrap').classList.add('stale');
      $('technicalDetails').open = false;
      $('status').textContent = '选择已变化，请重新生成预览';
      syncReadiness();
    }
    function selectMode(next) {
      mode = next;
      if (next !== 'custom') matrix = clone(state.presets[next]);
      syncModeControls();
      renderIdentities();
      syncHeroMap();
      invalidate();
    }
    function renderIdentities() {
      $('identities').innerHTML = Object.entries(state.identity_meta).map(([identity, meta]) => {
        const values = matrix[identity];
        const efforts = syncEffort(values);
        const verified = modelOption(values.backend, values.model);
        const source = verified ? verified.source : (values.model_source || 'existing config');
        const models = modelCatalog(values.backend, values.model, source);
        const modelOptions = models.length
          ? models.map(option => `<option value="${esc(option.value)}" ${values.model === option.value ? 'selected' : ''}>${esc(modelOptionLabel(option))}</option>`).join('')
          : '<option value="">未读取到可用模型</option>';
        return `<article class="identity" data-identity="${identity}">
          <div class="identity-head"><h3>${esc(meta.label)}</h3><small>${esc(meta.hint)}</small><code class="identity-code">${identity}</code></div>
          <div class="field"><label for="${identity}-backend">由谁执行</label><select id="${identity}-backend" data-field="backend"><option value="claude" ${values.backend === 'claude' ? 'selected' : ''}>Claude Code</option><option value="codex" ${values.backend === 'codex' ? 'selected' : ''}>Codex</option></select></div>
          <div class="field model-field"><label for="${identity}-model">模型</label><select id="${identity}-model" data-field="model" aria-describedby="${identity}-source" ${models.length ? '' : 'disabled'}>${modelOptions}</select><div class="source" id="${identity}-source">来自：${esc(sourceLabel(source))}</div></div>
          <div class="field"><label for="${identity}-effort">思考深度</label><select id="${identity}-effort" data-field="effort">${efforts.map(e => `<option value="${e}" ${values.effort === e ? 'selected' : ''}>${esc(EFFORT_LABELS[e] || e)}</option>`).join('')}</select></div>
        </article>`;
      }).join('');
      document.querySelectorAll('.identity select').forEach(control => control.addEventListener('input', event => {
        const card = event.target.closest('.identity');
        const identity = card.dataset.identity;
        const field = event.target.dataset.field;
        matrix[identity][field] = event.target.value;
        if (field === 'backend') {
          const options = modelCatalog(event.target.value, '', '');
          const selected = options.find(option => option.is_default) || options[0];
          matrix[identity].model = selected ? selected.value : '';
          matrix[identity].model_source = selected ? selected.source : 'custom (required)';
          syncEffort(matrix[identity]);
        } else if (field === 'model') {
          const selected = modelOption(matrix[identity].backend, event.target.value);
          matrix[identity].model_source = selected ? selected.source : 'existing config';
          syncEffort(matrix[identity]);
        }
        mode = 'custom';
        syncModeControls();
        if (field === 'backend') renderIdentities();
        syncHeroMap();
        if (field === 'model') card.querySelector('.source').textContent = `来自：${sourceLabel(matrix[identity].model_source)}`;
        invalidate();
      }));
    }
    function payload() {
      const identities = {};
      for (const identity of Object.keys(state.identity_meta)) {
        identities[identity] = {
          backend: matrix[identity].backend,
          model: matrix[identity].model,
          effort: matrix[identity].effort,
        };
      }
      return {
        mode,
        identities,
        scope: 'project',
        exclude_choice: 'git-exclude',
        write_agents: state.write_agents_available,
        smoke: true,
        routing_action: 'none',
        join_action: 'add',
      };
    }
    async function api(path, body) {
      const response = await fetch(path, {
        method: body ? 'POST' : 'GET',
        headers: {'Content-Type':'application/json','X-Partner-Token':token},
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    }
    async function load() {
      state = await api('/api/state');
      mode = state.initial_mode;
      matrix = clone(state.initial_matrix);
      $('repo').textContent = state.repo;
      const codex = state.detected.codex_model ? `${state.detected.codex_model} / ${state.detected.codex_effort || '未设置'}` : '未检测到模型';
      $('detect').innerHTML = `
        <div class="item"><div class="k">当前宿主</div><div class="v">${esc(state.host)}</div></div>
        <div class="item"><div class="k">项目配置</div><div class="v">${esc(state.config_source)}</div></div>
        <div class="item"><div class="k">Claude CLI</div><div class="v ${state.clis.claude.available ? 'ok':'bad'}">${esc(state.clis.claude.version || '未安装')}</div></div>
        <div class="item" title="${esc(state.clis.codex.path || '')}"><div class="k">Codex CLI (${esc(state.clis.codex.source)})</div><div class="v ${state.clis.codex.available ? 'ok':'bad'}">${esc(state.clis.codex.version || '未安装')}</div></div>
        <div class="item"><div class="k">Codex 检测值</div><div class="v ${state.detected.codex_model ? 'ok':'warn'}">${esc(codex)}</div></div>`;
      $('modes').innerHTML = PRESET_MODES.map(name => `<button type="button" class="mode ${name === mode ? 'active':''}" data-mode="${name}" aria-pressed="${name === mode}"><strong>${MODE_LABELS[name]}</strong><small>${modeSummary(name)}</small></button>`).join('');
      document.querySelectorAll('.mode').forEach(el => el.addEventListener('click', () => selectMode(el.dataset.mode)));
      renderIdentities();
      syncModeControls();
      syncHeroMap();
      const peerEntries = Object.entries(state.peer.identities || {});
      if (peerEntries.length) {
        $('peerSummary').textContent = '已有配置不会被覆盖，这次只补充当前宿主。';
        $('peerWrap').style.display = 'block';
      }
      syncReadiness();
      $('configWorkspace').setAttribute('aria-busy', 'false');
    }
    $('confirmed').addEventListener('change', () => $('apply').disabled = !$('confirmed').checked || !previewValid);
    $('previewBtn').addEventListener('click', async () => {
      $('previewBtn').disabled = true;
      $('previewBtn').textContent = '正在准备...';
      $('configWorkspace').setAttribute('aria-busy', 'true');
      $('previewWrap').classList.remove('stale');
      $('status').textContent = '正在核对将要修改的文件';
      try {
        const data = await api('/api/preview', payload());
        $('preview').textContent = [data.output, data.error].filter(Boolean).join('\n');
        $('previewWrap').style.display = 'block';
        $('previewWrap').classList.toggle('has-error', !data.ok);
        $('previewPlan').style.display = data.ok ? 'block' : 'none';
        $('technicalDetails').open = !data.ok;
        $('technicalSummary').textContent = data.ok ? '查看完整路径和技术 diff' : '查看失败原因';
        previewValid = data.ok;
        $('confirm').style.display = data.ok ? 'flex' : 'none';
        $('status').textContent = data.ok ? '预览完成，还没有修改文件' : '预览失败，没有修改文件';
        $('previewWrap').scrollIntoView({behavior:reduceMotion ? 'auto' : 'smooth',block:'start'});
      } catch (error) {
        $('preview').textContent = error.message;
        $('previewWrap').style.display = 'block';
        $('previewWrap').classList.add('has-error');
        $('previewPlan').style.display = 'none';
        $('technicalDetails').open = true;
        $('technicalSummary').textContent = '查看失败原因';
        $('confirm').style.display = 'none';
        $('status').textContent = '预览失败，没有修改文件';
        $('previewWrap').scrollIntoView({behavior:reduceMotion ? 'auto' : 'smooth',block:'start'});
      } finally {
        $('previewBtn').textContent = '预览安装内容';
        syncReadiness();
        $('configWorkspace').setAttribute('aria-busy', 'false');
      }
    });
    $('apply').addEventListener('click', async () => {
      $('apply').disabled = true;
      $('apply').textContent = '正在安装...';
      $('previewBtn').disabled = true;
      $('configWorkspace').setAttribute('aria-busy', 'true');
      $('status').textContent = '正在安装并自动检查';
      try {
        const data = await api('/api/apply', payload());
        const smoke = data.smoke ? `\nSmoke test:\n${data.smoke.output}${data.smoke.error}` : '';
        $('result').textContent = `${data.output}${data.error}${smoke}`;
        $('resultWrap').style.display = 'block';
        const checksOk = !data.smoke || data.smoke.ok;
        $('resultWrap').classList.toggle('has-error', !data.ok || !checksOk);
        $('status').textContent = !data.ok ? '安装失败' : (checksOk ? '搭子安装完成' : '安装完成，但自动检查未通过');
        previewValid = false;
        $('resultWrap').scrollIntoView({behavior:reduceMotion ? 'auto' : 'smooth',block:'start'});
      } catch (error) {
        $('result').textContent = error.message;
        $('resultWrap').style.display = 'block';
        $('resultWrap').classList.add('has-error');
        $('status').textContent = '安装失败';
        $('resultWrap').scrollIntoView({behavior:reduceMotion ? 'auto' : 'smooth',block:'start'});
      } finally {
        $('apply').textContent = '安装并自动检查';
        $('previewBtn').disabled = false;
        $('configWorkspace').setAttribute('aria-busy', 'false');
      }
    });
    load().catch(error => {
      $('configWorkspace').setAttribute('aria-busy', 'false');
      $('detect').innerHTML = `<div class="item"><div class="k">环境读取失败</div><div class="v bad">${esc(error.message)}</div></div>`;
      $('status').textContent = error.message;
    });
  </script>
</body>
</html>
'''


def make_handler(controller: SetupController, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PartnerSetupUI/1"

        def _host_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            return host.startswith("127.0.0.1:") or host.startswith("localhost:")

        def _authorized(self) -> bool:
            supplied = self.headers.get("X-Partner-Token")
            if not supplied:
                supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            return self._host_allowed() and hmac.compare_digest(supplied, token)

        def _headers(self, status: int, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()

        def _json(self, status: int, data: Mapping[str, Any]) -> None:
            encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8")
            self.wfile.write(encoded)

        def _body(self) -> Any:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise UIError("Content-Length 无效") from None
            if length < 1 or length > 131072:
                raise UIError("请求大小无效")
            try:
                return json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise UIError("请求不是有效 JSON") from None

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if not self._authorized():
                self._json(HTTPStatus.FORBIDDEN, {"error": "无效的本地访问令牌"})
                return
            path = urlparse(self.path).path
            if path == "/":
                self._headers(HTTPStatus.OK, "text/html; charset=utf-8")
                self.wfile.write(HTML.encode("utf-8"))
            elif path == "/api/state":
                self._json(HTTPStatus.OK, controller.state())
            elif path == "/favicon.ico":
                self._headers(HTTPStatus.NO_CONTENT, "image/x-icon")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if not self._authorized():
                self._json(HTTPStatus.FORBIDDEN, {"error": "无效的本地访问令牌"})
                return
            try:
                body = self._body()
                path = urlparse(self.path).path
                if path == "/api/preview":
                    result = controller.preview(body)
                elif path == "/api/apply":
                    result = controller.apply(body)
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._json(HTTPStatus.OK, result)
            except UIError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except subprocess.TimeoutExpired:
                self._json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "setup 引擎执行超时"})
            except (OSError, ValueError, engine.partner_config.ConfigError) as error:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

        def log_message(self, _format: str, *args: Any) -> None:
            return

    return Handler


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Open the Partner setup wizard in a local web UI.")
    result.add_argument("--host", choices=("claude_code", "codex"), help="Host namespace; auto-detected when possible.")
    result.add_argument("--repo", type=Path, default=Path.cwd(), help="Target repository (default: current directory).")
    result.add_argument("--port", type=int, default=0, help="Loopback port (default: choose an available port).")
    result.add_argument("--no-open", action="store_true", help="Print the URL without opening the default browser.")
    return result


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    args = parser().parse_args(argv)
    environ = dict(os.environ if env is None else env)
    host = args.host or engine._detected_host(environ)
    if not host:
        print("error: host could not be detected; pass --host claude_code|codex", file=sys.stderr)
        return 2
    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f"error: repository directory does not exist: {repo}", file=sys.stderr)
        return 2
    try:
        controller = SetupController(host, repo, environ)
        controller.state()
    except (OSError, ValueError, engine.SetupError, engine.partner_config.ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(controller, token))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/?token={token}"
    print(f"Partner Setup UI: {url}", flush=True)
    print("Only localhost can connect. Press Ctrl-C to stop.", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

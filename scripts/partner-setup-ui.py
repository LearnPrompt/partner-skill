#!/usr/bin/env python3
"""Run the Partner setup wizard as a local, single-page web UI."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
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
            env=dict(env),
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


def _codex_version(env: Mapping[str, str]) -> Dict[str, Any]:
    configured = env.get("PARTNER_CODEX_BIN")
    if configured:
        path = configured if "/" in configured else shutil.which(configured, path=env.get("PATH"))
        return _binary_version(path, env, "PARTNER_CODEX_BIN")
    if sys.platform == "darwin":
        for candidate in (
            "/Applications/ChatGPT.app/Contents/Resources/codex",
            "/Applications/Codex.app/Contents/Resources/codex",
        ):
            if os.access(candidate, os.X_OK):
                return _binary_version(candidate, env, "app")
    return _version("codex", env)


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
    initial_mode = "custom" if current else "balanced"
    initial_matrix = current or presets["balanced"]
    return {
        "host": host,
        "repo": str(repo),
        "config_source": resolved["source"],
        "clis": {
            "claude": _version("claude", env),
            "codex": _codex_version(env),
        },
        "detected": {
            "codex_model": codex_detected.get("model"),
            "codex_effort": codex_detected.get("model_reasoning_effort"),
            "claude_models": claude_detected,
        },
        "presets": presets,
        "initial_mode": initial_mode,
        "initial_matrix": initial_matrix,
        "efforts": list(engine.EFFORTS),
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
        effort = values.get("effort")
        if effort not in engine.EFFORTS:
            raise UIError(f"{identity} 的 effort 无效")
        identities[identity] = {
            "backend": backend,
            "model": _clean_string(values.get("model"), f"{identity} model"),
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
        payload = normalize_payload(raw, host=self.host, repo=self.repo, env=self.env)
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
        payload = normalize_payload(raw, host=self.host, repo=self.repo, env=self.env)
        with self.lock:
            if self.preview_digest != _digest(payload) or self.preview_code != 0:
                raise UIError("当前选择还没有通过精确预览，请先点击“生成精确预览”")
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
    /* Taste read: targeted developer-tool redesign. Variance 6, motion 3, density 6. */
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
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="title-block">
        <h1>配置你的搭子</h1>
        <p class="subtitle">三个角色一次定好。页面会先给出真实路径和精确 diff，只有确认后才写入。</p>
      </div>
      <div class="repo-block"><span>当前项目</span><code id="repo"></code></div>
    </header>

    <section class="detect" id="detect" aria-label="本机环境检测">
      <p class="loading-copy">正在读取本机环境...</p>
    </section>

    <div class="workspace" id="configWorkspace" aria-busy="true">
      <aside class="rail" aria-label="配置选项">
        <section class="rail-section">
          <div class="section-heading"><h2>工作模式</h2><p>先选一套起点，右侧可以逐项修改。</p></div>
          <div class="modes" id="modes"><p class="loading-copy">正在生成模式...</p></div>
        </section>

        <section class="rail-section">
          <div class="setting-block">
            <div class="section-heading"><h2>写入范围</h2><p>项目配置优先于全局配置。</p></div>
            <div class="choice-row">
              <label class="choice"><input type="radio" name="scope" value="project" checked> 当前项目</label>
              <label class="choice"><input type="radio" name="scope" value="global"> 所有项目</label>
            </div>
          </div>
          <div class="setting-block field-stack">
            <div>
              <label for="exclude">项目配置的 Git 处理</label>
              <select id="exclude">
                <option value="git-exclude">仅本机忽略（推荐）</option>
                <option value="track">提交到仓库</option>
                <option value="self">写入 .gitignore</option>
              </select>
            </div>
            <label class="choice"><input type="checkbox" id="agents"> 生成或刷新 Claude partner-* agents</label>
            <label class="choice"><input type="checkbox" id="smoke" checked> 写入后运行 smoke test</label>
            <div>
              <label for="routing">常驻路由块</label>
              <select id="routing">
                <option value="none">不修改（推荐）</option>
                <option value="write">写入或刷新</option>
                <option value="remove">移除已生成的路由块</option>
              </select>
            </div>
          </div>
        </section>

        <section class="rail-section peer" id="peerWrap">
          <h2>检测到另一宿主已有配置</h2>
          <p class="muted" id="peerSummary"></p>
          <div class="field-stack">
            <div>
              <label for="join">这次怎么处理</label>
              <select id="join">
                <option value="add">接入并添加本宿主配置（推荐）</option>
                <option value="shared">仅用共享 Goal/Loop，不生成配置</option>
                <option value="cancel">返回，不做修改</option>
              </select>
            </div>
          </div>
        </section>
      </aside>

      <section class="main-panel" aria-labelledby="matrixTitle">
        <div class="main-heading">
          <div><h2 id="matrixTitle">模型矩阵</h2><p>每个角色都明确显示执行 CLI、具体模型和 reasoning effort。</p></div>
          <span class="current-mode" id="currentMode">当前模式：读取中</span>
        </div>

        <div class="matrix" id="identities"><p class="loading-copy">正在读取具体模型...</p></div>

        <div class="output-section" id="previewWrap" aria-live="polite">
          <h2>精确预览</h2>
          <pre id="preview"></pre>
          <div class="confirm" id="confirm">
            <label class="choice"><input type="checkbox" id="confirmed"> 我确认按上面的路径和 diff 写入</label>
            <button class="apply" id="apply" disabled>确认并写入</button>
          </div>
        </div>

        <div class="output-section result" id="resultWrap" aria-live="polite">
          <h2>执行结果</h2>
          <pre id="result"></pre>
        </div>

        <div class="actions">
          <button class="primary" id="previewBtn">生成精确预览</button>
          <span class="status" id="status" role="status" aria-live="polite">尚未写入任何配置</span>
        </div>
      </section>
    </div>
  </main>
  <script>
    const token = new URLSearchParams(location.search).get('token');
    let state;
    let mode = 'balanced';
    let matrix = {};
    let previewValid = false;
    const MODE_LABELS = {balanced:'均衡',quality:'质量',cost:'成本',custom:'自定义'};
    const SHORT_ROLE_LABELS = {deep_reasoner:'推理',fast_worker:'执行',arbiter:'仲裁'};
    const $ = (id) => document.getElementById(id);
    const clone = (value) => JSON.parse(JSON.stringify(value));

    function esc(value) {
      return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    }
    function modeSummary(name) {
      if (name === 'custom') return '<span class="mode-line">逐项选择具体值</span>';
      return Object.entries(state.presets[name]).map(([identity, values]) =>
        `<span class="mode-line"><b>${esc(SHORT_ROLE_LABELS[identity])}</b>${esc(values.backend)} / ${esc(values.model || '需填写')} / ${esc(values.effort)}</span>`
      ).join('');
    }
    function sourceLabel(source) {
      return ({
        'detected':'本机检测',
        'built-in alias':'内置别名',
        'existing config':'现有配置',
        'custom (required)':'需要填写',
        'custom (unverified)':'自定义，未验证',
        'built-in':'内置值',
      })[source] || source;
    }
    function syncModeControls() {
      document.querySelectorAll('.mode').forEach(el => {
        const active = el.dataset.mode === mode;
        el.classList.toggle('active', active);
        el.setAttribute('aria-pressed', String(active));
      });
      $('currentMode').textContent = `当前模式：${MODE_LABELS[mode]}`;
    }
    function invalidate() {
      previewValid = false;
      $('confirmed').checked = false;
      $('apply').disabled = true;
      $('confirm').style.display = 'none';
      $('status').textContent = '选择已变化，请重新生成预览';
    }
    function selectMode(next) {
      mode = next;
      if (next !== 'custom') matrix = clone(state.presets[next]);
      syncModeControls();
      renderIdentities();
      invalidate();
    }
    function renderIdentities() {
      $('identities').innerHTML = Object.entries(state.identity_meta).map(([identity, meta]) => {
        const values = matrix[identity];
        const source = values.model_source || (mode === 'custom' ? 'custom (unverified)' : 'built-in');
        return `<article class="identity" data-identity="${identity}">
          <div class="identity-head"><h3>${esc(meta.label)}</h3><small>${esc(meta.hint)}</small><code class="identity-code">${identity}</code></div>
          <div class="field"><label for="${identity}-backend">执行 CLI</label><select id="${identity}-backend" data-field="backend"><option value="claude" ${values.backend === 'claude' ? 'selected' : ''}>Claude Code</option><option value="codex" ${values.backend === 'codex' ? 'selected' : ''}>Codex</option></select></div>
          <div class="field model-field"><label for="${identity}-model">具体模型</label><input id="${identity}-model" type="text" data-field="model" value="${esc(values.model)}" placeholder="填写真实模型或别名" aria-describedby="${identity}-source"><div class="source" id="${identity}-source">来源：${esc(sourceLabel(source))}</div></div>
          <div class="field"><label for="${identity}-effort">Reasoning effort</label><select id="${identity}-effort" data-field="effort">${state.efforts.map(e => `<option value="${e}" ${values.effort === e ? 'selected' : ''}>${e}</option>`).join('')}</select></div>
        </article>`;
      }).join('');
      document.querySelectorAll('.identity select,.identity input').forEach(control => control.addEventListener('input', event => {
        const card = event.target.closest('.identity');
        const identity = card.dataset.identity;
        matrix[identity][event.target.dataset.field] = event.target.value;
        matrix[identity].model_source = 'custom (unverified)';
        mode = 'custom';
        syncModeControls();
        card.querySelector('.source').textContent = '来源：自定义，未验证';
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
        scope: document.querySelector('input[name=scope]:checked').value,
        exclude_choice: $('exclude').value,
        write_agents: $('agents').checked,
        smoke: $('smoke').checked,
        routing_action: $('routing').value,
        join_action: $('join').value,
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
      $('modes').innerHTML = Object.entries(MODE_LABELS).map(([name,label]) => `<button class="mode ${name === mode ? 'active':''}" data-mode="${name}" aria-pressed="${name === mode}"><strong>${label}</strong><small>${modeSummary(name)}</small></button>`).join('');
      document.querySelectorAll('.mode').forEach(el => el.addEventListener('click', () => selectMode(el.dataset.mode)));
      $('agents').disabled = !state.write_agents_available;
      $('agents').checked = state.write_agents_available;
      if (!state.write_agents_available) $('agents').parentElement.title = 'Codex 宿主不生成 Claude Code 专属 agent 文件';
      renderIdentities();
      syncModeControls();
      const peerEntries = Object.entries(state.peer.identities || {});
      if (peerEntries.length) {
        $('peerSummary').textContent = `${state.peer.host} / ${state.peer.source} / ` + peerEntries.map(([name,v]) => `${name}: ${v.backend}/${v.model}/${v.effort}`).join('；');
        $('peerWrap').style.display = 'block';
      }
      $('configWorkspace').setAttribute('aria-busy', 'false');
    }
    document.querySelectorAll('input[name=scope],#exclude,#agents,#smoke,#routing,#join').forEach(el => el.addEventListener('change', () => {
      invalidate();
      const blocked = $('join').value !== 'add';
      $('previewBtn').disabled = blocked;
      if (blocked) $('status').textContent = '已选择不写入配置，可以直接关闭页面';
    }));
    $('confirmed').addEventListener('change', () => $('apply').disabled = !$('confirmed').checked || !previewValid);
    $('previewBtn').addEventListener('click', async () => {
      $('previewBtn').disabled = true;
      $('previewBtn').textContent = '正在生成...';
      $('configWorkspace').setAttribute('aria-busy', 'true');
      $('status').textContent = '正在生成精确 diff...';
      try {
        const data = await api('/api/preview', payload());
        $('preview').textContent = [data.output, data.error].filter(Boolean).join('\n');
        $('previewWrap').style.display = 'block';
        $('previewWrap').classList.toggle('has-error', !data.ok);
        previewValid = data.ok;
        $('confirm').style.display = data.ok ? 'flex' : 'none';
        $('status').textContent = data.ok ? '预览完成，尚未写入' : '预览失败，没有写入';
      } catch (error) {
        $('preview').textContent = error.message;
        $('previewWrap').style.display = 'block';
        $('previewWrap').classList.add('has-error');
        $('confirm').style.display = 'none';
        $('status').textContent = '预览失败，没有写入';
      } finally {
        $('previewBtn').textContent = '生成精确预览';
        $('previewBtn').disabled = false;
        $('configWorkspace').setAttribute('aria-busy', 'false');
      }
    });
    $('apply').addEventListener('click', async () => {
      $('apply').disabled = true;
      $('apply').textContent = '正在写入...';
      $('previewBtn').disabled = true;
      $('configWorkspace').setAttribute('aria-busy', 'true');
      $('status').textContent = '正在写入并验证...';
      try {
        const data = await api('/api/apply', payload());
        const smoke = data.smoke ? `\nSmoke test:\n${data.smoke.output}${data.smoke.error}` : '';
        $('result').textContent = `${data.output}${data.error}${smoke}`;
        $('resultWrap').style.display = 'block';
        $('resultWrap').classList.toggle('has-error', !data.ok);
        $('status').textContent = data.ok ? '配置已写入' : '写入失败';
        previewValid = false;
      } catch (error) {
        $('result').textContent = error.message;
        $('resultWrap').style.display = 'block';
        $('resultWrap').classList.add('has-error');
        $('status').textContent = '写入失败';
      } finally {
        $('apply').textContent = '确认并写入';
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

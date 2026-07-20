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
    :root { color-scheme: dark; --bg:#090b10; --panel:#11151d; --panel2:#171c26; --line:#293141; --text:#f5f7fb; --muted:#98a2b3; --blue:#6ea8fe; --green:#62d9a0; --amber:#f7c76b; --red:#ff7b86; }
    * { box-sizing:border-box; }
    body { margin:0; background:radial-gradient(circle at 15% 0%,#172033 0,transparent 36%),var(--bg); color:var(--text); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    .shell { width:min(1120px,calc(100% - 32px)); margin:36px auto 72px; }
    header { display:flex; justify-content:space-between; gap:24px; align-items:end; margin-bottom:22px; }
    h1 { font-size:34px; line-height:1.1; margin:0 0 7px; letter-spacing:-.04em; }
    h2 { font-size:16px; margin:0 0 14px; }
    p { margin:0; }
    .muted { color:var(--muted); }
    .panel { background:color-mix(in srgb,var(--panel) 94%,transparent); border:1px solid var(--line); border-radius:18px; padding:20px; box-shadow:0 18px 60px rgba(0,0,0,.22); }
    .detect { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin-bottom:18px; }
    .detect .item { background:var(--panel2); border:1px solid var(--line); padding:12px 14px; border-radius:12px; min-width:0; }
    .k { color:var(--muted); font-size:12px; margin-bottom:4px; }
    .v { font-weight:650; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .ok { color:var(--green); } .warn { color:var(--amber); } .bad { color:var(--red); }
    .section { margin-top:18px; }
    .modes { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
    .mode { appearance:none; text-align:left; color:var(--text); background:var(--panel2); border:1px solid var(--line); border-radius:13px; padding:13px; cursor:pointer; min-height:86px; }
    .mode:hover { border-color:#44516a; }
    .mode.active { border-color:var(--blue); box-shadow:0 0 0 2px rgba(110,168,254,.13) inset; }
    .mode strong { display:block; margin-bottom:5px; }
    .mode small { color:var(--muted); display:block; line-height:1.35; }
    .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
    .identity { background:var(--panel2); border:1px solid var(--line); border-radius:14px; padding:16px; }
    .identity-head { display:flex; justify-content:space-between; gap:8px; margin-bottom:14px; }
    .identity h3 { margin:0; font-size:16px; }
    .identity-head small { color:var(--muted); }
    .tag { color:var(--blue); background:rgba(110,168,254,.1); border:1px solid rgba(110,168,254,.24); padding:3px 7px; border-radius:999px; font:11px ui-monospace,SFMono-Regular,Menlo,monospace; height:max-content; }
    label { display:block; color:var(--muted); font-size:12px; margin:11px 0 5px; }
    select,input[type=text] { width:100%; border:1px solid var(--line); border-radius:9px; background:#0d1118; color:var(--text); padding:9px 10px; font:13px ui-monospace,SFMono-Regular,Menlo,monospace; outline:none; }
    select:focus,input:focus { border-color:var(--blue); }
    .source { color:var(--muted); font-size:11px; margin-top:5px; }
    .options { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .option-group { background:var(--panel2); border:1px solid var(--line); border-radius:14px; padding:15px; }
    .peer { display:none; margin:18px 0 0; border-color:rgba(247,199,107,.42); }
    .choice-row { display:flex; gap:16px; flex-wrap:wrap; }
    .choice { display:flex; align-items:center; gap:7px; color:var(--text); font-size:14px; cursor:pointer; }
    .choice input { accent-color:var(--blue); }
    .actions { display:flex; gap:10px; align-items:center; position:sticky; bottom:12px; padding:14px; margin-top:16px; background:rgba(17,21,29,.92); border:1px solid var(--line); border-radius:15px; backdrop-filter:blur(18px); }
    button.primary,button.apply { border:0; border-radius:10px; padding:11px 16px; font-weight:700; cursor:pointer; }
    button.primary { background:#e8eefb; color:#10131a; }
    button.apply { background:var(--green); color:#07130d; }
    button:disabled { opacity:.4; cursor:not-allowed; }
    .status { margin-left:auto; color:var(--muted); font-size:13px; text-align:right; }
    .preview { display:none; margin-top:16px; }
    pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#080a0f; border:1px solid var(--line); border-radius:12px; padding:16px; max-height:430px; overflow:auto; color:#d9e1ee; font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; }
    .confirm { display:none; align-items:center; gap:12px; margin-top:12px; }
    .confirm label { margin:0; font-size:13px; color:var(--text); }
    .result { display:none; margin-top:16px; border-left:3px solid var(--green); }
    @media (max-width:850px) { .detect,.modes { grid-template-columns:1fr 1fr; } .grid { grid-template-columns:1fr; } .options { grid-template-columns:1fr; } }
    @media (max-width:520px) { .shell { width:min(100% - 18px,1120px); margin-top:18px; } header { display:block; } .detect,.modes { grid-template-columns:1fr; } .actions { flex-wrap:wrap; } .status { width:100%; text-align:left; margin:0; } }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div><h1>搭子配置</h1><p class="muted">一次选完，先看精确 diff，再写入。</p></div>
      <div class="muted" id="repo"></div>
    </header>

    <section class="detect" id="detect"></section>

    <section class="panel peer" id="peerWrap">
      <h2>检测到另一宿主已有配置</h2>
      <p class="muted" id="peerSummary"></p>
      <label for="join">这次怎么处理</label>
      <select id="join">
        <option value="add">接入并添加本宿主配置（推荐）</option>
        <option value="shared">仅用共享 Goal/Loop，不生成配置</option>
        <option value="cancel">返回，不做修改</option>
      </select>
    </section>

    <section class="panel">
      <h2>1 · 工作模式</h2>
      <div class="modes" id="modes"></div>

      <div class="section">
        <h2>2 · 具体模型</h2>
        <div class="grid" id="identities"></div>
      </div>

      <div class="section options">
        <div class="option-group">
          <h2>3 · 写到哪里</h2>
          <div class="choice-row">
            <label class="choice"><input type="radio" name="scope" value="project" checked> 当前项目</label>
            <label class="choice"><input type="radio" name="scope" value="global"> 所有项目</label>
          </div>
          <label for="exclude">项目配置的 Git 处理</label>
          <select id="exclude">
            <option value="git-exclude">仅本机忽略（推荐）</option>
            <option value="track">提交到仓库</option>
            <option value="self">写入 .gitignore</option>
          </select>
        </div>
        <div class="option-group">
          <h2>4 · 生成与验证</h2>
          <label class="choice"><input type="checkbox" id="agents"> 生成或刷新 Claude partner-* agents</label>
          <label class="choice"><input type="checkbox" id="smoke" checked> 写入后运行 smoke test</label>
          <label for="routing">常驻路由块</label>
          <select id="routing">
            <option value="none">不修改（推荐）</option>
            <option value="write">写入或刷新</option>
            <option value="remove">移除已生成的路由块</option>
          </select>
        </div>
      </div>

      <div class="preview" id="previewWrap">
        <h2>精确预览</h2>
        <pre id="preview"></pre>
        <div class="confirm" id="confirm">
          <label class="choice"><input type="checkbox" id="confirmed"> 我确认按上面的路径和 diff 写入</label>
          <button class="apply" id="apply" disabled>确认并写入</button>
        </div>
      </div>

      <div class="result" id="resultWrap">
        <h2>执行结果</h2>
        <pre id="result"></pre>
      </div>

      <div class="actions">
        <button class="primary" id="previewBtn">生成精确预览</button>
        <span class="status" id="status">尚未写入任何配置</span>
      </div>
    </section>
  </main>
  <script>
    const token = new URLSearchParams(location.search).get('token');
    let state;
    let mode = 'balanced';
    let matrix = {};
    let previewValid = false;
    const $ = (id) => document.getElementById(id);
    const clone = (value) => JSON.parse(JSON.stringify(value));

    function esc(value) {
      return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    }
    function modeSummary(name) {
      if (name === 'custom') return '逐项选择 CLI、模型和 effort';
      return Object.values(state.presets[name]).map(v => `${v.backend} · ${v.model || '需填写'} · ${v.effort}`).join('<br>');
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
      document.querySelectorAll('.mode').forEach(el => el.classList.toggle('active', el.dataset.mode === next));
      renderIdentities();
      invalidate();
    }
    function renderIdentities() {
      $('identities').innerHTML = Object.entries(state.identity_meta).map(([identity, meta]) => {
        const values = matrix[identity];
        const source = values.model_source || (mode === 'custom' ? 'custom (unverified)' : 'built-in');
        return `<article class="identity" data-identity="${identity}">
          <div class="identity-head"><div><h3>${esc(meta.label)}</h3><small>${esc(meta.hint)}</small></div><span class="tag">${identity}</span></div>
          <label>执行 CLI</label>
          <select data-field="backend"><option value="claude" ${values.backend === 'claude' ? 'selected' : ''}>Claude Code</option><option value="codex" ${values.backend === 'codex' ? 'selected' : ''}>Codex</option></select>
          <label>具体模型</label>
          <input type="text" data-field="model" value="${esc(values.model)}" placeholder="必须填写真实模型或别名">
          <div class="source">来源：${esc(source)}</div>
          <label>Reasoning effort</label>
          <select data-field="effort">${state.efforts.map(e => `<option value="${e}" ${values.effort === e ? 'selected' : ''}>${e}</option>`).join('')}</select>
        </article>`;
      }).join('');
      document.querySelectorAll('.identity select,.identity input').forEach(control => control.addEventListener('input', event => {
        const card = event.target.closest('.identity');
        const identity = card.dataset.identity;
        matrix[identity][event.target.dataset.field] = event.target.value;
        matrix[identity].model_source = 'custom (unverified)';
        mode = 'custom';
        document.querySelectorAll('.mode').forEach(el => el.classList.toggle('active', el.dataset.mode === 'custom'));
        card.querySelector('.source').textContent = '来源：custom (unverified)';
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
        <div class="item" title="${esc(state.clis.codex.path || '')}"><div class="k">Codex CLI · ${esc(state.clis.codex.source)}</div><div class="v ${state.clis.codex.available ? 'ok':'bad'}">${esc(state.clis.codex.version || '未安装')}</div></div>
        <div class="item"><div class="k">Codex 检测值</div><div class="v ${state.detected.codex_model ? 'ok':'warn'}">${esc(codex)}</div></div>`;
      const labels = {balanced:'均衡',quality:'质量',cost:'成本',custom:'自定义'};
      $('modes').innerHTML = Object.entries(labels).map(([name,label]) => `<button class="mode ${name === mode ? 'active':''}" data-mode="${name}"><strong>${label}</strong><small>${modeSummary(name)}</small></button>`).join('');
      document.querySelectorAll('.mode').forEach(el => el.addEventListener('click', () => selectMode(el.dataset.mode)));
      $('agents').disabled = !state.write_agents_available;
      $('agents').checked = state.write_agents_available;
      if (!state.write_agents_available) $('agents').parentElement.title = 'Codex 宿主不生成 Claude Code 专属 agent 文件';
      renderIdentities();
      const peerEntries = Object.entries(state.peer.identities || {});
      if (peerEntries.length) {
        $('peerSummary').textContent = `${state.peer.host} · ${state.peer.source} · ` + peerEntries.map(([name,v]) => `${name}: ${v.backend}/${v.model}/${v.effort}`).join('；');
        $('peerWrap').style.display = 'block';
      }
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
      $('status').textContent = '正在生成精确 diff…';
      try {
        const data = await api('/api/preview', payload());
        $('preview').textContent = [data.output, data.error].filter(Boolean).join('\n');
        $('previewWrap').style.display = 'block';
        previewValid = data.ok;
        $('confirm').style.display = data.ok ? 'flex' : 'none';
        $('status').textContent = data.ok ? '预览完成，尚未写入' : '预览失败，没有写入';
      } catch (error) {
        $('preview').textContent = error.message;
        $('previewWrap').style.display = 'block';
        $('confirm').style.display = 'none';
        $('status').textContent = '预览失败，没有写入';
      } finally { $('previewBtn').disabled = false; }
    });
    $('apply').addEventListener('click', async () => {
      $('apply').disabled = true;
      $('previewBtn').disabled = true;
      $('status').textContent = '正在写入并验证…';
      try {
        const data = await api('/api/apply', payload());
        const smoke = data.smoke ? `\nSmoke test:\n${data.smoke.output}${data.smoke.error}` : '';
        $('result').textContent = `${data.output}${data.error}${smoke}`;
        $('resultWrap').style.display = 'block';
        $('status').textContent = data.ok ? '配置已写入' : '写入失败';
        previewValid = false;
      } catch (error) {
        $('result').textContent = error.message;
        $('resultWrap').style.display = 'block';
        $('status').textContent = '写入失败';
      } finally { $('previewBtn').disabled = false; }
    });
    load().catch(error => { $('status').textContent = error.message; });
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

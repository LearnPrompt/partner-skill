#!/usr/bin/env python3
"""Configure partner-skill identities and deterministic host artifacts."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from partner_runtime import clean_claude_env

ROOT = SCRIPT_DIR.parent
CONFIG_SCRIPT = SCRIPT_DIR / "partner-config.py"
SPEC = importlib.util.spec_from_file_location("partner_config", CONFIG_SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - installation failure
    raise RuntimeError(f"cannot load {CONFIG_SCRIPT}")
partner_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = partner_config
SPEC.loader.exec_module(partner_config)

IDENTITIES = partner_config.IDENTITIES
BACKENDS = partner_config.BACKENDS
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
BACKEND_EFFORTS = {
    "claude": CLAUDE_EFFORTS,
    "codex": CODEX_EFFORTS,
}
EFFORTS = tuple(dict.fromkeys((*CODEX_EFFORTS, *CLAUDE_EFFORTS)))
BEGIN_MARKER = "<!-- BEGIN PARTNER MANAGED ROUTING (do not edit; managed by partner-skill) -->"
END_MARKER = "<!-- END PARTNER MANAGED ROUTING -->"
HASH_PREFIX = "<!-- partner-content-hash:sha256:"
ROUTING_POLICY = (
    "Route reasoning-intensive, ambiguous work to partner-deep-reasoner.\n"
    "Route mechanical, well-scoped execution to partner-fast-worker.\n"
    "Route independent blind-solve arbitration to partner-arbiter.\n"
)
MANAGED_COMMENT = '<!-- managed by partner-skill - edit via "搭子，配置" -->'

# ``None`` means that the Codex model must be detected or explicitly supplied.
PRESETS: Dict[str, Dict[str, Tuple[str, Optional[str], str]]] = {
    "balanced": {
        "deep_reasoner": ("claude", "opus", "high"),
        "fast_worker": ("codex", None, "high"),
        "arbiter": ("codex", None, "xhigh"),
    },
    "quality": {
        "deep_reasoner": ("claude", "opus", "high"),
        "fast_worker": ("claude", "opus", "high"),
        "arbiter": ("codex", None, "xhigh"),
    },
    "cost": {
        "deep_reasoner": ("codex", None, "xhigh"),
        "fast_worker": ("codex", None, "medium"),
        "arbiter": ("claude", "sonnet", "high"),
    },
}

class SetupError(Exception):
    """A user-actionable setup failure."""


def validate_backend_efforts(identities: Mapping[str, Mapping[str, Any]]) -> None:
    for identity, values in identities.items():
        backend = values["backend"]
        effort = values["effort"]
        supported = BACKEND_EFFORTS[backend]
        if effort not in supported:
            raise SetupError(
                f"--role-effort for {identity} with backend={backend} must be one of "
                f"{', '.join(supported)}"
            )

@dataclass
class FileChange:
    path: Path
    old: str
    new: str
    existed: bool
    blocked: Optional[str] = None
    delete: bool = False

    @property
    def changed(self) -> bool:
        return not self.blocked and (not self.existed or self.old != self.new)

@dataclass
class Plan:
    changes: List[FileChange]
    notes: List[str]
    choices: Dict[str, Dict[str, str]]
    unavailable: List[str]

def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def home_path(env: Mapping[str, str]) -> Path:
    value = env.get("HOME")
    if not value:
        raise SetupError("HOME is unset; set HOME or pass an environment with an isolated home")
    return Path(value).expanduser()

def config_path(scope: str, repo: Path, env: Mapping[str, str]) -> Path:
    if scope == "project":
        return partner_config.project_config_path(repo)
    return partner_config.global_config_path(env)

def manifest_path(repo: Path) -> Path:
    return repo.resolve() / ".partner" / ".generated-manifest"

def backup_root(repo: Path) -> Path:
    return repo.resolve() / ".partner" / "backups"

def parse_identity_values(items: Sequence[str], option: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SetupError(f"{option} must be IDENTITY=VALUE; got {item!r}")
        identity, value = item.split("=", 1)
        if identity not in IDENTITIES:
            raise SetupError(
                f"{option} identity must be one of {', '.join(IDENTITIES)}; got {identity!r}"
            )
        if identity in values:
            raise SetupError(f"{option} repeats identity {identity!r}")
        if not value.strip() or value != value.strip() or any(ord(char) < 32 for char in value):
            raise SetupError(
                f"{option} value for {identity} must be non-empty and contain no control characters"
            )
        values[identity] = value
    return values

def _top_level_codex_values(path: Path) -> Dict[str, str]:
    """Read two top-level scalar strings from Codex TOML, failing open."""

    try:
        text = read_text(path)
    except (OSError, UnicodeError):
        return {}
    result: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            break
        match = re.match(
            r'^\s*(model|model_reasoning_effort)\s*=\s*("(?:\\.|[^"\\])*")\s*(?:#.*)?$',
            line,
        )
        if not match:
            continue
        try:
            value = json.loads(match.group(2))
        except (ValueError, TypeError):
            continue
        if isinstance(value, str) and value.strip():
            result[match.group(1)] = value
    return result

def detect_codex(env: Mapping[str, str]) -> Dict[str, str]:
    root = Path(env.get("CODEX_HOME") or home_path(env) / ".codex").expanduser()
    return _top_level_codex_values(root / "config.toml")

def _frontmatter_model(path: Path) -> Optional[str]:
    try:
        lines = read_text(path).splitlines()
    except (OSError, UnicodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^model:\s*(.*?)\s*$", line)
        if match and match.group(1):
            raw = match.group(1)
            try:
                parsed = json.loads(raw) if raw.startswith('"') else raw
            except ValueError:
                return None
            return parsed if isinstance(parsed, str) and parsed.strip() else None
    return None

def detect_claude(env: Mapping[str, str]) -> Dict[str, str]:
    home = home_path(env)
    detected: Dict[str, str] = {}
    settings = home / ".claude" / "settings.json"
    try:
        data = json.loads(read_text(settings))
        native_env = data.get("env", {}) if isinstance(data, dict) else {}
        if isinstance(native_env, dict):
            if isinstance(native_env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"), str):
                detected["deep_reasoner"] = native_env["ANTHROPIC_DEFAULT_OPUS_MODEL"]
            if isinstance(native_env.get("ANTHROPIC_DEFAULT_SONNET_MODEL"), str):
                detected["fast_worker"] = native_env["ANTHROPIC_DEFAULT_SONNET_MODEL"]
    except (OSError, UnicodeError, ValueError):
        pass
    agents = home / ".claude" / "agents"
    for identity in IDENTITIES:
        for name in (
            f"partner-{identity.replace('_', '-')}.md",
            f"{identity.replace('_', '-')}.md",
        ):
            model = _frontmatter_model(agents / name)
            if model:
                detected[identity] = model
                break
    return detected

def choose_identities(
    args: argparse.Namespace,
    env: Mapping[str, str],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, str]], List[str]]:
    backends = parse_identity_values(args.role_backend, "--role-backend")
    models = parse_identity_values(args.role_model, "--role-model")
    efforts = parse_identity_values(args.role_effort, "--role-effort")
    for identity, backend in backends.items():
        if backend not in BACKENDS:
            raise SetupError(
                f"--role-backend for {identity} must be one of {', '.join(BACKENDS)}"
            )
    for identity, effort in efforts.items():
        if effort not in EFFORTS:
            raise SetupError(
                f"--role-effort for {identity} must be one of {', '.join(EFFORTS)}"
            )
    identities: Dict[str, Dict[str, Any]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    notes: List[str] = []
    if args.mode == "custom":
        for identity in IDENTITIES:
            if identity not in backends or identity not in models or identity not in efforts:
                raise SetupError(
                    "custom mode requires --role-backend, --role-model, and "
                    "--role-effort for all three identities"
                )
            identities[identity] = {
                "backend": backends[identity],
                "model": models[identity],
                "effort": efforts[identity],
                "verified": False,
            }
            sources[identity] = {field: "custom" for field in ("backend", "model", "effort")}
        validate_backend_efforts(identities)
        return identities, sources, notes

    codex_detected = detect_codex(env)
    detected_model = codex_detected.get("model")
    if codex_detected:
        notes.append(
            "Codex detected: "
            + ", ".join(f"{key}={value}" for key, value in sorted(codex_detected.items()))
        )
    missing_models: List[str] = []
    for identity in IDENTITIES:
        preset_backend, preset_model, preset_effort = PRESETS[args.mode][identity]
        backend = backends.get(identity, preset_backend)
        if identity in backends and backend != preset_backend and identity not in models:
            raise SetupError(
                f"--role-backend changes {identity} from {preset_backend} to {backend}; "
                f"also pass --role-model {identity}=<model>"
            )
        if identity in models:
            model = models[identity]
            model_source = "custom"
        elif backend == "codex":
            model = detected_model
            model_source = "detected"
            if not model:
                missing_models.append(identity)
        else:
            model = preset_model
            model_source = "built-in"
        identities[identity] = {
            "backend": backend,
            "model": model,
            "effort": efforts.get(identity, preset_effort),
            "verified": False,
        }
        sources[identity] = {
            "backend": "custom" if identity in backends else "built-in",
            "model": model_source,
            "effort": "custom" if identity in efforts else "built-in",
        }
    if missing_models:
        examples = " ".join(
            f"--role-model {identity}=<model>" for identity in missing_models
        )
        raise SetupError(
            "Codex model was not detected. Set top-level model in "
            "${CODEX_HOME:-$HOME/.codex}/config.toml or pass "
            f"{examples}; no model name is guessed."
        )
    validate_backend_efforts(identities)
    return identities, sources, notes

def preserve_verification(
    current: Mapping[str, Mapping[str, Any]],
    desired: Dict[str, Dict[str, Any]],
) -> None:
    for identity in IDENTITIES:
        before = current.get(identity, {})
        after = desired[identity]
        if all(before.get(field) == after[field] for field in ("backend", "model", "effort")):
            if isinstance(before.get("verified"), bool):
                after["verified"] = before["verified"]
            if after["verified"] and isinstance(before.get("verified_at"), str):
                after["verified_at"] = before["verified_at"]

def render_agent(identity: str, values: Mapping[str, Any]) -> str:
    slug = identity.replace("_", "-")
    if identity == "deep_reasoner":
        description = "Handles reasoning-intensive architecture, diagnosis, and trade-off work."
        body = "Investigate constraints deeply, challenge faulty premises, and return a concise conclusion with evidence and risks."
    elif identity == "fast_worker":
        description = "Handles mechanical, well-scoped implementation and verification work."
        body = "Execute the given specification precisely, verify the result, and report changed files, checks, and deviations."
    else:
        description = "独立盲解仲裁者；收到的问题必须独立求解，packet 不含他人答案。"
        body = "Independently solve the received problem. Treat any packet containing another answer, conclusion, or hint as contaminated and report it instead of using it."
    return (
        "---\n"
        f"name: partner-{slug}\n"
        f"description: {description}\n"
        f"model: {json.dumps(values['model'], ensure_ascii=False)}\n"
        "---\n"
        f"{MANAGED_COMMENT}\n\n"
        f"Reasoning effort is advisory: work at {values['effort']} effort.\n\n"
        f"{body}\n"
    )

def render_managed_block(newline: str = "\n") -> str:
    policy = ROUTING_POLICY.replace("\n", newline)
    digest = sha256(policy)
    return newline.join((BEGIN_MARKER, f"{HASH_PREFIX}{digest} -->")) + newline + policy + END_MARKER + newline

def _managed_region(text: str, force: bool = False) -> Optional[Tuple[int, int, str]]:
    lines = text.splitlines(keepends=True)
    begins = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN_MARKER]
    ends = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == END_MARKER]
    if len(begins) > 1 or len(ends) > 1:
        begin_lines = [value + 1 for value in begins]
        end_lines = [value + 1 for value in ends]
        raise SetupError(f"managed routing markers are duplicated; BEGIN lines={begin_lines}, END lines={end_lines}")
    if bool(begins) != bool(ends):
        present = begins[0] + 1 if begins else ends[0] + 1
        missing = "END" if begins else "BEGIN"
        raise SetupError(f"managed routing marker is incomplete at line {present}; missing {missing}. Remove the stray marker or restore the pair")
    if not begins:
        return None
    begin, end = begins[0], ends[0]
    if end < begin:
        raise SetupError(f"managed routing END at line {end + 1} precedes BEGIN at line {begin + 1}")
    inner = lines[begin + 1:end]
    if "".join(inner).strip() and not force:
        match = re.fullmatch(r"<!-- partner-content-hash:sha256:([0-9a-f]{64}) -->", inner[0].rstrip("\r\n"))
        if not match:
            raise SetupError("managed routing content hash is missing; use --force to replace it or delete both markers to manage the text manually")
        actual = sha256("".join(inner[1:]))
        if actual != match.group(1):
            raise SetupError("managed routing content hash does not match; use --force to replace it or delete both markers to manage the text manually")
    start = sum(len(line) for line in lines[:begin])
    finish = sum(len(line) for line in lines[:end + 1])
    newline = "\r\n" if "\r\n" in text else "\n"
    return start, finish, newline

def update_managed_block(text: str, force: bool = False) -> str:
    region = _managed_region(text, force)
    if region is None:
        newline = "\r\n" if "\r\n" in text else "\n"
        separator = newline if text else ""
        return text + separator + render_managed_block(newline)
    start, finish, newline = region
    return text[:start] + render_managed_block(newline) + text[finish:]

def remove_managed_block(text: str, force: bool = False) -> str:
    region = _managed_region(text, force)
    if region is None:
        return text
    start, finish, newline = region
    before, after = text[:start], text[finish:]
    # update_managed_block always adds one separator before a newly appended block.
    if before.endswith(newline):
        before = before[:-len(newline)]
    return before + after

def load_manifest(path: Path) -> Tuple[str, Dict[str, str]]:
    if not path.exists():
        return "", {}
    old = read_text(path)
    try:
        data = json.loads(old)
    except ValueError as error:
        raise SetupError(f"generated manifest is invalid JSON: {path}: {error}") from None
    if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
        raise SetupError(f"generated manifest must be a JSON path-to-sha256 object: {path}")
    return old, data

def _agent_paths(args: argparse.Namespace, env: Mapping[str, str]) -> Dict[str, Path]:
    root = args.repo.resolve() / ".claude" / "agents" if args.scope == "project" else home_path(env) / ".claude" / "agents"
    return {
        identity: root / f"partner-{identity.replace('_', '-')}.md"
        for identity in IDENTITIES
    }

def _routing_path(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    if args.scope == "project":
        return args.repo.resolve() / ("CLAUDE.md" if args.host == "claude_code" else "AGENTS.md")
    if args.host == "claude_code":
        return home_path(env) / ".claude" / "CLAUDE.md"
    codex_root = Path(env.get("CODEX_HOME") or home_path(env) / ".codex").expanduser()
    return codex_root / "AGENTS.md"

def _git_exclude_change(args: argparse.Namespace) -> Tuple[Optional[FileChange], Optional[str]]:
    if args.scope != "project":
        return None, None
    check = subprocess.run(
        ["git", "-C", str(args.repo), "check-ignore", "-q", "--", ".partner/config.toml"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if check.returncode == 0:
        return None, "project config is already ignored by Git"
    inside = subprocess.run(
        ["git", "-C", str(args.repo), "rev-parse", "--is-inside-work-tree"],
        text=True, capture_output=True, check=False,
    )
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None, "repository is not a Git work tree; exclude step skipped"
    if args.exclude_choice == "self":
        return None, "config is not ignored; add .partner/config.toml to .gitignore yourself"
    if args.exclude_choice == "track":
        return None, "config is not ignored; explicit track choice accepted"
    location = subprocess.run(
        ["git", "-C", str(args.repo), "rev-parse", "--git-path", "info/exclude"],
        text=True, capture_output=True, check=False,
    )
    if location.returncode != 0:
        raise SetupError(f"cannot resolve .git/info/exclude: {location.stderr.strip()}")
    path = Path(location.stdout.strip())
    if not path.is_absolute():
        path = args.repo.resolve() / path
    old = read_text(path) if path.exists() else ""
    entry = ".partner/config.toml"
    if entry in {line.strip() for line in old.splitlines()}:
        new = old
    else:
        new = old + ("" if not old or old.endswith(("\n", "\r")) else "\n") + entry + "\n"
    return FileChange(path, old, new, path.exists()), "config will be excluded through .git/info/exclude"

def _is_legacy_v1(text: str) -> bool:
    if re.search(r"(?m)^\s*schema_version\s*=\s*1\s*(?:#.*)?$", text):
        return True
    return any(
        chunk.name and re.match(r"^hosts\.[^.]+\.roles(?:\.|$)", chunk.name)
        for chunk in partner_config.split_sections(text)
    )

def _migrate_v1(
    text: str,
    current_host: str,
    desired: Dict[str, Dict[str, Any]],
    sources: Dict[str, Dict[str, str]],
) -> str:
    migrated: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for host in partner_config.HOSTS:
        legacy = partner_config.read_legacy_v1(text, host)
        if host == current_host:
            host_identities = {identity: dict(values) for identity, values in desired.items()}
            for identity, old_values in legacy.items():
                if sources[identity]["backend"] != "custom":
                    host_identities[identity]["backend"] = (
                        "claude" if host == "claude_code" else "codex"
                    )
                    sources[identity]["backend"] = "legacy"
                for field in ("model", "effort"):
                    if field in old_values and sources[identity][field] != "custom":
                        host_identities[identity][field] = old_values[field]
                        sources[identity][field] = "legacy"
            desired.clear()
            desired.update(host_identities)
        else:
            default_backend = "claude" if host == "claude_code" else "codex"
            host_identities = {
                identity: {
                    "backend": default_backend,
                    "model": values["model"],
                    "effort": values["effort"],
                    "verified": False,
                }
                for identity, values in legacy.items()
                if "model" in values and "effort" in values
            }
        if host_identities:
            migrated[host] = host_identities

    blocks = ["schema_version = 2\nrevision = 0\n"]
    for host in partner_config.HOSTS:
        emitted = partner_config.emit_host_sections(host, migrated.get(host, {}))
        if emitted:
            blocks.append(emitted)
    blocks.append("[routing]\nalways_on_host_rules = false\n")
    candidate = "\n".join(block.rstrip("\n") for block in blocks) + "\n"
    for host in partner_config.HOSTS:
        partner_config.validate_config(candidate, host)
    return candidate

def _cli_unavailable(
    desired: Mapping[str, Mapping[str, Any]],
    env: Mapping[str, str],
) -> List[str]:
    path = env.get("PATH")
    available = {
        backend: shutil.which(backend, path=path) is not None
        for backend in BACKENDS
    }
    return [
        identity
        for identity in IDENTITIES
        if not available[str(desired[identity]["backend"])]
    ]

def build_plan(args: argparse.Namespace, env: Mapping[str, str]) -> Plan:
    desired, sources, notes = choose_identities(args, env)
    path = config_path(args.scope, args.repo, env)
    old_config = read_text(path) if path.exists() else ""
    current_identities: Mapping[str, Mapping[str, Any]] = {}
    legacy = bool(old_config and _is_legacy_v1(old_config))
    if legacy:
        new_config = _migrate_v1(old_config, args.host, desired, sources)
        notes.append("v1 → v2 升级，旧值已保留为初值")
    else:
        if old_config:
            parsed = partner_config.validate_config(old_config, args.host, path=path)
            current_identities = parsed["hosts"][args.host]["identities"]
        preserve_verification(current_identities, desired)
        new_config = partner_config.update_host(old_config, args.host, desired, path=path)
        # A newly created base document has one transitional separator; converge it
        # before the first write so the next identical apply is byte-idempotent.
        new_config = partner_config.update_host(new_config, args.host, desired, path=path)

    unavailable = _cli_unavailable(desired, env)
    for identity in IDENTITIES:
        sources[identity]["backend_value"] = str(desired[identity]["backend"])
        sources[identity]["model_value"] = str(desired[identity]["model"])
        sources[identity]["effort_value"] = str(desired[identity]["effort"])
        sources[identity]["availability"] = (
            "unavailable" if identity in unavailable else "available"
        )
    if unavailable:
        grouped = ", ".join(
            f"{identity}({desired[identity]['backend']})" for identity in unavailable
        )
        notes.append(
            f"CLI unavailable: {grouped}; install the corresponding CLI or change backend"
        )
    if desired["arbiter"]["backend"] == desired["deep_reasoner"]["backend"]:
        notes.append("盲评价值下降（same-vendor）")
    changes = [FileChange(path, old_config, new_config, path.exists())]

    if args.host == "claude_code" and args.write_agents:
        mpath = manifest_path(args.repo)
        old_manifest, manifest = load_manifest(mpath)
        updated_manifest = dict(manifest)
        for identity, agent_path in _agent_paths(args, env).items():
            old = read_text(agent_path) if agent_path.exists() else ""
            expected = manifest.get(str(agent_path))
            key = str(agent_path)
            if desired[identity]["backend"] == "claude":
                blocked = None
                if agent_path.exists() and (expected is None or sha256(old) != expected):
                    blocked = (
                        "refusing to overwrite a user-owned or modified agent file; "
                        "choose import, a different namespaced file, or skip in references/setup.md"
                    )
                rendered = render_agent(identity, desired[identity])
                changes.append(
                    FileChange(agent_path, old, rendered, agent_path.exists(), blocked)
                )
                if not blocked:
                    updated_manifest[key] = sha256(rendered)
            elif expected is not None:
                if not agent_path.exists():
                    updated_manifest.pop(key, None)
                elif sha256(old) == expected:
                    changes.append(
                        FileChange(agent_path, old, "", True, delete=True)
                    )
                    updated_manifest.pop(key, None)
                else:
                    changes.append(
                        FileChange(
                            agent_path,
                            old,
                            old,
                            True,
                            "refusing to delete an agent file modified since generation",
                        )
                    )
        new_manifest = json.dumps(updated_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        changes.append(FileChange(mpath, old_manifest, new_manifest, mpath.exists()))

    if args.routing_block or args.remove_routing_block:
        rpath = _routing_path(args, env)
        old = read_text(rpath) if rpath.exists() else ""
        try:
            new = remove_managed_block(old, args.force) if args.remove_routing_block else update_managed_block(old, args.force)
            changes.append(FileChange(rpath, old, new, rpath.exists()))
        except SetupError as error:
            changes.append(FileChange(rpath, old, old, rpath.exists(), str(error)))

    exclude, note = _git_exclude_change(args)
    if exclude:
        changes.append(exclude)
    if note:
        notes.append(note)
    return Plan(changes, notes, sources, unavailable)

def unified_diff(change: FileChange) -> str:
    before = change.old.splitlines(keepends=True)
    after = change.new.splitlines(keepends=True)
    fromfile = str(change.path) if change.existed else "/dev/null"
    lines = difflib.unified_diff(before, after, fromfile=fromfile, tofile=str(change.path))
    return "".join(lines) or "(no changes)\n"

def print_plan(plan: Plan) -> None:
    print("Selections:")
    for identity in IDENTITIES:
        selected = plan.choices[identity]
        print(
            f"  {identity}: backend={selected['backend_value']} [{selected['backend']}], "
            f"model={selected['model_value']} [{selected['model']}], "
            f"effort={selected['effort_value']} [{selected['effort']}], "
            f"availability={selected['availability']}"
        )
    for note in plan.notes:
        print(f"NOTE: {note}")
    print("Files:")
    for change in plan.changes:
        state = "REFUSED" if change.blocked else (
            "DELETE" if change.delete and change.changed else (
                "WRITE" if change.changed else "UNCHANGED"
            )
        )
        print(f"  [{state}] {change.path}")
    for change in plan.changes:
        print(f"\nDiff: {change.path}")
        if change.blocked:
            print(f"REFUSED: {change.blocked}")
        print(unified_diff(change), end="")

def _backup_id(timestamp: Optional[str]) -> str:
    raw = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)

def create_backup(repo: Path, changes: Sequence[FileChange], timestamp: Optional[str]) -> Optional[Path]:
    changed = [change for change in changes if change.changed]
    if not changed:
        return None
    root = backup_root(repo)
    candidate = root / _backup_id(timestamp)
    suffix = 2
    while candidate.exists():
        candidate = root / f"{_backup_id(timestamp)}-{suffix}"
        suffix += 1
    records: List[Dict[str, Any]] = []
    for index, change in enumerate(changed):
        backup_name: Optional[str] = None
        if change.existed:
            backup_name = f"files/{index:03d}-{change.path.name}"
            partner_config.atomic_write(candidate / backup_name, change.old)
        records.append({"path": str(change.path), "existed": change.existed, "backup": backup_name})
    partner_config.atomic_write(
        candidate / "manifest.json",
        json.dumps({"files": records}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    directories = sorted(path for path in root.iterdir() if path.is_dir() and (path / "manifest.json").exists())
    for old in directories[:-3]:
        shutil.rmtree(str(old))
    return candidate

def _require_available(plan: Plan) -> None:
    if not plan.unavailable:
        return
    details = ", ".join(
        f"{identity}({plan.choices[identity]['backend_value']})"
        for identity in plan.unavailable
    )
    raise SetupError(
        f"required backend CLI unavailable: {details}; install the CLI or change backend"
    )

def apply_plan(
    args: argparse.Namespace,
    env: Mapping[str, str],
    preflight: Optional[Plan] = None,
) -> int:
    _require_available(preflight or build_plan(args, env))
    lock_path = config_path(args.scope, args.repo, env)
    with partner_config.ConfigLock(lock_path, owner_host=args.host):
        plan = build_plan(args, env)
        _require_available(plan)
        backup = create_backup(args.repo, plan.changes, args.timestamp)
        for change in plan.changes:
            if change.blocked:
                print(f"REFUSED {change.path}: {change.blocked}", file=sys.stderr)
            elif change.changed:
                if change.delete:
                    change.path.unlink(missing_ok=True)
                    print(f"REMOVED {change.path}")
                else:
                    partner_config.atomic_write(change.path, change.new)
                    print(f"APPLIED {change.path}")
            else:
                print(f"UNCHANGED {change.path}")
        if backup:
            print(f"BACKUP {backup}")
    return 1 if any(change.blocked for change in plan.changes) else 0

def rollback(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    root = backup_root(args.repo)
    candidates = sorted(path for path in root.glob("*") if (path / "manifest.json").is_file()) if root.exists() else []
    if not candidates:
        raise SetupError(f"no apply backup found under {root}")
    selected = candidates[-1]
    data = json.loads(read_text(selected / "manifest.json"))
    records = data.get("files") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise SetupError(f"invalid backup manifest: {selected / 'manifest.json'}")
    lock_path = config_path(args.scope, args.repo, env)
    with partner_config.ConfigLock(lock_path, owner_host=args.host):
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise SetupError(f"invalid file record in {selected / 'manifest.json'}")
            target = Path(record["path"])
            if record.get("existed"):
                backup_name = record.get("backup")
                if not isinstance(backup_name, str):
                    raise SetupError(f"backup payload is missing for {target}")
                partner_config.atomic_write(target, read_text(selected / backup_name))
                print(f"RESTORED {target}")
            elif target.exists():
                target.unlink()
                print(f"REMOVED {target}")
    print(f"ROLLED_BACK {selected}")
    return 0

def show_status(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    resolved = partner_config.resolve_config(args.repo, args.host, env=env)
    print(f"host={args.host} config_source={resolved['source']}")
    identities = resolved["hosts"][args.host]["identities"]
    for identity in IDENTITIES:
        values = identities.get(identity, {})
        print(
            f"{identity}: backend={values.get('backend', '<unset>')} "
            f"model={values.get('model', '<unset>')} "
            f"effort={values.get('effort', '<unset>')} "
            f"verified={str(values.get('verified', False)).lower()} "
            f"verified_at={values.get('verified_at', '<unset>')}"
        )
    return 0


def _nested_claude_env(env: Mapping[str, str]) -> Dict[str, str]:
    """Backward-compatible local name for the shared Claude env boundary."""

    return clean_claude_env(env)


def smoke_claude_identity(
    args: argparse.Namespace,
    env: Mapping[str, str],
    identity: str,
    values: Mapping[str, Any],
) -> Tuple[bool, str]:
    claude = shutil.which("claude", path=env.get("PATH"))
    if not claude:
        return False, "Claude CLI not found"
    command = [
        claude,
        "--print",
        "--no-session-persistence",
        "--no-chrome",
        "--permission-mode",
        "plan",
        "--tools",
        "",
        "--model",
        str(values["model"]),
        "--effort",
        str(values["effort"]),
    ]
    agent_path = _agent_paths(args, env)[identity]
    if args.host == "claude_code" and agent_path.is_file():
        command.extend(("--agent", f"partner-{identity.replace('_', '-')}"))
    command.append(
        "This is a configuration smoke test. Reply with exactly "
        "PARTNER_SMOKE_OK and nothing else. Do not use tools."
    )
    try:
        result = subprocess.run(
            command,
            cwd=args.repo,
            env=_nested_claude_env(env),
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "fresh Claude session timed out after 120 seconds"
    except OSError as error:
        return False, f"fresh Claude session could not start: {error}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, detail or f"Claude CLI exited {result.returncode}"
    if "PARTNER_SMOKE_OK" not in result.stdout:
        return False, "fresh Claude session returned an unexpected response"
    return True, ""


def smoke(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    resolved = partner_config.resolve_config(args.repo, args.host, env=env)
    configured = resolved["hosts"][args.host]["identities"]
    missing = [identity for identity in IDENTITIES if identity not in configured]
    if missing:
        raise SetupError(
            f"identities are not configured: {', '.join(missing)}; run --apply first"
        )

    successes: List[str] = []
    failures = False
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md") as prompt:
        prompt.write("Resolve the configured identity only; this is a dry-run smoke check.\n")
        prompt.flush()
        for identity in IDENTITIES:
            if configured[identity]["backend"] == "claude":
                passed, detail = smoke_claude_identity(
                    args, env, identity, configured[identity]
                )
                if passed:
                    successes.append(identity)
                    print(f"{identity}: PASS (fresh Claude session)")
                else:
                    failures = True
                    print(f"{identity}: FAIL\n{detail}", file=sys.stderr)
                continue
            result = subprocess.run(
                [
                    "bash", str(SCRIPT_DIR / "delegate-codex.sh"), "submit",
                    "--repo", str(args.repo), "--prompt-file", prompt.name,
                    "--role", identity, "--host", args.host,
                    "--read-only", "--dry-run",
                ],
                cwd=ROOT, env=dict(env), text=True, capture_output=True, check=False,
            )
            if result.returncode == 0:
                successes.append(identity)
                print(f"{identity}: PASS")
            elif identity == "arbiter" and re.search(
                r"(?:invalid|unknown|unsupported).*(?:--role|arbiter)|"
                r"(?:--role|arbiter).*(?:invalid|unknown|unsupported)",
                result.stderr,
                re.IGNORECASE,
            ):
                print("arbiter: SKIP delegate does not support --role arbiter yet")
            else:
                failures = True
                print(f"{identity}: FAIL\n{result.stderr.rstrip()}", file=sys.stderr)
    if successes:
        timestamp = args.timestamp or utc_now()
        path = config_path(args.scope, args.repo, env)
        with partner_config.ConfigLock(path, owner_host=args.host):
            old = read_text(path) if path.exists() else ""
            parsed_identities = (
                partner_config.validate_config(old, args.host)["hosts"][args.host]["identities"]
                if old else {}
            )
            identities = {
                identity: dict(values)
                for identity, values in parsed_identities.items()
            }
            for identity in IDENTITIES:
                identities.setdefault(identity, dict(configured[identity]))
            for identity in successes:
                identities[identity]["verified"] = True
                identities[identity]["verified_at"] = timestamp
            partner_config.atomic_write(
                path, partner_config.update_host(old, args.host, identities)
            )
    return 1 if failures else 0

def uninstall(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    """Remove only what this host generated: manifest-matched agent files,
    a structurally valid managed routing block, and (opt-in) this host's
    config identities. A file that drifted from its recorded hash is treated as
    user-owned and left in place, reported as skipped."""

    removed: List[str] = []
    skipped: List[str] = []
    lock_path = config_path(args.scope, args.repo, env)
    with partner_config.ConfigLock(lock_path, owner_host=args.host):
        if args.host == "claude_code":
            mpath = manifest_path(args.repo)
            _, manifest = load_manifest(mpath)
            updated_manifest = dict(manifest)
            for agent_path in _agent_paths(args, env).values():
                key = str(agent_path)
                if key not in manifest:
                    continue
                if not agent_path.exists():
                    updated_manifest.pop(key, None)
                    continue
                if sha256(read_text(agent_path)) != manifest[key]:
                    skipped.append(f"{agent_path}: modified since generation; left in place")
                    continue
                if not args.dry_run:
                    agent_path.unlink()
                    updated_manifest.pop(key, None)
                removed.append(str(agent_path))
            if not args.dry_run and updated_manifest != manifest:
                partner_config.atomic_write(
                    mpath, json.dumps(updated_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                )

        rpath = _routing_path(args, env)
        if rpath.exists():
            old = read_text(rpath)
            try:
                new = remove_managed_block(old, args.force)
            except SetupError as error:
                skipped.append(f"{rpath}: {error}")
            else:
                if new != old:
                    if not args.dry_run:
                        partner_config.atomic_write(rpath, new)
                    removed.append(f"{rpath} (managed routing block)")

        if args.remove_config:
            cpath = config_path(args.scope, args.repo, env)
            if cpath.exists():
                old = read_text(cpath)
                cleared = partner_config.update_host(old, args.host, {})
                if cleared != old:
                    if not args.dry_run:
                        partner_config.atomic_write(cpath, cleared)
                    removed.append(f"{cpath} (hosts.{args.host}.identities cleared)")

    prefix = "WOULD_REMOVE" if args.dry_run else "REMOVED"
    for line in removed:
        print(f"{prefix} {line}")
    for line in skipped:
        print(f"SKIPPED {line}", file=sys.stderr)
    if not removed and not skipped:
        print("nothing to remove")
    return 0

def _detected_host(env: Mapping[str, str]) -> Optional[str]:
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude_code"
    if env.get("CODEX_THREAD_ID") or env.get("CODEX_SANDBOX") or env.get("CODEX_HOME"):
        return "codex"
    return None

def interactive(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    if not sys.stdin.isatty():
        raise SetupError("--interactive requires a TTY; use --preview/--apply with explicit parameters")
    host = args.host or _detected_host(env)
    if not host:
        raise SetupError("host could not be detected; rerun --interactive --host claude_code|codex")
    search_path = env.get("PATH")
    print(
        f"Detected host: {host}; paired CLI: "
        f"claude={bool(shutil.which('claude', path=search_path))}, "
        f"codex={bool(shutil.which('codex', path=search_path))}"
    )
    native = detect_claude(env) if host == "claude_code" else detect_codex(env)
    print(
        "Detected native values: "
        + (", ".join(f"{key}={value} [detected]" for key, value in sorted(native.items())) or "none")
    )
    peer = "codex" if host == "claude_code" else "claude_code"
    try:
        peer_config = partner_config.resolve_config(args.repo, peer, env=env)
        peer_identities = peer_config["hosts"][peer]["identities"]
    except partner_config.ConfigError:
        peer_identities = {}
        peer_source = "legacy-v1"
        for candidate in (
            partner_config.project_config_path(args.repo),
            partner_config.global_config_path(env),
        ):
            if not candidate.is_file():
                continue
            candidate_text = read_text(candidate)
            if not _is_legacy_v1(candidate_text):
                continue
            default_backend = "claude" if peer == "claude_code" else "codex"
            peer_identities = {
                identity: {"backend": default_backend, **values}
                for identity, values in partner_config.read_legacy_v1(
                    candidate_text, peer
                ).items()
            }
            peer_source = f"legacy-v1:{candidate}"
            break
        if not peer_identities:
            raise
        peer_config = {"source": peer_source}
    if peer_identities:
        summary = ", ".join(
            f"{identity}={values.get('backend', '<unset>')}/"
            f"{values.get('model', '<unset>')}/{values.get('effort', '<unset>')}"
            for identity, values in sorted(peer_identities.items())
        )
        print(f"Existing {peer} config ({peer_config['source']}): {summary}")
        join = input("Second host [1 add this host/2 shared Goal-Loop only/3 return] (1): ").strip() or "1"
        if join == "2":
            print("Shared Goal/Loop only; no host config or agents written.")
            return 0
        if join == "3":
            print("No changes applied.")
            return 0
        if join != "1":
            raise SetupError("invalid second-host selection")
    mode_values = {"1": "balanced", "2": "quality", "3": "cost", "4": "custom"}
    mode = mode_values.get(input("Mode [1 balanced/2 quality/3 cost/4 custom] (1): ").strip() or "1")
    if not mode:
        raise SetupError("invalid mode selection")
    scope = "global" if (input("Scope [1 project/2 global] (1): ").strip() or "1") == "2" else "project"
    write_agents = host == "claude_code" and (input("Generate partner agents? [Y/n]: ").strip().lower() not in ("n", "no"))
    routing = input("Write managed routing block? [y/N]: ").strip().lower() in ("y", "yes")
    identity_backends: List[str] = []
    identity_models: List[str] = []
    identity_efforts: List[str] = []
    if mode == "custom":
        for identity in IDENTITIES:
            identity_backends.append(
                f"{identity}={input(f'{identity} backend [claude/codex]: ').strip()}"
            )
            identity_models.append(
                f"{identity}={input(f'{identity} model: ').strip()}"
            )
            identity_efforts.append(
                f"{identity}={input(f'{identity} effort: ').strip()}"
            )
    selected = argparse.Namespace(**vars(args))
    selected.host, selected.mode, selected.scope = host, mode, scope
    selected.write_agents, selected.routing_block = write_agents, routing
    selected.role_backend = identity_backends
    selected.role_model, selected.role_effort = identity_models, identity_efforts
    plan = build_plan(selected, env)
    print_plan(plan)
    if input("Apply these changes? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("No changes applied.")
        return 0
    status = apply_plan(selected, env, plan)
    print("Next: run partner-setup.py --smoke --host " + host + " --repo " + str(args.repo))
    return status

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview, apply, inspect, smoke-test, or roll back partner-skill setup.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true", help="Show resolved identity values and verification state.")
    action.add_argument("--preview", action="store_true", help="Print exact target paths and unified diffs without writing.")
    action.add_argument("--apply", action="store_true", help="Atomically apply the same plan shown by --preview.")
    action.add_argument("--interactive", action="store_true", help="Run the pure-terminal fallback wizard.")
    action.add_argument("--rollback", action="store_true", help="Restore the newest apply backup.")
    action.add_argument("--smoke", action="store_true", help="Smoke-check configured identities and record successful backend checks.")
    action.add_argument("--uninstall", action="store_true", help="Remove manifest-tracked generated files, the managed routing block, and optionally this host's config.")
    parser.add_argument("--host", choices=("claude_code", "codex"), help="Host namespace (required for preview/apply; otherwise auto-detected when possible).")
    parser.add_argument("--scope", choices=("project", "global"), default="project", help="Config/artifact scope (default: project).")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root (default: current directory).")
    parser.add_argument("--mode", choices=("balanced", "quality", "cost", "custom"), default="balanced", help="Identity preset (default: balanced).")
    parser.add_argument("--role-backend", action="append", default=[], metavar="IDENTITY=BACKEND", help="Override an identity backend; repeat per identity. Required for all identities in custom mode.")
    parser.add_argument("--role-model", action="append", default=[], metavar="IDENTITY=MODEL", help="Override an identity model; repeat per identity. Required for all identities in custom mode.")
    parser.add_argument("--role-effort", action="append", default=[], metavar="IDENTITY=EFFORT", help="Override an identity effort; repeat per identity. Required for all identities in custom mode.")
    agents = parser.add_mutually_exclusive_group()
    agents.add_argument("--write-agents", dest="write_agents", action="store_true", help="Generate namespaced Claude agents (default).")
    agents.add_argument("--no-write-agents", dest="write_agents", action="store_false", help="Skip Claude agent generation.")
    parser.set_defaults(write_agents=True)
    routing = parser.add_mutually_exclusive_group()
    routing.add_argument("--routing-block", action="store_true", help="Add or refresh the managed host routing block.")
    routing.add_argument("--remove-routing-block", action="store_true", help="Remove a valid managed routing block.")
    parser.add_argument("--force", action="store_true", help="Skip managed-content hash validation only; structural checks still apply.")
    parser.add_argument("--exclude-choice", choices=("git-exclude", "self", "track"), default="git-exclude", help="Project config Git handling (default: git-exclude).")
    parser.add_argument("--timestamp", help="Explicit smoke verified_at value; also gives deterministic backup IDs in tests.")
    parser.add_argument("--remove-config", action="store_true", help="With --uninstall, also clear this host's identities from the config (other host and top-level fields untouched).")
    parser.add_argument("--dry-run", action="store_true", help="With --uninstall, report what would be removed without writing anything.")
    return parser

def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    environ = os.environ if env is None else env
    args.repo = args.repo.resolve()
    try:
        if args.interactive:
            return interactive(args, environ)
        if args.status:
            if not args.host:
                args.host = _detected_host(environ)
            if not args.host:
                for index, host in enumerate(("claude_code", "codex")):
                    if index:
                        print()
                    args.host = host
                    show_status(args, environ)
                return 0
            return show_status(args, environ)
        if args.rollback:
            args.host = args.host or _detected_host(environ) or "setup"
            return rollback(args, environ)
        if args.smoke:
            args.host = args.host or _detected_host(environ)
            if not args.host:
                raise SetupError("smoke host could not be detected; pass --host claude_code|codex")
            return smoke(args, environ)
        if args.uninstall:
            args.host = args.host or _detected_host(environ)
            if not args.host:
                raise SetupError("uninstall host could not be detected; pass --host claude_code|codex")
            return uninstall(args, environ)
        if not args.host:
            raise SetupError("--host is required for --preview and --apply")
        plan = build_plan(args, environ)
        if args.preview:
            print_plan(plan)
            return 1 if any(change.blocked for change in plan.changes) else 0
        return apply_plan(args, environ, plan)
    except (SetupError, partner_config.ConfigError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

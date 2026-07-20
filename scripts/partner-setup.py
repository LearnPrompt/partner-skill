#!/usr/bin/env python3
"""Configure partner-skill roles and deterministic host artifacts."""

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
ROOT = SCRIPT_DIR.parent
CONFIG_SCRIPT = SCRIPT_DIR / "partner-config.py"
SPEC = importlib.util.spec_from_file_location("partner_config", CONFIG_SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - installation failure
    raise RuntimeError(f"cannot load {CONFIG_SCRIPT}")
partner_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = partner_config
SPEC.loader.exec_module(partner_config)

ROLES = ("deep_reasoner", "fast_worker")
EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
BEGIN_MARKER = "<!-- BEGIN PARTNER MANAGED ROUTING (do not edit; managed by partner-skill) -->"
END_MARKER = "<!-- END PARTNER MANAGED ROUTING -->"
HASH_PREFIX = "<!-- partner-content-hash:sha256:"
ROUTING_POLICY = (
    "Route reasoning-intensive, ambiguous work to partner-deep-reasoner.\n"
    "Route mechanical, well-scoped execution to partner-fast-worker.\n"
)
MANAGED_COMMENT = '<!-- managed by partner-skill - edit via "搭子，配置" -->'

# Presets are starting values only. Claude uses stable aliases; Codex deliberately
# has no built-in model names and must detect one or receive an explicit override.
CLAUDE_PRESETS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "balanced": {"deep_reasoner": ("opus", "high"), "fast_worker": ("sonnet", "medium")},
    "quality": {"deep_reasoner": ("opus", "high"), "fast_worker": ("opus", "high")},
    "cost": {"deep_reasoner": ("sonnet", "medium"), "fast_worker": ("haiku", "low")},
}
CODEX_EFFORT_PRESETS: Dict[str, Dict[str, str]] = {
    "balanced": {"deep_reasoner": "high", "fast_worker": "medium"},
    "quality": {"deep_reasoner": "xhigh", "fast_worker": "high"},
    "cost": {"deep_reasoner": "medium", "fast_worker": "low"},
}

class SetupError(Exception):
    """A user-actionable setup failure."""

@dataclass
class FileChange:
    path: Path
    old: str
    new: str
    existed: bool
    blocked: Optional[str] = None

    @property
    def changed(self) -> bool:
        return not self.blocked and (not self.existed or self.old != self.new)

@dataclass
class Plan:
    changes: List[FileChange]
    notes: List[str]
    choices: Dict[str, Dict[str, str]]

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

def parse_role_values(items: Sequence[str], option: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SetupError(f"{option} must be ROLE=VALUE; got {item!r}")
        role, value = item.split("=", 1)
        if role not in ROLES:
            raise SetupError(f"{option} role must be one of {', '.join(ROLES)}; got {role!r}")
        if role in values:
            raise SetupError(f"{option} repeats role {role!r}")
        if not value.strip() or value != value.strip() or any(ord(char) < 32 for char in value):
            raise SetupError(f"{option} value for {role} must be non-empty and contain no control characters")
        values[role] = value
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
    for role in ROLES:
        for name in (f"partner-{role.replace('_', '-')}.md", f"{role.replace('_', '-')}.md"):
            model = _frontmatter_model(agents / name)
            if model:
                detected[role] = model
                break
    return detected

def choose_roles(args: argparse.Namespace, env: Mapping[str, str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, str]], List[str]]:
    models = parse_role_values(args.role_model, "--role-model")
    efforts = parse_role_values(args.role_effort, "--role-effort")
    for role, effort in efforts.items():
        if effort not in EFFORTS:
            raise SetupError(f"--role-effort for {role} must be one of {', '.join(EFFORTS)}")
    roles: Dict[str, Dict[str, Any]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    notes: List[str] = []
    if args.mode == "custom":
        for role in ROLES:
            if role not in models or role not in efforts:
                raise SetupError(
                    "custom mode requires --role-model and --role-effort for both roles"
                )
            roles[role] = {"model": models[role], "effort": efforts[role], "verified": False}
            sources[role] = {"model": "custom", "effort": "custom"}
        return roles, sources, notes

    if args.host == "claude_code":
        detected = detect_claude(env)
        if detected:
            summary = ", ".join(f"{role}={value}" for role, value in sorted(detected.items()))
            notes.append(f"Claude detected models (read-only): {summary}")
        preset = CLAUDE_PRESETS[args.mode]
        for role in ROLES:
            model, effort = preset[role]
            roles[role] = {
                "model": models.get(role, model),
                "effort": efforts.get(role, effort),
                "verified": False,
            }
            sources[role] = {
                "model": "custom" if role in models else "built-in",
                "effort": "custom" if role in efforts else "built-in",
            }
    else:
        detected = detect_codex(env)
        detected_model = detected.get("model")
        if detected:
            notes.append(
                "Codex detected: "
                + ", ".join(f"{key}={value}" for key, value in sorted(detected.items()))
            )
        missing = [role for role in ROLES if role not in models and not detected_model]
        if missing:
            raise SetupError(
                "Codex model was not detected. Set top-level model in "
                "${CODEX_HOME:-$HOME/.codex}/config.toml or pass "
                "--role-model deep_reasoner=<model> --role-model fast_worker=<model>; "
                "no model name is guessed."
            )
        preset = CODEX_EFFORT_PRESETS[args.mode]
        for role in ROLES:
            roles[role] = {
                "model": models.get(role, detected_model),
                "effort": efforts.get(role, preset[role]),
                "verified": False,
            }
            sources[role] = {
                "model": "custom" if role in models else "detected",
                "effort": "custom" if role in efforts else "built-in",
            }
    return roles, sources, notes

def preserve_verification(current: Mapping[str, Mapping[str, Any]], desired: Dict[str, Dict[str, Any]]) -> None:
    for role in ROLES:
        before = current.get(role, {})
        after = desired[role]
        if before.get("model") == after["model"] and before.get("effort") == after["effort"]:
            if isinstance(before.get("verified"), bool):
                after["verified"] = before["verified"]
            if after["verified"] and isinstance(before.get("verified_at"), str):
                after["verified_at"] = before["verified_at"]

def render_agent(role: str, values: Mapping[str, Any]) -> str:
    slug = role.replace("_", "-")
    if role == "deep_reasoner":
        description = "Handles reasoning-intensive architecture, diagnosis, and trade-off work."
        body = "Investigate constraints deeply, challenge faulty premises, and return a concise conclusion with evidence and risks."
    else:
        description = "Handles mechanical, well-scoped implementation and verification work."
        body = "Execute the given specification precisely, verify the result, and report changed files, checks, and deviations."
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
    return {role: root / f"partner-{role.replace('_', '-')}.md" for role in ROLES}

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

def build_plan(args: argparse.Namespace, env: Mapping[str, str]) -> Plan:
    desired, sources, notes = choose_roles(args, env)
    for role in ROLES:
        sources[role]["model_value"] = str(desired[role]["model"])
        sources[role]["effort_value"] = str(desired[role]["effort"])
    path = config_path(args.scope, args.repo, env)
    old_config = read_text(path) if path.exists() else ""
    current_roles: Mapping[str, Mapping[str, Any]] = {}
    if old_config:
        parsed = partner_config.validate_config(old_config, args.host)
        current_roles = parsed["hosts"][args.host]["roles"]
    preserve_verification(current_roles, desired)
    new_config = partner_config.update_host(old_config, args.host, desired)
    # A newly created base document has one transitional separator; converge it
    # before the first write so the next identical apply is byte-idempotent.
    new_config = partner_config.update_host(new_config, args.host, desired)
    changes = [FileChange(path, old_config, new_config, path.exists())]

    if args.host == "claude_code" and args.write_agents:
        mpath = manifest_path(args.repo)
        old_manifest, manifest = load_manifest(mpath)
        updated_manifest = dict(manifest)
        for role, agent_path in _agent_paths(args, env).items():
            old = read_text(agent_path) if agent_path.exists() else ""
            expected = manifest.get(str(agent_path))
            blocked = None
            if agent_path.exists() and (expected is None or sha256(old) != expected):
                blocked = (
                    "refusing to overwrite a user-owned or modified agent file; "
                    "choose import, a different namespaced file, or skip in references/setup.md"
                )
            rendered = render_agent(role, desired[role])
            changes.append(FileChange(agent_path, old, rendered, agent_path.exists(), blocked))
            if not blocked:
                updated_manifest[str(agent_path)] = sha256(rendered)
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
    return Plan(changes, notes, sources)

def unified_diff(change: FileChange) -> str:
    before = change.old.splitlines(keepends=True)
    after = change.new.splitlines(keepends=True)
    fromfile = str(change.path) if change.existed else "/dev/null"
    lines = difflib.unified_diff(before, after, fromfile=fromfile, tofile=str(change.path))
    return "".join(lines) or "(no changes)\n"

def print_plan(plan: Plan) -> None:
    print("Selections:")
    for role in ROLES:
        selected = plan.choices[role]
        print(
            f"  {role}: model={selected['model_value']} [{selected['model']}], "
            f"effort={selected['effort_value']} [{selected['effort']}]"
        )
    for note in plan.notes:
        print(f"NOTE: {note}")
    print("Files:")
    for change in plan.changes:
        state = "REFUSED" if change.blocked else ("WRITE" if change.changed else "UNCHANGED")
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

def apply_plan(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    lock_path = config_path(args.scope, args.repo, env)
    with partner_config.ConfigLock(lock_path, owner_host=args.host):
        plan = build_plan(args, env)
        backup = create_backup(args.repo, plan.changes, args.timestamp)
        for change in plan.changes:
            if change.blocked:
                print(f"REFUSED {change.path}: {change.blocked}", file=sys.stderr)
            elif change.changed:
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
    roles = resolved["hosts"][args.host]["roles"]
    for role in ROLES:
        values = roles.get(role, {})
        print(
            f"{role}: model={values.get('model', '<unset>')} "
            f"effort={values.get('effort', '<unset>')} "
            f"verified={str(values.get('verified', False)).lower()} "
            f"verified_at={values.get('verified_at', '<unset>')}"
        )
    return 0

def smoke(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    resolved = partner_config.resolve_config(args.repo, args.host, env=env)
    configured = resolved["hosts"][args.host]["roles"]
    missing = [role for role in ROLES if role not in configured]
    if missing:
        raise SetupError(f"roles are not configured: {', '.join(missing)}; run --apply first")
    if args.host == "claude_code":
        for role in ROLES:
            print(f"{role}: needs_new_session; verified remains false")
        print("Start a new Claude Code session, invoke the partner-* agents, and verify their reported agent/model metadata.")
        return 0

    successes: List[str] = []
    failures = False
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md") as prompt:
        prompt.write("Resolve the configured role only; this is a dry-run smoke check.\n")
        prompt.flush()
        for role in ROLES:
            result = subprocess.run(
                [
                    "bash", str(SCRIPT_DIR / "delegate-codex.sh"), "submit",
                    "--repo", str(args.repo), "--prompt-file", prompt.name,
                    "--role", role, "--read-only", "--dry-run",
                ],
                cwd=ROOT, env=dict(env), text=True, capture_output=True, check=False,
            )
            if result.returncode == 0:
                successes.append(role)
                print(f"{role}: PASS")
            else:
                failures = True
                print(f"{role}: FAIL\n{result.stderr.rstrip()}", file=sys.stderr)
    if successes:
        timestamp = args.timestamp or utc_now()
        path = config_path(args.scope, args.repo, env)
        with partner_config.ConfigLock(path, owner_host=args.host):
            old = read_text(path) if path.exists() else ""
            parsed_roles = partner_config.validate_config(old, args.host)["hosts"][args.host]["roles"] if old else {}
            roles = {role: dict(values) for role, values in parsed_roles.items()}
            for role in ROLES:
                roles.setdefault(role, dict(configured[role]))
            for role in successes:
                roles[role]["verified"] = True
                roles[role]["verified_at"] = timestamp
            partner_config.atomic_write(path, partner_config.update_host(old, args.host, roles))
    return 1 if failures else 0

def uninstall(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    """Remove only what this host generated: manifest-matched agent files,
    a structurally valid managed routing block, and (opt-in) this host's
    config roles. A file that drifted from its recorded hash is treated as
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
                    removed.append(f"{cpath} (hosts.{args.host}.roles cleared)")

    prefix = "WOULD_REMOVE" if args.dry_run else "REMOVED"
    for line in removed:
        print(f"{prefix} {line}")
    for line in skipped:
        print(f"SKIPPED {line}", file=sys.stderr)
    if not removed and not skipped:
        print("nothing to remove")
    return 0



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
    print(f"Detected host: {host}; paired CLI: claude={bool(shutil.which('claude'))}, codex={bool(shutil.which('codex'))}")
    native = detect_claude(env) if host == "claude_code" else detect_codex(env)
    print(
        "Detected native values: "
        + (", ".join(f"{key}={value} [detected]" for key, value in sorted(native.items())) or "none")
    )
    peer = "codex" if host == "claude_code" else "claude_code"
    peer_config = partner_config.resolve_config(args.repo, peer, env=env)
    peer_roles = peer_config["hosts"][peer]["roles"]
    if peer_roles:
        summary = ", ".join(
            f"{role}={values.get('model', '<unset>')}/{values.get('effort', '<unset>')}"
            for role, values in sorted(peer_roles.items())
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
    role_models: List[str] = []
    role_efforts: List[str] = []
    if mode == "custom":
        for role in ROLES:
            role_models.append(f"{role}={input(f'{role} model: ').strip()}")
            role_efforts.append(f"{role}={input(f'{role} effort: ').strip()}")
    selected = argparse.Namespace(**vars(args))
    selected.host, selected.mode, selected.scope = host, mode, scope
    selected.write_agents, selected.routing_block = write_agents, routing
    selected.role_model, selected.role_effort = role_models, role_efforts
    plan = build_plan(selected, env)
    print_plan(plan)
    if input("Apply these changes? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("No changes applied.")
        return 0
    status = apply_plan(selected, env)
    print("Next: run partner-setup.py --smoke --host " + host + " --repo " + str(args.repo))
    return status

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview, apply, inspect, smoke-test, or roll back partner-skill setup.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true", help="Show resolved role values and verification state.")
    action.add_argument("--preview", action="store_true", help="Print exact target paths and unified diffs without writing.")
    action.add_argument("--apply", action="store_true", help="Atomically apply the same plan shown by --preview.")
    action.add_argument("--interactive", action="store_true", help="Run the pure-terminal fallback wizard.")
    action.add_argument("--rollback", action="store_true", help="Restore the newest apply backup.")
    action.add_argument("--smoke", action="store_true", help="Smoke-check configured roles and record successful Codex checks.")
    action.add_argument("--uninstall", action="store_true", help="Remove manifest-tracked generated files, the managed routing block, and optionally this host's config.")
    parser.add_argument("--host", choices=("claude_code", "codex"), help="Host namespace (required for preview/apply; otherwise auto-detected when possible).")
    parser.add_argument("--scope", choices=("project", "global"), default="project", help="Config/artifact scope (default: project).")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root (default: current directory).")
    parser.add_argument("--mode", choices=("balanced", "quality", "cost", "custom"), default="balanced", help="Role preset (default: balanced).")
    parser.add_argument("--role-model", action="append", default=[], metavar="ROLE=MODEL", help="Override a role model; repeat per role.")
    parser.add_argument("--role-effort", action="append", default=[], metavar="ROLE=EFFORT", help="Override a role effort; repeat per role.")
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
    parser.add_argument("--remove-config", action="store_true", help="With --uninstall, also clear this host's roles from the config (other host and top-level fields untouched).")
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
        return apply_plan(args, environ)
    except (SetupError, partner_config.ConfigError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

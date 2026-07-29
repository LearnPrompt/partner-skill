#!/usr/bin/env python3
"""Run one bounded, tool-free Claude planning turn from Partner config.

The outer host prepares a compact planning packet. This runner validates that
packet, resolves the configured role without fallback, and starts Claude with
safe mode, no tools, explicit wall/idle limits, and a CLI-enforced API budget.
It persists only sanitized event metadata and visible text deltas; thinking
content and the original packet are never copied into the run log.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from partner_runtime import clean_claude_env


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_SCRIPT = SCRIPT_DIR / "partner-config.py"
SPEC = importlib.util.spec_from_file_location("partner_config", CONFIG_SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - installation failure
    raise RuntimeError(f"cannot load {CONFIG_SCRIPT}")
partner_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = partner_config
SPEC.loader.exec_module(partner_config)

PACKET_TITLE = "# Partner Bounded Planning Packet"
REQUIRED_SECTIONS = (
    "Goal",
    "Non-goals",
    "Current-State Evidence",
    "Constraints",
    "Acceptance",
    "Open Decisions",
    "Truncation",
)
PLAN_TITLE = "# Plan Checkpoint"
PLAN_REQUIRED_SECTIONS = (
    "Goal",
    "Non-goals",
    "Current-State Evidence",
    "File Scope",
    "Steps",
    "Risks",
    "Acceptance Checks",
    "Rollback",
)
DEFAULT_MAX_INPUT_CHARS = 24_000
ABSOLUTE_MAX_INPUT_CHARS = 24_000
DEFAULT_WALL_TIMEOUT_SECONDS = 600.0
DEFAULT_IDLE_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_BUDGET_USD = 2.0
DRAIN_TIMEOUT_SECONDS = 1.0
READ_CHUNK_BYTES = 65_536
PROCESS_TERMINATE_GRACE_SECONDS = 3.0
MAX_STREAM_BUFFER_BYTES = 1_048_576
MAX_VISIBLE_OUTPUT_CHARS = 100_000
MAX_EVENT_LOG_BYTES = 10_000_000
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
STREAM_EVENT_TYPES = frozenset(("system", "stream_event", "assistant", "result"))
SECRET_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[op]_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"npm_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bya29\.[A-Za-z0-9._~-]{10,}"),
    re.compile(
        r"(?i)\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/-]{10,}=*"
    ),
    re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*(?:password|passwd|pwd|"
        r"api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
        r"secret[_-]?access[_-]?key|session[_-]?token|token)"
        r"\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\b"
    ),
    re.compile(r"BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY"),
)


class PlannerError(Exception):
    """A user-actionable bounded-planner failure."""


@dataclass(frozen=True)
class Identity:
    role: str
    model: str
    effort: str
    verified: bool
    config_source: str


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    events: Path
    checkpoint: Path
    metadata: Path
    recovery: Path
    plan: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_create(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_secret_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def bounded_visible_text(text: str) -> str:
    if len(text) <= MAX_VISIBLE_OUTPUT_CHARS:
        return text
    return (
        text[:MAX_VISIBLE_OUTPUT_CHARS]
        + "\n\n[Partner truncated failure checkpoint at "
        + str(MAX_VISIBLE_OUTPUT_CHARS)
        + " characters.]\n"
    )


def section_bodies(text: str) -> Dict[str, str]:
    matches = list(re.finditer(r"(?m)^## ([^\n]+)\s*$", text))
    bodies: Dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        bodies[match.group(1).strip()] = text[match.end() : end].strip()
    return bodies


def validate_packet(text: str, max_input_chars: int) -> None:
    if not text.startswith(PACKET_TITLE + "\n"):
        raise PlannerError(f"packet must start with {PACKET_TITLE!r}")
    if "\x00" in text:
        raise PlannerError("packet contains a NUL byte")
    if max_input_chars < 1 or max_input_chars > ABSOLUTE_MAX_INPUT_CHARS:
        raise PlannerError(
            f"--max-input-chars must be between 1 and {ABSOLUTE_MAX_INPUT_CHARS}"
        )
    if len(text) > max_input_chars:
        raise PlannerError(
            f"packet has {len(text)} characters; limit is {max_input_chars}; "
            "reduce evidence explicitly instead of silently truncating"
        )
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise PlannerError(
                "packet contains secret-like text; replace it with a non-secret fact"
            )

    matches = list(re.finditer(r"(?m)^## ([^\n]+)\s*$", text))
    headings = tuple(match.group(1).strip() for match in matches)
    if headings != REQUIRED_SECTIONS:
        raise PlannerError(
            "packet sections must appear exactly in this order: "
            + ", ".join(REQUIRED_SECTIONS)
        )
    bodies = section_bodies(text)
    empty = [name for name in REQUIRED_SECTIONS if not bodies.get(name)]
    if empty:
        raise PlannerError(f"packet sections must not be empty: {', '.join(empty)}")
    truncation = bodies["Truncation"].splitlines()[0].strip().lower()
    if truncation != "none" and not truncation.startswith("present:"):
        raise PlannerError(
            "Truncation must begin with 'none' or 'present:' and name omitted evidence"
        )


def load_packet(path: Path, max_input_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PlannerError(f"cannot read packet {path}: {error}") from error
    validate_packet(text, max_input_chars)
    return text


def plan_validation_error(text: str) -> str:
    if len(text) > MAX_VISIBLE_OUTPUT_CHARS:
        return (
            f"Claude plan has {len(text)} characters; "
            f"limit is {MAX_VISIBLE_OUTPUT_CHARS}"
        )
    if not text.startswith(PLAN_TITLE + "\n"):
        return f"Claude plan must start with {PLAN_TITLE!r}"
    matches = list(re.finditer(r"(?m)^## ([^\n]+)\s*$", text))
    headings = []
    for match in matches:
        heading = match.group(1).strip()
        if re.fullmatch(r"Acceptance Checks(?:\s+\(binary\))?", heading):
            heading = "Acceptance Checks"
        headings.append(heading)
    if tuple(headings) != PLAN_REQUIRED_SECTIONS:
        return (
            "Claude plan sections must appear exactly in this order: "
            + ", ".join(PLAN_REQUIRED_SECTIONS)
        )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if not text[match.end() : end].strip():
            return f"Claude plan section is empty: {match.group(1).strip()}"
    return ""


def resolve_identity(
    repo: Path,
    host: str,
    role: str,
    env: Mapping[str, str],
    allow_unverified: bool,
) -> Identity:
    try:
        resolved = partner_config.resolve_config(repo, host, env=env)
    except partner_config.ConfigError as error:
        raise PlannerError(f"cannot resolve Partner config: {error}") from error
    values = (
        resolved.get("hosts", {})
        .get(host, {})
        .get("identities", {})
        .get(role)
    )
    if not values:
        raise PlannerError(
            f"{role} is not configured for host={host}; run 搭子，配置 first"
        )
    missing = [
        field
        for field in ("backend", "model", "effort")
        if not isinstance(values.get(field), str) or not values[field].strip()
    ]
    if missing:
        raise PlannerError(
            f"{role} config is missing required fields: {', '.join(missing)}"
        )
    if values["backend"] != "claude":
        raise PlannerError(
            f"{role} resolves to backend={values['backend']}; "
            "run-claude-plan.py never substitutes a Claude model"
        )
    verified = values.get("verified") is True
    if not verified and not allow_unverified:
        raise PlannerError(
            f"{role} is unverified; run 搭子，配置 smoke or pass "
            "--allow-unverified explicitly"
        )
    return Identity(
        role=role,
        model=values["model"],
        effort=values["effort"],
        verified=verified,
        config_source=resolved.get("source", "unknown"),
    )


def make_run_paths(repo: Path, run_id: str, output: Optional[Path]) -> RunPaths:
    run_dir = repo / ".partner" / "runs" / run_id
    plan = output if output is not None else repo / ".partner" / "plans" / f"{run_id}.md"
    return RunPaths(
        run_dir=run_dir,
        events=run_dir / "events.jsonl",
        checkpoint=run_dir / "checkpoint.md",
        metadata=run_dir / "metadata.json",
        recovery=run_dir / "recovery.md",
        plan=plan,
    )


def sanitize_event(payload: Mapping[str, Any]) -> Dict[str, Any]:
    event_type = str(payload.get("type", "unknown"))
    sanitized: Dict[str, Any] = {"recorded_at": utc_now(), "type": event_type}
    if event_type == "system":
        for field in ("subtype", "session_id", "model", "claude_code_version"):
            if payload.get(field) is not None:
                sanitized[field] = payload[field]
        tools = payload.get("tools")
        if isinstance(tools, list):
            sanitized["tool_count"] = len(tools)
    elif event_type == "stream_event":
        event = payload.get("event")
        if isinstance(event, Mapping):
            sanitized["event_type"] = event.get("type")
            delta = event.get("delta")
            if isinstance(delta, Mapping):
                sanitized["delta_type"] = delta.get("type")
                if delta.get("type") == "text_delta" and isinstance(
                    delta.get("text"), str
                ):
                    sanitized["text"] = redact_secret_text(delta["text"])
    elif event_type == "assistant":
        message = payload.get("message")
        if isinstance(message, Mapping):
            sanitized["model"] = message.get("model")
            sanitized["stop_reason"] = message.get("stop_reason")
            content = message.get("content")
            if isinstance(content, list):
                sanitized["content_types"] = [
                    item.get("type")
                    for item in content
                    if isinstance(item, Mapping) and item.get("type")
                ]
    elif event_type == "result":
        for field in (
            "subtype",
            "is_error",
            "api_error_status",
            "duration_ms",
            "duration_api_ms",
            "num_turns",
            "session_id",
            "total_cost_usd",
            "terminal_reason",
        ):
            if payload.get(field) is not None:
                sanitized[field] = payload[field]
        usage = payload.get("usage")
        if isinstance(usage, Mapping):
            sanitized["usage"] = {
                key: usage.get(key)
                for key in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                    "output_tokens",
                )
                if usage.get(key) is not None
            }
    return sanitized


def visible_text_delta(payload: Mapping[str, Any]) -> str:
    if payload.get("type") != "stream_event":
        return ""
    event = payload.get("event")
    if not isinstance(event, Mapping) or event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta")
    if not isinstance(delta, Mapping) or delta.get("type") != "text_delta":
        return ""
    text = delta.get("text")
    return text if isinstance(text, str) else ""


def visible_assistant_text(payload: Mapping[str, Any]) -> str:
    if payload.get("type") != "assistant":
        return ""
    message = payload.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, list):
        return ""
    return "".join(
        item.get("text", "")
        for item in content
        if isinstance(item, Mapping)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    )


def has_tool_use(payload: Mapping[str, Any]) -> bool:
    if payload.get("type") == "system":
        tools = payload.get("tools")
        if isinstance(tools, list) and tools:
            return True
    if payload.get("type") != "assistant":
        return False
    message = payload.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    return bool(
        isinstance(content, list)
        and any(
            isinstance(item, Mapping) and item.get("type") == "tool_use"
            for item in content
        )
    )


def result_text(payload: Optional[Mapping[str, Any]]) -> str:
    if not payload:
        return ""
    value = payload.get("result")
    return value.strip() if isinstance(value, str) else ""


def classify_result(
    result: Optional[Mapping[str, Any]],
    returncode: int,
    stderr: str,
    visible_output: str = "",
) -> Tuple[str, str]:
    nominal_success = bool(
        result and result.get("is_error") is not True and result_text(result)
    )
    if nominal_success and returncode == 0:
        return "success", ""
    if nominal_success:
        return (
            "protocol_error",
            f"Claude emitted a success result but exited {returncode}",
        )
    haystack = " ".join(
        str(value)
        for value in (
            result.get("subtype") if result else "",
            result.get("terminal_reason") if result else "",
            result.get("api_error_status") if result else "",
            stderr,
            visible_output,
        )
    ).lower()
    if "budget" in haystack:
        return "budget_exceeded", "Claude CLI stopped at --max-budget-usd"
    if "401" in haystack or "auth" in haystack or "login" in haystack:
        return "authentication", "Claude CLI authentication failed"
    if "idle" in haystack:
        return "upstream_idle", "Claude API reported an idle stream"
    if result and result.get("is_error") is True:
        return "claude_error", f"Claude result subtype={result.get('subtype', 'unknown')}"
    return "protocol_error", f"Claude exited {returncode} without a non-empty result"


def planning_prompt(packet: str, resume: bool) -> str:
    if resume:
        return (
            "Continue the bounded planning turn already stored in this session. "
            "Do not use tools or agents. Start visible output with "
            "'# Plan Checkpoint', then return only the final Markdown plan with "
            "Goal, Non-goals, Current-State Evidence, File Scope, Steps, Risks, "
            "binary Acceptance Checks, and Rollback."
        )
    return (
        "You are Partner's bounded Deep Reasoner. The outer Codex host already "
        "collected the repository evidence below. Do not use tools, agents, web, "
        "or unstated facts. Start visible output with '# Plan Checkpoint', then "
        "return a concise Markdown plan containing Goal, Non-goals, Current-State "
        "Evidence, File Scope, Steps, Risks, binary Acceptance Checks, and "
        "Rollback. If evidence is insufficient, name the exact missing evidence "
        "instead of exploring.\n\n"
        + packet
    )


def claude_command(
    claude_bin: str,
    identity: Identity,
    args: argparse.Namespace,
    session_id: str,
) -> List[str]:
    command = [
        claude_bin,
        "--print",
        "--safe-mode",
        "--no-chrome",
        "--tools",
        "",
        "--permission-mode",
        "plan",
        "--model",
        identity.model,
        "--effort",
        identity.effort,
        "--max-budget-usd",
        str(args.max_budget_usd),
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]
    if args.resume_session:
        command.extend(("--resume", args.resume_session))
    else:
        command.extend(("--session-id", session_id, "--name", f"partner-{args.run_id}"))
    return command


def process_group_exists(process: subprocess.Popen[Any]) -> bool:
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False


def terminate(process: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return
    deadline = time.monotonic() + PROCESS_TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline:
        process.poll()
        if not process_group_exists(process):
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=DRAIN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=DRAIN_TIMEOUT_SECONDS)


def write_recovery(
    paths: RunPaths,
    args: argparse.Namespace,
    session_id: str,
    session_observed: bool,
    failure_kind: str,
    detail: str,
) -> None:
    command = [
        "python3",
        str(SCRIPT_DIR / "run-claude-plan.py"),
        "--repo",
        str(args.repo),
        "--host",
        args.host,
        "--role",
        args.role,
        "--packet",
        str(args.packet),
        "--resume-session",
        session_id,
        "--wall-timeout-seconds",
        str(args.wall_timeout_seconds),
        "--idle-timeout-seconds",
        str(args.idle_timeout_seconds),
        "--max-budget-usd",
        str(args.max_budget_usd),
    ]
    if args.allow_unverified:
        command.append("--allow-unverified")
    text = (
        "# Partner bounded-plan recovery\n\n"
        f"- failure: `{failure_kind}`\n"
        f"- detail: {detail}\n"
        f"- session_id: `{session_id}`\n"
        f"- session observed from Claude CLI: "
        f"`{'true' if session_observed else 'false'}`\n"
        "- automatic model fallback: disabled\n\n"
        + (
            "Resume the same configured model/session:\n\n"
            if session_observed
            else (
                "Claude CLI did not emit a session event before failure. The "
                "same-session command below is an exact recovery attempt, but "
                "the upstream session may not have been persisted.\n\n"
            )
        )
        + "```bash\n"
        + " ".join(shlex.quote(part) for part in command)
        + "\n```\n\n"
        "To use another configured role, obtain explicit user approval and rerun "
        "with `--role <approved-role>`. Partner never substitutes it automatically.\n"
    )
    atomic_write(paths.recovery, text)


def write_metadata(path: Path, metadata: Mapping[str, Any]) -> None:
    atomic_write(path, json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def run_planner(
    args: argparse.Namespace,
    identity: Identity,
    packet: str,
    claude_bin: str,
    env: Mapping[str, str],
) -> int:
    paths = make_run_paths(args.repo, args.run_id, args.output)
    session_id = args.resume_session or str(uuid.uuid4())
    prompt = planning_prompt(packet, bool(args.resume_session))
    command = claude_command(claude_bin, identity, args, session_id)
    runner_sha256 = sha256_file(Path(__file__).resolve())

    if args.dry_run:
        print(f"run_id={args.run_id}")
        print(f"role={identity.role}")
        print(f"model={identity.model}")
        print(f"effort={identity.effort}")
        print(f"verified={'true' if identity.verified else 'false'}")
        print(f"config_source={identity.config_source}")
        print(f"packet_chars={len(packet)}")
        print(f"packet_sha256={sha256_text(packet)}")
        print(f"runner_sha256={runner_sha256}")
        print("tools=disabled")
        print("safe_mode=true")
        print(f"wall_timeout_seconds={args.wall_timeout_seconds:g}")
        print(f"idle_timeout_seconds={args.idle_timeout_seconds:g}")
        print(f"max_budget_usd={args.max_budget_usd:g}")
        return 0

    paths.run_dir.mkdir(parents=True, exist_ok=False)
    paths.plan.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        paths.checkpoint,
        "# Partial planning checkpoint\n\nNo visible text received yet.\n",
    )
    started_at = utc_now()
    started = time.monotonic()
    last_stream_event = started
    failure_kind = ""
    failure_detail = ""
    result: Optional[Mapping[str, Any]] = None
    stderr_tail = ""
    checkpoint_text = ""
    latest_assistant_text = ""
    session_observed = False
    observed_session_ids: List[str] = []
    observed_models: List[str] = []
    returncode = -1

    with paths.events.open("w", encoding="utf-8") as event_log:
        initial_event = (
            json.dumps(
                {
                    "recorded_at": started_at,
                    "type": "partner_init",
                    "run_id": args.run_id,
                    "session_id": session_id,
                    "role": identity.role,
                    "model": identity.model,
                    "effort": identity.effort,
                    "packet_chars": len(packet),
                    "packet_sha256": sha256_text(packet),
                    "runner_sha256": runner_sha256,
                    "tools": "disabled",
                    "safe_mode": True,
                    "max_budget_usd": args.max_budget_usd,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        event_log.write(initial_event)
        event_log.flush()
        event_log_bytes = len(initial_event.encode("utf-8"))
        process = subprocess.Popen(
            command,
            cwd=args.repo,
            env=clean_claude_env(env),
            text=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        selector = selectors.DefaultSelector()
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stderr.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        prompt_bytes = prompt.encode("utf-8")
        prompt_offset = 0
        drain_deadline: Optional[float] = None

        def stop_for_failure(kind: str, detail: str) -> None:
            nonlocal failure_kind, failure_detail, drain_deadline
            if failure_kind:
                return
            failure_kind = kind
            failure_detail = detail
            terminate(process)
            drain_deadline = time.monotonic() + DRAIN_TIMEOUT_SECONDS

        def write_event(payload: Mapping[str, Any]) -> bool:
            nonlocal event_log_bytes
            serialized = json.dumps(payload, ensure_ascii=False) + "\n"
            encoded_size = len(serialized.encode("utf-8"))
            if event_log_bytes + encoded_size > MAX_EVENT_LOG_BYTES:
                stop_for_failure(
                    "protocol_error",
                    f"sanitized event log exceeded {MAX_EVENT_LOG_BYTES} bytes",
                )
                return False
            event_log.write(serialized)
            event_log.flush()
            event_log_bytes += encoded_size
            return True

        def handle_line(stream_name: str, raw_line: bytes) -> None:
            nonlocal result, latest_assistant_text, session_observed, drain_deadline
            nonlocal stderr_tail, checkpoint_text, last_stream_event
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r")
            if stream_name == "stderr":
                stderr_tail = (stderr_tail + line + "\n")[-4000:]
                return
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                write_event(
                    {
                        "recorded_at": utc_now(),
                        "type": "invalid_json",
                        "line_length": len(line),
                    }
                )
                stop_for_failure(
                    "protocol_error", "Claude emitted non-JSON stream output"
                )
                return
            if not isinstance(payload, Mapping):
                write_event(
                    {
                        "recorded_at": utc_now(),
                        "type": "invalid_event",
                        "json_type": type(payload).__name__,
                    }
                )
                stop_for_failure(
                    "protocol_error",
                    "Claude stream event must be a JSON object",
                )
                return
            event_type = payload.get("type")
            if event_type not in STREAM_EVENT_TYPES:
                write_event(
                    {
                        "recorded_at": utc_now(),
                        "type": "invalid_event",
                        "event_type": (
                            event_type if isinstance(event_type, str) else None
                        ),
                    }
                )
                stop_for_failure(
                    "protocol_error",
                    "Claude stream event has a missing or unsupported type",
                )
                return
            last_stream_event = time.monotonic()
            sanitized = sanitize_event(payload)
            if not write_event(sanitized):
                return
            observed_session_id = payload.get("session_id")
            if isinstance(observed_session_id, str):
                session_observed = True
                if observed_session_id not in observed_session_ids:
                    observed_session_ids.append(observed_session_id)
            observed_model = payload.get("model")
            if (
                payload.get("type") == "system"
                and isinstance(observed_model, str)
                and observed_model not in observed_models
            ):
                observed_models.append(observed_model)
            delta = visible_text_delta(payload)
            if delta:
                if len(checkpoint_text) + len(delta) > MAX_VISIBLE_OUTPUT_CHARS:
                    stop_for_failure(
                        "protocol_error",
                        f"visible checkpoint exceeded "
                        f"{MAX_VISIBLE_OUTPUT_CHARS} characters",
                    )
                    return
                checkpoint_text += delta
                atomic_write(paths.checkpoint, checkpoint_text)
            assistant_text = visible_assistant_text(payload)
            if assistant_text:
                if len(assistant_text) > MAX_VISIBLE_OUTPUT_CHARS:
                    stop_for_failure(
                        "protocol_error",
                        f"visible assistant output exceeded "
                        f"{MAX_VISIBLE_OUTPUT_CHARS} characters",
                    )
                    return
                latest_assistant_text = assistant_text
            if has_tool_use(payload):
                stop_for_failure(
                    "tool_use_violation",
                    "Claude exposed or attempted a tool in bounded mode",
                )
            if payload.get("type") == "result":
                result = payload
                if drain_deadline is None:
                    drain_deadline = time.monotonic() + DRAIN_TIMEOUT_SECONDS

        def flush_complete_lines(stream_name: str) -> None:
            buffer = buffers[stream_name]
            while True:
                newline = buffer.find(b"\n")
                if newline < 0:
                    return
                raw_line = bytes(buffer[:newline])
                del buffer[: newline + 1]
                handle_line(stream_name, raw_line)

        def close_stream(stream: Any, stream_name: str) -> None:
            buffer = buffers[stream_name]
            if buffer:
                handle_line(stream_name, bytes(buffer))
                buffer.clear()
            try:
                selector.unregister(stream)
            except KeyError:
                pass
            stream.close()

        def close_stdin() -> None:
            try:
                selector.unregister(process.stdin)
            except KeyError:
                pass
            try:
                process.stdin.close()
            except OSError:
                pass

        try:
            while selector.get_map():
                now = time.monotonic()
                if not failure_kind and now - started > args.wall_timeout_seconds:
                    stop_for_failure(
                        "wall_timeout",
                        f"wall time exceeded {args.wall_timeout_seconds:g} seconds"
                    )
                elif (
                    not failure_kind
                    and now - last_stream_event > args.idle_timeout_seconds
                ):
                    stop_for_failure(
                        "idle_timeout",
                        f"no Claude stream event for "
                        f"{args.idle_timeout_seconds:g} seconds",
                    )
                if drain_deadline is not None and now >= drain_deadline:
                    for key in list(selector.get_map().values()):
                        if key.data == "stdin":
                            close_stdin()
                        else:
                            close_stream(key.fileobj, key.data)
                    break

                for key, _ in selector.select(timeout=0.1):
                    if key.data == "stdin":
                        try:
                            written = os.write(
                                process.stdin.fileno(),
                                prompt_bytes[prompt_offset:],
                            )
                        except BlockingIOError:
                            continue
                        except (BrokenPipeError, OSError) as error:
                            close_stdin()
                            stop_for_failure(
                                "protocol_error",
                                "Claude closed stdin before accepting the "
                                f"planning prompt: {error}",
                            )
                            continue
                        prompt_offset += written
                        if prompt_offset == len(prompt_bytes):
                            close_stdin()
                        continue
                    stream = key.fileobj
                    try:
                        chunk = os.read(stream.fileno(), READ_CHUNK_BYTES)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        close_stream(stream, key.data)
                        continue
                    buffers[key.data].extend(chunk)
                    if len(buffers[key.data]) > MAX_STREAM_BUFFER_BYTES:
                        buffers[key.data].clear()
                        stop_for_failure(
                            "protocol_error",
                            f"{key.data} line exceeded "
                            f"{MAX_STREAM_BUFFER_BYTES} bytes",
                        )
                        continue
                    flush_complete_lines(key.data)
                if process.poll() is not None and drain_deadline is None:
                    drain_deadline = time.monotonic() + DRAIN_TIMEOUT_SECONDS
            if process.poll() is None:
                try:
                    returncode = process.wait(timeout=DRAIN_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    stop_for_failure(
                        "protocol_error",
                        "Claude closed stdout and stderr before exiting",
                    )
                    returncode = process.wait()
            else:
                returncode = process.wait()
        finally:
            selector.close()
            terminate(process)

    raw_stderr = stderr_tail.strip()
    if not failure_kind:
        failure_kind, failure_detail = classify_result(
            result, returncode, raw_stderr, latest_assistant_text
        )
    plan = result_text(result)
    if failure_kind == "success":
        if not session_observed:
            failure_kind = "protocol_error"
            failure_detail = "Claude reported success without a session id"
        elif any(value != session_id for value in observed_session_ids):
            failure_kind = "protocol_error"
            failure_detail = (
                "Claude reported a session id different from the requested session"
            )
        elif identity.model not in observed_models:
            failure_kind = "protocol_error"
            failure_detail = (
                "Claude reported success without the exact configured model"
            )
        else:
            plan_error = plan_validation_error(plan)
            if plan_error:
                failure_kind = "protocol_error"
                failure_detail = plan_error
    if failure_kind == "success":
        try:
            atomic_create(paths.plan, plan + "\n")
        except FileExistsError:
            failure_kind = "protocol_error"
            failure_detail = f"refusing to overwrite existing plan: {paths.plan}"
        except OSError as error:
            failure_kind = "protocol_error"
            failure_detail = f"cannot create plan atomically: {error}"
    succeeded = failure_kind == "success"
    stderr = redact_secret_text(raw_stderr)
    metadata: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": args.run_id,
        "status": "success" if succeeded else "failed",
        "failure_kind": None if succeeded else failure_kind,
        "failure_detail": None if succeeded else failure_detail,
        "started_at": started_at,
        "finished_at": utc_now(),
        "wall_elapsed_seconds": round(time.monotonic() - started, 3),
        "session_id": (result or {}).get("session_id", session_id),
        "requested_session_id": session_id,
        "session_observed": session_observed,
        "observed_session_ids": observed_session_ids,
        "role": identity.role,
        "model": identity.model,
        "observed_models": observed_models,
        "effort": identity.effort,
        "verified": identity.verified,
        "allow_unverified": args.allow_unverified,
        "config_source": identity.config_source,
        "packet_chars": len(packet),
        "packet_sha256": sha256_text(packet),
        "runner_sha256": runner_sha256,
        "tools": "disabled",
        "safe_mode": True,
        "wall_timeout_seconds": args.wall_timeout_seconds,
        "idle_timeout_seconds": args.idle_timeout_seconds,
        "max_budget_usd": args.max_budget_usd,
        "budget_enforced_by": "claude_cli",
        "max_stream_buffer_bytes": MAX_STREAM_BUFFER_BYTES,
        "max_visible_output_chars": MAX_VISIBLE_OUTPUT_CHARS,
        "max_event_log_bytes": MAX_EVENT_LOG_BYTES,
        "event_log_bytes": event_log_bytes,
        "total_cost_usd": (result or {}).get("total_cost_usd"),
        "num_turns": (result or {}).get("num_turns"),
        "returncode": returncode,
        "events_path": str(paths.events),
        "checkpoint_path": str(paths.checkpoint),
        "plan_path": str(paths.plan) if succeeded else None,
        "recovery_path": None if succeeded else str(paths.recovery),
        "stderr_tail": stderr or None,
    }
    if succeeded:
        atomic_write(paths.checkpoint, plan + "\n")
    else:
        if latest_assistant_text and not checkpoint_text:
            atomic_write(
                paths.checkpoint,
                bounded_visible_text(latest_assistant_text) + "\n",
            )
        elif plan and not checkpoint_text:
            atomic_write(paths.checkpoint, bounded_visible_text(plan) + "\n")
        elif not checkpoint_text:
            atomic_write(
                paths.checkpoint,
                "# Partial planning checkpoint\n\n"
                "No visible text was received before the run failed.\n",
            )
        write_recovery(
            paths,
            args,
            metadata["session_id"],
            session_observed,
            failure_kind,
            failure_detail,
        )
    write_metadata(paths.metadata, metadata)

    print(f"status={metadata['status']}")
    print(f"run_id={args.run_id}")
    print(f"session_id={metadata['session_id']}")
    print(f"model={identity.model}")
    print(f"effort={identity.effort}")
    print(f"events={paths.events}")
    print(f"checkpoint={paths.checkpoint}")
    print(f"metadata={paths.metadata}")
    if succeeded:
        print(f"plan={paths.plan}")
        if metadata["total_cost_usd"] is not None:
            print(f"total_cost_usd={metadata['total_cost_usd']}")
        return 0
    print(f"failure_kind={failure_kind}")
    print(f"recovery={paths.recovery}")
    if stderr:
        print(f"claude_error={stderr}", file=sys.stderr)
    return 4


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def budget_float(value: str) -> float:
    parsed = positive_float(value)
    if parsed > 10:
        raise argparse.ArgumentTypeError("must be at most 10 USD")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded, tool-free Claude planning turn from Partner config."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--host", choices=partner_config.HOSTS, default="codex")
    parser.add_argument(
        "--role", choices=partner_config.IDENTITIES, default="deep_reasoner"
    )
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-session")
    parser.add_argument(
        "--max-input-chars", type=int, default=DEFAULT_MAX_INPUT_CHARS
    )
    parser.add_argument(
        "--wall-timeout-seconds",
        type=positive_float,
        default=DEFAULT_WALL_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--idle-timeout-seconds",
        type=positive_float,
        default=DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--max-budget-usd", type=budget_float, default=DEFAULT_MAX_BUDGET_USD
    )
    parser.add_argument("--allow-unverified", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--claude-bin",
        help="Claude binary override; PARTNER_CLAUDE_BIN is checked next.",
    )
    return parser


def default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"bounded-plan-{stamp}-{uuid.uuid4().hex[:8]}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.repo = args.repo.resolve()
    args.packet = args.packet.resolve()
    if args.output is not None:
        args.output = args.output.resolve()
    args.run_id = args.run_id or default_run_id()
    if not RUN_ID_RE.fullmatch(args.run_id):
        print(
            "error: --run-id must match [A-Za-z0-9][A-Za-z0-9._-]{0,79}",
            file=sys.stderr,
        )
        return 2
    if args.resume_session:
        try:
            uuid.UUID(args.resume_session)
        except ValueError:
            print("error: --resume-session must be a UUID", file=sys.stderr)
            return 2
    if not args.repo.is_dir():
        print(f"error: repo is not a directory: {args.repo}", file=sys.stderr)
        return 2
    try:
        packet = load_packet(args.packet, args.max_input_chars)
        identity = resolve_identity(
            args.repo,
            args.host,
            args.role,
            os.environ,
            args.allow_unverified,
        )
        claude_bin = (
            args.claude_bin
            or os.environ.get("PARTNER_CLAUDE_BIN")
            or shutil.which("claude")
        )
        if not claude_bin:
            raise PlannerError(
                "Claude CLI not found; set PARTNER_CLAUDE_BIN or install Claude Code"
            )
        if not args.dry_run and (args.repo / ".partner" / "runs" / args.run_id).exists():
            raise PlannerError(f"run already exists: {args.run_id}")
        if not args.dry_run:
            output_path = make_run_paths(args.repo, args.run_id, args.output).plan
            if output_path.exists():
                raise PlannerError(f"refusing to overwrite existing plan: {output_path}")
        return run_planner(args, identity, packet, claude_bin, os.environ)
    except (PlannerError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

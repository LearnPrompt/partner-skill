#!/usr/bin/env bash
set -euo pipefail

# delegate-codex.sh — Claude-driven Partner delegation primitive.
#
# Wraps `codex exec --json` as background jobs with durable state under
# <repo>/.partner/jobs/<jobId>/ so a Claude Code session (or a /loop tick)
# can submit work to Codex, poll it, collect the result, and send follow-up
# fix rounds against the same Codex session.
#
# Job directory layout:
#   prompt.md    the exact prompt sent to codex exec
#   run.sh       the command actually executed (audit trail)
#   log.jsonl    codex exec --json event stream
#   stderr.log   codex stderr (tokens, warnings, auth errors)
#   pid          background worker pid
#   exit_code    written when the worker finishes
#   session_id   codex thread/session id, extracted from log.jsonl
#   meta         label, effort, mode, parent job, timestamps

usage() {
  cat <<'USAGE'
delegate-codex.sh — background Codex jobs for the Claude-driven Partner flow

Usage:
  delegate-codex.sh submit --repo <path> --prompt-file <file>
                    [--label <name>] [--effort minimal|low|medium|high|xhigh]
                    [--model <model>] [--role deep_reasoner|fast_worker]
                    [--read-only] [--dry-run]
  delegate-codex.sh status <jobId> --repo <path> [--wait] [--timeout <seconds>]
  delegate-codex.sh result <jobId> --repo <path> [--json]
  delegate-codex.sh resume <jobId> --repo <path> --prompt-file <file> [--read-only]
  delegate-codex.sh cancel <jobId> --repo <path>
  delegate-codex.sh list   --repo <path>

Defaults: --effort high (Partner default for delegated work), read-write
sandbox per the user's codex config. Use --read-only for review/adversarial
jobs that must not touch the repo.

Exit codes: status prints RUNNING/DONE/FAILED/CANCELLED; `status --wait`
returns non-zero on timeout or failure so callers can branch on it.
USAGE
}

JOBS_SUBDIR=".partner/jobs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_repo() {
  [ -n "${REPO:-}" ] || die "--repo is required"
  [ -d "$REPO" ] || die "repo not found: $REPO"
  REPO="$(cd "$REPO" && pwd)"
}

job_dir() {
  echo "$REPO/$JOBS_SUBDIR/$1"
}

require_job() {
  JOB="$(job_dir "$1")"
  [ -d "$JOB" ] || die "job not found: $1 (looked in $REPO/$JOBS_SUBDIR)"
}

now_utc() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

make_job_id() {
  local label="$1"
  printf 'job-%s-%s-%s-%s\n' "$(date +%Y%m%d%H%M%S)" "$$" "$RANDOM" "${label:-task}"
}

kill_tree() {
  local pid="$1"
  local child
  local children
  if command -v pgrep >/dev/null 2>&1; then
    children="$(pgrep -P "$pid" 2>/dev/null || true)"
  else
    children="$(ps -o pid= -P "$pid" 2>/dev/null || true)"
  fi
  for child in $children; do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

job_state() {
  # Prints RUNNING | DONE | FAILED | CANCELLED for $JOB.
  if [ -f "$JOB/cancelled" ]; then
    echo "CANCELLED"
  elif [ -f "$JOB/exit_code" ]; then
    if [ "$(cat "$JOB/exit_code")" = "0" ]; then echo "DONE"; else echo "FAILED"; fi
  elif [ -f "$JOB/pid" ] && kill -0 "$(cat "$JOB/pid")" 2>/dev/null; then
    echo "RUNNING"
  else
    # Worker died without writing exit_code (crash, reboot).
    echo "FAILED"
  fi
}

extract_session_id() {
  # Best-effort session/thread id from the JSONL stream; caches into session_id.
  if [ -s "$JOB/session_id" ]; then
    cat "$JOB/session_id"
    return 0
  fi
  python3 - "$JOB/log.jsonl" <<'PY' | tee "$JOB/session_id"
import json, sys
sid = ""
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("thread_id", "session_id"):
                found = event.get(key) or (event.get("thread") or {}).get("id")
                if found:
                    sid = found
            if sid:
                break
except FileNotFoundError:
    pass
print(sid)
PY
}

cmd_submit() {
  local PROMPT_FILE="" LABEL="task" EFFORT="high" MODEL="" ROLE="" READ_ONLY="false" DRY_RUN="false"
  local EFFORT_EXPLICIT="false" MODEL_EXPLICIT="false"
  local EFFORT_SOURCE="default" MODEL_SOURCE="default"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo) REPO="${2:-}"; shift 2 ;;
      --prompt-file) PROMPT_FILE="${2:-}"; shift 2 ;;
      --label) LABEL="${2:-}"; shift 2 ;;
      --effort) EFFORT="${2:-}"; EFFORT_EXPLICIT="true"; shift 2 ;;
      --model) MODEL="${2:-}"; MODEL_EXPLICIT="true"; shift 2 ;;
      --role) ROLE="${2:-}"; shift 2 ;;
      --read-only) READ_ONLY="true"; shift ;;
      --dry-run) DRY_RUN="true"; shift ;;
      *) die "unknown submit argument: $1" ;;
    esac
  done
  require_repo
  [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ] || die "--prompt-file is required and must exist"
  case "$ROLE" in ""|deep_reasoner|fast_worker) ;; *) die "invalid --role: $ROLE" ;; esac

  if [ -n "$ROLE" ]; then
    local CONFIG_JSON CONFIG_SOURCE ROLE_MODEL ROLE_EFFORT
    if ! CONFIG_JSON="$(python3 "$SCRIPT_DIR/partner-config.py" --host codex --repo "$REPO" resolve)"; then
      die "failed to resolve Codex role config; run 'python3 scripts/partner-config.py --host codex init' and then 'set --role $ROLE --model <model> --effort <effort>'"
    fi
    CONFIG_SOURCE="$(printf '%s' "$CONFIG_JSON" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("source", ""))')" || die "invalid JSON from partner-config.py resolve"
    ROLE_MODEL="$(printf '%s' "$CONFIG_JSON" | python3 -c 'import json, sys; role = sys.argv[1]; print(json.load(sys.stdin).get("hosts", {}).get("codex", {}).get("roles", {}).get(role, {}).get("model", ""))' "$ROLE")" || die "invalid JSON from partner-config.py resolve"
    ROLE_EFFORT="$(printf '%s' "$CONFIG_JSON" | python3 -c 'import json, sys; role = sys.argv[1]; print(json.load(sys.stdin).get("hosts", {}).get("codex", {}).get("roles", {}).get(role, {}).get("effort", ""))' "$ROLE")" || die "invalid JSON from partner-config.py resolve"
    if [ -z "$ROLE_MODEL" ] || [ -z "$ROLE_EFFORT" ]; then
      die "Codex role '$ROLE' is missing model or effort; run 'python3 scripts/partner-config.py --host codex init' and then 'set --role $ROLE --model <model> --effort <effort>'"
    fi
    if [ "$MODEL_EXPLICIT" = "false" ]; then
      MODEL="$ROLE_MODEL"
      MODEL_SOURCE="config:$CONFIG_SOURCE"
    fi
    if [ "$EFFORT_EXPLICIT" = "false" ]; then
      EFFORT="$ROLE_EFFORT"
      EFFORT_SOURCE="config:$CONFIG_SOURCE"
    fi
  fi
  [ "$MODEL_EXPLICIT" = "false" ] || MODEL_SOURCE="explicit"
  [ "$EFFORT_EXPLICIT" = "false" ] || EFFORT_SOURCE="explicit"
  case "$EFFORT" in minimal|low|medium|high|xhigh) ;; *) die "invalid --effort: $EFFORT" ;; esac

  LABEL="$(echo "$LABEL" | tr -cs 'A-Za-z0-9_-' '-' | sed 's/^-//;s/-$//')"
  if [ "$DRY_RUN" = "true" ]; then
    printf 'role=%s\nmodel=%s\neffort=%s\nmodel_source=%s\neffort_source=%s\n' \
      "${ROLE:-none}" "${MODEL:-default}" "$EFFORT" "$MODEL_SOURCE" "$EFFORT_SOURCE"
    return 0
  fi
  command -v codex >/dev/null 2>&1 || die "codex CLI not found on PATH"
  local JOB_ID
  JOB_ID="$(make_job_id "$LABEL")"
  JOB="$(job_dir "$JOB_ID")"
  [ -e "$JOB" ] && die "job dir already exists: $JOB"
  mkdir -p "$JOB"
  cp "$PROMPT_FILE" "$JOB/prompt.md"

  {
    printf 'label=%s\neffort=%s\nmodel=%s\nrole=%s\nmodel_source=%s\neffort_source=%s\nread_only=%s\nsubmitted_at=%s\nmode=fresh\n' \
      "$LABEL" "$EFFORT" "${MODEL:-default}" "${ROLE:-none}" "$MODEL_SOURCE" "$EFFORT_SOURCE" "$READ_ONLY" "$(now_utc)"
  } >"$JOB/meta"

  write_run_script "$JOB" "$EFFORT" "$MODEL" "$READ_ONLY" ""
  launch_job "$JOB"
  echo "$JOB_ID"
}

cmd_resume() {
  local PARENT_ID="$1"; shift
  local PROMPT_FILE="" READ_ONLY="false"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo) REPO="${2:-}"; shift 2 ;;
      --prompt-file) PROMPT_FILE="${2:-}"; shift 2 ;;
      --read-only) READ_ONLY="true"; shift ;;
      *) die "unknown resume argument: $1" ;;
    esac
  done
  require_repo
  require_job "$PARENT_ID"
  [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ] || die "--prompt-file is required and must exist"
  [ "$(job_state)" = "RUNNING" ] && die "parent job still running; wait or cancel first"

  local PARENT_JOB="$JOB"
  local SESSION_ID
  SESSION_ID="$(extract_session_id)"
  [ -n "$SESSION_ID" ] || die "no session id found in $PARENT_JOB/log.jsonl; cannot resume"

  local EFFORT
  EFFORT="$(sed -n 's/^effort=//p' "$PARENT_JOB/meta")"
  local ROUND=2
  case "$PARENT_ID" in *-r[0-9]*) ROUND=$(( ${PARENT_ID##*-r} + 1 )) ;; esac
  local JOB_ID="${PARENT_ID%-r[0-9]*}-r${ROUND}"
  JOB="$(job_dir "$JOB_ID")"
  [ -e "$JOB" ] && die "job dir already exists: $JOB"
  mkdir -p "$JOB"
  cp "$PROMPT_FILE" "$JOB/prompt.md"
  printf '%s' "$SESSION_ID" >"$JOB/session_id"

  {
    printf 'label=resume\neffort=%s\nmodel=inherit\nread_only=%s\nsubmitted_at=%s\nmode=resume\nparent=%s\n' \
      "${EFFORT:-high}" "$READ_ONLY" "$(now_utc)" "$PARENT_ID"
  } >"$JOB/meta"

  write_run_script "$JOB" "${EFFORT:-high}" "" "$READ_ONLY" "$SESSION_ID"
  launch_job "$JOB"
  echo "$JOB_ID"
}

write_run_script() {
  local job="$1" effort="$2" model="$3" read_only="$4" session_id="$5"
  {
    echo '#!/usr/bin/env bash'
    echo 'set -uo pipefail'
    printf 'JOB=%q\n' "$job"
    printf 'REPO=%q\n' "$REPO"
    echo 'PROMPT="$(cat "$JOB/prompt.md")"'
    if [ -n "$session_id" ]; then
      # `codex exec resume` accepts no -C/-s flags: cwd comes from the shell,
      # sandbox and effort go through -c config overrides.
      local args="--json -c 'model_reasoning_effort=\"$effort\"'"
      [ "$read_only" = "true" ] && args="$args -c 'sandbox_mode=\"read-only\"'"
      echo 'cd "$REPO"'
      printf 'codex exec resume %q "$PROMPT" %s >"$JOB/log.jsonl" 2>"$JOB/stderr.log"\n' "$session_id" "$args"
    else
      local args="--json -C \"\$REPO\" -c 'model_reasoning_effort=\"$effort\"'"
      [ -n "$model" ] && args="$args -m \"$model\""
      [ "$read_only" = "true" ] && args="$args -s read-only"
      printf 'codex exec "$PROMPT" %s >"$JOB/log.jsonl" 2>"$JOB/stderr.log"\n' "$args"
    fi
    echo 'echo $? >"$JOB/exit_code"'
  } >"$job/run.sh"
  chmod +x "$job/run.sh"
}

launch_job() {
  local job="$1"
  nohup bash "$job/run.sh" >/dev/null 2>&1 &
  echo $! >"$job/pid"
  disown || true
}

cmd_status() {
  local JOB_ID="$1"; shift
  local WAIT="false" TIMEOUT=1800
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo) REPO="${2:-}"; shift 2 ;;
      --wait) WAIT="true"; shift ;;
      --timeout) TIMEOUT="${2:-}"; shift 2 ;;
      *) die "unknown status argument: $1" ;;
    esac
  done
  require_repo
  require_job "$JOB_ID"

  local state elapsed=0
  state="$(job_state)"
  if [ "$WAIT" = "true" ]; then
    while [ "$state" = "RUNNING" ] && [ "$elapsed" -lt "$TIMEOUT" ]; do
      sleep 10
      elapsed=$((elapsed + 10))
      state="$(job_state)"
    done
  fi

  local last_event=""
  if [ -s "$JOB/log.jsonl" ]; then
    last_event="$(tail -1 "$JOB/log.jsonl" | python3 -c 'import json,sys
try: print(json.loads(sys.stdin.read()).get("type",""))
except Exception: print("")' 2>/dev/null || true)"
  fi
  echo "job: $JOB_ID"
  echo "state: $state"
  echo "last_event: ${last_event:-none}"
  echo "log: $JOB/log.jsonl"
  if [ "$state" = "RUNNING" ] && [ "$WAIT" = "true" ]; then
    echo "note: timed out after ${TIMEOUT}s while still running"
    return 2
  fi
  [ "$state" = "DONE" ] || [ "$state" = "RUNNING" ]
}

cmd_result() {
  local JOB_ID="$1"; shift
  local AS_JSON="false"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo) REPO="${2:-}"; shift 2 ;;
      --json) AS_JSON="true"; shift ;;
      *) die "unknown result argument: $1" ;;
    esac
  done
  require_repo
  require_job "$JOB_ID"
  extract_session_id >/dev/null || true

  python3 - "$JOB/log.jsonl" "$JOB/session_id" "$AS_JSON" <<'PY'
import json, sys

log_path, sid_path, as_json = sys.argv[1], sys.argv[2], sys.argv[3] == "true"
messages, commands, reasoning, usage = [], [], [], {}
try:
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type", "")
            item = event.get("item") or {}
            itype = item.get("type") or item.get("item_type") or ""
            if etype == "item.completed":
                text = item.get("text") or item.get("content") or ""
                if itype == "agent_message" and text:
                    messages.append(text)
                elif itype == "reasoning" and text:
                    reasoning.append(text)
                elif itype == "command_execution":
                    commands.append(item.get("command", ""))
            elif etype == "turn.completed":
                usage = event.get("usage") or {}
except FileNotFoundError:
    print("ERROR: no log.jsonl for this job", file=sys.stderr)
    sys.exit(1)

try:
    session_id = open(sid_path, encoding="utf-8").read().strip()
except FileNotFoundError:
    session_id = ""

if as_json:
    print(json.dumps({
        "session_id": session_id,
        "agent_message": messages[-1] if messages else "",
        "commands": [c for c in commands if c],
        "usage": usage,
    }, ensure_ascii=False))
else:
    print(f"session_id: {session_id or 'unknown'}")
    if usage:
        print(f"usage: {json.dumps(usage)}")
    if commands:
        print(f"commands_run: {len(commands)}")
    print("--- agent message ---")
    print(messages[-1] if messages else "(no agent_message found — check stderr.log)")
PY
}

cmd_cancel() {
  local JOB_ID="$1"; shift
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo) REPO="${2:-}"; shift 2 ;;
      *) die "unknown cancel argument: $1" ;;
    esac
  done
  require_repo
  require_job "$JOB_ID"
  if [ -f "$JOB/pid" ]; then
    kill_tree "$(cat "$JOB/pid")"
  fi
  touch "$JOB/cancelled"
  echo "cancelled: $JOB_ID"
}

cmd_list() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo) REPO="${2:-}"; shift 2 ;;
      *) die "unknown list argument: $1" ;;
    esac
  done
  require_repo
  local base="$REPO/$JOBS_SUBDIR"
  [ -d "$base" ] || { echo "(no jobs)"; return 0; }
  local found="false"
  for dir in "$base"/job-*; do
    [ -d "$dir" ] || continue
    found="true"
    JOB="$dir"
    printf '%-40s %s\n' "$(basename "$dir")" "$(job_state)"
  done
  [ "$found" = "true" ] || echo "(no jobs)"
}

[ "$#" -ge 1 ] || { usage; exit 2; }
COMMAND="$1"; shift
REPO="${REPO:-}"

case "$COMMAND" in
  submit) cmd_submit "$@" ;;
  status|result|resume|cancel)
    [ "$#" -ge 1 ] || die "$COMMAND requires a jobId"
    JOB_ID_ARG="$1"; shift
    "cmd_$COMMAND" "$JOB_ID_ARG" "$@"
    ;;
  list) cmd_list "$@" ;;
  -h|--help|help) usage ;;
  *) usage; die "unknown command: $COMMAND" ;;
esac

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
                    [--model <model>] [--role deep_reasoner|fast_worker|arbiter]
                    [--host claude_code|codex]
                    [--read-only] [--dry-run]
  delegate-codex.sh status <jobId> --repo <path> [--wait] [--timeout <seconds>]
  delegate-codex.sh result <jobId> --repo <path> [--json]
  delegate-codex.sh resume <jobId> --repo <path> --prompt-file <file> [--read-only]
  delegate-codex.sh cancel <jobId> --repo <path>
  delegate-codex.sh list   --repo <path>

Defaults: --effort high (Partner default for delegated work), read-write
sandbox per the user's codex config. Use --read-only for review/adversarial
jobs that must not touch the repo. --host selects the identity routing table;
identities with backend=claude must be spawned as host subagents.

Codex binary: set PARTNER_CODEX_BIN to an executable path or command name to
override discovery. On macOS the ChatGPT/Codex app-bundled CLI is preferred
when present so app-only models use a compatible client; otherwise PATH is used.

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

is_git_repo() {
  # `codex exec` refuses to run outside a trusted (git) directory unless
  # --skip-git-repo-check is passed. Detect via rev-parse rather than a
  # bare `-d "$1/.git"` check so worktrees/submodules (where .git is a
  # file, not a directory) are still recognized as git repos.
  git -C "$1" rev-parse --git-dir >/dev/null 2>&1
}

resolve_codex_bin() {
  local configured="${PARTNER_CODEX_BIN:-}"
  local candidate=""

  CODEX_BIN_SOURCE="path"
  if [ -n "$configured" ]; then
    CODEX_BIN_SOURCE="env"
    if [[ "$configured" == */* ]]; then
      candidate="$configured"
    else
      candidate="$(command -v "$configured" 2>/dev/null || true)"
    fi
    [ -n "$candidate" ] && [ -x "$candidate" ] || die "PARTNER_CODEX_BIN is not executable: $configured"
  elif [ "$(uname -s)" = "Darwin" ]; then
    for candidate in "/Applications/ChatGPT.app/Contents/Resources/codex" "/Applications/Codex.app/Contents/Resources/codex"; do
      if [ -x "$candidate" ]; then
        CODEX_BIN_SOURCE="app"
        break
      fi
      candidate=""
    done
  fi

  if [ -z "$candidate" ]; then
    candidate="$(command -v codex 2>/dev/null || true)"
    CODEX_BIN_SOURCE="path"
  fi
  [ -n "$candidate" ] && [ -x "$candidate" ] || die "codex CLI not found; install it or set PARTNER_CODEX_BIN"

  CODEX_BIN="$candidate"
  CODEX_VERSION="$("$CODEX_BIN" --version 2>/dev/null | head -1 || true)"
  CODEX_VERSION="${CODEX_VERSION:-unknown}"
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
  local PROMPT_FILE="" LABEL="task" EFFORT="high" MODEL="" ROLE="" CONFIG_HOST="codex" READ_ONLY="false" DRY_RUN="false"
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
      --host) CONFIG_HOST="${2:-}"; shift 2 ;;
      --read-only) READ_ONLY="true"; shift ;;
      --dry-run) DRY_RUN="true"; shift ;;
      *) die "unknown submit argument: $1" ;;
    esac
  done
  require_repo
  [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ] || die "--prompt-file is required and must exist"
  case "$ROLE" in ""|deep_reasoner|fast_worker|arbiter) ;; *) die "invalid --role: $ROLE" ;; esac
  case "$CONFIG_HOST" in claude_code|codex) ;; *) die "invalid --host: $CONFIG_HOST" ;; esac

  if [ -n "$ROLE" ]; then
    local CONFIG_JSON CONFIG_SOURCE ROLE_BACKEND ROLE_MODEL ROLE_EFFORT
    if ! CONFIG_JSON="$(python3 "$SCRIPT_DIR/partner-config.py" --host "$CONFIG_HOST" --repo "$REPO" resolve)"; then
      die "failed to resolve Codex identity config; run 'python3 scripts/partner-config.py --host $CONFIG_HOST init' and then 'set --role $ROLE --backend codex --model <model> --effort <effort>'"
    fi
    CONFIG_SOURCE="$(printf '%s' "$CONFIG_JSON" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("source", ""))')" || die "invalid JSON from partner-config.py resolve"
    ROLE_BACKEND="$(printf '%s' "$CONFIG_JSON" | python3 -c 'import json, sys; host, role = sys.argv[1:]; print(json.load(sys.stdin).get("hosts", {}).get(host, {}).get("identities", {}).get(role, {}).get("backend", ""))' "$CONFIG_HOST" "$ROLE")" || die "invalid JSON from partner-config.py resolve"
    ROLE_MODEL="$(printf '%s' "$CONFIG_JSON" | python3 -c 'import json, sys; host, role = sys.argv[1:]; print(json.load(sys.stdin).get("hosts", {}).get(host, {}).get("identities", {}).get(role, {}).get("model", ""))' "$CONFIG_HOST" "$ROLE")" || die "invalid JSON from partner-config.py resolve"
    ROLE_EFFORT="$(printf '%s' "$CONFIG_JSON" | python3 -c 'import json, sys; host, role = sys.argv[1:]; print(json.load(sys.stdin).get("hosts", {}).get(host, {}).get("identities", {}).get(role, {}).get("effort", ""))' "$CONFIG_HOST" "$ROLE")" || die "invalid JSON from partner-config.py resolve"
    if [ -z "$ROLE_BACKEND" ] || [ -z "$ROLE_MODEL" ] || [ -z "$ROLE_EFFORT" ]; then
      die "Codex identity '$ROLE' is missing backend, model, or effort; run 'python3 scripts/partner-config.py --host $CONFIG_HOST init' and then 'set --role $ROLE --backend codex --model <model> --effort <effort>'"
    fi
    if [ "$ROLE_BACKEND" != "codex" ]; then
      die "identity $ROLE is configured as backend=$ROLE_BACKEND; spawn partner-$ROLE subagent inside the host instead of delegating to Codex"
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
  resolve_codex_bin

  LABEL="$(echo "$LABEL" | tr -cs 'A-Za-z0-9_-' '-' | sed 's/^-//;s/-$//')"
  if [ "$DRY_RUN" = "true" ]; then
    local SKIP_GIT_REPO_CHECK=""
    is_git_repo "$REPO" || SKIP_GIT_REPO_CHECK="--skip-git-repo-check"
    printf 'role=%s\nbackend=codex\nconfig_host=%s\nmodel=%s\neffort=%s\nmodel_source=%s\neffort_source=%s\ncodex_bin=%s\ncodex_bin_source=%s\ncodex_version=%s\nskip_git_repo_check=%s\n' \
      "${ROLE:-none}" "$CONFIG_HOST" "${MODEL:-default}" "$EFFORT" "$MODEL_SOURCE" "$EFFORT_SOURCE" \
      "$CODEX_BIN" "$CODEX_BIN_SOURCE" "$CODEX_VERSION" "$SKIP_GIT_REPO_CHECK"
    return 0
  fi
  local JOB_ID
  JOB_ID="$(make_job_id "$LABEL")"
  JOB="$(job_dir "$JOB_ID")"
  [ -e "$JOB" ] && die "job dir already exists: $JOB"
  mkdir -p "$JOB"
  cp "$PROMPT_FILE" "$JOB/prompt.md"

  {
    printf 'label=%s\neffort=%s\nmodel=%s\nrole=%s\nbackend=codex\nconfig_host=%s\nmodel_source=%s\neffort_source=%s\ncodex_bin=%s\ncodex_bin_source=%s\ncodex_version=%s\nread_only=%s\nsubmitted_at=%s\nmode=fresh\n' \
      "$LABEL" "$EFFORT" "${MODEL:-default}" "${ROLE:-none}" "$CONFIG_HOST" "$MODEL_SOURCE" "$EFFORT_SOURCE" \
      "$CODEX_BIN" "$CODEX_BIN_SOURCE" "$CODEX_VERSION" "$READ_ONLY" "$(now_utc)"
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
  CODEX_BIN="$(sed -n 's/^codex_bin=//p' "$PARENT_JOB/meta")"
  if [ -n "$CODEX_BIN" ] && [ -x "$CODEX_BIN" ]; then
    CODEX_BIN_SOURCE="parent"
    CODEX_VERSION="$("$CODEX_BIN" --version 2>/dev/null | head -1 || true)"
    CODEX_VERSION="${CODEX_VERSION:-unknown}"
  else
    resolve_codex_bin
  fi
  local ROUND=2
  case "$PARENT_ID" in *-r[0-9]*) ROUND=$(( ${PARENT_ID##*-r} + 1 )) ;; esac
  local JOB_ID="${PARENT_ID%-r[0-9]*}-r${ROUND}"
  JOB="$(job_dir "$JOB_ID")"
  [ -e "$JOB" ] && die "job dir already exists: $JOB"
  mkdir -p "$JOB"
  cp "$PROMPT_FILE" "$JOB/prompt.md"
  printf '%s' "$SESSION_ID" >"$JOB/session_id"

  {
    printf 'label=resume\neffort=%s\nmodel=inherit\ncodex_bin=%s\ncodex_bin_source=%s\ncodex_version=%s\nread_only=%s\nsubmitted_at=%s\nmode=resume\nparent=%s\n' \
      "${EFFORT:-high}" "$CODEX_BIN" "$CODEX_BIN_SOURCE" "$CODEX_VERSION" "$READ_ONLY" "$(now_utc)" "$PARENT_ID"
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
    printf 'CODEX_BIN=%q\n' "$CODEX_BIN"
    echo 'PROMPT="$(cat "$JOB/prompt.md")"'
    # </dev/null: a long prompt can make codex exec also wait on stdin for
    # more input ("Reading additional input from stdin..."); the background
    # job's stdin is never closed on its own, so without this the job hangs
    # forever with no further JSONL events.
    if [ -n "$session_id" ]; then
      # `codex exec resume` accepts no -C/-s flags: cwd comes from the shell,
      # sandbox and effort go through -c config overrides.
      local args="--json -c 'model_reasoning_effort=\"$effort\"'"
      [ "$read_only" = "true" ] && args="$args -c 'sandbox_mode=\"read-only\"'"
      echo 'cd "$REPO"'
      printf '"$CODEX_BIN" exec resume %q "$PROMPT" %s >"$JOB/log.jsonl" 2>"$JOB/stderr.log" </dev/null\n' "$session_id" "$args"
    else
      local args="--json -C \"\$REPO\" -c 'model_reasoning_effort=\"$effort\"'"
      # Non-git --repo targets need --skip-git-repo-check or codex exec
      # refuses to run ("Not inside a trusted directory").
      is_git_repo "$REPO" || args="$args --skip-git-repo-check"
      [ -n "$model" ] && args="$args -m \"$model\""
      [ "$read_only" = "true" ] && args="$args -s read-only"
      printf '"$CODEX_BIN" exec "$PROMPT" %s >"$JOB/log.jsonl" 2>"$JOB/stderr.log" </dev/null\n' "$args"
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

#!/usr/bin/env bash

set -u
set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETUP="$ROOT/scripts/partner-setup.py"
CONFIG="$ROOT/scripts/partner-config.py"
PASS_COUNT=0
FAIL_COUNT=0
SCRATCH_DIRS=()
TMP_BASE="${TMPDIR:-/tmp}"
TMP_BASE="${TMP_BASE%/}"

cleanup() {
  local scratch
  for scratch in "${SCRATCH_DIRS[@]}"; do
    case "$scratch" in
      "$TMP_BASE"/partner-sandbox.*) rm -rf -- "$scratch" ;;
    esac
  done
}
trap cleanup EXIT

run_setup() {
  local scratch="$1"
  local log="$2"
  shift 2
  env \
    HOME="$scratch/home" \
    XDG_CONFIG_HOME="$scratch/xdg" \
    CODEX_HOME="$scratch/codex" \
    PATH="$scratch/bin:$PATH" \
    python3 "$SETUP" "$@" >"$log" 2>&1
}

prepare_scratch() {
  local scratch="$1"
  local backend
  mkdir -p "$scratch/repo" "$scratch/home" "$scratch/xdg" "$scratch/codex" "$scratch/bin" || return 1
  for backend in claude codex; do
    printf '#!/usr/bin/env bash\nexit 0\n' >"$scratch/bin/$backend" || return 1
    chmod +x "$scratch/bin/$backend" || return 1
  done
  export HOME="$scratch/home"
  export XDG_CONFIG_HOME="$scratch/xdg"
  export CODEX_HOME="$scratch/codex"
}

extract_host_sections() {
  local config_path="$1"
  local host="$2"
  local output_path="$3"
  python3 - "$CONFIG" "$config_path" "$host" >"$output_path" <<'PY'
import importlib.util
import sys

script_path, config_path, host = sys.argv[1:]
spec = importlib.util.spec_from_file_location("partner_config", script_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {script_path}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
with open(config_path, "r", encoding="utf-8", newline="") as handle:
    text = handle.read()
prefix = f"hosts.{host}.identities."
for chunk in module.split_sections(text):
    if chunk.name and chunk.name.startswith(prefix):
        sys.stdout.buffer.write(chunk.text.encode("utf-8"))
PY
}

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib
import sys

with open(sys.argv[1], "rb") as handle:
    print(hashlib.sha256(handle.read()).hexdigest())
PY
}

setup_claude() {
  local scratch="$1"
  local log="$2"
  run_setup "$scratch" "$log" \
    --apply --host claude_code --repo "$scratch/repo" \
    --mode balanced --exclude-choice track \
    --role-model deep_reasoner=gpt-test \
    --role-model fast_worker=gpt-test \
    --role-model arbiter=gpt-test
}

setup_codex() {
  local scratch="$1"
  local log="$2"
  run_setup "$scratch" "$log" \
    --apply --host codex --repo "$scratch/repo" \
    --mode balanced --exclude-choice track \
    --role-model deep_reasoner=gpt-test \
    --role-model fast_worker=gpt-test \
    --role-model arbiter=gpt-test
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    printf 'missing expected file: %s\n' "$path"
    return 1
  fi
}

compare_sha() {
  local label="$1"
  local expected="$2"
  local path="$3"
  local actual
  actual="$(sha256_file "$path")" || return 1
  if [[ "$actual" != "$expected" ]]; then
    printf '%s sha256 changed: before=%s after=%s\n' "$label" "$expected" "$actual"
    return 1
  fi
}

scenario_claude_then_codex() {
  local scratch="$1"
  local repo="$scratch/repo"
  local config="$repo/.partner/config.toml"
  local deep_agent="$repo/.claude/agents/partner-deep-reasoner.md"
  local deep_sha

  prepare_scratch "$scratch" || {
    printf 'could not prepare isolated environment: %s\n' "$scratch"
    return 1
  }
  if ! setup_claude "$scratch" "$scratch/claude.log"; then
    printf 'Claude setup failed\n'
    sed 's/^/  /' "$scratch/claude.log"
    return 1
  fi
  require_file "$config" && require_file "$deep_agent" || return 1
  extract_host_sections "$config" claude_code "$scratch/claude.before" || return 1
  if [[ ! -s "$scratch/claude.before" ]]; then
    printf 'no hosts.claude_code.identities sections found\n'
    return 1
  fi
  deep_sha="$(sha256_file "$deep_agent")" || return 1

  if ! setup_codex "$scratch" "$scratch/codex.log"; then
    printf 'Codex setup failed\n'
    sed 's/^/  /' "$scratch/codex.log"
    return 1
  fi
  extract_host_sections "$config" claude_code "$scratch/claude.after" || return 1
  if ! cmp -s "$scratch/claude.before" "$scratch/claude.after"; then
    printf 'hosts.claude_code.identities sections changed:\n'
    diff -u "$scratch/claude.before" "$scratch/claude.after" || true
    return 1
  fi
  compare_sha "partner-deep-reasoner.md" "$deep_sha" "$deep_agent" || return 1
}

scenario_codex_then_claude() {
  local scratch="$1"
  local repo="$scratch/repo"
  local config="$repo/.partner/config.toml"

  prepare_scratch "$scratch" || {
    printf 'could not prepare isolated environment: %s\n' "$scratch"
    return 1
  }
  if ! setup_codex "$scratch" "$scratch/codex.log"; then
    printf 'Codex setup failed\n'
    sed 's/^/  /' "$scratch/codex.log"
    return 1
  fi
  require_file "$config" || return 1
  extract_host_sections "$config" codex "$scratch/codex.before" || return 1
  if [[ ! -s "$scratch/codex.before" ]]; then
    printf 'no hosts.codex.identities sections found\n'
    return 1
  fi

  if ! setup_claude "$scratch" "$scratch/claude.log"; then
    printf 'Claude setup failed\n'
    sed 's/^/  /' "$scratch/claude.log"
    return 1
  fi
  extract_host_sections "$config" codex "$scratch/codex.after" || return 1
  if ! cmp -s "$scratch/codex.before" "$scratch/codex.after"; then
    printf 'hosts.codex.identities sections changed:\n'
    diff -u "$scratch/codex.before" "$scratch/codex.after" || true
    return 1
  fi
}

scenario_idempotent_rerun() {
  local scratch="$1"
  local repo="$scratch/repo"
  local config="$repo/.partner/config.toml"
  local deep_agent="$repo/.claude/agents/partner-deep-reasoner.md"
  local path label before

  prepare_scratch "$scratch" || {
    printf 'could not prepare isolated environment: %s\n' "$scratch"
    return 1
  }
  if ! setup_claude "$scratch" "$scratch/first.log"; then
    printf 'first Claude setup failed\n'
    sed 's/^/  /' "$scratch/first.log"
    return 1
  fi
  require_file "$config" && require_file "$deep_agent" || return 1
  cp "$config" "$scratch/config.before"
  cp "$deep_agent" "$scratch/deep.before"

  if ! setup_claude "$scratch" "$scratch/second.log"; then
    printf 'second Claude setup failed\n'
    sed 's/^/  /' "$scratch/second.log"
    return 1
  fi
  for path in "$config" "$deep_agent"; do
    case "$path" in
      "$config") label="config.toml"; before="$scratch/config.before" ;;
      *) label="partner-deep-reasoner.md"; before="$scratch/deep.before" ;;
    esac
    if ! cmp -s "$before" "$path"; then
      printf '%s changed on identical re-apply: before=%s after=%s\n' \
        "$label" "$(sha256_file "$before")" "$(sha256_file "$path")"
      return 1
    fi
  done
}

scenario_invalid_role_effort() {
  local scratch="$1"
  local config="$scratch/repo/.partner/config.toml"

  prepare_scratch "$scratch" || {
    printf 'could not prepare isolated environment: %s\n' "$scratch"
    return 1
  }
  if run_setup "$scratch" "$scratch/invalid.log" \
    --apply --host claude_code --repo "$scratch/repo" \
    --mode balanced --exclude-choice track \
    --role-model deep_reasoner=gpt-test \
    --role-model fast_worker=gpt-test \
    --role-model arbiter=gpt-test \
    --role-effort deep_reasoner=invalid; then
    printf 'invalid --role-effort unexpectedly exited zero\n'
    return 1
  fi
  if [[ -e "$config" ]]; then
    printf 'config was written after invalid --role-effort: %s\n' "$config"
    return 1
  fi
}

run_scenario() {
  local name="$1"
  local function_name="$2"
  local scratch detail status

  scratch="$(mktemp -d "$TMP_BASE/partner-sandbox.XXXXXX")" || {
    printf 'FAIL %s: could not create scratch directory\n' "$name"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    return
  }
  SCRATCH_DIRS[${#SCRATCH_DIRS[@]}]="$scratch"
  detail="$("$function_name" "$scratch" 2>&1)"
  status=$?
  if [[ $status -eq 0 ]]; then
    printf 'PASS %s\n' "$name"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    printf 'FAIL %s: %s\n' "$name" "$detail"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

run_scenario "Claude then Codex" scenario_claude_then_codex
run_scenario "Codex then Claude" scenario_codex_then_claude
run_scenario "Idempotent rerun" scenario_idempotent_rerun
run_scenario "Invalid role effort" scenario_invalid_role_effort

printf 'SUMMARY pass=%d fail=%d\n' "$PASS_COUNT" "$FAIL_COUNT"
if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
fi

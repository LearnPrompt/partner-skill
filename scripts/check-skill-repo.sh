#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

SCAN_TMP="$(mktemp)"
trap 'rm -f "$SCAN_TMP"' EXIT

fail=0
warn=0

check_file() {
  local file="$1"
  if [ -f "$file" ]; then
    echo "PASS file $file"
  else
    echo "FAIL missing $file"
    fail=$((fail + 1))
  fi
}

check_dir() {
  local dir="$1"
  if [ -d "$dir" ]; then
    echo "PASS dir  $dir"
  else
    echo "WARN missing dir $dir"
    warn=$((warn + 1))
  fi
}

check_file "SKILL.md"
check_file "README.md"
check_file "README.en.md"
check_file "test-prompts.json"
check_file "install.sh"
check_file "LICENSE"
check_file "examples/showcase-cost-ledger.json"
check_file "docs/showcase-cost-model.md"
check_file "docs/receipt-schema.json"
check_file "examples/session-receipt.md"
check_file "references/monitoring.md"
check_file "references/handoff-template.md"
check_file "references/failure-playbook.md"
check_file "references/scenarios.md"
check_file "references/darwin-ratchet.md"
check_file "scripts/check-claude-cli.sh"
check_file "scripts/make-handoff.sh"
check_file "scripts/make-receipt.py"
check_file "scripts/session-snapshot.sh"
check_file "scripts/validate-receipt.py"
check_file "scripts/run-test-prompts.py"
check_dir "references"
check_dir "examples"
check_dir "scripts"

python3 scripts/check-readme-parity.py
echo "PASS README parity gate"

if python3 scripts/validate-receipt.py examples/session-receipt.md >/dev/null; then
  echo "PASS example receipt validates against receipt contract"
else
  echo "FAIL examples/session-receipt.md does not validate; run scripts/validate-receipt.py on it"
  fail=$((fail + 1))
fi

# The receipt template block is duplicated across three files by design
# (SKILL.md is the contract; the references repeat it for locality). Any
# field change must land in all three, so drift is a FAIL, not a WARN.
if python3 - <<'PY'
import re
import sys

paths = ["SKILL.md", "references/monitoring.md", "references/handoff-template.md"]
blocks = []
for path in paths:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    start = text.find("[Partner session receipt]")
    if start < 0:
        print(f"missing receipt template in {path}")
        sys.exit(1)
    lines = []
    for line in text[start:].splitlines()[1:]:
        line = line.strip()
        if not re.match(r"^[a-z_]+:", line):
            break
        lines.append(line)
    blocks.append((path, lines))

base_path, base_lines = blocks[0]
drift = False
for path, lines in blocks[1:]:
    if lines != base_lines:
        drift = True
        print(f"receipt template drift: {path} differs from {base_path}")
        for a, b in zip(base_lines, lines):
            if a != b:
                print(f"  {base_path}: {a}")
                print(f"  {path}: {b}")
sys.exit(1 if drift else 0)
PY
then
  echo "PASS receipt template consistent across SKILL.md and references"
else
  echo "FAIL receipt template blocks have drifted"
  fail=$((fail + 1))
fi

if python3 scripts/run-test-prompts.py >/dev/null; then
  echo "PASS test-prompts static regression checks"
else
  echo "FAIL scripts/run-test-prompts.py static checks"
  fail=$((fail + 1))
fi

if command -v jq >/dev/null 2>&1; then
  jq -e 'type == "array" and length >= 4 and all(.[]; has("id") and has("prompt") and has("expected_behavior") and has("must_not"))' test-prompts.json >/dev/null
  echo "PASS test-prompts.json schema"
  if jq -e '[.[] | (.expected_behavior[]?, .prompt)] | map(select(test("git reset --hard|rm -rf|force push|--force"))) | length == 0' test-prompts.json >/dev/null; then
    echo "PASS test-prompts risky text confined to must_not"
  else
    echo "FAIL test-prompts.json has risky command text outside must_not"
    fail=$((fail + 1))
  fi
else
  if python3 - <<'PY'
import json
import sys

with open("test-prompts.json", encoding="utf-8") as handle:
    data = json.load(handle)

required = {"id", "prompt", "expected_behavior", "must_not"}
ok = (
    isinstance(data, list)
    and len(data) >= 4
    and all(isinstance(entry, dict) and required <= set(entry) for entry in data)
)
sys.exit(0 if ok else 1)
PY
  then
    echo "PASS test-prompts.json schema (python3 fallback)"
  else
    echo "FAIL test-prompts.json schema (python3 fallback)"
    fail=$((fail + 1))
  fi
fi

if grep -q '^name: partner-skill$' SKILL.md; then
  echo "PASS SKILL.md name"
else
  echo "FAIL SKILL.md frontmatter name must be partner-skill"
  fail=$((fail + 1))
fi

if grep -qE '^version: [0-9]+\.[0-9]+\.[0-9]+$' SKILL.md; then
  echo "PASS SKILL.md version"
else
  echo "FAIL SKILL.md frontmatter must declare a semantic version"
  fail=$((fail + 1))
fi

if grep -qF '"搭子"' SKILL.md; then
  echo "PASS SKILL.md bare 搭子 trigger"
else
  echo "FAIL SKILL.md description must include bare \"搭子\" as a trigger"
  fail=$((fail + 1))
fi

if grep -qF '搭子.skill' README.md && grep -qF '我的 Claude Code 和 Codex 天下第一好' README.md; then
  echo "PASS README identity"
else
  echo "FAIL README must include Partner identity and slogan"
  fail=$((fail + 1))
fi

if grep -qF 'README.en.md' README.md && grep -qF 'README.md' README.en.md; then
  echo "PASS README language split"
else
  echo "FAIL README.md and README.en.md must link to each other"
  fail=$((fail + 1))
fi

if grep -qF 'docs/showcase-cost-model.md' README.md && \
  grep -qF 'docs/showcase-cost-model.md' README.en.md; then
  echo "PASS docs entrypoints"
else
  echo "FAIL README files must link the cost model doc"
  fail=$((fail + 1))
fi

if grep -qF 'Showcase 正在重做' README.md && grep -qF 'showcase is being redesigned' README.en.md; then
  echo "PASS showcase placeholder"
elif [ -f assets/showcase.gif ] && grep -qF 'assets/showcase.gif' README.md && grep -qF 'assets/showcase.gif' README.en.md; then
  echo "PASS showcase asset (gif)"
elif [ -f assets/showcase.png ] && grep -qF 'assets/showcase.png' README.md && grep -qF 'assets/showcase.png' README.en.md; then
  echo "PASS showcase asset"
else
  echo "FAIL README files must have a showcase placeholder or a valid showcase asset"
  fail=$((fail + 1))
fi

if [ -s examples/showcase-cost-ledger.json ] && \
  grep -qF 'examples/showcase-cost-ledger.json' README.md && \
  grep -qF 'examples/showcase-cost-ledger.json' README.en.md; then
  echo "PASS showcase cost ledger"
else
  echo "FAIL showcase cost ledger must exist and be linked from both README files"
  fail=$((fail + 1))
fi

if grep -qF 'Partner Session Receipt' SKILL.md && \
  grep -qF 'new_claude_p_sessions' SKILL.md && \
  grep -qF 'monitoring_level' SKILL.md && \
  grep -qF 'Partner Session Receipt' README.md && \
  grep -qF 'session-receipt-required' test-prompts.json; then
  echo "PASS Partner Session Receipt contract"
else
  echo "FAIL Partner Session Receipt contract must be present in SKILL.md, README.md, and test-prompts.json"
  fail=$((fail + 1))
fi

if find . -path './.git' -prune -o -type f \( -name '.env' -o -name '.env.*' \) -print | grep -q .; then
  echo "FAIL .env-like files are tracked or present in the package tree"
  fail=$((fail + 1))
elif grep -RInE 'gho_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|BEGIN (RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}' \
  --exclude-dir='.git' \
  --exclude='check-skill-repo.sh' \
  . >"$SCAN_TMP"; then
  echo "FAIL possible secret-like text:"
  cat "$SCAN_TMP"
  fail=$((fail + 1))
else
  echo "PASS secret scan"
fi

# High-risk command text is allowed only in prohibition context (safety
# boundaries that forbid the command) or on lines annotated with risk-ok.
# test-prompts.json is checked structurally above: risky text must stay
# inside must_not arrays.
if grep -RInE 'git reset --hard|rm -rf|force push|--force' \
  --exclude-dir='.git' \
  --exclude='check-skill-repo.sh' \
  --exclude='test-prompts.json' \
  . \
  | grep -vE 'risk-ok|[Dd]o not|not \`|不要|不用|不默认|避免|禁止' \
  >"$SCAN_TMP"; then
  echo "WARN high-risk command text found:"
  cat "$SCAN_TMP"
  warn=$((warn + 1))
else
  echo "PASS high-risk command scan"
fi

echo "SUMMARY fail=$fail warn=$warn"
[ "$fail" -eq 0 ]

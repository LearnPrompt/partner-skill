#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

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
check_file "test-prompts.json"
check_file "install.sh"
check_file "LICENSE"
check_dir "references"
check_dir "examples"
check_dir "scripts"

if command -v jq >/dev/null 2>&1; then
  jq -e 'type == "array" and length >= 4 and all(.[]; has("id") and has("prompt") and has("expected_behavior") and has("must_not"))' test-prompts.json >/dev/null
  echo "PASS test-prompts.json schema"
else
  echo "WARN jq not found; skipped test-prompts schema check"
  warn=$((warn + 1))
fi

if grep -q '^name: partner-skill$' SKILL.md; then
  echo "PASS SKILL.md name"
else
  echo "FAIL SKILL.md frontmatter name must be partner-skill"
  fail=$((fail + 1))
fi

if grep -q '搭子.skill' README.md && grep -q '我的 Claude Code 和 Codex 天下第一好' README.md; then
  echo "PASS README identity"
else
  echo "FAIL README must include Partner identity and slogan"
  fail=$((fail + 1))
fi

if find . -path './.git' -prune -o -type f \( -name '.env' -o -name '.env.*' \) -print | grep -q .; then
  echo "FAIL .env-like files are tracked or present in the package tree"
  fail=$((fail + 1))
elif grep -RInE 'gho_[A-Za-z0-9_]+|BEGIN (RSA|OPENSSH|PRIVATE) KEY|sk-[A-Za-z0-9_-]{20,}' \
  --exclude-dir='.git' \
  --exclude='check-skill-repo.sh' \
  . >/tmp/partner-skill-secret-scan.txt; then
  echo "FAIL possible secret-like text:"
  cat /tmp/partner-skill-secret-scan.txt
  fail=$((fail + 1))
else
  echo "PASS secret scan"
fi

if grep -RInE 'git reset --hard|rm -rf|force push|--force' \
  --exclude-dir='.git' \
  --exclude='darwin-ratchet.md' \
  --exclude='check-skill-repo.sh' \
  . >/tmp/partner-skill-risk-scan.txt; then
  echo "WARN high-risk command text found:"
  cat /tmp/partner-skill-risk-scan.txt
  warn=$((warn + 1))
else
  echo "PASS high-risk command scan"
fi

echo "SUMMARY fail=$fail warn=$warn"
[ "$fail" -eq 0 ]

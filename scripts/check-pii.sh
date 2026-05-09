#!/usr/bin/env bash
# Repo-wide PII grep guard.
#
# Run before commit / in CI. Catches:
#   - Real strength FIT date filenames (YYYY-MM-DD pattern)
#   - Personal Garmin paths (Archer, garmin/activities)
#   - Real-year datetime literals in examples (must use year=2000 for synthetic)
#   - Real-year ISO date strings in docs/ and tests/ (must use year=2000)
#
# Synthetic generators live in examples/synthetic_*.py and must use
# datetime(2000, ...) per V2.18 / T-FIT-1 determinism guard.

set -euo pipefail

cd "$(dirname "$0")/.."

EXCLUDES=(
  --exclude-dir=.git
  --exclude-dir=.venv
  --exclude-dir=venv
  --exclude-dir=__pycache__
  --exclude-dir=node_modules
  --exclude-dir=.pytest_cache
  --exclude-dir=.ruff_cache
  --exclude-dir=.mypy_cache
  --exclude=*.lock
  --exclude=LICENSE
)

fail=0

# Real-year dated FIT filenames (any month — spring-only was too narrow)
if grep -rEn "${EXCLUDES[@]}" '[0-9]{4}-(0[1-9]|1[0-2])-[0-9]{2}\.(fit|FIT)' . 2>/dev/null; then
  echo "PII: real-year dated FIT filenames found"
  fail=1
fi

# Personal Garmin paths (any home subdir, allow digits/underscores/hyphens in usernames)
if grep -rEn "${EXCLUDES[@]}" '/home/[a-zA-Z0-9_-]+/(Archer|garmin)' . 2>/dev/null; then
  echo "PII: personal Garmin paths leaked"
  fail=1
fi

# Real-year datetime literals in examples/ (synthetic must use year=2000)
if [ -d examples ] && grep -rEn "${EXCLUDES[@]}" 'datetime\(202[0-9]' examples/ 2>/dev/null; then
  echo "PII: real-year datetime in examples/ (synthetic must use year=2000)"
  fail=1
fi

# Real-year ISO date strings in docs/ and tests/ (year 2000 only).
# CHANGELOG.md / TODOS.md / pyproject.toml live at repo root and may
# legitimately reference release dates; this rule covers the artifacts
# most likely to leak per-night PII via the cross-file join rule.
for d in docs tests; do
  if [ -d "$d" ] && grep -rEn "${EXCLUDES[@]}" \
      --include='*.md' --include='*.py' \
      '\b20[1-9][0-9]-(0[1-9]|1[0-2])-[0-3][0-9]\b' "$d" 2>/dev/null; then
    echo "PII: real-year ISO date string in $d/ (synthetic must use year=2000)"
    fail=1
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "PII grep clean"
fi

exit "$fail"

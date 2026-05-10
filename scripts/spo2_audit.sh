#!/usr/bin/env bash
# SpO2 sentinel audit for v0.3.1 (issue #10 P7 follow-up).
#
# Scans `*-spo2.csv` from parse_daily_fit's per-day output and prints any
# row where `spo2_percent` is <= 0 — the sentinel regime that mirrors the
# `respiration_rate = -1` and `hr_bpm = 0` patterns v0.3.1 already filters.
#
# Why a script and not an inline filter: the SpO2 sentinel pattern has not
# been observed in user archive at v0.3.1 ship time; per Approach D in
# TODOS.md the filter generalization waits until the first hit. Run this
# pre-PR so the v0.3.1 CHANGELOG can record an empirical "checked: N hits"
# rather than a speculative claim.
#
# Usage:
#   scripts/spo2_audit.sh [path/to/daily/]
#   # default search path: garmin/timeseries/daily/
#
# Output:
#   zero lines        — clean (no sentinels under the search path)
#   FILE:ROW: <row>   — one line per hit (header skipped)
#
# Exit:
#   0  — script ran
#   1  — no *-spo2.csv files found (likely wrong path)

set -eu

DIR="${1:-garmin/timeseries/daily}"

if [ ! -d "$DIR" ]; then
  echo "spo2_audit: directory not found: $DIR" >&2
  echo "  pass an explicit path, e.g. scripts/spo2_audit.sh /path/to/daily/" >&2
  exit 1
fi

found=0
# `FNR>1` is per-file (not per-stream) so multi-file invocations skip each
# file's header. Header-name lookup avoids the original audit script's
# silently-wrong assumption that spo2_percent lives in column 2.
while IFS= read -r f; do
  found=1
  awk -F, '
    FNR == 1 {
      c = 0
      for (i = 1; i <= NF; i++) if ($i == "spo2_percent") c = i
      next
    }
    c && $c != "" && $c + 0 <= 0 {
      print FILENAME ":" FNR ": " $0
    }
  ' "$f"
done < <(find "$DIR" -type f -name "*-spo2.csv" | sort)

if [ "$found" = "0" ]; then
  echo "spo2_audit: no *-spo2.csv files found under $DIR" >&2
  exit 1
fi

#!/usr/bin/env python3
"""Reproduce the transition-vs-official validation table.

Walks `--daily-dir` for `*-sleep-levels.csv`, pairs each with the matching
row in `--sleep-official`, computes naive + smart per-stage ratios, and
emits a markdown summary at `--out`.

Anyone with their own daily/ directory + sleep-official.csv can re-run
this to check whether the package's documented warnings hold on their
device and sleep profile.

PII / commit safety:
    Outlier rows default to `night_N` IDs (1-based row order). Pass
    `--show-dates` to substitute real dates back in for local audit only.
    Never commit a docs/sleep-validation.md generated with --show-dates
    per CLAUDE.md cross-file join rule.

Usage:
    python scripts/sleep_transition_vs_official.py \\
        --daily-dir garmin/timeseries/daily \\
        --sleep-official garmin/timeseries/history/sleep-official.csv \\
        --out docs/sleep-validation.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from blackswan._sleep_validation import (
    aggregate,
    collect_nights,
    find_outliers,
    render_markdown,
)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Validate naive/smart transition math vs sleep-official.csv",
    )
    p.add_argument("--daily-dir", type=Path, required=True,
                   help="directory of {date}-sleep-levels.csv files")
    p.add_argument("--sleep-official", type=Path, required=True,
                   help="path to sleep-official.csv (build with build_sleep_official)")
    p.add_argument("--out", type=Path, required=True,
                   help="output markdown path (e.g. docs/sleep-validation.md)")
    p.add_argument("--show-dates", action="store_true",
                   help="emit real dates instead of night_N. Local audit only — "
                        "never commit the resulting markdown.")
    args = p.parse_args()

    if not args.daily_dir.is_dir():
        print(f"--daily-dir not a directory: {args.daily_dir}", file=sys.stderr)
        return 2
    if not args.sleep_official.is_file():
        print(f"--sleep-official not a file: {args.sleep_official}", file=sys.stderr)
        return 2

    nights = collect_nights(args.daily_dir, args.sleep_official)
    if not nights:
        print(
            f"no overlapping nights between {args.daily_dir} "
            f"and {args.sleep_official}",
            file=sys.stderr,
        )
        return 1

    aggs = aggregate(nights)
    outliers = find_outliers(nights)
    md = render_markdown(nights, aggs, outliers, anonymize=not args.show_dates)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"wrote {args.out}: n={len(nights)} nights, outliers={len(outliers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

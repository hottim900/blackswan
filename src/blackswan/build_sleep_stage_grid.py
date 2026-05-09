"""Build {date}-sleep-stage-grid.csv — per-minute stage grid for cross-tab.

Expands `{date}-sleep-levels.csv` transitions into a fixed-cadence grid so
HR / SpO2 / respiration minute-level series can be joined on `timestamp`.
Uses `_sleep.stage_at()` so brief in-sleep arousals inherit the surrounding
non-awake stage (matching `analyze_spo2_vs_stage` and `forensic_spo2_event`
semantics).

NOT a totals aggregator. Per-stage totals (Deep/Light/REM/Awake seconds)
must come from `sleep-official.csv` — naive transition math is unreliable
for any single night (see docs/sleep-validation.md). For per-day stage
totals, use `build_daily_summary`.

Output:
    {date}-sleep-stage-grid.csv  — columns: timestamp, stage
                                    one row per `--granularity-sec` step
                                    spanning [first_transition, last_transition]

Granularity: default 60s, accepts `30` or `60`. Other values raise — extending
the allowlist is cheap if a use case surfaces.

Usage:
    python -m blackswan.build_sleep_stage_grid \\
        garmin/timeseries/daily/ \\
        garmin/timeseries/sleep-stage-grid/ \\
        [--date 2000-01-15] \\
        [--all] \\
        [--granularity-sec 60]

Errors:
    ValueError              — granularity not in {30, 60}.
    Empty / single-row CSV  — skipped with a warning, not raised.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

from blackswan._sleep import stage_at

ALLOWED_GRANULARITY_SEC = (30, 60)
GRID_COLS = ["timestamp", "stage"]


def _load_transitions(path: Path) -> list[tuple[datetime, str]]:
    """Read transitions, drop empty rows, dedupe by timestamp (latest wins),
    and sort by timestamp. Mirrors `parse_daily_fit._dedupe_sort` philosophy."""
    rows: list[tuple[datetime, str]] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            ts_str = (row.get("timestamp") or "").strip()
            level = (row.get("level") or "").strip()
            if not ts_str or not level:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            rows.append((ts, level))
    if not rows:
        return []
    rows.sort(key=lambda r: r[0])
    # Dedupe duplicates by timestamp (last value wins) — protects against the
    # "data quirk" path documented in the test plan.
    deduped: list[tuple[datetime, str]] = []
    last_ts: datetime | None = None
    for ts, lvl in rows:
        if last_ts is not None and ts == last_ts:
            deduped[-1] = (ts, lvl)
        else:
            deduped.append((ts, lvl))
            last_ts = ts
    return deduped


def expand_to_grid(
    transitions: list[tuple[datetime, str]],
    *,
    granularity_sec: int,
) -> list[tuple[str, str]]:
    """Yield (iso_timestamp, stage) rows at fixed `granularity_sec` cadence.

    Window is [first_transition, last_transition]. Stage at each grid point
    comes from `_sleep.stage_at` — pre-window readings (or all-awake nights)
    surface as the empty string, mirroring stage_at's `default=None` contract.
    """
    if len(transitions) < 2:
        return []
    start, end = transitions[0][0], transitions[-1][0]
    step = timedelta(seconds=granularity_sec)
    out: list[tuple[str, str]] = []
    t = start
    while t <= end:
        stage = stage_at(t, transitions) or ""
        out.append((t.isoformat(), stage))
        t += step
    return out


def _validate_granularity(granularity_sec: int) -> None:
    if granularity_sec not in ALLOWED_GRANULARITY_SEC:
        raise ValueError(
            f"granularity_sec={granularity_sec} not allowed; "
            f"must be one of {ALLOWED_GRANULARITY_SEC}"
        )


def build_one(
    daily_dir: Path,
    out_dir: Path,
    date: str,
    *,
    granularity_sec: int = 60,
) -> Path | None:
    """Build the grid for a single date. Returns the output path on success,
    None when skipped (empty/single-row sleep-levels)."""
    _validate_granularity(granularity_sec)
    in_path = daily_dir / f"{date}-sleep-levels.csv"
    if not in_path.is_file():
        print(f"  {date}: missing {in_path.name}, skipping", file=sys.stderr)
        return None

    transitions = _load_transitions(in_path)
    if len(transitions) < 2:
        print(
            f"  {date}: {len(transitions)} usable transitions (need ≥2), skipping",
            file=sys.stderr,
        )
        return None

    if all(lvl == "awake" for _, lvl in transitions):
        print(
            f"  {date}: all transitions are awake — emitting empty stages",
            file=sys.stderr,
        )

    rows = expand_to_grid(transitions, granularity_sec=granularity_sec)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}-sleep-stage-grid.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(GRID_COLS)
        w.writerows(rows)
    print(f"  {date}: {len(rows)} rows @ {granularity_sec}s")
    return out_path


def build_all(
    daily_dir: Path,
    out_dir: Path,
    *,
    granularity_sec: int = 60,
) -> list[Path]:
    """Build grids for every {date}-sleep-levels.csv in daily_dir."""
    _validate_granularity(granularity_sec)
    paths: list[Path] = []
    for in_path in sorted(daily_dir.glob("*-sleep-levels.csv")):
        date = in_path.name[: -len("-sleep-levels.csv")]
        result = build_one(daily_dir, out_dir, date,
                           granularity_sec=granularity_sec)
        if result is not None:
            paths.append(result)
    return paths


def main() -> int:
    p = argparse.ArgumentParser(
        description="Per-minute sleep stage grid for cross-tab analyses",
    )
    p.add_argument("daily_dir", type=Path,
                   help="directory of {date}-sleep-levels.csv files")
    p.add_argument("out_dir", type=Path,
                   help="output directory for {date}-sleep-stage-grid.csv files")
    p.add_argument("--date",
                   help="single date to process (YYYY-MM-DD); omit for all "
                        "or pair with --all to be explicit")
    p.add_argument("--all", action="store_true",
                   help="process every *-sleep-levels.csv in daily_dir")
    p.add_argument("--granularity-sec", type=int, default=60,
                   help=f"grid spacing in seconds (allowed: "
                        f"{', '.join(str(g) for g in ALLOWED_GRANULARITY_SEC)})")
    args = p.parse_args()

    if not args.daily_dir.is_dir():
        print(f"daily_dir not a directory: {args.daily_dir}", file=sys.stderr)
        return 2

    if args.date and args.all:
        print("--date and --all are mutually exclusive", file=sys.stderr)
        return 2

    try:
        if args.date:
            built = build_one(args.daily_dir, args.out_dir, args.date,
                              granularity_sec=args.granularity_sec)
            return 0 if built is not None else 1
        # default to --all when neither is given
        built = build_all(args.daily_dir, args.out_dir,
                          granularity_sec=args.granularity_sec)
        if not built:
            print("no grids produced", file=sys.stderr)
            return 1
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

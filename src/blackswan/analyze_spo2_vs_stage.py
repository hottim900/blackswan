"""Cross-align SpO2 readings with sleep stages across many nights.

For each day with both `{date}-spo2.csv` and `{date}-sleep-levels.csv`:
- Scan SpO2 readings whose timestamp falls inside a sleep window
  (between the first sleep-level event and the next awake/end event).
- Resolve the sleep stage in effect at that moment.
- Emit per-reading rows AND aggregate stats.

Outputs:
    garmin/analysis/spo2-by-stage.csv          per-reading detail
    garmin/analysis/spo2-stage-summary.csv     per-(date, stage) summary

Standalone report printed to stdout, with optional --threshold knob.

IMPORTANT — sleep-level awake semantics (per-minute lookup):
    Garmin's `sleep_level` transitions emit an 'awake' marker for each brief
    in-sleep arousal (typically < 1 min). For per-minute SpO2-to-stage
    classification we use _sleep.stage_at(), which inherits the preceding
    non-awake stage across these arousals.

IMPORTANT — stage_minutes data source (per-night totals):
    Per-night stage durations come from sleep-official.csv (Garmin Connect
    post-processed authoritative values), NOT from naive transition math
    on sleep-levels.csv. The transition math systematically diverges from
    Garmin UI by 1.4-4.5x for deep/REM on individual nights. When a date
    is missing from sleep-official.csv we fall back to transition math and
    flag the row with stage_minutes_source='transition_fallback' so the
    consumer knows. Pass --sleep-official to override the default path.

Usage:
    python -m blackswan.analyze_spo2_vs_stage \\
        garmin/timeseries/daily/ \\
        garmin/analysis/ \\
        [--threshold 85] \\
        [--sleep-official garmin/timeseries/history/sleep-official.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

from blackswan._sleep import stage_at

# Map our stage labels to sleep-official.csv column names.
# STAGES iteration order also drives summary CSV row order — keep insertion order.
_OFFICIAL_STAGE_COLS = {
    "light": "light_sec",
    "deep": "deep_sec",
    "rem": "rem_sec",
    "unmeasurable": "unmeasurable_sec",
}
STAGES = tuple(_OFFICIAL_STAGE_COLS)


def _load_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _parse_ts(s: str) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _pair_days(daily_dir: Path) -> list[tuple[str, Path, Path]]:
    """Find dates where both spo2 and sleep-levels CSVs exist and are non-empty."""
    pairs = []
    for spo2_path in sorted(daily_dir.glob("*-spo2.csv")):
        date = spo2_path.name[: -len("-spo2.csv")]
        sleep_path = daily_dir / f"{date}-sleep-levels.csv"
        if not sleep_path.exists():
            continue
        # Skip empty (header-only) CSVs
        if spo2_path.stat().st_size < 40 or sleep_path.stat().st_size < 30:
            continue
        pairs.append((date, spo2_path, sleep_path))
    return pairs


def _load_official_stage_minutes(path: Path) -> dict[str, dict[str, float]]:
    """Read sleep-official.csv → {date: {stage: minutes}}.

    Only includes stages where the *_sec column has a value. Returns an empty
    dict if the file is missing — the caller then falls back to transition math
    for every date.
    """
    if not path.exists():
        return {}
    out: dict[str, dict[str, float]] = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            date = row["calendar_date"]
            day_stages: dict[str, float] = {}
            for stage, col in _OFFICIAL_STAGE_COLS.items():
                val = row.get(col, "").strip()
                if val:
                    try:
                        day_stages[stage] = int(val) / 60.0
                    except ValueError:
                        continue
            if day_stages:
                out[date] = day_stages
    return out


def _sleep_window(transitions: list[tuple[datetime, str]]) -> tuple[datetime, datetime] | None:
    """Boundary: first transition ts to last transition ts.

    Sleep-levels CSV includes a trailing 'awake' transition at wake time, so
    the last transition is effectively the sleep end. Everything between is
    'in the sleep session'."""
    if len(transitions) < 2:
        return None
    return transitions[0][0], transitions[-1][0]


def analyze(daily_dir: Path, out_dir: Path, threshold: int,
            sleep_official_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs = _pair_days(daily_dir)
    official = _load_official_stage_minutes(sleep_official_path)
    print(f"Found {len(pairs)} days with both SpO2 and sleep-levels data.")
    print(f"Loaded sleep-official.csv: {len(official)} dates with stage data.")

    per_reading: list[dict] = []
    per_day_stage: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    stage_minutes: defaultdict[tuple[str, str], float] = defaultdict(float)
    stage_minutes_source: dict[str, str] = {}  # date -> 'official' | 'transition_fallback'

    for date, spo2_path, sleep_path in pairs:
        transitions = []
        for row in _load_csv(sleep_path):
            ts = _parse_ts(row["timestamp"])
            if ts and row["level"]:
                transitions.append((ts, row["level"]))
        window = _sleep_window(transitions)
        if not window:
            continue
        start, end = window

        # Stage durations: prefer Garmin Connect post-processed values from
        # sleep-official.csv (authoritative). Fall back to transition math on
        # sleep-levels.csv only when the date is missing from official —
        # that fallback systematically diverges from Garmin UI by 1.4-4.5x
        # for deep/REM, but is the best we can do without an official row.
        if date in official:
            for stage, minutes in official[date].items():
                stage_minutes[(date, stage)] = minutes
            stage_minutes_source[date] = "official"
        else:
            non_awake = [(ts, lvl) for ts, lvl in transitions if lvl != "awake"]
            for i, (ts0, lvl0) in enumerate(non_awake):
                ts1 = non_awake[i + 1][0] if i + 1 < len(non_awake) else end
                stage_minutes[(date, lvl0)] += (ts1 - ts0).total_seconds() / 60.0
            stage_minutes_source[date] = "transition_fallback"

        # Walk each SpO2 reading inside the sleep window, look up stage.
        for row in _load_csv(spo2_path):
            ts = _parse_ts(row["timestamp"])
            val = row["spo2_percent"]
            if not ts or not val:
                continue
            if ts < start or ts > end:
                continue
            v = int(val)
            stage = stage_at(ts, transitions) or "unknown"
            per_reading.append({
                "date": date, "timestamp": ts.isoformat(),
                "spo2": v, "stage": stage,
                "confidence": row.get("confidence"),
                "mode": row.get("mode"),
            })
            per_day_stage[(date, stage)].append(v)

    # Write per-reading
    detail_path = out_dir / "spo2-by-stage.csv"
    with detail_path.open("w", newline="") as f:
        w = csv.DictWriter(f, ["date", "timestamp", "spo2", "stage", "confidence", "mode"])
        w.writeheader()
        w.writerows(per_reading)

    # Per-(date, stage) summary. Iterate stage_minutes (every (date, stage) with
    # any duration data) and left-join SpO2 stats — official stage minutes for a
    # date must show up even when no SpO2 readings landed in the sleep window.
    summary_path = out_dir / "spo2-stage-summary.csv"
    with summary_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "stage", "stage_minutes", "stage_minutes_source",
                    "spo2_n", "spo2_median",
                    "spo2_min", f"spo2_lt_{threshold}_n",
                    f"spo2_lt_{threshold}_pct"])
        for (date, stage) in sorted(stage_minutes):
            vals = per_day_stage.get((date, stage), [])
            below = sum(1 for v in vals if v < threshold)
            pct = below / len(vals) * 100 if vals else 0
            w.writerow([
                date, stage, f"{stage_minutes[(date, stage)]:.1f}",
                stage_minutes_source.get(date, "transition_fallback"),
                len(vals),
                median(vals) if vals else "",
                min(vals) if vals else "",
                below, f"{pct:.1f}",
            ])

    # Aggregate report
    print()
    n_official = sum(1 for s in stage_minutes_source.values() if s == "official")
    n_fallback = sum(1 for s in stage_minutes_source.values() if s == "transition_fallback")
    print(f"stage_minutes source: official={n_official} fallback={n_fallback}")
    print(f"== Aggregate across {len(pairs)} days, threshold SpO2 < {threshold}% ==")
    agg_by_stage = defaultdict(list)
    for r in per_reading:
        agg_by_stage[r["stage"]].append(r["spo2"])
    total_minutes_by_stage = defaultdict(float)
    for (_, stage), mins in stage_minutes.items():
        total_minutes_by_stage[stage] += mins
    total_sleep_minutes = sum(total_minutes_by_stage.values()) or 1

    print(f"{'stage':12} {'readings':>9} {'median':>7} {'min':>5} "
          f"{f'<{threshold}%n':>8} {f'<{threshold}%rate':>9} {'time_share':>11}")
    for stage in STAGES:
        vals = agg_by_stage.get(stage, [])
        if not vals:
            continue
        below = sum(1 for v in vals if v < threshold)
        rate = below / len(vals) * 100
        time_share = total_minutes_by_stage[stage] / total_sleep_minutes * 100
        print(f"{stage:12} {len(vals):>9} {median(vals):>7} {min(vals):>5} "
              f"{below:>8} {rate:>8.1f}% {time_share:>10.1f}%")

    # Severe sustained events: ≥ 5 consecutive readings (~5 min at 1/min) below threshold
    # Per day, walk per_reading in timestamp order, count runs.
    severe_events = []
    per_reading_sorted = sorted(per_reading, key=lambda r: (r["date"], r["timestamp"]))
    run = []
    prev_date = None
    for r in per_reading_sorted:
        if r["date"] != prev_date:
            if len(run) >= 5:
                severe_events.append(run)
            run = []
            prev_date = r["date"]
        if r["spo2"] < threshold:
            run.append(r)
        else:
            if len(run) >= 5:
                severe_events.append(run)
            run = []
    if len(run) >= 5:
        severe_events.append(run)

    print()
    print(f"Sustained events (≥5 consecutive readings < {threshold}%): {len(severe_events)}")
    # Per-stage count of these sustained events (use majority stage in run)
    sev_by_stage = Counter()
    for run in severe_events:
        stages_in_run = Counter(r["stage"] for r in run)
        dominant = stages_in_run.most_common(1)[0][0]
        sev_by_stage[dominant] += 1
    for stage in STAGES:
        if sev_by_stage[stage]:
            print(f"  dominant_stage={stage:12}  count={sev_by_stage[stage]}")

    # List top-10 most severe runs
    if severe_events:
        print()
        print("Top 10 longest sustained events (date / duration / min / stages):")
        ranked = sorted(severe_events, key=lambda r: -len(r))[:10]
        for run in ranked:
            first = run[0]
            last = run[-1]
            mn = min(r["spo2"] for r in run)
            stages_in_run = Counter(r["stage"] for r in run)
            t0 = datetime.fromisoformat(first["timestamp"]).strftime("%H:%M")
            t1 = datetime.fromisoformat(last["timestamp"]).strftime("%H:%M")
            print(f"  {first['date']}  {t0}-{t1}  len={len(run):2}  min={mn}%  "
                  f"stages={dict(stages_in_run)}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("daily_dir", type=Path)
    p.add_argument("out_dir", type=Path)
    p.add_argument("--threshold", type=int, default=85)
    p.add_argument("--sleep-official", type=Path,
                   default=Path("garmin/timeseries/history/sleep-official.csv"),
                   help="path to sleep-official.csv (SSOT for stage durations)")
    args = p.parse_args()
    analyze(args.daily_dir, args.out_dir, args.threshold, args.sleep_official)
    return 0


if __name__ == "__main__":
    sys.exit(main())

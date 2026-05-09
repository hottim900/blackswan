"""Build {date}-daily-summary.csv — single-row daily aggregate.

Mirrors Garmin Connect's per-day export semantics: HR/SpO2/respiration
aggregates, HRV passthrough, sleep stage durations, body battery in/out.

Sleep stage durations REQUIRE sleep-official.csv. Naive transition math on
sleep-levels.csv is NOT a fallback — see docs/sleep-validation.md for the
evidence. Without --allow-missing-sleep-official the CLI raises
MissingSSOTError pointing at build_sleep_official.

Required raw inputs (per date):
    daily/{date}-hr.csv             avg + n_readings
    daily/{date}-spo2.csv           avg/min/max + n_readings
    daily/{date}-respiration.csv    avg/min/max + sleep/awake split
    daily/{date}-sleep-assessment.csv  session_start, session_end (window)
    daily/{date}-hrv-summary.csv    7 HRV columns (passthrough)
    daily/{date}-intraday-rhr.csv   resting_hr_bpm (latest current_day_resting)
    history/sleep-official.csv      stage_sec + sleep_start/end_gmt + total

Optional input:
    history/daily-summary.csv (--bulk-history)  body_battery_charged/drained

Per-input policy (_INPUT_REQUIREMENTS):
    sleep-official.csv missing date row → raise MissingSSOTError unless
        --allow-missing-sleep-official is set (then partial mode).
    Each daily/*.csv missing or header-only → that sensor's columns become
        None and data_completeness="partial". HRV missing keeps "full" since
        HRV is optional on watches without an HRV-status surface.
    Bulk history missing or row missing → body_battery cols None + partial.

CLI:
    python -m blackswan.build_daily_summary daily/ \\
        --sleep-official garmin/timeseries/history/sleep-official.csv \\
        --bulk-history garmin/timeseries/history/daily-summary.csv \\
        --out garmin/timeseries/daily-summary/2000-01-15-daily-summary.csv

    # batch mode:
    python -m blackswan.build_daily_summary daily/ \\
        --sleep-official ... [--bulk-history ...] \\
        --out-dir garmin/timeseries/daily-summary/ --all
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean

_OUT_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")

__all__ = [
    "DAILY_SUMMARY_COLS",
    "MissingSSOTError",
    "build_one",
    "build_all",
]


# ── Schema (SSOT) ───────────────────────────────────────────────────────────

DAILY_SUMMARY_COLS = [
    # Provenance — calendar_date is the LOCAL day (UTC+8 per _time.LOCAL_TZ)
    # matching daily_dir's per-day CSV prefix; sleep windows that cross
    # local midnight stay keyed to the start-day.
    "calendar_date",
    "data_completeness",
    # HR
    "avg_hr_bpm", "n_hr_readings",
    "resting_hr_bpm",
    # SpO2
    "avg_spo2_pct", "min_spo2_pct", "max_spo2_pct", "n_spo2_readings",
    # Respiration (overall + sleep/awake split)
    "avg_respiration_brpm", "min_respiration_brpm", "max_respiration_brpm",
    "n_respiration_readings",
    "sleep_avg_respiration_brpm", "awake_avg_respiration_brpm",
    # HRV — passthrough from {date}-hrv-summary.csv
    "weekly_avg_ms", "last_night_avg_ms", "last_night_5min_high_ms",
    "baseline_low_upper", "baseline_balanced_lower", "baseline_balanced_upper",
    "status",
    # Sleep stage durations — ALL from sleep-official.csv
    "sleep_start_gmt", "sleep_end_gmt", "total_sleep_sec",
    "deep_sec", "light_sec", "rem_sec", "awake_sec", "unmeasurable_sec",
    # Body battery — bulk-export passthrough (energy in/out, not level curve)
    "body_battery_charged", "body_battery_drained",
]


_HRV_COLS = [
    "weekly_avg_ms", "last_night_avg_ms", "last_night_5min_high_ms",
    "baseline_low_upper", "baseline_balanced_lower", "baseline_balanced_upper",
    "status",
]


_OFFICIAL_STAGE_COLS = ["deep_sec", "light_sec", "rem_sec",
                        "awake_sec", "unmeasurable_sec"]


class MissingSSOTError(FileNotFoundError):
    """Raised when sleep-official.csv lacks the requested date row.

    Build with: python -m blackswan.build_sleep_official ...
    Pass --allow-missing-sleep-official to downgrade to partial mode.
    """


# Required inputs flip data_completeness to "partial" when missing/empty.
# Optional inputs silently None; completeness stays "full".
_REQUIRED_INPUTS = frozenset({
    "hr.csv", "spo2.csv", "respiration.csv",
    "sleep-assessment.csv", "intraday-rhr.csv",
})


# ── Helpers ─────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    """Read a CSV; return [] for missing or header-only files."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _to_float(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(s: str | None) -> int | None:
    v = _to_float(s)
    return int(v) if v is not None else None


def _aggregate_floats(rows, col: str) -> dict:
    """Return avg/min/max/n for a numeric column. Empty → all None / 0."""
    vals: list[float] = []
    for row in rows:
        v = _to_float(row.get(col))
        if v is not None:
            vals.append(v)
    if not vals:
        return {"avg": None, "min": None, "max": None, "n": 0}
    return {
        "avg": mean(vals),
        "min": min(vals),
        "max": max(vals),
        "n": len(vals),
    }


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip())
    except ValueError:
        return None


def _split_respiration_by_window(
    resp_rows: list[dict],
    session_start: datetime | None,
    session_end: datetime | None,
) -> tuple[float | None, float | None]:
    """Return (sleep_avg, awake_avg). When the window is unknown both are None
    — by design, we do NOT silently classify all readings as awake."""
    if session_start is None or session_end is None:
        return None, None
    sleep_vals: list[float] = []
    awake_vals: list[float] = []
    for row in resp_rows:
        ts = _parse_iso(row.get("timestamp"))
        v = _to_float(row.get("respiration_rate_brpm"))
        if ts is None or v is None:
            continue
        if session_start <= ts <= session_end:
            sleep_vals.append(v)
        else:
            awake_vals.append(v)
    return (
        mean(sleep_vals) if sleep_vals else None,
        mean(awake_vals) if awake_vals else None,
    )


def _resting_hr(rows: list[dict]) -> float | None:
    """Latest non-null `current_day_resting_hr_bpm` (resting trend stabilizes
    over the day; the most recent reading is the day's authoritative value).
    Falls back to `resting_hr_bpm` when current_day is empty."""
    if not rows:
        return None
    sorted_rows = sorted(rows, key=lambda r: (r.get("timestamp") or ""))
    for col in ("current_day_resting_hr_bpm", "resting_hr_bpm"):
        for row in reversed(sorted_rows):
            v = _to_float(row.get(col))
            if v is not None:
                return v
    return None


def _latest_hrv_summary(rows: list[dict]) -> dict | None:
    """Pick the latest-timestamp row + warn if multiple rows present.

    Parser writes one row per HRV summary mesg; multiple HRV-emitting FITs
    in a day's directory (WELLNESS.fit + HRV_STATUS.fit) can produce >1 row.
    """
    if not rows:
        return None
    if len(rows) > 1:
        print(
            f"  warning: {len(rows)} HRV summary rows, "
            "keeping latest timestamp",
            file=sys.stderr,
        )
    return max(rows, key=lambda r: (r.get("timestamp") or ""))


def _infer_date_from_out(out_path: Path) -> str | None:
    """Pull a leading YYYY-MM-DD from `out_path.name` (e.g.,
    `2000-01-15-daily-summary.csv` → `2000-01-15`). Returns None if the
    filename does not start with a date."""
    m = _OUT_DATE_RE.match(out_path.name)
    return m.group(1) if m else None


def _bulk_row_for_date(rows: list[dict], date: str) -> dict | None:
    for row in rows:
        if (row.get("calendar_date") or "").strip() == date:
            return row
    return None


def _official_row_for_date(path: Path, date: str) -> dict | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("calendar_date") or "").strip() == date:
                return row
    return None


# ── Builder ─────────────────────────────────────────────────────────────────

def build_one(
    daily_dir: Path,
    sleep_official_path: Path,
    *,
    bulk_history_path: Path | None = None,
    date: str,
    out_path: Path,
    allow_missing_sleep_official: bool = False,
) -> tuple[Path, str]:
    """Build {date}-daily-summary.csv. Returns (out_path, completeness).

    `date` is the LOCAL calendar day (UTC+8 per `_time.LOCAL_TZ`) — the
    same string `parse_daily_fit` uses to prefix per-day CSV filenames in
    `daily_dir`. Nights that cross local midnight live under the start-day
    key; sleep_start_gmt and sleep_end_gmt may straddle two calendar days.
    """
    completeness = "full"

    # Sleep-official is the SSOT-required input for stage durations.
    official_row = _official_row_for_date(sleep_official_path, date)
    if official_row is None:
        if not allow_missing_sleep_official:
            raise MissingSSOTError(
                f"sleep-official.csv missing row for date={date} "
                f"at {sleep_official_path}\n"
                f"  cause: no entry for this date in the SSOT\n"
                f"  fix:   python -m blackswan.build_sleep_official "
                f"<sleep-all.csv> --manual-dirs <dir>... --out "
                f"{sleep_official_path}"
            )
        completeness = "partial"

    inputs = {
        "hr.csv": _read_csv(daily_dir / f"{date}-hr.csv"),
        "spo2.csv": _read_csv(daily_dir / f"{date}-spo2.csv"),
        "respiration.csv": _read_csv(daily_dir / f"{date}-respiration.csv"),
        "sleep-assessment.csv": _read_csv(daily_dir / f"{date}-sleep-assessment.csv"),
        "hrv-summary.csv": _read_csv(daily_dir / f"{date}-hrv-summary.csv"),
        "intraday-rhr.csv": _read_csv(daily_dir / f"{date}-intraday-rhr.csv"),
    }
    for fname in _REQUIRED_INPUTS:
        if not inputs[fname]:
            print(f"  warning: {date}-{fname} missing/empty; partial mode",
                  file=sys.stderr)
            completeness = "partial"

    hr_rows = inputs["hr.csv"]
    spo2_rows = inputs["spo2.csv"]
    resp_rows = inputs["respiration.csv"]
    sa_rows = inputs["sleep-assessment.csv"]
    hrv_rows = inputs["hrv-summary.csv"]
    rhr_rows = inputs["intraday-rhr.csv"]

    hr_stats = _aggregate_floats(hr_rows, "hr_bpm")
    spo2_stats = _aggregate_floats(spo2_rows, "spo2_percent")
    resp_stats = _aggregate_floats(resp_rows, "respiration_rate_brpm")
    resting_hr = _resting_hr(rhr_rows)

    session_start = None
    session_end = None
    if sa_rows:
        ss = (sa_rows[0].get("session_start") or "").strip()
        se = (sa_rows[0].get("session_end") or "").strip()
        # Empty session window legitimately happens when no FIT in the day's
        # directory contains event=74. Emit None+partial — never silently
        # bucket all respiration as awake.
        if not ss or not se:
            print(
                f"  warning: {date} sleep-assessment session window empty; "
                "respiration sleep/awake split skipped",
                file=sys.stderr,
            )
            completeness = "partial"
        else:
            session_start = _parse_iso(ss)
            session_end = _parse_iso(se)

    sleep_avg, awake_avg = _split_respiration_by_window(
        resp_rows, session_start, session_end
    )

    hrv = _latest_hrv_summary(hrv_rows)

    # Body battery (optional).
    bb_row: dict | None = None
    if bulk_history_path is not None:
        bulk_rows = _read_csv(bulk_history_path)
        bb_row = _bulk_row_for_date(bulk_rows, date)
    if bb_row is None:
        if bulk_history_path is None:
            print(
                "  warning: --bulk-history not provided; "
                "body_battery columns will be empty",
                file=sys.stderr,
            )
        else:
            print(
                f"  warning: {date} not in {bulk_history_path}; "
                "body_battery columns will be empty",
                file=sys.stderr,
            )
        completeness = "partial"

    # Sleep stage durations from official.
    sleep_start = sleep_end = total_sleep = None
    deep = light = rem = awake = unmeas = None
    if official_row is not None:
        sleep_start = (official_row.get("sleep_start_gmt") or "").strip() or None
        sleep_end = (official_row.get("sleep_end_gmt") or "").strip() or None
        deep = _to_int(official_row.get("deep_sec"))
        light = _to_int(official_row.get("light_sec"))
        rem = _to_int(official_row.get("rem_sec"))
        awake = _to_int(official_row.get("awake_sec"))
        unmeas = _to_int(official_row.get("unmeasurable_sec"))
        # total_sleep_sec is computed from the parts (Garmin Connect's
        # "total sleep" is deep+light+rem; awake is excluded by convention).
        parts = [v for v in (deep, light, rem) if v is not None]
        total_sleep = sum(parts) if parts else None

    # Assemble output row.
    row: dict[str, object | None] = {
        "calendar_date": date,
        "data_completeness": completeness,
        "avg_hr_bpm": hr_stats["avg"],
        "n_hr_readings": hr_stats["n"],
        "resting_hr_bpm": resting_hr,
        "avg_spo2_pct": spo2_stats["avg"],
        "min_spo2_pct": spo2_stats["min"],
        "max_spo2_pct": spo2_stats["max"],
        "n_spo2_readings": spo2_stats["n"],
        "avg_respiration_brpm": resp_stats["avg"],
        "min_respiration_brpm": resp_stats["min"],
        "max_respiration_brpm": resp_stats["max"],
        "n_respiration_readings": resp_stats["n"],
        "sleep_avg_respiration_brpm": sleep_avg,
        "awake_avg_respiration_brpm": awake_avg,
        "sleep_start_gmt": sleep_start,
        "sleep_end_gmt": sleep_end,
        "total_sleep_sec": total_sleep,
        "deep_sec": deep,
        "light_sec": light,
        "rem_sec": rem,
        "awake_sec": awake,
        "unmeasurable_sec": unmeas,
        "body_battery_charged": (
            _to_int(bb_row.get("body_battery_charged")) if bb_row else None
        ),
        "body_battery_drained": (
            _to_int(bb_row.get("body_battery_drained")) if bb_row else None
        ),
    }

    if hrv is not None:
        for col in _HRV_COLS:
            v = (hrv.get(col) or "").strip()
            row[col] = v if col == "status" else _to_float(v)
    else:
        for col in _HRV_COLS:
            row[col] = None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DAILY_SUMMARY_COLS)
        w.writeheader()
        w.writerow({c: ("" if row[c] is None else row[c]) for c in DAILY_SUMMARY_COLS})

    print(f"{date}: completeness={row['data_completeness']} → {out_path}")
    return out_path, completeness


def build_all(
    daily_dir: Path,
    sleep_official_path: Path,
    out_dir: Path,
    *,
    bulk_history_path: Path | None = None,
    allow_missing_sleep_official: bool = False,
) -> tuple[list[Path], int, list[str]]:
    """Build a daily-summary for every date present in `daily_dir`.

    Returns (built_paths, n_partial, missing_official_dates). The third
    element is the list of dates that raised MissingSSOTError when
    `allow_missing_sleep_official=False`. Empty in permissive mode.
    """
    dates = sorted({
        p.name[: -len("-hr.csv")]
        for p in daily_dir.glob("*-hr.csv")
    })
    built: list[Path] = []
    n_partial = 0
    missing: list[str] = []
    for date in dates:
        out_path = out_dir / f"{date}-daily-summary.csv"
        try:
            _, completeness = build_one(
                daily_dir, sleep_official_path,
                bulk_history_path=bulk_history_path,
                date=date, out_path=out_path,
                allow_missing_sleep_official=allow_missing_sleep_official,
            )
        except MissingSSOTError as exc:
            print(f"  {date}: {exc}", file=sys.stderr)
            missing.append(date)
            continue
        if completeness == "partial":
            n_partial += 1
        built.append(out_path)
    return built, n_partial, missing


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("daily_dir", type=Path,
                   help="directory of {date}-*.csv files from parse_daily_fit")
    p.add_argument("--sleep-official", type=Path,
                   default=Path("garmin/timeseries/history/sleep-official.csv"),
                   help="path to sleep-official.csv (SSOT for stage durations)")
    p.add_argument("--bulk-history", type=Path,
                   help="path to history/daily-summary.csv from parse_bulk_export "
                        "(provides body_battery_charged/drained)")
    p.add_argument("--out", type=Path,
                   help="output path (single-date mode)")
    p.add_argument("--out-dir", type=Path,
                   help="output directory (batch mode; pair with --all)")
    p.add_argument("--date",
                   help="single date YYYY-MM-DD; required unless --all "
                        "or inferable from --out filename")
    p.add_argument("--all", action="store_true",
                   help="batch mode: process every date in daily_dir")
    p.add_argument("--allow-missing-sleep-official", action="store_true",
                   help="partial mode: emit non-stage columns even when "
                        "sleep-official.csv is missing the date row")
    args = p.parse_args()

    if not args.daily_dir.is_dir():
        print(f"daily_dir not a directory: {args.daily_dir}", file=sys.stderr)
        return 2

    try:
        if args.all:
            if not args.out_dir:
                print("--all requires --out-dir", file=sys.stderr)
                return 2
            if args.out:
                print("--out is ignored in batch mode (--all uses --out-dir)",
                      file=sys.stderr)
                return 2
            built, n_partial, missing = build_all(
                args.daily_dir, args.sleep_official, args.out_dir,
                bulk_history_path=args.bulk_history,
                allow_missing_sleep_official=args.allow_missing_sleep_official,
            )
            print(f"built {len(built)} summaries ({n_partial} partial)")
            if not built:
                return 1
            if missing and not args.allow_missing_sleep_official:
                print(
                    f"error: {len(missing)} date(s) missing from sleep-official.csv "
                    "(strict mode); pass --allow-missing-sleep-official to downgrade",
                    file=sys.stderr,
                )
                return 1
            return 0
        else:
            if args.out is None:
                print("single-date mode requires --out", file=sys.stderr)
                return 2
            if args.out_dir:
                print("--out-dir requires --all (single-date mode uses --out)",
                      file=sys.stderr)
                return 2
            date = args.date or _infer_date_from_out(args.out)
            if date is None:
                print(
                    "single-date mode requires --date YYYY-MM-DD "
                    "(or an --out filename starting with YYYY-MM-DD-)",
                    file=sys.stderr,
                )
                return 2
            build_one(
                args.daily_dir, args.sleep_official,
                bulk_history_path=args.bulk_history,
                date=date, out_path=args.out,
                allow_missing_sleep_official=args.allow_missing_sleep_official,
            )
            return 0
    except MissingSSOTError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

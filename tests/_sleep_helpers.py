"""Synthetic CSV fixture builders for sleep-related tests.

Year=2000 timestamps only (PII guard, matches `_strength_helpers` convention
and the year-2000 rule in CLAUDE.md). All helpers write plain CSVs — no FIT
encoding round-trip — so tests stay fast and deterministic.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from blackswan._sleep import SLEEP_COLS
from blackswan._time import LOCAL_TZ
from blackswan.parse_bulk_export import UDS_COLS

SYNTH_SLEEP_DATE = "2000-01-15"
SYNTH_SLEEP_TS_START = datetime(2000, 1, 15, 23, 30, tzinfo=LOCAL_TZ)
SYNTH_SLEEP_TS_END = datetime(2000, 1, 16, 7, 15, tzinfo=LOCAL_TZ)


# ── Default happy-path rows ──────────────────────────────────────────────────

def _default_hr_rows():
    """24 hourly readings spanning the synthetic day."""
    base = datetime(2000, 1, 15, 8, 0, tzinfo=LOCAL_TZ)
    return [(base + timedelta(hours=h), 60 + (h % 7)) for h in range(24)]


def _default_spo2_rows():
    """6 readings inside the sleep window."""
    return [
        (SYNTH_SLEEP_TS_START + timedelta(minutes=30 + i * 60), 96 - (i % 3), 95, 1)
        for i in range(6)
    ]


def _default_resp_rows():
    """20 readings: 10 awake (noon onwards), 10 sleep (after midnight)."""
    awake_base = datetime(2000, 1, 15, 12, 0, tzinfo=LOCAL_TZ)
    sleep_base = SYNTH_SLEEP_TS_START + timedelta(minutes=30)
    awake = [
        (awake_base + timedelta(minutes=30 * i), 18.0 + (i % 3)) for i in range(10)
    ]
    sleep = [
        (sleep_base + timedelta(minutes=30 * i), 14.0 + (i % 2)) for i in range(10)
    ]
    return awake + sleep


def _default_sleep_levels_rows():
    """5 transitions including a brief arousal — exercises stage_at inheritance."""
    s = SYNTH_SLEEP_TS_START
    return [
        (s, "light"),
        (s + timedelta(minutes=30), "deep"),
        (s + timedelta(minutes=120), "awake"),  # brief arousal
        (s + timedelta(minutes=121), "rem"),
        (s + timedelta(minutes=160), "light"),
        (SYNTH_SLEEP_TS_END, "awake"),
    ]


def _default_intraday_rhr_rows():
    """One snapshot near end of day."""
    return [(SYNTH_SLEEP_TS_END - timedelta(hours=2), 58, 58)]


def _default_hrv_summary_rows():
    """Single-row HRV passthrough."""
    return [(
        SYNTH_SLEEP_TS_START,  # timestamp
        45,    # weekly_avg_ms
        42,    # last_night_avg_ms
        58,    # last_night_5min_high_ms
        38,    # baseline_low_upper
        40,    # baseline_balanced_lower
        50,    # baseline_balanced_upper
        "BALANCED",
    )]


# ── Writers ──────────────────────────────────────────────────────────────────

def _iso(ts):
    return ts.isoformat() if hasattr(ts, "isoformat") else ts


def _write_csv(path: Path, header: list[str], rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


# Sleep-assessment writer header — full column list mirrors parse_daily_fit.
_SLEEP_ASSESSMENT_COLS = [
    "session_start", "session_end",
    "overall_sleep_score", "sleep_quality_score", "sleep_duration_score",
    "sleep_recovery_score", "deep_sleep_score", "light_sleep_score",
    "rem_sleep_score", "sleep_restlessness_score", "interruptions_score",
    "combined_awake_score", "awake_time_score", "awakenings_count_score",
    "awakenings_count", "average_stress_during_sleep",
    "_unknown_f12", "_unknown_f13",
]

_HRV_SUMMARY_COLS = [
    "timestamp", "weekly_avg_ms", "last_night_avg_ms", "last_night_5min_high_ms",
    "baseline_low_upper", "baseline_balanced_lower", "baseline_balanced_upper",
    "status",
]


def make_daily_csvs(
    tmp_path: Path,
    date: str = SYNTH_SLEEP_DATE,
    *,
    hr_rows=None,
    spo2_rows=None,
    resp_rows=None,
    sleep_levels_rows=None,
    session_start=None,
    session_end=None,
    intraday_rhr_rows=None,
    hrv_summary_rows=None,
    write_hr: bool = True,
    write_spo2: bool = True,
    write_respiration: bool = True,
    write_sleep_levels: bool = True,
    write_sleep_assessment: bool = True,
    write_hrv_summary: bool = True,
    write_intraday_rhr: bool = True,
) -> Path:
    """Write a `daily/` directory with the 12 minute-level CSVs.

    Returns the daily directory path. `*_rows=None` uses defaults; pass `[]`
    for a header-only CSV. `write_X=False` omits the file entirely (mirrors
    `parse_daily_fit` behavior — sleep-assessment is omitted for days with no
    sleep FIT, etc.).
    """
    daily = tmp_path / "daily"
    daily.mkdir(parents=True, exist_ok=True)

    if hr_rows is None:
        hr_rows = _default_hr_rows()
    if spo2_rows is None:
        spo2_rows = _default_spo2_rows()
    if resp_rows is None:
        resp_rows = _default_resp_rows()
    if sleep_levels_rows is None:
        sleep_levels_rows = _default_sleep_levels_rows()
    if intraday_rhr_rows is None:
        intraday_rhr_rows = _default_intraday_rhr_rows()
    if hrv_summary_rows is None:
        hrv_summary_rows = _default_hrv_summary_rows()
    if session_start is None:
        session_start = SYNTH_SLEEP_TS_START.isoformat()
    if session_end is None:
        session_end = SYNTH_SLEEP_TS_END.isoformat()

    if write_hr:
        _write_csv(daily / f"{date}-hr.csv",
                   ["timestamp", "hr_bpm"],
                   [(_iso(t), v) for t, v in hr_rows])
    if write_spo2:
        _write_csv(daily / f"{date}-spo2.csv",
                   ["timestamp", "spo2_percent", "confidence", "mode"],
                   [(_iso(t), v, c, m) for t, v, c, m in spo2_rows])
    if write_respiration:
        _write_csv(daily / f"{date}-respiration.csv",
                   ["timestamp", "respiration_rate_brpm"],
                   [(_iso(t), v) for t, v in resp_rows])
    if write_sleep_levels:
        _write_csv(daily / f"{date}-sleep-levels.csv",
                   ["timestamp", "level"],
                   [(_iso(t), lvl) for t, lvl in sleep_levels_rows])

    # Always write the other 5 (build_daily_summary doesn't read them, but
    # parse_daily_fit emits them — exercise the read-glob behavior).
    _write_csv(daily / f"{date}-stress.csv", ["timestamp", "stress_level"], [])
    _write_csv(daily / f"{date}-activity.csv",
               ["timestamp", "activity_type", "intensity"], [])
    _write_csv(daily / f"{date}-hrv-5min.csv", ["timestamp", "hrv_ms"], [])
    _write_csv(daily / f"{date}-sleep-disruptions.csv",
               ["timestamp", "period_index", "severity"], [])
    _write_csv(daily / f"{date}-vo2max.csv",
               ["timestamp", "vo2_max", "sport", "sub_sport",
                "category", "calibrated"], [])

    if write_sleep_assessment:
        body = [session_start, session_end] + [""] * (len(_SLEEP_ASSESSMENT_COLS) - 2)
        _write_csv(daily / f"{date}-sleep-assessment.csv",
                   _SLEEP_ASSESSMENT_COLS, [body])

    if write_hrv_summary:
        rows = [(_iso(r[0]),) + tuple(r[1:]) for r in hrv_summary_rows]
        _write_csv(daily / f"{date}-hrv-summary.csv", _HRV_SUMMARY_COLS, rows)

    if write_intraday_rhr:
        _write_csv(daily / f"{date}-intraday-rhr.csv",
                   ["timestamp", "resting_hr_bpm", "current_day_resting_hr_bpm"],
                   [(_iso(t), r1, r2) for t, r1, r2 in intraday_rhr_rows])

    return daily


def make_sleep_official_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Write `history/sleep-official.csv` — each row dict keyed by SLEEP_COLS."""
    history = tmp_path / "history"
    history.mkdir(parents=True, exist_ok=True)
    path = history / "sleep-official.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SLEEP_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in SLEEP_COLS})
    return path


def make_bulk_daily_summary_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Write `history/daily-summary.csv` — body_battery_charged/drained source."""
    history = tmp_path / "history"
    history.mkdir(parents=True, exist_ok=True)
    path = history / "daily-summary.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=UDS_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in UDS_COLS})
    return path


def default_official_row(date: str = SYNTH_SLEEP_DATE) -> dict:
    """Representative sleep-official.csv row for happy-path tests."""
    start_iso = SYNTH_SLEEP_TS_START.isoformat()
    end_iso = SYNTH_SLEEP_TS_END.isoformat()
    return {
        "calendar_date": date,
        "sleep_start_gmt": start_iso,
        "sleep_end_gmt": end_iso,
        "deep_sec": "5400",
        "light_sec": "10800",
        "rem_sec": "5400",
        "awake_sec": "300",
        "unmeasurable_sec": "0",
        "awake_count": "2",
        "restless_moment_count": "10",
        "avg_respiration": "14.5",
        "lowest_respiration": "12",
        "highest_respiration": "18",
        "avg_sleep_stress": "20.0",
        "overall_score": "85",
        "quality_score": "90",
        "duration_score": "85",
        "recovery_score": "80",
        "deep_score": "85",
        "rem_score": "80",
        "light_score": "82",
        "awakenings_count_score": "75",
        "awake_time_score": "82",
        "combined_awake_score": "85",
        "interruptions_score": "80",
        "restfulness_score": "85",
        "avg_sleep_spo2": "96",
        "lowest_sleep_spo2": "92",
        "avg_sleep_hr": "60",
        "sleep_measurement_start_gmt": start_iso,
        "sleep_measurement_end_gmt": end_iso,
        "breathing_disruption_severity": "NONE",
        "confirmation_type": "ENHANCED_CONFIRMED_FINAL",
        "retro": "False",
    }


def default_bulk_daily_row(date: str = SYNTH_SLEEP_DATE) -> dict:
    """Representative bulk daily-summary row for body_battery passthrough."""
    return {
        "calendar_date": date,
        "body_battery_charged": "75",
        "body_battery_drained": "60",
    }

"""Tests for `build_daily_summary` — single-row daily aggregate.

Covers:
- T1   full inputs → all 30 columns populated, completeness=full
- T2   missing sleep-official date → MissingSSOTError pointing at build_sleep_official
- T3   --allow-missing-sleep-official → stage cols empty, completeness=partial,
       non-stage cols populated
- T4   HRV passthrough — single-row hrv-summary copies into 7 columns verbatim
- T5   respiration sleep/awake split sub-cases (a-d)
- T6   schema lock: DAILY_SUMMARY_COLS matches CSV header
- T11  per-input missing-CSV: each sensor independently triggers partial,
       hrv missing keeps "full"
- T12  header-only CSV treated as missing
- T13  --bulk-history not provided / row missing → bb columns None + partial
- T14  cross-midnight sleep window
- T17  multi-row hrv-summary → latest-timestamp wins, warning logged
- T-PII1  no real-year date strings escape into output
"""

from __future__ import annotations

import csv
import re
from datetime import timedelta
from pathlib import Path

import pytest

from blackswan.build_daily_summary import (
    DAILY_SUMMARY_COLS,
    MissingSSOTError,
    _infer_date_from_out,
    build_all,
    build_one,
)
from tests._sleep_helpers import (
    SYNTH_SLEEP_DATE,
    SYNTH_SLEEP_TS_END,
    SYNTH_SLEEP_TS_START,
    default_bulk_daily_row,
    default_official_row,
    make_bulk_daily_summary_csv,
    make_daily_csvs,
    make_sleep_official_csv,
)


def _read_one(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1, f"expected single row, got {len(rows)}"
    return rows[0]


def _build_full(tmp_path: Path, **daily_kwargs) -> Path:
    daily = make_daily_csvs(tmp_path, **daily_kwargs)
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out" / f"{SYNTH_SLEEP_DATE}-daily-summary.csv"
    written, _ = build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE,
        out_path=out_path,
    )
    return written


# ── T1 + T6 ──────────────────────────────────────────────────────────────────

def test_t1_full_inputs_populate_every_column(tmp_path):
    out_path = _build_full(tmp_path)
    row = _read_one(out_path)
    assert row["data_completeness"] == "full"
    # Provenance + every group has at least one populated column.
    assert row["calendar_date"] == SYNTH_SLEEP_DATE
    assert row["avg_hr_bpm"]
    assert row["resting_hr_bpm"]
    assert row["sleep_avg_hr_bpm"]
    assert row["awake_avg_hr_bpm"]
    assert row["avg_spo2_pct"]
    assert row["avg_respiration_brpm"]
    assert row["sleep_avg_respiration_brpm"]
    assert row["awake_avg_respiration_brpm"]
    assert row["weekly_avg_ms"]
    assert row["sleep_start_gmt"]
    assert row["deep_sec"]
    assert row["body_battery_charged"]


# v0.3.0 schema, frozen verbatim. The append-only invariant means new
# columns may extend this list (T6 below) but never reorder or remove from
# its prefix — readers iterating columns by index stay stable.
_V030_COLS = [
    "calendar_date", "data_completeness",
    "avg_hr_bpm", "n_hr_readings", "resting_hr_bpm",
    "avg_spo2_pct", "min_spo2_pct", "max_spo2_pct", "n_spo2_readings",
    "avg_respiration_brpm", "min_respiration_brpm", "max_respiration_brpm",
    "n_respiration_readings",
    "sleep_avg_respiration_brpm", "awake_avg_respiration_brpm",
    "weekly_avg_ms", "last_night_avg_ms", "last_night_5min_high_ms",
    "baseline_low_upper", "baseline_balanced_lower", "baseline_balanced_upper",
    "status",
    "sleep_start_gmt", "sleep_end_gmt", "total_sleep_sec",
    "deep_sec", "light_sec", "rem_sec", "awake_sec", "unmeasurable_sec",
    "body_battery_charged", "body_battery_drained",
]


def test_t6_schema_lock_matches_csv_header(tmp_path):
    out_path = _build_full(tmp_path)
    with out_path.open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == DAILY_SUMMARY_COLS
    # And every column appears in the row exactly once
    assert len(header) == len(set(header))
    # v0.3.1: v0.3.0 prefix must remain stable (append-only invariant).
    assert header[: len(_V030_COLS)] == _V030_COLS


# ── T2 ───────────────────────────────────────────────────────────────────────

def test_t2_missing_sleep_official_raises_with_remediation(tmp_path):
    daily = make_daily_csvs(tmp_path)
    sleep_official = make_sleep_official_csv(tmp_path, [])  # empty file
    out_path = tmp_path / "out.csv"
    with pytest.raises(MissingSSOTError) as exc_info:
        build_one(daily, sleep_official,
                  date=SYNTH_SLEEP_DATE, out_path=out_path)
    assert "build_sleep_official" in str(exc_info.value)


# ── T3 ───────────────────────────────────────────────────────────────────────

def test_t3_partial_mode_empties_stage_cols_keeps_others(tmp_path):
    daily = make_daily_csvs(tmp_path)
    sleep_official = make_sleep_official_csv(tmp_path, [])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
        allow_missing_sleep_official=True,
    )
    row = _read_one(out_path)
    assert row["data_completeness"] == "partial"
    # Stage columns are empty in partial mode...
    for col in ("deep_sec", "light_sec", "rem_sec", "awake_sec",
                "unmeasurable_sec", "total_sleep_sec",
                "sleep_start_gmt", "sleep_end_gmt"):
        assert row[col] == "", f"{col} should be empty in partial mode"
    # ...but non-stage columns still populate.
    assert row["avg_hr_bpm"]
    assert row["body_battery_charged"]


# ── T4 ───────────────────────────────────────────────────────────────────────

def test_t4_hrv_passthrough_verbatim(tmp_path):
    out_path = _build_full(tmp_path)
    row = _read_one(out_path)
    # Default hrv_summary_rows: weekly=45, last_night=42, 5min_high=58,
    # baseline_low_upper=38, balanced_lower=40, balanced_upper=50, status=BALANCED
    assert float(row["weekly_avg_ms"]) == 45.0
    assert float(row["last_night_avg_ms"]) == 42.0
    assert float(row["last_night_5min_high_ms"]) == 58.0
    assert float(row["baseline_low_upper"]) == 38.0
    assert float(row["baseline_balanced_lower"]) == 40.0
    assert float(row["baseline_balanced_upper"]) == 50.0
    assert row["status"] == "BALANCED"


# ── T5 ───────────────────────────────────────────────────────────────────────

def test_t5a_respiration_split_inside_outside_window(tmp_path):
    """6 sleep readings + 4 awake readings → both columns populated."""
    out_path = _build_full(tmp_path)
    row = _read_one(out_path)
    sleep_avg = float(row["sleep_avg_respiration_brpm"])
    awake_avg = float(row["awake_avg_respiration_brpm"])
    # Default fixture: sleep readings ~14, awake readings ~18-20
    assert 13 < sleep_avg < 16
    assert 17 < awake_avg < 21


def test_t5b_all_inside_window_awake_avg_is_none(tmp_path):
    """All respiration timestamps inside [session_start, session_end] →
    awake_avg = None."""
    s = SYNTH_SLEEP_TS_START
    sleep_only = [
        (s + timedelta(minutes=30 * i), 14.5) for i in range(8)
    ]
    daily = make_daily_csvs(tmp_path, resp_rows=sleep_only)
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    out_path = tmp_path / "out.csv"
    build_one(daily, sleep_official, date=SYNTH_SLEEP_DATE, out_path=out_path)
    row = _read_one(out_path)
    assert row["sleep_avg_respiration_brpm"]
    assert row["awake_avg_respiration_brpm"] == ""


def test_t5c_all_outside_window_sleep_avg_is_none(tmp_path):
    """All readings outside the sleep window → sleep_avg = None."""
    daytime_base = SYNTH_SLEEP_TS_START.replace(hour=10, minute=0)
    awake_only = [
        (daytime_base + timedelta(minutes=30 * i), 18.0) for i in range(8)
    ]
    daily = make_daily_csvs(tmp_path, resp_rows=awake_only)
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    out_path = tmp_path / "out.csv"
    build_one(daily, sleep_official, date=SYNTH_SLEEP_DATE, out_path=out_path)
    row = _read_one(out_path)
    assert row["sleep_avg_respiration_brpm"] == ""
    assert row["awake_avg_respiration_brpm"]


def test_t5d_empty_session_window_blanks_split_and_partial(tmp_path):
    """Empty session_start → both split columns None + completeness=partial."""
    daily = make_daily_csvs(
        tmp_path,
        session_start="",
        session_end="",
    )
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
    )
    row = _read_one(out_path)
    assert row["sleep_avg_respiration_brpm"] == ""
    assert row["awake_avg_respiration_brpm"] == ""
    assert row["data_completeness"] == "partial"


# ── T11 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag", [
    "write_hr", "write_spo2", "write_respiration",
    "write_sleep_assessment", "write_intraday_rhr",
])
def test_t11_per_input_required_csv_missing_triggers_partial(tmp_path, flag):
    daily = make_daily_csvs(tmp_path, **{flag: False})
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
    )
    row = _read_one(out_path)
    assert row["data_completeness"] == "partial"


def test_t11_hrv_summary_missing_keeps_full(tmp_path):
    """HRV summary is optional — its absence does NOT downgrade to partial."""
    daily = make_daily_csvs(tmp_path, write_hrv_summary=False)
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
    )
    row = _read_one(out_path)
    assert row["data_completeness"] == "full"
    for col in ("weekly_avg_ms", "last_night_avg_ms", "status"):
        assert row[col] == ""


# ── T12 ──────────────────────────────────────────────────────────────────────

def test_t12_header_only_csv_treated_as_missing(tmp_path):
    """Header-only HR CSV (zero data rows) → same partial-mode behavior as missing."""
    daily = make_daily_csvs(tmp_path, hr_rows=[])
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
    )
    row = _read_one(out_path)
    assert row["data_completeness"] == "partial"
    assert row["avg_hr_bpm"] == ""
    assert row["n_hr_readings"] == "0"


# ── T13 ──────────────────────────────────────────────────────────────────────

def test_t13_no_bulk_history_blanks_body_battery_and_partial(tmp_path):
    daily = make_daily_csvs(tmp_path)
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=None,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
    )
    row = _read_one(out_path)
    assert row["body_battery_charged"] == ""
    assert row["body_battery_drained"] == ""
    assert row["data_completeness"] == "partial"


def test_t13_bulk_history_date_missing_blanks_bb(tmp_path):
    daily = make_daily_csvs(tmp_path)
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    # bulk row for a different date — no match for SYNTH_SLEEP_DATE
    bulk = make_bulk_daily_summary_csv(
        tmp_path, [default_bulk_daily_row(date="2000-02-15")]
    )
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
    )
    row = _read_one(out_path)
    assert row["body_battery_charged"] == ""
    assert row["data_completeness"] == "partial"


# ── T14 ──────────────────────────────────────────────────────────────────────

def test_t14_cross_midnight_sleep_window(tmp_path):
    """Sleep window 23:30 (Jan 15) → 07:15 (Jan 16). calendar_date = Jan 15.
    Respiration readings split correctly across midnight."""
    out_path = _build_full(tmp_path)
    row = _read_one(out_path)
    assert row["calendar_date"] == "2000-01-15"
    # sleep_start should fall on Jan 15 in our default fixtures
    assert row["sleep_start_gmt"].startswith("2000-01-15")
    assert row["sleep_end_gmt"].startswith("2000-01-16")
    # The default fixture has resp readings on both sides of midnight inside
    # the sleep window — the split column should be populated, not empty.
    assert row["sleep_avg_respiration_brpm"]


# ── T17 ──────────────────────────────────────────────────────────────────────

def test_t17_multi_row_hrv_takes_latest_with_warning(tmp_path, capsys):
    """Two HRV summary rows → latest wins, warning to stderr."""
    earlier = (
        SYNTH_SLEEP_TS_START.replace(hour=22, minute=0),  # earlier ts
        99, 99, 99, 99, 99, 99, "EARLIER",
    )
    later = (
        SYNTH_SLEEP_TS_END.replace(hour=23, minute=0),    # later ts
        45, 42, 58, 38, 40, 50, "LATER",
    )
    daily = make_daily_csvs(tmp_path, hrv_summary_rows=[earlier, later])
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
    )
    captured = capsys.readouterr()
    assert "HRV summary rows" in captured.err
    row = _read_one(out_path)
    assert row["status"] == "LATER"


# ── T18 ── respiration sentinel filter (issue #10)

def test_t18_respiration_sentinel_filter(tmp_path):
    """-1/-2 Garmin sentinels and sub-physiological values (0-3 brpm) drop
    out of min/max/avg AND out of the sleep/awake split (Codex H7).
    See issue #10."""
    base = SYNTH_SLEEP_TS_START
    awake_base = SYNTH_SLEEP_TS_END + timedelta(hours=2)
    resp_rows = [
        # Inside sleep window: sentinels + valid
        (base + timedelta(minutes=0), -1.0),
        (base + timedelta(minutes=1), -2.0),
        (base + timedelta(minutes=2),  0.0),
        (base + timedelta(minutes=3),  3.0),
        (base + timedelta(minutes=4),  5.0),    # kept
        (base + timedelta(minutes=5), 12.0),    # kept
        (base + timedelta(minutes=6), 20.0),    # kept
        # Outside sleep window: sentinel + valid
        (awake_base + timedelta(minutes=0), -1.0),
        (awake_base + timedelta(minutes=1), 15.0),  # kept
        (awake_base + timedelta(minutes=2), 17.0),  # kept
    ]
    out_path = _build_full(tmp_path, resp_rows=resp_rows)
    row = _read_one(out_path)
    # Aggregate over kept-only [5, 12, 20, 15, 17]
    assert float(row["min_respiration_brpm"]) == 5.0
    assert float(row["max_respiration_brpm"]) == 20.0
    assert abs(float(row["avg_respiration_brpm"]) - 13.8) < 1e-6
    assert int(row["n_respiration_readings"]) == 5
    # Split inherits filter — sleep mean over [5, 12, 20]
    assert abs(float(row["sleep_avg_respiration_brpm"]) - 37.0 / 3.0) < 1e-6
    # Awake mean over [15, 17]
    assert abs(float(row["awake_avg_respiration_brpm"]) - 16.0) < 1e-6


# ── T19 ── HR sleep/awake split (issue #10 part 2)

def test_t19_hr_sleep_awake_split(tmp_path):
    """sleep_avg_hr_bpm and awake_avg_hr_bpm reuse the same window helper as
    respiration. Boundaries are inclusive on both ends — rows at exactly
    session_start or session_end land in the sleep bucket; 1µs after end
    is awake."""
    sleep_start = SYNTH_SLEEP_TS_START
    sleep_end = SYNTH_SLEEP_TS_END
    hr_rows = [
        # Inside sleep window — 4 readings @ 60 bpm
        (sleep_start + timedelta(hours=1), 60),
        (sleep_start + timedelta(hours=2), 60),
        # Outside sleep window — 3 readings @ 80 bpm
        (sleep_end + timedelta(hours=2),   80),
        (sleep_end + timedelta(hours=4),   80),
        # Boundaries — sleep is inclusive on both ends
        (sleep_start,                                    60),  # exact start
        (sleep_end,                                      60),  # exact end
        (sleep_end + timedelta(microseconds=1),          80),  # 1µs after
    ]
    out_path = _build_full(tmp_path, hr_rows=hr_rows)
    row = _read_one(out_path)
    # Sleep readings: 4 × 60 → avg 60.
    assert float(row["sleep_avg_hr_bpm"]) == 60.0
    # Awake readings: 3 × 80 → avg 80.
    assert float(row["awake_avg_hr_bpm"]) == 80.0
    # All-day average over 7 readings stays correct (backward compat).
    assert abs(float(row["avg_hr_bpm"]) - (60 * 4 + 80 * 3) / 7) < 1e-6
    assert int(row["n_hr_readings"]) == 7


# ── T20 ── empty session window blanks HR split + partial (mirrors T5d)

def test_t20_hr_split_empty_session_window(tmp_path):
    """Empty session_start/end blanks the new HR split columns and downgrades
    to partial — same shape as T5d for respiration."""
    out_path = _build_full(tmp_path, session_start="", session_end="")
    row = _read_one(out_path)
    assert row["sleep_avg_hr_bpm"] == ""
    assert row["awake_avg_hr_bpm"] == ""
    # Sanity: existing respiration behavior unchanged.
    assert row["sleep_avg_respiration_brpm"] == ""
    assert row["awake_avg_respiration_brpm"] == ""
    assert row["data_completeness"] == "partial"


# ── T24 ── tz-naive timestamps normalized to LOCAL_TZ (audit F3 / Codex H5)

def test_t24_tz_naive_timestamps_normalized_to_local(tmp_path):
    """Defensive contract: legacy or hand-authored CSVs may emit naive
    timestamps. The window helper interprets naive ts as LOCAL_TZ rather
    than crash on `<=` against the tz-aware session window."""
    from datetime import datetime as _dt
    naive_sleep = _dt(2000, 1, 16, 1, 0)   # 01:00 next day → inside window
    naive_awake = _dt(2000, 1, 15, 14, 0)  # 14:00 same day → outside
    hr_rows = [(naive_sleep, 60), (naive_awake, 80)]
    out_path = _build_full(tmp_path, hr_rows=hr_rows)
    row = _read_one(out_path)
    assert float(row["sleep_avg_hr_bpm"]) == 60.0
    assert float(row["awake_avg_hr_bpm"]) == 80.0


# ── T22 ── all-sentinel respiration → partial (audit F1)

def test_t22_all_sentinel_respiration_partial(tmp_path):
    """Every respiration row is sentinel → all aggregate cells empty,
    n_respiration_readings == 0, completeness=partial. Catches the
    silent-success mode where _REQUIRED_INPUTS sees rows but the filter
    drops all of them."""
    base = SYNTH_SLEEP_TS_START
    resp_rows = [(base + timedelta(minutes=i), -1.0) for i in range(5)]
    out_path = _build_full(tmp_path, resp_rows=resp_rows)
    row = _read_one(out_path)
    assert row["avg_respiration_brpm"] == ""
    assert row["min_respiration_brpm"] == ""
    assert row["max_respiration_brpm"] == ""
    assert row["n_respiration_readings"] == "0"
    assert row["sleep_avg_respiration_brpm"] == ""
    assert row["awake_avg_respiration_brpm"] == ""
    assert row["data_completeness"] == "partial"


# ── T-PII1 ───────────────────────────────────────────────────────────────────

def test_tpii1_no_real_year_dates_in_output(tmp_path):
    """Generated CSV must contain no real-year date strings (years 2010-2099)."""
    out_path = _build_full(tmp_path)
    text = out_path.read_text(encoding="utf-8")
    real_year = re.compile(r"\b20[1-9]\d-\d\d-\d\d\b")
    assert not real_year.search(text), (
        f"real-year date string leaked into output: {real_year.findall(text)}"
    )


# ── Robustness extras ───────────────────────────────────────────────────────

def test_infer_date_from_out_filename(tmp_path):
    """`--out` filename starting with YYYY-MM-DD- yields inferable date."""
    assert _infer_date_from_out(
        tmp_path / "2000-01-15-daily-summary.csv"
    ) == "2000-01-15"
    assert _infer_date_from_out(
        tmp_path / "out" / "2000-01-15-daily-summary.csv"
    ) == "2000-01-15"
    # No leading date → None
    assert _infer_date_from_out(tmp_path / "summary.csv") is None
    # Wrong format → None
    assert _infer_date_from_out(tmp_path / "20000115-daily-summary.csv") is None


def test_build_all_strict_mode_tracks_missing_dates(tmp_path):
    """build_all returns missing-date list for SSOT-strict callers."""
    make_daily_csvs(tmp_path, date="2000-01-15")
    make_daily_csvs(tmp_path, date="2000-01-16")
    # sleep-official only has Jan 15
    sleep_official = make_sleep_official_csv(
        tmp_path, [default_official_row(date="2000-01-15")]
    )
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_dir = tmp_path / "out"
    built, n_partial, missing = build_all(
        tmp_path / "daily", sleep_official, out_dir,
        bulk_history_path=bulk,
        allow_missing_sleep_official=False,
    )
    assert [p.name for p in built] == ["2000-01-15-daily-summary.csv"]
    assert missing == ["2000-01-16"]
    assert n_partial == 0


def test_build_all_permissive_mode_no_missing(tmp_path):
    """allow_missing_sleep_official=True → all dates build, missing list empty."""
    make_daily_csvs(tmp_path, date="2000-01-15")
    make_daily_csvs(tmp_path, date="2000-01-16")
    sleep_official = make_sleep_official_csv(
        tmp_path, [default_official_row(date="2000-01-15")]
    )
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_dir = tmp_path / "out"
    built, _, missing = build_all(
        tmp_path / "daily", sleep_official, out_dir,
        bulk_history_path=bulk,
        allow_missing_sleep_official=True,
    )
    assert len(built) == 2
    assert missing == []


def test_partial_flag_with_present_official_keeps_full(tmp_path):
    """--allow-missing-sleep-official is permissive, not forced-partial."""
    daily = make_daily_csvs(tmp_path)
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    bulk = make_bulk_daily_summary_csv(tmp_path, [default_bulk_daily_row()])
    out_path = tmp_path / "out.csv"
    build_one(
        daily, sleep_official,
        bulk_history_path=bulk,
        date=SYNTH_SLEEP_DATE, out_path=out_path,
        allow_missing_sleep_official=True,
    )
    row = _read_one(out_path)
    assert row["data_completeness"] == "full"
    assert row["deep_sec"]

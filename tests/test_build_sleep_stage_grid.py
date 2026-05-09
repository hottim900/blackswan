"""Tests for `build_sleep_stage_grid` — minute-grid stage expansion.

Covers:
- T7   60s default grid: row count = ceil(window / 60s) + 1
- T8   stage_at inheritance through brief awake arousals
- T9   empty (header-only) sleep-levels.csv → skip with warning
- T15  invalid granularity raises ValueError naming allowed values
- T22  single-row sleep-levels → skip-with-warn (matches _sleep_window contract)
- T23  duplicate timestamps → latest wins
- T24  unsorted input → defensive sort
- T25  all-awake transitions → empty `stage` column + warn (stage_at default)
"""

from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

import pytest

from blackswan.build_sleep_stage_grid import (
    ALLOWED_GRANULARITY_SEC,
    build_all,
    build_one,
    expand_to_grid,
)
from tests._sleep_helpers import (
    SYNTH_SLEEP_DATE,
    SYNTH_SLEEP_TS_END,
    SYNTH_SLEEP_TS_START,
    make_daily_csvs,
)


def _read_grid(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_t7_60s_grid_default(tmp_path):
    """Default 60s cadence → one row per minute over the window inclusive."""
    s = SYNTH_SLEEP_TS_START
    levels = [
        (s, "light"),
        (s + timedelta(minutes=10), "deep"),
        (s + timedelta(minutes=30), "rem"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    out_path = build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    assert out_path is not None and out_path.exists()
    rows = _read_grid(out_path)
    # window is 30 min wide, inclusive endpoints @ 60s = 31 rows
    assert len(rows) == 31
    assert rows[0]["timestamp"] == s.isoformat()


def test_t7_30s_grid_doubles_density(tmp_path):
    """30s cadence emits 2× rows of the 60s grid."""
    s = SYNTH_SLEEP_TS_START
    levels = [
        (s, "light"),
        (s + timedelta(minutes=10), "deep"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    out_path = build_one(daily, out_dir, SYNTH_SLEEP_DATE, granularity_sec=30)
    rows = _read_grid(out_path)
    # 10 min @ 30s inclusive = 21 rows
    assert len(rows) == 21


def test_t8_brief_awake_inherits_prior_non_awake(tmp_path):
    """A brief awake arousal mid-deep does NOT change the grid stage."""
    s = SYNTH_SLEEP_TS_START
    levels = [
        (s, "deep"),
        (s + timedelta(minutes=10), "awake"),     # arousal
        (s + timedelta(minutes=11), "deep"),      # back to deep
        (s + timedelta(minutes=20), "light"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    rows = _read_grid(out_dir / f"{SYNTH_SLEEP_DATE}-sleep-stage-grid.csv")
    by_min = {i: rows[i]["stage"] for i in range(len(rows))}
    # minute 10 (the awake row) inherits deep, since stage_at skips awake
    assert by_min[10] == "deep"
    # minute 11 onward is back to deep (matching), then transitions to light
    assert by_min[11] == "deep"
    assert by_min[20] == "light"


def test_t8_awake_followed_by_light_switches_to_light(tmp_path):
    """When the arousal is followed by a different stage, grid switches."""
    s = SYNTH_SLEEP_TS_START
    levels = [
        (s, "deep"),
        (s + timedelta(minutes=10), "awake"),
        (s + timedelta(minutes=11), "light"),
        (s + timedelta(minutes=20), "rem"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    rows = _read_grid(out_dir / f"{SYNTH_SLEEP_DATE}-sleep-stage-grid.csv")
    assert rows[10]["stage"] == "deep"   # at the arousal moment, still deep
    assert rows[11]["stage"] == "light"  # one minute later, now light


def test_t9_empty_sleep_levels_skips_with_warning(tmp_path, capsys):
    """Header-only sleep-levels CSV → skip, no exception, no output file."""
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=[])
    out_dir = tmp_path / "stage-grid"
    result = build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    captured = capsys.readouterr()
    assert result is None
    assert "skipping" in captured.err
    # no output file should have been written
    assert not (out_dir / f"{SYNTH_SLEEP_DATE}-sleep-stage-grid.csv").exists()


def test_t15_invalid_granularity_raises(tmp_path):
    """Granularity not in {30, 60} → ValueError naming the allowed values."""
    daily = make_daily_csvs(tmp_path)
    out_dir = tmp_path / "stage-grid"
    for bad in (1, 45, 120):
        with pytest.raises(ValueError, match=str(ALLOWED_GRANULARITY_SEC)):
            build_one(daily, out_dir, SYNTH_SLEEP_DATE, granularity_sec=bad)


def test_t22_single_row_sleep_levels_skips(tmp_path, capsys):
    """One transition cannot define a window — skip with warning."""
    s = SYNTH_SLEEP_TS_START
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=[(s, "light")])
    out_dir = tmp_path / "stage-grid"
    result = build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    captured = capsys.readouterr()
    assert result is None
    assert "skipping" in captured.err


def test_t23_duplicate_timestamps_latest_wins(tmp_path):
    """Two rows with identical timestamps → latest level wins after sort."""
    s = SYNTH_SLEEP_TS_START
    levels = [
        (s, "light"),
        (s + timedelta(minutes=10), "deep"),
        (s + timedelta(minutes=10), "rem"),       # dup ts, different level
        (s + timedelta(minutes=20), "light"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    rows = _read_grid(out_dir / f"{SYNTH_SLEEP_DATE}-sleep-stage-grid.csv")
    # At minute 10, the deduped level should be 'rem' (the latest of the dup)
    assert rows[10]["stage"] == "rem"


def test_t24_unsorted_input_is_defensively_sorted(tmp_path):
    """Out-of-order rows on disk → output is still time-ordered."""
    s = SYNTH_SLEEP_TS_START
    # Write rows in reverse chronological order
    levels = [
        (s + timedelta(minutes=20), "light"),
        (s, "deep"),
        (s + timedelta(minutes=10), "rem"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    rows = _read_grid(out_dir / f"{SYNTH_SLEEP_DATE}-sleep-stage-grid.csv")
    # Row 0 must be the actual earliest timestamp
    assert rows[0]["timestamp"] == s.isoformat()
    # Output strictly increasing
    timestamps = [r["timestamp"] for r in rows]
    assert timestamps == sorted(timestamps)


def test_t25_all_awake_emits_empty_stage_with_warning(tmp_path, capsys):
    """All-awake transitions → grid stage is the empty string + warning."""
    s = SYNTH_SLEEP_TS_START
    levels = [
        (s, "awake"),
        (s + timedelta(minutes=10), "awake"),
        (s + timedelta(minutes=20), "awake"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    captured = capsys.readouterr()
    assert "all transitions are awake" in captured.err
    rows = _read_grid(out_dir / f"{SYNTH_SLEEP_DATE}-sleep-stage-grid.csv")
    assert all(r["stage"] == "" for r in rows)


def test_expand_to_grid_pure(tmp_path):
    """Direct unit test of the pure helper — no I/O."""
    s = SYNTH_SLEEP_TS_START
    transitions = [
        (s, "light"),
        (s + timedelta(minutes=5), "deep"),
        (s + timedelta(minutes=10), "rem"),
    ]
    rows = expand_to_grid(transitions, granularity_sec=60)
    assert len(rows) == 11  # 0..10 inclusive
    assert rows[0] == (s.isoformat(), "light")
    assert rows[5][1] == "deep"
    assert rows[10][1] == "rem"


def test_build_all_processes_every_date(tmp_path):
    """build_all walks the dir and emits one grid per usable date."""
    for date in ("2000-01-15", "2000-01-16"):
        make_daily_csvs(tmp_path, date=date)
    out_dir = tmp_path / "stage-grid"
    paths = build_all(tmp_path / "daily", out_dir)
    assert {p.name for p in paths} == {
        "2000-01-15-sleep-stage-grid.csv",
        "2000-01-16-sleep-stage-grid.csv",
    }


def test_window_endpoints_match_first_and_last_transition(tmp_path):
    """Output spans [first_ts, last_ts] inclusive."""
    s = SYNTH_SLEEP_TS_START
    e = SYNTH_SLEEP_TS_END
    levels = [
        (s, "light"),
        (s + timedelta(minutes=240), "deep"),
        (e, "awake"),
    ]
    daily = make_daily_csvs(tmp_path, sleep_levels_rows=levels)
    out_dir = tmp_path / "stage-grid"
    build_one(daily, out_dir, SYNTH_SLEEP_DATE)
    rows = _read_grid(out_dir / f"{SYNTH_SLEEP_DATE}-sleep-stage-grid.csv")
    assert rows[0]["timestamp"] == s.isoformat()
    # The last grid timestamp is at-or-before e (granularity 60s, e is on a
    # minute boundary so it's exactly e).
    assert rows[-1]["timestamp"] == e.isoformat()

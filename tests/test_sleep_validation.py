"""Tests for `_sleep_validation.py` — naive/smart transition math vs official.

Covers:
- T10  smoke: 3-night synthetic fixture round-trips through CLI
- T18  naive ratio math hand-calc
- T19  zero-denominator (awake_sec=0) → None, rendered as "—"
- T20  smart with no non-awake transitions doesn't crash
- T21  outlier IDs default to night_N; anonymize=False flips to real dates
"""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from blackswan._sleep_validation import (
    aggregate,
    collect_nights,
    compute_ratios,
    find_outliers,
    naive_durations,
    render_markdown,
    smart_durations,
)
from tests._sleep_helpers import (
    SYNTH_SLEEP_DATE,
    SYNTH_SLEEP_TS_END,
    SYNTH_SLEEP_TS_START,
    default_official_row,
    make_daily_csvs,
    make_sleep_official_csv,
)


def test_t18_naive_ratio_math_hand_calc():
    """Hand-calculated transitions/official ratios per stage."""
    s = SYNTH_SLEEP_TS_START
    transitions = [
        (s, "deep"),                              # deep: +600s
        (s + timedelta(seconds=600), "light"),    # light: +300s
        (s + timedelta(seconds=900), "awake"),    # awake: +60s
        (s + timedelta(seconds=960), "rem"),      # rem: +1200s
        (s + timedelta(seconds=2160), "awake"),   # last → 0s contribution
    ]
    naive = naive_durations(transitions)
    assert naive == {"awake": 60.0, "deep": 600.0, "light": 300.0, "rem": 1200.0}

    official = {"awake": 30.0, "deep": 600.0, "light": 600.0, "rem": 1200.0}
    ratios = compute_ratios(naive, official)
    assert ratios["awake"] == 2.0      # 60/30
    assert ratios["deep"] == 1.0       # 600/600
    assert ratios["light"] == 0.5      # 300/600
    assert ratios["rem"] == 1.0        # 1200/1200


def test_smart_collapses_awake_into_surrounding_stage():
    """Smart awake is always 0; awake-flanked time merges into the prior stage."""
    s = SYNTH_SLEEP_TS_START
    transitions = [
        (s, "deep"),
        (s + timedelta(seconds=600), "awake"),    # 60s arousal
        (s + timedelta(seconds=660), "rem"),
        (s + timedelta(seconds=1860), "awake"),   # last
    ]
    end_ts = transitions[-1][0]
    smart = smart_durations(transitions, end_ts)
    # deep absorbs the awake gap (660-0 = 660s); rem runs to end (1860-660 = 1200s)
    assert smart == {"awake": 0.0, "deep": 660.0, "light": 0.0, "rem": 1200.0}


def test_t19_zero_denominator_returns_none():
    """awake_sec=0 in official → ratio is None, not inf or division error."""
    naive = {"awake": 600.0, "deep": 0.0, "light": 0.0, "rem": 0.0}
    official = {"awake": 0.0, "deep": 5400.0, "light": None, "rem": 0.0}
    ratios = compute_ratios(naive, official)
    assert ratios["awake"] is None       # zero denominator
    assert ratios["deep"] == 0.0         # legit zero numerator, nonzero denom
    assert ratios["light"] is None       # missing official
    assert ratios["rem"] is None         # zero denominator


def test_t20_smart_no_non_awake_doesnt_crash():
    """All-awake transitions: smart contributes 0 to every stage, no crash."""
    s = SYNTH_SLEEP_TS_START
    transitions = [
        (s, "awake"),
        (s + timedelta(seconds=600), "awake"),
        (s + timedelta(seconds=1200), "awake"),
    ]
    smart = smart_durations(transitions, transitions[-1][0])
    assert smart == {"awake": 0.0, "deep": 0.0, "light": 0.0, "rem": 0.0}


def test_t19_renders_em_dash_in_markdown(tmp_path):
    """When official awake_sec=0, awake naive line is all em-dashes."""
    make_daily_csvs(tmp_path)
    official_row = default_official_row()
    official_row["awake_sec"] = "0"
    sleep_official = make_sleep_official_csv(tmp_path, [official_row])
    nights = collect_nights(tmp_path / "daily", sleep_official)
    assert len(nights) == 1
    aggs = aggregate(nights)
    md = render_markdown(nights, aggs, find_outliers(nights))
    awake_naive_line = next(
        line for line in md.splitlines() if line.startswith("| awake | naive |")
    )
    # awake ratio is None on both methods → n=0, all 6 stat columns dashed
    assert "| 0 | — | — | — | — | — | — |" in awake_naive_line


def test_t21_outliers_anonymize_default_to_night_n(tmp_path):
    """Outlier IDs default to night_N. anonymize=False flips to real dates."""
    s = SYNTH_SLEEP_TS_START
    long_awake_levels = [
        (s, "light"),
        (s + timedelta(minutes=10), "awake"),
        (s + timedelta(minutes=22), "light"),     # 12 min naive "awake"
        (s + timedelta(minutes=240), "awake"),    # last
    ]
    make_daily_csvs(tmp_path, sleep_levels_rows=long_awake_levels)
    official_row = default_official_row()
    official_row["awake_sec"] = "60"   # 1 min — naive ratio = 12.0×
    sleep_official = make_sleep_official_csv(tmp_path, [official_row])

    nights = collect_nights(tmp_path / "daily", sleep_official)
    outliers = find_outliers(nights)
    assert len(outliers) == 1
    aggs = aggregate(nights)

    md_anon = render_markdown(nights, aggs, outliers, anonymize=True)
    md_real = render_markdown(nights, aggs, outliers, anonymize=False)
    assert "night_1" in md_anon
    assert SYNTH_SLEEP_DATE not in md_anon
    assert SYNTH_SLEEP_DATE in md_real
    assert "night_1" not in md_real


def test_t10_smoke_three_night_fixture(tmp_path):
    """End-to-end CLI smoke: 3 nights → table generated with naive+smart rows."""
    s = SYNTH_SLEEP_TS_START
    e = SYNTH_SLEEP_TS_END
    nights_data = [
        ("2000-01-15", "300", "5400", "10800", "5400"),
        ("2000-01-16", "240", "5100", "10500", "5700"),
        ("2000-01-17", "360", "5700", "11100", "5100"),
    ]
    rows = []
    for date, awake_sec, deep_sec, light_sec, rem_sec in nights_data:
        levels = [
            (s, "light"),
            (s + timedelta(minutes=30), "deep"),
            (s + timedelta(minutes=120), "rem"),
            (s + timedelta(minutes=160), "light"),
            (e, "awake"),
        ]
        make_daily_csvs(tmp_path, date=date, sleep_levels_rows=levels)
        row = default_official_row(date=date)
        row["awake_sec"] = awake_sec
        row["deep_sec"] = deep_sec
        row["light_sec"] = light_sec
        row["rem_sec"] = rem_sec
        rows.append(row)
    sleep_official = make_sleep_official_csv(tmp_path, rows)
    daily_dir = tmp_path / "daily"

    out_path = tmp_path / "validation.md"
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "sleep_transition_vs_official.py"

    subprocess.run(
        [sys.executable, str(script),
         "--daily-dir", str(daily_dir),
         "--sleep-official", str(sleep_official),
         "--out", str(out_path)],
        capture_output=True, text=True, check=True,
    )
    md = out_path.read_text(encoding="utf-8")
    assert "n=3" in md
    assert "| awake | naive |" in md
    assert "| awake | smart |" in md
    assert "| deep | naive |" in md
    assert "| deep | smart |" in md
    # Default CLI flow anonymizes; no real dates leak into the output.
    assert "2000-01-1" not in md


def test_collect_nights_skips_dates_without_official(tmp_path):
    """A date with sleep-levels but no official row is silently dropped."""
    make_daily_csvs(tmp_path, date="2000-01-15")
    make_daily_csvs(tmp_path, date="2000-01-16")
    sleep_official = make_sleep_official_csv(
        tmp_path, [default_official_row(date="2000-01-15")]
    )
    nights = collect_nights(tmp_path / "daily", sleep_official)
    assert [n.date for n in nights] == ["2000-01-15"]
    assert nights[0].night_id == 1


def test_collect_nights_skips_singleton_transitions(tmp_path):
    """A night with only one sleep-level row has no window — skipped."""
    s = SYNTH_SLEEP_TS_START
    make_daily_csvs(tmp_path, sleep_levels_rows=[(s, "light")])
    sleep_official = make_sleep_official_csv(tmp_path, [default_official_row()])
    nights = collect_nights(tmp_path / "daily", sleep_official)
    assert nights == []


def test_aggregate_empty_input_returns_zero_n():
    """Empty pool of valid ratios → StageStats(0, None, ...)."""
    aggs = aggregate([])
    s = aggs[("awake", "naive")]
    assert s.n == 0
    assert all(v is None for v in (s.min, s.median, s.max, s.mean))

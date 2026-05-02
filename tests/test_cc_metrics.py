"""Synthetic-data tests for cc_metrics.

Covers the comparison primitives used in Layer 3 (cross-session) without
needing real FIT files. All TrialStats here are hand-built.
"""
from __future__ import annotations

import pytest

from blackswan.cc_metrics import (
    TrialStats,
    cc_back_half_mean,
    cc_trial_2_3_mean,
    compare_sessions,
    compute_confounders,
)


def trial(
    *,
    dur: float = 120.0,
    dist: float = 200.0,
    kmh: float = 6.0,
    grade: float = 15.0,
    start_hr: float = 130.0,
    avg_hr: float = 150.0,
    max_hr: float = 170.0,
    cc: float = 25.0,
) -> TrialStats:
    return TrialStats(
        dur=dur, dist=dist, kmh=kmh, grade=grade,
        start_hr=start_hr, avg_hr=avg_hr, max_hr=max_hr, cc=cc,
    )


# ── Mean helpers ──────────────────────────────────────────────────────────────

def test_cc_trial_2_3_mean_picks_indices_1_and_2():
    trials = [trial(cc=20), trial(cc=25), trial(cc=30), trial(cc=35)]
    # 1-indexed "trial 2 + trial 3" = 0-indexed [1] + [2] = (25 + 30) / 2
    assert cc_trial_2_3_mean(trials) == pytest.approx(27.5)


def test_cc_trial_2_3_mean_returns_none_when_fewer_than_3():
    assert cc_trial_2_3_mean([]) is None
    assert cc_trial_2_3_mean([trial()]) is None
    assert cc_trial_2_3_mean([trial(), trial()]) is None


def test_cc_back_half_mean_averages_from_index_2():
    trials = [trial(cc=20), trial(cc=25), trial(cc=30), trial(cc=35)]
    # mean of trials[2:] = (30 + 35) / 2
    assert cc_back_half_mean(trials) == pytest.approx(32.5)


def test_cc_back_half_mean_returns_none_when_fewer_than_3():
    assert cc_back_half_mean([trial(), trial()]) is None


# ── Confounder math ───────────────────────────────────────────────────────────

def test_compute_confounders_grade_only():
    """Baseline 2% steeper than recent → positive grade_penalty_cc."""
    b = [trial(grade=10.0, dur=120.0, kmh=5.0)] * 4
    r = [trial(grade=8.0, dur=120.0, kmh=5.0)] * 4
    c = compute_confounders(b, r)
    # grade_diff = 10 - 8 = +2
    # hr_penalty = 2 * 1.5 = 3.0 bpm
    # cc_penalty = 3.0 / 5 km/h = 0.6
    assert c.grade_diff == pytest.approx(2.0)
    assert c.grade_penalty_cc == pytest.approx(0.6)
    assert c.duration_penalty_cc == pytest.approx(0.0)


def test_compute_confounders_duration_only():
    """Baseline 60s longer than recent → positive duration_penalty_cc."""
    b = [trial(dur=180.0, grade=10.0, kmh=5.0)] * 4
    r = [trial(dur=120.0, grade=10.0, kmh=5.0)] * 4
    c = compute_confounders(b, r, drift_bpm_per_min=8.0)
    # dur_diff = 180 - 120 = +60s = +1 min
    # hr_penalty = 1 * 8.0 = 8.0 bpm
    # cc_penalty = 8.0 / 5 = 1.6
    assert c.dur_diff == pytest.approx(60.0)
    assert c.duration_penalty_cc == pytest.approx(1.6)
    assert c.grade_penalty_cc == pytest.approx(0.0)
    assert c.drift_used == pytest.approx(8.0)


def test_compute_confounders_default_drift_is_7_5():
    b = [trial(dur=180.0)] * 3
    r = [trial(dur=120.0)] * 3
    c = compute_confounders(b, r)
    assert c.drift_used == pytest.approx(7.5)


def test_total_cc_penalty_sums_components():
    b = [trial(grade=10.0, dur=180.0, kmh=5.0)] * 4
    r = [trial(grade=8.0, dur=120.0, kmh=5.0)] * 4
    c = compute_confounders(b, r, drift_bpm_per_min=7.5)
    assert c.total_cc_penalty == pytest.approx(c.grade_penalty_cc + c.duration_penalty_cc)


# ── compare_sessions integration ──────────────────────────────────────────────

def test_compare_sessions_basic():
    b = [trial(cc=30), trial(cc=28), trial(cc=27), trial(cc=26)]
    r = [trial(cc=29), trial(cc=27), trial(cc=26), trial(cc=25)]
    rep = compare_sessions(b, r)
    # raw 2-3 = (26+25)/2 - (27+26)/2 = 25.5 - 26.5 = -1.0
    assert rep.raw_delta_2_3 == pytest.approx(-1.0)
    # raw back-half = (26+25)/2 - (27+26)/2 = same here
    assert rep.raw_delta_back == pytest.approx(-1.0)


def test_compare_sessions_noise_floor_is_5_percent_of_baseline_mean():
    b = [trial(cc=30), trial(cc=30), trial(cc=30)]
    r = [trial(cc=28), trial(cc=28), trial(cc=28)]
    rep = compare_sessions(b, r)
    assert rep.cc_noise_floor == pytest.approx(30.0 * 0.05)


def test_compare_sessions_raises_on_too_few_trials():
    b = [trial(), trial()]  # only 2
    r = [trial(), trial(), trial()]
    with pytest.raises(ValueError):
        compare_sessions(b, r)


def test_compare_sessions_excluded_indices_are_filtered():
    """Excluded trials drop out before metrics — exclusion of an outlier
    pulls trial-2-3 mean closer to baseline."""
    b = [trial(cc=30), trial(cc=28), trial(cc=27), trial(cc=26)]
    r = [trial(cc=29), trial(cc=10), trial(cc=27), trial(cc=26)]  # idx 1 outlier
    rep = compare_sessions(b, r, excluded_indices_recent={1})
    # After excluding idx 1, recent = [29, 27, 26]; trial-2-3 = (27+26)/2 = 26.5
    # baseline trial-2-3 = (28+27)/2 = 27.5; raw = -1.0
    assert rep.raw_delta_2_3 == pytest.approx(-1.0)

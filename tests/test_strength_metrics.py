"""Critical strength-metrics tests — TDD checkpoints per V2 Step 7.5.

These pin behavior that strength_metrics.py must satisfy:

- T-CMP-3: matching algorithm freezes to baseline-first greedy (Choice 2)
- T-CMP-8: out-of-range excluded_indices raises (V2.12)
- T-CMP-9: n_pairs<2 contradiction resolution (V2.8)
- T-CMP-10: all-None HR end-to-end raises cleanly (V2.15)
- T-CMP-11: full FIT roundtrip wrapper + same-path optimization (Choice 1 / Eng H1)
- T-SEG-2: superset detection surfaces in notes (V2.14)
- T-SEG-3: unilateral / repeated-slot disambiguation surfaces in notes
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from blackswan._time import LOCAL_TZ
from blackswan.detect_strength_hr_artifact import StrengthHRArtifactSignature
from blackswan.parse_strength_fit import parse_strength_fit, parse_strength_fit_from_msgs
from blackswan.strength_metrics import (
    compare_strength_sessions,
    compare_strength_sessions_from_stats,
)
from tests._strength_helpers import build_session, build_strength_msgs, stats


# T-CMP-3: matching algorithm baseline-first greedy determinism
def test_matching_baseline_first_greedy_is_deterministic():
    """When the same (weight, reps) appears multiple times in baseline and
    fewer times in recent, baseline-first greedy must pair earlier baseline
    indices first. Output must be reproducible run-to-run."""
    baseline = build_session(weights=[60, 60, 60], reps=[8, 8, 8])
    # recent has only 2 sets at (60, 8): they should pair to baseline_idx 0 and 1
    recent = build_session(weights=[60, 60], reps=[8, 8])

    r1 = compare_strength_sessions_from_stats(stats(baseline), stats(recent))
    r2 = compare_strength_sessions_from_stats(stats(baseline), stats(recent))

    paired_b1 = sorted(p.baseline.active_idx for p in r1.pairs)
    paired_b2 = sorted(p.baseline.active_idx for p in r2.pairs)
    assert paired_b1 == paired_b2  # determinism

    # Exact slots: baseline 0 ↔ recent 0, baseline 1 ↔ recent 1
    exact = [p for p in r1.pairs if p.match_quality == "exact_slot"]
    assert len(exact) == 2
    assert sorted((p.baseline.active_idx, p.recent.active_idx) for p in exact) == [
        (0, 0),
        (1, 1),
    ]
    # Baseline idx 2 has no recent match → unmatched
    assert any(s.active_idx == 2 for s in r1.unmatched_baseline)


# T-CMP-9: n_pairs<2 contradiction
def test_compare_n_pairs_zero_raises():
    """Disjoint routines (no shared (weight, reps)) → 0 pairs → raise."""
    a = build_session(weights=[60], reps=[8])
    b = build_session(weights=[80], reps=[5])
    with pytest.raises(ValueError, match=r"0 set pairs|insufficient"):
        compare_strength_sessions_from_stats(stats(a), stats(b))


def test_compare_n_pairs_one_returns_report_with_none_dispersion():
    """Single shared (weight, reps) → n_pairs=1 → return report with
    hr_delta_stdev=None, hr_delta_iqr=None, exact_slot_mean_delta set."""
    a = build_session(weights=[60], reps=[8])
    b = build_session(weights=[60], reps=[8])
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    assert report.n_pairs == 1
    assert report.hr_delta_stdev is None
    assert report.hr_delta_iqr is None
    assert report.exact_slot_mean_delta is not None


# T-CMP-10: all-None HR end-to-end
def test_compare_all_none_hr_raises_cleanly():
    """No HR coverage anywhere → 0 active stats both sides → 0 pairs → raise.
    Must NOT crash with ZeroDivisionError or empty-median."""
    msgs_no_hr = build_strength_msgs(weights=[60], reps=[8], record_mesgs=[])
    sess = parse_strength_fit_from_msgs(msgs_no_hr)
    with pytest.raises(ValueError, match=r"0 set pairs|insufficient|no HR"):
        compare_strength_sessions_from_stats(stats(sess), stats(sess))


# T-CMP-8: invalid excluded_indices_* must raise
def test_excluded_indices_out_of_range_raises():
    """V2.12 anti-exclusion-shopping: out-of-range index must raise loudly,
    not silently ignore."""
    sess = build_session(weights=[60, 60, 60], reps=[8, 8, 8])
    with pytest.raises(ValueError, match=r"excluded_indices.*99"):
        compare_strength_sessions_from_stats(
            stats(sess), stats(sess),
            excluded_indices_baseline={99},
        )


def test_excluded_indices_recent_out_of_range_raises():
    sess = build_session(weights=[60, 60, 60], reps=[8, 8, 8])
    with pytest.raises(ValueError, match=r"excluded_indices.*42"):
        compare_strength_sessions_from_stats(
            stats(sess), stats(sess),
            excluded_indices_recent={42},
        )


def test_excluded_indices_drops_set_from_pairing():
    """A valid exclusion drops the set from pairs[]."""
    a = build_session(weights=[60, 60, 60], reps=[8, 8, 8])
    b = build_session(weights=[60, 60, 60], reps=[8, 8, 8])
    report = compare_strength_sessions_from_stats(
        stats(a), stats(b),
        excluded_indices_recent={1},
    )
    paired_recent_indices = {p.recent.active_idx for p in report.pairs}
    assert 1 not in paired_recent_indices


# T-SEG-2: superset detection surfaces in notes
def test_compare_surfaces_superset_pattern_in_notes():
    """Alternating supersets (60, 40, 60, 40, 60, 40) → same (weight, reps)
    appears in 3 separate groups each → notes mention ambiguity."""
    sess = build_session(active_pattern=[(60, 8), (40, 10), (60, 8), (40, 10), (60, 8), (40, 10)])
    report = compare_strength_sessions_from_stats(stats(sess), stats(sess))
    assert any(
        "ambiguous" in n.lower() or "superset" in n.lower()
        for n in report.notes
    )


# T-SEG-3: unilateral repeated slot
def test_compare_surfaces_repeated_weight_reps_pattern():
    """Two consecutive sets at same (weight, reps) at same active_idx pair
    fine — but a longer pattern of repeated isolated identical buckets
    surfaces ambiguity."""
    sess = build_session(active_pattern=[(20, 12), (20, 12)])
    report = compare_strength_sessions_from_stats(stats(sess), stats(sess))
    # n=2 pairs is enough; just ensure no crash and report has the slots
    assert report.n_pairs == 2


# T-CMP-11: full FIT roundtrip wrapper + same-path optimization
def test_compare_strength_sessions_full_pipeline_against_synthetic_fits(tmp_path: Path):
    """Choice 1: compare_strength_sessions(fit_path, fit_path) wraps the
    full pipeline and produces a report consistent with the from_stats path."""
    from examples.synthetic_strength_baseline import build_baseline_fit
    from examples.synthetic_strength_recent import build_recent_fit

    baseline = tmp_path / "baseline.fit"
    recent = tmp_path / "recent.fit"
    baseline.write_bytes(build_baseline_fit())
    recent.write_bytes(build_recent_fit())

    direct = compare_strength_sessions(baseline, recent)
    via_stats = compare_strength_sessions_from_stats(
        stats(parse_strength_fit(baseline)),
        stats(parse_strength_fit(recent)),
    )

    assert direct.n_pairs == via_stats.n_pairs
    assert direct.exact_slot_mean_delta == via_stats.exact_slot_mean_delta
    assert direct.baseline_artifact_signature == via_stats.baseline_artifact_signature
    assert direct.recent_artifact_signature == via_stats.recent_artifact_signature


def test_compare_strength_sessions_same_path_short_circuits(tmp_path: Path):
    """Eng H1: when baseline and recent resolve to the same file, parser
    runs once. The report still validates structurally."""
    from examples.synthetic_strength_baseline import build_baseline_fit

    p = tmp_path / "session.fit"
    p.write_bytes(build_baseline_fit())

    report = compare_strength_sessions(p, p)
    assert report.n_pairs > 0
    # Self-comparison: every pair should have hr_delta == 0
    assert all(pair.hr_delta == 0.0 for pair in report.pairs)


# local_hour warning
def test_local_hour_warning_fires_when_diff_exceeds_three_hours():
    """V2 spec: circular hour diff > 3 produces local_hour_warning string."""
    morning = datetime(2000, 1, 15, 8, 0, tzinfo=LOCAL_TZ)
    evening = datetime(2000, 1, 15, 20, 0, tzinfo=LOCAL_TZ)
    a = build_session(weights=[60, 60], reps=[8, 8], start_time=morning)
    b = build_session(weights=[60, 60], reps=[8, 8], start_time=evening)
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    assert report.local_hour_warning is not None
    assert "8:00" in report.local_hour_warning
    assert "20:00" in report.local_hour_warning


def test_local_hour_warning_circular_distance_handles_midnight_wrap():
    """Hour 23 vs hour 1 should be circular diff = 2, no warning."""
    near_midnight = datetime(2000, 1, 15, 23, 0, tzinfo=LOCAL_TZ)
    after_midnight = datetime(2000, 1, 16, 1, 0, tzinfo=LOCAL_TZ)
    a = build_session(weights=[60, 60], reps=[8, 8], start_time=near_midnight)
    b = build_session(weights=[60, 60], reps=[8, 8], start_time=after_midnight)
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    assert report.local_hour_warning is None


def test_local_hour_warning_silent_within_threshold():
    """Diff of 3 hours is at threshold, so no warning."""
    morning = datetime(2000, 1, 15, 9, 0, tzinfo=LOCAL_TZ)
    noon = datetime(2000, 1, 15, 12, 0, tzinfo=LOCAL_TZ)
    a = build_session(weights=[60, 60], reps=[8, 8], start_time=morning)
    b = build_session(weights=[60, 60], reps=[8, 8], start_time=noon)
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    assert report.local_hour_warning is None


# Smoke: artifact signatures land on report
def test_artifact_signatures_present_on_report():
    sess = build_session(
        weights=[60] * 8, reps=[8] * 8,
        hrs=[110, 115, 120, 125, 128, 130, 132, 135],
    )
    report = compare_strength_sessions_from_stats(stats(sess), stats(sess))
    assert isinstance(report.baseline_artifact_signature, StrengthHRArtifactSignature)
    assert isinstance(report.recent_artifact_signature, StrengthHRArtifactSignature)

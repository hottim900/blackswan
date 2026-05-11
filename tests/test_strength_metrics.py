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
from blackswan.segment_strength_sets import identify_exercises
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


# T-SEG-2: superset detection surfaces in notes + groups split correctly
def test_compare_surfaces_superset_pattern_in_notes():
    """Alternating supersets (60, 40, 60, 40, 60, 40) → identify_exercises
    yields 6 groups (one per active set) because no two adjacent active sets
    share (weight, reps). The strength_metrics layer then detects this as
    ambiguous in notes."""
    sess = build_session(active_pattern=[(60, 8), (40, 10), (60, 8), (40, 10), (60, 8), (40, 10)])

    # Direct assertion on the segmenter — catches a regression that merges
    # adjacent groups even when signatures differ. The note assertion below
    # only catches one specific downstream consumer; this catches the source.
    groups = identify_exercises(sess)
    assert len(groups) == 6

    report = compare_strength_sessions_from_stats(stats(sess), stats(sess))
    assert any(
        "ambiguous" in n.lower() or "superset" in n.lower()
        for n in report.notes
    )


# T-SEG-3: unilateral repeated slot — known spec gap
def test_compare_surfaces_repeated_weight_reps_pattern():
    """Two consecutive sets at same (weight, reps) at same active_idx pair
    fine. No notes ambiguity is expected for contiguous repeats: the
    ``_count_ambiguous_groupings`` heuristic only flags non-contiguous
    occurrences (max_idx - min_idx > len - 1), so two adjacent (20, 12)
    sets correctly produce one group with no ambiguity flag.

    This test pins the n_pairs smoke contract; broader unilateral
    detection (interleaved L/R sets at the same weight/reps) is a known
    gap because the FIT spec carries no laterality flag — see TODOS.md.
    """
    sess = build_session(active_pattern=[(20, 12), (20, 12)])
    report = compare_strength_sessions_from_stats(stats(sess), stats(sess))
    assert report.n_pairs == 2
    # And confirm the (correct) absence of a false positive.
    assert not any("ambiguous" in n.lower() for n in report.notes)


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


# Issue #5 — ghost (reps=0) filter at stats build + downstream surfacing.
# T1: filter drops zero-reps active sets and increments the counter.
def test_zero_reps_filtered_from_active_set_stats():
    """Synthetic session with [60kg×8, 0kg×0, 60kg×8] yields 2 active stats
    (not 3), with the (0, 0) ghost dropped + n_zero_reps_dropped == 1."""
    sess = build_session(
        active_pattern=[(60, 8), (0, 0), (60, 8)],
        hrs=[130.0, 136.0, 132.0],
    )
    s = stats(sess)
    assert len(s.active_set_stats) == 2
    assert s.n_zero_reps_dropped == 1
    # Raw session.sets retains the ghost — only the stats layer drops it.
    raw_active = [x for x in sess.sets if x.set_type == "active"]
    assert len(raw_active) == 3


# T2: ghosts never pair via exact-slot or exercise-level fallback.
def test_zero_reps_does_not_match_via_exact_or_exercise_level():
    """With ghosts on both sides, the (0, 0) slot must not appear in pairs
    or unmatched_baseline (it was dropped pre-pairing). This pins the
    issue #5 regression — previously (0, 0) leaked into unmatched_baseline."""
    baseline = build_session(
        active_pattern=[(60, 8), (0, 0), (60, 8)],
        hrs=[130.0, 136.0, 132.0],
    )
    recent = build_session(
        active_pattern=[(60, 8), (60, 8)],
        hrs=[125.0, 128.0],
    )
    report = compare_strength_sessions_from_stats(stats(baseline), stats(recent))
    for p in report.pairs:
        assert (p.baseline.weight, p.baseline.reps) != (0.0, 0)
        assert (p.recent.weight, p.recent.reps) != (0.0, 0)
    for s in report.unmatched_baseline:
        assert (s.weight, s.reps) != (0.0, 0)
    for s in report.unmatched_recent:
        assert (s.weight, s.reps) != (0.0, 0)


# T5: 0-pairs raise message includes drop count when filter empties a side.
def test_zero_reps_drop_count_in_zero_pairs_raise_message():
    """If filter drains a side so 0 pairs result, the raise message must
    breadcrumb the drop count so users know zero-reps caused it."""
    baseline = build_session(active_pattern=[(0, 0)], hrs=[136.0])
    recent = build_session(active_pattern=[(60, 8)], hrs=[130.0])
    with pytest.raises(ValueError, match=r"dropped 1 zero-reps.*from baseline"):
        compare_strength_sessions_from_stats(stats(baseline), stats(recent))


# T6: stored ghost-targeting indices in excluded_indices_* now raise (V2.12).
def test_excluded_indices_ghost_active_idx_now_raises():
    """Behavior change: a stored exclusion targeting a ghost active_idx now
    fails the V2.12 anti-shopping guard because the ghost is filtered before
    pairing. Users must drop ghost indices from stored exclusion sets after
    upgrading."""
    sess = build_session(
        active_pattern=[(60, 8), (0, 0), (60, 8)],
        hrs=[130.0, 136.0, 132.0],
    )
    with pytest.raises(ValueError, match=r"excluded_indices.*1.*not found"):
        compare_strength_sessions_from_stats(
            stats(sess), stats(sess),
            excluded_indices_baseline={1},
        )


# T7: warmup_avg_hr invariant — zero-reps groups never feed warmup HR.
def test_warmup_avg_hr_excludes_zero_reps_groups():
    """If the first group is now labelled "zero_reps" (was "bodyweight"
    before this fix), warmup_avg_hr must remain None — no leakage from
    failed-attempt HR into the warmup baseline. Pins P5 invariant."""
    sess = build_session(
        active_pattern=[(0, 0), (60, 8), (60, 8)],
        hrs=[150.0, 130.0, 132.0],
    )
    s = stats(sess)
    # warmup HR must be None (no warmup group), not 150 from the ghost.
    assert s.warmup_avg_hr is None


# T8: per-side notes wording — emit only when side has drops.
def test_zero_reps_notes_per_side_wording():
    """Notes emit one line per side that had drops; sides with zero drops
    stay silent (mirrors bucket_exhausted style)."""
    baseline = build_session(
        active_pattern=[(60, 8), (0, 0), (60, 8), (60, 8)],
        hrs=[130.0, 136.0, 131.0, 132.0],
    )
    recent = build_session(
        active_pattern=[(60, 8), (60, 8)],
        hrs=[125.0, 128.0],
    )
    report = compare_strength_sessions_from_stats(stats(baseline), stats(recent))
    baseline_notes = [n for n in report.notes if "zero-reps" in n and "baseline" in n]
    recent_notes = [n for n in report.notes if "zero-reps" in n and "recent" in n]
    assert len(baseline_notes) == 1
    assert "1 zero-reps" in baseline_notes[0]
    assert len(recent_notes) == 0  # recent had no drops → no line


# v0.4.0 — Issue #1 P3 warning-only branch: 3-component warning contract.
# Test plan: ~/.gstack/projects/hottim900-blackswan/tim-main-eng-review-test-plan-...
def test_local_hour_warning_includes_n5_calibration_reference():
    """Component B of the 3-component contract: the warning surfaces the
    n=5 calibration numerals (early/late/overall) sourced from module
    constants — NOT literal '+27'/'+11'/'+19'. If the corpus recalibrates,
    bumping the constants auto-updates the warning AND this test."""
    from blackswan.strength_metrics import (
        N5_CALIBRATION_DELTA_EARLY_BPM,
        N5_CALIBRATION_DELTA_LATE_BPM,
        N5_CALIBRATION_DELTA_OVERALL_BPM,
        N5_CALIBRATION_N,
    )

    morning = datetime(2000, 1, 15, 8, 0, tzinfo=LOCAL_TZ)
    evening = datetime(2000, 1, 15, 20, 0, tzinfo=LOCAL_TZ)
    a = build_session(weights=[60, 60], reps=[8, 8], start_time=morning)
    b = build_session(weights=[60, 60], reps=[8, 8], start_time=evening)
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    assert report.local_hour_warning is not None
    msg = report.local_hour_warning
    assert f"+{N5_CALIBRATION_DELTA_EARLY_BPM}" in msg
    assert f"+{N5_CALIBRATION_DELTA_LATE_BPM}" in msg
    assert f"+{N5_CALIBRATION_DELTA_OVERALL_BPM}" in msg
    assert f"n={N5_CALIBRATION_N}" in msg


def test_local_hour_warning_includes_artifact_or_circadian_qualifier():
    """Component C of the contract: artifact-OR-circadian attribution
    qualifier. Refuses to attribute the +27/+11/+19 magnitudes to
    circadian alone — they are equally consistent with the documented
    EARLY_DEFICIT_LATE_NORMAL artifact shape per confounders.md § 9."""
    morning = datetime(2000, 1, 15, 8, 0, tzinfo=LOCAL_TZ)
    evening = datetime(2000, 1, 15, 20, 0, tzinfo=LOCAL_TZ)
    a = build_session(weights=[60, 60], reps=[8, 8], start_time=morning)
    b = build_session(weights=[60, 60], reps=[8, 8], start_time=evening)
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    msg = report.local_hour_warning
    assert msg is not None
    assert "artifact" in msg.lower()
    assert "circadian" in msg.lower()
    assert "EARLY_DEFICIT_LATE_NORMAL" in msg
    assert "§ 9" in msg


def test_local_hour_warning_preserves_hour_diff_line():
    """Component A of the contract: the hour-diff line is preserved
    verbatim from the pre-v0.4.0 warning so existing regression assertions
    (lines 202-231 of this file) keep passing."""
    morning = datetime(2000, 1, 15, 8, 0, tzinfo=LOCAL_TZ)
    evening = datetime(2000, 1, 15, 20, 0, tzinfo=LOCAL_TZ)
    a = build_session(weights=[60, 60], reps=[8, 8], start_time=morning)
    b = build_session(weights=[60, 60], reps=[8, 8], start_time=evening)
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    msg = report.local_hour_warning
    assert msg is not None
    assert "8:00" in msg
    assert "20:00" in msg
    assert "circular diff" in msg
    assert "12h" in msg


def test_format_local_hour_warning_helper_callable_directly():
    """The composition lives in `_format_local_hour_warning` so its 3
    components are unit-testable without constructing a full
    StrengthComparisonReport (or any stats objects). The helper derives
    the circular diff internally from the two hours."""
    from blackswan.strength_metrics import (
        N5_CALIBRATION_DELTA_EARLY_BPM,
        _format_local_hour_warning,
    )

    msg = _format_local_hour_warning(baseline_hour=8, recent_hour=20)
    assert "8:00" in msg and "20:00" in msg and "12h" in msg
    assert f"+{N5_CALIBRATION_DELTA_EARLY_BPM}" in msg
    assert "artifact" in msg.lower() and "circadian" in msg.lower()

    # Wrap-around: hour 23 and hour 2 should produce circular diff = 3.
    msg2 = _format_local_hour_warning(baseline_hour=23, recent_hour=2)
    assert "circular diff 3h" in msg2


def test_n5_calibration_constants_match_confounders_doc():
    """SSOT contract between `strength_metrics.py` constants and
    `docs/confounders.md § 9` calibration table. If this fails, EITHER
    the constants OR the doc table is stale — update both in the same
    commit. The literal numerals here mirror the doc; that is the SSOT
    pin point. Production code reads the constants, not literals."""
    from blackswan.strength_metrics import (
        N5_CALIBRATION_DELTA_EARLY_BPM,
        N5_CALIBRATION_DELTA_LATE_BPM,
        N5_CALIBRATION_DELTA_OVERALL_BPM,
        N5_CALIBRATION_N,
    )

    assert N5_CALIBRATION_DELTA_EARLY_BPM == 27
    assert N5_CALIBRATION_DELTA_LATE_BPM == 11
    assert N5_CALIBRATION_DELTA_OVERALL_BPM == 19
    assert N5_CALIBRATION_N == 5

    doc_path = Path(__file__).resolve().parent.parent / "docs" / "confounders.md"
    doc = doc_path.read_text(encoding="utf-8")
    assert f"+{N5_CALIBRATION_DELTA_EARLY_BPM} bpm" in doc, (
        "confounders.md § 9 must contain the early-bpm numeral; recalibrate both "
        "the doc table AND strength_metrics.N5_CALIBRATION_DELTA_EARLY_BPM together."
    )
    assert f"+{N5_CALIBRATION_DELTA_LATE_BPM} bpm" in doc
    assert f"+{N5_CALIBRATION_DELTA_OVERALL_BPM} bpm" in doc


def test_local_hour_correction_bpm_field_exists_and_defaults_to_none():
    """v0.4.0 ships the warning-only branch. `local_hour_correction_bpm`
    is an always-ship field (sentinel semantics: None / 0.0 / non-zero)
    so consumers do not have to branch on which v0.X.Y shipped. On
    warning-only, it is always None — even when the hour-diff warning
    fires."""
    morning = datetime(2000, 1, 15, 8, 0, tzinfo=LOCAL_TZ)
    evening = datetime(2000, 1, 15, 20, 0, tzinfo=LOCAL_TZ)
    a = build_session(weights=[60, 60], reps=[8, 8], start_time=morning)
    b = build_session(weights=[60, 60], reps=[8, 8], start_time=evening)
    report = compare_strength_sessions_from_stats(stats(a), stats(b))
    assert hasattr(report, "local_hour_correction_bpm")
    assert report.local_hour_correction_bpm is None
    assert report.local_hour_warning is not None  # warning still fires

    # And when no warning fires (within threshold) the field is also None.
    morn_a = datetime(2000, 1, 15, 9, 0, tzinfo=LOCAL_TZ)
    morn_b = datetime(2000, 1, 15, 11, 0, tzinfo=LOCAL_TZ)
    a2 = build_session(weights=[60, 60], reps=[8, 8], start_time=morn_a)
    b2 = build_session(weights=[60, 60], reps=[8, 8], start_time=morn_b)
    r2 = compare_strength_sessions_from_stats(stats(a2), stats(b2))
    assert r2.local_hour_correction_bpm is None
    assert r2.local_hour_warning is None

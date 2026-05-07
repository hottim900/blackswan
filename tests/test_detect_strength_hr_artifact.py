"""Critical detector tests — TDD checkpoint per V2 Implementation Step 7.5."""

from __future__ import annotations

from blackswan.detect_strength_hr_artifact import (
    StrengthHRArtifactSignature,
    detect_strength_hr_artifact,
)
from tests._strength_helpers import build_session


# T-DET-3: late_window None short-circuit (release-blocking)
def test_detect_late_window_all_none_returns_clean_no_crash():
    """When all late-window sets have hr_avg=None, detector returns CLEAN
    without ZeroDivisionError or median-of-empty crash. UC#1 short-circuit."""
    sess = build_session(
        weights=[60, 60, 60, 60, 60, 60],
        reps=[8] * 6,
        hrs=[80, 80, None, None, None, None],  # late half all None
    )
    sig, warns = detect_strength_hr_artifact(sess)
    assert sig is StrengthHRArtifactSignature.CLEAN
    assert warns == []


def test_detect_n_active_zero_returns_clean():
    """No active sets → CLEAN."""
    sess = build_session(weights=[], reps=[])
    sig, warns = detect_strength_hr_artifact(sess)
    assert sig is StrengthHRArtifactSignature.CLEAN
    assert warns == []


# T-DET-4-EXT: small n_active deterministic behavior
def test_detect_n_active_one_returns_clean():
    """n_active=1 → CLEAN. Late window may overlap early window; ship CLEAN."""
    sess = build_session(weights=[60], reps=[8])
    sig, _ = detect_strength_hr_artifact(sess)
    assert sig is StrengthHRArtifactSignature.CLEAN


def test_detect_n_active_two_three_documented():
    """n_active in {2, 3}: early/late may overlap; v1 returns CLEAN unless
    triggered. We assert no crash and CLEAN by default."""
    for n in (2, 3):
        sess = build_session(weights=[60] * n, reps=[8] * n)
        sig, _ = detect_strength_hr_artifact(sess)
        assert sig is StrengthHRArtifactSignature.CLEAN


def test_detect_clean_session_returns_clean():
    """Realistic clean session: HR rises gradually. No artifact."""
    sess = build_session(
        weights=[60] * 8,
        reps=[8] * 8,
        hrs=[110, 115, 120, 125, 128, 130, 132, 135],
    )
    sig, _ = detect_strength_hr_artifact(sess)
    assert sig is StrengthHRArtifactSignature.CLEAN


def test_detect_classic_early_deficit_late_normal_fires():
    """Early-window <90 (3 sets) AND late_normal (>=115) → flag."""
    sess = build_session(
        weights=[60] * 8,
        reps=[8] * 8,
        hrs=[60, 70, 75, 95, 110, 120, 130, 135],
    )
    sig, warns = detect_strength_hr_artifact(sess)
    assert sig is StrengthHRArtifactSignature.EARLY_DEFICIT_LATE_NORMAL
    assert any("EARLY_DEFICIT_LATE_NORMAL" in w for w in warns)


def test_detect_late_jump_alone_does_not_fire_without_early_deficit():
    """Late jump >=30 bpm vs early WITHOUT enough early-deficit count
    should NOT fire (need both rules)."""
    sess = build_session(
        weights=[60] * 8,
        reps=[8] * 8,
        hrs=[100, 102, 105, 110, 130, 135, 140, 145],  # early >= 90, no deficit
    )
    sig, _ = detect_strength_hr_artifact(sess)
    assert sig is StrengthHRArtifactSignature.CLEAN


def test_detect_relative_threshold_with_reference():
    """In comparison mode, reference triggers relative-deficit even if
    absolute hr_avg is above 90."""
    baseline = build_session(
        weights=[60] * 6,
        reps=[8] * 6,
        hrs=[130, 132, 135, 138, 140, 145],
    )
    recent = build_session(
        weights=[60] * 6,
        reps=[8] * 6,
        hrs=[100, 102, 105, 130, 135, 140],  # early below baseline by 25+ bpm
    )
    sig, _ = detect_strength_hr_artifact(recent, reference=baseline)
    assert sig is StrengthHRArtifactSignature.EARLY_DEFICIT_LATE_NORMAL


# Issue #5 — ghost (reps=0) sets must not feed early-deficit window.
def test_detect_zero_reps_ghosts_do_not_feed_early_deficit_window():
    """Two early-session ghost button-presses with sitting HR (~80 bpm)
    must NOT false-trigger EARLY_DEFICIT_LATE_NORMAL. The detector only
    sees real exercises (reps > 0 or reps None), not failed-attempt ghosts."""
    sess = build_session(
        active_pattern=[(0, 0), (0, 0), (60, 8), (60, 8), (60, 8), (60, 8)],
        hrs=[80, 82, 95, 130, 130, 120],
    )
    sig, _ = detect_strength_hr_artifact(sess)
    assert sig is StrengthHRArtifactSignature.CLEAN

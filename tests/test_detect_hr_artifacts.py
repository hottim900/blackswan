"""Tests for the trial-level escalation helper from detect_hr_artifacts.

Numeric epoch seconds are used as timestamps to keep the tests free of
datetime fixtures — the helper accepts any subtractable type.
"""
from __future__ import annotations

import pytest

from blackswan.detect_hr_artifacts import trial_flagged_fraction


def seg(start, end):
    return {"start_ts": start, "end_ts": end}


def test_no_overlap_returns_zero():
    segs = [seg(0, 50)]
    assert trial_flagged_fraction(segs, 100, 200) == 0.0


def test_full_overlap_returns_one():
    segs = [seg(100, 200)]
    assert trial_flagged_fraction(segs, 100, 200) == pytest.approx(1.0)


def test_partial_overlap_inside():
    """40s flagged inside a 100s trial -> 0.4 — the canonical escalation
    threshold from confounders.md §5."""
    segs = [seg(120, 160)]
    assert trial_flagged_fraction(segs, 100, 200) == pytest.approx(0.4)


def test_segment_extends_outside_trial_clips():
    """A segment from t=50 to t=150, against a trial [100, 200]: only the
    [100, 150] window counts."""
    segs = [seg(50, 150)]
    assert trial_flagged_fraction(segs, 100, 200) == pytest.approx(0.5)


def test_multiple_segments_sum():
    segs = [seg(110, 120), seg(140, 160)]  # 10 + 20 = 30s in 100s trial
    assert trial_flagged_fraction(segs, 100, 200) == pytest.approx(0.3)


def test_empty_trial_window_returns_zero():
    """Inverted or zero-width trial window -> 0.0 (caller's job to filter
    those before deciding to exclude)."""
    assert trial_flagged_fraction([seg(100, 150)], 100, 100) == 0.0
    assert trial_flagged_fraction([seg(100, 150)], 200, 100) == 0.0


def test_no_segments_returns_zero():
    assert trial_flagged_fraction([], 100, 200) == 0.0


def test_escalation_decision_at_threshold():
    """The 0.4 boundary in confounders.md §5: callers decide
    fraction > 0.4 to exclude. Verify the helper produces fractions
    on the right side of that line."""
    # Just under 0.4 (39%): keep
    assert trial_flagged_fraction([seg(100, 139)], 100, 200) < 0.4
    # Just over 0.4 (41%): escalate
    assert trial_flagged_fraction([seg(100, 141)], 100, 200) > 0.4

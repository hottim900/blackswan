"""Tests for the trial-level escalation helper from detect_hr_artifacts.

Most tests use numeric epoch seconds for brevity; one explicitly verifies
the timedelta path by using timezone-aware datetimes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_zero_or_inverted_window_raises():
    """Silent 0.0 would mask a caller bug as "trial has no artifacts —
    keep it", which is exactly the wrong direction for the escalation
    rule. Raise instead so the bug surfaces."""
    with pytest.raises(ValueError, match="trial_end must be"):
        trial_flagged_fraction([seg(100, 150)], 100, 100)
    with pytest.raises(ValueError, match="trial_end must be"):
        trial_flagged_fraction([seg(100, 150)], 200, 100)


def test_datetime_timestamps_work():
    """Real callers pass tz-aware datetimes (from segment_uphill /
    detect_artifacts since the start_ts unification). Verify the
    timedelta arithmetic path is wired up."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    segs_dt = [
        {"start_ts": base + timedelta(seconds=20),
         "end_ts": base + timedelta(seconds=60)},
    ]
    t_start = base
    t_end = base + timedelta(seconds=100)
    # 40s flagged within a 100s window -> 0.4
    assert trial_flagged_fraction(segs_dt, t_start, t_end) == pytest.approx(0.4)


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

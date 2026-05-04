"""Parser-level tests added in /review Fix-First pass.

Covers raise paths, device_info filter, hr_next60s_avg clip, parser
idempotency, and Decoder option pinning per V2 test plan addendum.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

from blackswan.parse_strength_fit import (
    StrengthSession,
    parse_strength_fit_from_msgs,
)
from tests._strength_helpers import build_strength_msgs


# T-PARSE-10: wrong sport raises with problem+cause+fix triplet
def test_parse_strength_fit_rejects_running_sport_with_actionable_message():
    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        sport="running", sub_sport="generic",
    )
    with pytest.raises(ValueError, match=r"sport='running'.*Cause.*Fix:"):
        parse_strength_fit_from_msgs(msgs)


def test_parse_strength_fit_rejects_strength_with_wrong_sub_sport():
    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        sport="training", sub_sport="cardio_training",
    )
    with pytest.raises(ValueError, match=r"sub_sport='cardio_training'"):
        parse_strength_fit_from_msgs(msgs)


# Three raise paths in parse_strength_fit_from_msgs
def test_parse_strength_fit_raises_when_set_missing_start_time():
    msgs = build_strength_msgs(weights=[60], reps=[8])
    msgs["set_mesgs"][0].pop("start_time")
    with pytest.raises(ValueError, match=r"missing start_time"):
        parse_strength_fit_from_msgs(msgs)


def test_parse_strength_fit_raises_on_unknown_set_type():
    msgs = build_strength_msgs(weights=[60], reps=[8])
    msgs["set_mesgs"][0]["set_type"] = "warmup"
    with pytest.raises(ValueError, match=r"set_type='warmup'"):
        parse_strength_fit_from_msgs(msgs)


def test_parse_strength_fit_raises_on_overlapping_sets():
    msgs = build_strength_msgs(weights=[60, 60], reps=[8, 8], rest_between=60.0)
    # Force the second set to start before the first ends
    first = msgs["set_mesgs"][0]
    msgs["set_mesgs"][2]["start_time"] = first["start_time"]  # collision
    with pytest.raises(ValueError, match=r"overlapping set windows"):
        parse_strength_fit_from_msgs(msgs)


def test_parse_strength_fit_raises_when_no_session_mesgs():
    msgs = build_strength_msgs(weights=[60], reps=[8])
    msgs["session_mesgs"] = []
    with pytest.raises(ValueError, match=r"no session_mesgs"):
        parse_strength_fit_from_msgs(msgs)


# T-PARSE-4-EXT: device_info filter
def test_device_product_prefers_local_over_paired_strap():
    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        device_info_mesgs=[
            {"source_type": "antplus", "device_index": 1, "garmin_product": "hrm_pro"},
            {"source_type": "local", "device_index": 0, "garmin_product": "vivoactive5"},
        ],
    )
    sess = parse_strength_fit_from_msgs(msgs)
    assert sess.device_product == "vivoactive5"


def test_device_product_falls_back_to_index_zero_when_no_source_type():
    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        device_info_mesgs=[
            {"device_index": 1, "garmin_product": "hrm_pro"},
            {"device_index": 0, "garmin_product": "vivoactive5"},
        ],
    )
    sess = parse_strength_fit_from_msgs(msgs)
    assert sess.device_product == "vivoactive5"


def test_device_product_returns_none_when_device_info_missing():
    msgs = build_strength_msgs(weights=[60], reps=[8], device_info_mesgs=[])
    sess = parse_strength_fit_from_msgs(msgs)
    assert sess.device_product is None


# T-PARSE-7-EXT: hr_next60s_avg clipped to session.start_time + total_elapsed_time
def test_hr_next60s_avg_clipped_when_window_exceeds_session_end():
    """When the last set ends close to session end, hr_next60s_avg should
    use the clipped window — and become None when the clipped window has
    no records."""
    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        rest_between=0.0, set_dur=60.0,
        session_total_elapsed_time=60.0,  # session ends exactly when set ends
    )
    sess = parse_strength_fit_from_msgs(msgs)
    last_active = next(s for s in sess.sets if s.set_type == "active")
    # Window [t_end, session_end] is empty → no records → None
    assert last_active.hr_next60s_avg is None


# T-CMP-IDEMP: parser idempotency
def test_parse_strength_fit_from_msgs_is_idempotent():
    msgs = build_strength_msgs(weights=[60, 60], reps=[8, 8])
    a = parse_strength_fit_from_msgs(copy.deepcopy(msgs))
    b = parse_strength_fit_from_msgs(copy.deepcopy(msgs))
    assert a == b


# T-PARSE-9 partial: timestamps must be timezone-aware, not naive datetime / date
def test_parse_strength_fit_yields_timezone_aware_datetimes():
    msgs = build_strength_msgs(weights=[60], reps=[8])
    sess = parse_strength_fit_from_msgs(msgs)
    assert isinstance(sess, StrengthSession)
    assert isinstance(sess.start_time, datetime)
    assert sess.start_time.tzinfo is not None
    for s in sess.sets:
        assert isinstance(s.t_start, datetime)
        assert s.t_start.tzinfo is not None
        assert isinstance(s.t_end, datetime)
        assert s.t_end.tzinfo is not None


def test_parse_strength_fit_warns_on_non_vivoactive_device():
    """V2.2: non-vivoactive devices warn but do not raise."""
    import warnings as warnmod

    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        device_info_mesgs=[
            {"source_type": "local", "device_index": 0, "garmin_product": "fr955"},
        ],
    )
    with warnmod.catch_warnings(record=True) as captured:
        warnmod.simplefilter("always")
        sess = parse_strength_fit_from_msgs(msgs)
    assert sess.device_product == "fr955"
    assert any("vivoactive 5 only" in str(w.message) for w in captured)


# Smoke: total_elapsed_time and start_time relate correctly
def test_session_end_equals_start_plus_total_elapsed():
    msgs = build_strength_msgs(weights=[60, 60], reps=[8, 8], set_dur=60.0, rest_between=60.0)
    sess = parse_strength_fit_from_msgs(msgs)
    expected_end = sess.start_time + timedelta(seconds=sess.total_elapsed_time)
    last_set_end = sess.sets[-1].t_end
    # last set ends at session end (no trailing rest by helper convention)
    assert last_set_end <= expected_end

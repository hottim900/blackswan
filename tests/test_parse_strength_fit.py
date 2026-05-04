"""Parser-level tests added in /review Fix-First pass.

Covers raise paths, device_info filter, hr_next60s_avg clip, parser
idempotency, and Decoder option pinning per V2 test plan addendum.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from blackswan.parse_strength_fit import (
    StrengthSession,
    parse_strength_fit,
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
    no records (short-circuit branch)."""
    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        rest_between=0.0, set_dur=60.0,
        session_total_elapsed_time=60.0,  # session ends exactly when set ends
    )
    sess = parse_strength_fit_from_msgs(msgs)
    last_active = next(s for s in sess.sets if s.set_type == "active")
    # Window [t_end, session_end] is empty → no records → None
    assert last_active.hr_next60s_avg is None


def test_hr_next60s_avg_clip_excludes_records_past_session_end():
    """T-PARSE-7-EXT (clip branch): the actual clip ``min(t_end+60, session_end)``
    must drop records beyond ``session_end`` even if records exist there. This
    is the branch the short-circuit test above does NOT cover.

    Setup: set 0-60s, session ends at 80s. Records span 0-120s with
    distinct HR in three buckets:
      - 0-60s @ 130 bpm (during the set)
      - 60-80s @ 150 bpm (post-set, in-session)
      - 80-120s @ 200 bpm (past session_end — phantom)

    With clip: window [60, 80] → average over 20 records of 150 bpm = 150.
    Without clip: window [60, 120] → mixes 150 and 200 → ~175. The
    assertion catches a regression that drops the ``min(...)``.
    """
    msgs = build_strength_msgs(
        weights=[60], reps=[8],
        rest_between=0.0, set_dur=60.0,
        session_total_elapsed_time=80.0,  # session ends 20s after the set
    )
    set_start = msgs["set_mesgs"][0]["start_time"]
    records = []
    for sec in range(60):
        records.append({"timestamp": set_start + timedelta(seconds=sec), "heart_rate": 130})
    # In-session post-set records (60-80s, inclusive of the 80s boundary
    # since _hr_records_in uses ``<= t_end``).
    for sec in range(60, 81):
        records.append({"timestamp": set_start + timedelta(seconds=sec), "heart_rate": 150})
    # Phantom records strictly past session_end (sec >= 81). The clip
    # ``min(t_end + 60, session_end)`` must exclude these.
    for sec in range(82, 121):
        records.append({"timestamp": set_start + timedelta(seconds=sec), "heart_rate": 200})
    msgs["record_mesgs"] = records

    sess = parse_strength_fit_from_msgs(msgs)
    last_active = next(s for s in sess.sets if s.set_type == "active")
    assert last_active.hr_next60s_avg is not None
    assert abs(last_active.hr_next60s_avg - 150.0) < 0.5, (
        f"hr_next60s_avg={last_active.hr_next60s_avg} — expected ~150, got "
        "value contaminated by post-session phantom records (clip regressed)."
    )


# T-CMP-IDEMP: parser idempotency
def test_parse_strength_fit_from_msgs_is_idempotent():
    msgs = build_strength_msgs(weights=[60, 60], reps=[8, 8])
    a = parse_strength_fit_from_msgs(copy.deepcopy(msgs))
    b = parse_strength_fit_from_msgs(copy.deepcopy(msgs))
    assert a == b


# T-PARSE-9 (from_msgs path): timestamps timezone-aware, not naive / date
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


# T-PARSE-9 (disk path): the from_msgs test above feeds datetime objects in
# directly so it can't fail when the Decoder pin regresses. This test goes
# through the full Decoder pipeline and proves the
# convert_datetimes_to_dates=False pin is actually engaged: if it's removed,
# the SDK returns date objects, and parse_strength_fit either raises in
# _to_local (date is not a datetime subclass) or yields .hour=0 — the
# explicit type+hour assertions below catch both.
def test_parse_strength_fit_disk_path_pins_decoder_to_datetime(tmp_path: Path):
    from examples.synthetic_strength_baseline import build_baseline_fit

    fit_path = tmp_path / "baseline.fit"
    fit_path.write_bytes(build_baseline_fit())

    sess = parse_strength_fit(fit_path)

    # type-check: datetime is a subclass of date, so isinstance(..., date)
    # passes for datetimes too. type(x) is datetime is the strict check.
    assert type(sess.start_time) is datetime, (
        f"start_time type={type(sess.start_time).__name__} — Decoder pin "
        "convert_datetimes_to_dates=False likely regressed."
    )
    for s in sess.sets:
        assert type(s.t_start) is datetime
        assert type(s.t_end) is datetime

    # Round-trip sanity: baseline encodes 18:30 LOCAL_TZ. A date object
    # would have no .hour attribute (would AttributeError before this
    # comparison), and a datetime stripped to date and re-cast would give
    # hour=0. 18 is the only correct answer for the disk-path through pin.
    assert sess.start_time.hour == 18, sess.start_time
    # Also verify date subclass relation: every set's t_start is a datetime
    # AND a date (datetime is subclass), but a regression that returns date
    # would fail the strict type check above first.
    for s in sess.sets:
        assert isinstance(s.t_start, date)  # always true for datetime


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

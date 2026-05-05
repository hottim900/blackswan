"""Parser-level tests added in /review Fix-First pass.

Covers raise paths, device_info filter, hr_next60s_avg clip, parser
idempotency, and Decoder option pinning per V2 test plan addendum.
"""

from __future__ import annotations

import copy
import dataclasses
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from blackswan.parse_strength_fit import (
    INVERSION_TOLERANCE_S,
    StrengthSession,
    parse_strength_fit,
    parse_strength_fit_from_msgs,
)
from tests._strength_helpers import SYNTH_START, build_strength_msgs


def _build_strength_session(tmp_path: Path, sets: list, filename: str) -> StrengthSession:
    """Build a synthetic strength FIT, write to ``tmp_path``, parse via the
    full disk path. ``rest_between=0.0`` is hard-coded because every v0.2.1
    precision-asymmetry test needs the cursor's fractional component
    preserved across the device-truncation step (see ``examples/_strength_fit_synth``)."""
    from examples._strength_fit_synth import build_strength_fit_bytes

    fit = build_strength_fit_bytes(sets=sets, start_time=SYNTH_START, rest_between=0.0)
    fit_path = tmp_path / filename
    fit_path.write_bytes(fit)
    return parse_strength_fit(fit_path)


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


# v0.2.1 — FIT precision-asymmetry tolerance regression suite
# See docs/confounders.md § 10 and the design plan for hand-derived expected values.


# T-1: sub-second tolerance, single boundary, full Encoder→Decoder→parser disk path.
def test_disk_path_tolerates_subsecond_truncation(tmp_path: Path):
    from examples._strength_fit_synth import SyntheticSet

    with pytest.warns(UserWarning, match=r"FIT precision-asymmetry"):
        sess = _build_strength_session(
            tmp_path,
            sets=[
                SyntheticSet(weight=60.0, reps=8, set_type="active", duration=3.298),
                SyntheticSet(weight=None, reps=None, set_type="rest", duration=30.0),
            ],
            filename="subsecond.fit",
        )

    assert sess.n_set_boundaries_clamped == 1
    assert sess.sets[0].t_end == sess.sets[1].t_start
    duration_after_clamp = (sess.sets[1].t_end - sess.sets[1].t_start).total_seconds()
    assert duration_after_clamp == 30.0
    assert sess.sets[0].duration == 3.298


# T-1b: integer-aligned back-to-back boundary does NOT clamp (noise floor = 0).
def test_back_to_back_integer_boundary_does_not_clamp(tmp_path: Path):
    from examples._strength_fit_synth import SyntheticSet

    sess = _build_strength_session(
        tmp_path,
        sets=[
            SyntheticSet(weight=60.0, reps=8, set_type="active", duration=10.0),
            SyntheticSet(weight=60.0, reps=8, set_type="active", duration=10.0),
        ],
        filename="integer.fit",
    )

    assert sess.n_set_boundaries_clamped == 0
    assert sess.sets[1].t_start == sess.sets[0].t_end


# T-1c: max sub-second inversion (0.999s) clamps.
def test_max_subsecond_inversion_clamps(tmp_path: Path):
    from examples._strength_fit_synth import SyntheticSet

    sess = _build_strength_session(
        tmp_path,
        sets=[
            SyntheticSet(weight=60.0, reps=8, set_type="active", duration=0.999),
            SyntheticSet(weight=60.0, reps=8, set_type="active", duration=10.0),
        ],
        filename="max_sub.fit",
    )

    assert sess.n_set_boundaries_clamped == 1
    aligned_after = (sess.sets[0].t_end - sess.sets[1].t_start).total_seconds()
    assert aligned_after == 0.0


# T-2: inversion above tolerance raises, error message references the named constant.
def test_msgs_path_raises_on_overlap_above_tolerance():
    msgs = build_strength_msgs(
        weights=[60, 60], reps=[8, 8], rest_between=0.0, set_dur=10.0
    )
    set0_start = msgs["set_mesgs"][0]["start_time"]
    msgs["set_mesgs"][2]["start_time"] = set0_start + timedelta(seconds=8.0)

    with pytest.raises(ValueError) as excinfo:
        parse_strength_fit_from_msgs(msgs)
    err = str(excinfo.value)
    assert f"{INVERSION_TOLERANCE_S}s" in err
    assert f"{2.0:.4f}s" in err
    assert "FIT-precision tolerance" in err
    assert "Cause:" in err and "Fix:" in err


# T-2b: inversion of exactly 1.0s raises (strict-less-than gate).
def test_msgs_path_inversion_at_one_second_exactly_raises():
    msgs = build_strength_msgs(
        weights=[60, 60], reps=[8, 8], rest_between=0.0, set_dur=10.0
    )
    set0_start = msgs["set_mesgs"][0]["start_time"]
    msgs["set_mesgs"][2]["start_time"] = set0_start + timedelta(seconds=9.0)

    with pytest.raises(ValueError, match=r"FIT-precision tolerance"):
        parse_strength_fit_from_msgs(msgs)


# T-2c: inversion just below tolerance (0.9999s) clamps (FP edge).
def test_msgs_path_inversion_just_below_tolerance_clamps():
    msgs = build_strength_msgs(
        weights=[60, 60], reps=[8, 8], rest_between=0.0, set_dur=10.0
    )
    set0_start = msgs["set_mesgs"][0]["start_time"]
    msgs["set_mesgs"][2]["start_time"] = set0_start + timedelta(seconds=9.0001)

    sess = parse_strength_fit_from_msgs(msgs)
    assert sess.n_set_boundaries_clamped == 1


# T-3: cascade of sub-second truncations stays monotonic; clamp count locked at 4.
def test_disk_path_cascade_clamp_remains_monotonic(tmp_path: Path):
    from examples._strength_fit_synth import SyntheticSet

    sess = _build_strength_session(
        tmp_path,
        sets=[
            SyntheticSet(weight=60.0, reps=8, set_type="active", duration=47.7)
            for _ in range(5)
        ],
        filename="cascade.fit",
    )

    assert len(sess.sets) == 5
    assert sess.n_set_boundaries_clamped == 4
    for i in range(len(sess.sets) - 1):
        assert sess.sets[i].t_end <= sess.sets[i + 1].t_start
    assert all(s.duration == 47.7 for s in sess.sets)
    assert sum(s.duration for s in sess.sets) == 5 * 47.7


# Cascade emits exactly one warning across all 4 clamps (one-shot contract).
def test_cascade_clamp_emits_exactly_one_warning(tmp_path: Path):
    from examples._strength_fit_synth import SyntheticSet

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        sess = _build_strength_session(
            tmp_path,
            sets=[
                SyntheticSet(weight=60.0, reps=8, set_type="active", duration=47.7)
                for _ in range(5)
            ],
            filename="cascade_warn.fit",
        )

    asym = [w for w in captured if "FIT precision-asymmetry" in str(w.message)]
    assert len(asym) == 1, f"expected one-shot warning, got {len(asym)}"
    assert sess.n_set_boundaries_clamped == 4


# T-4: HR window uses CLAMPED t_start/t_end after clamp (silent-corruption guard).
def test_hr_records_use_clamped_window_after_clamp():
    T = SYNTH_START
    msgs = {
        "session_mesgs": [{
            "start_time": T,
            "sport": "training",
            "sub_sport": "strength_training",
            "total_elapsed_time": 70.0,
        }],
        "set_mesgs": [
            {
                "start_time": T,
                "duration": 2.5,
                "weight": 60,
                "repetitions": 8,
                "set_type": "active",
                "category": None,
                "category_subtype": None,
            },
            {
                "start_time": T + timedelta(seconds=2),
                "duration": 10.0,
                "weight": 60,
                "repetitions": 8,
                "set_type": "active",
                "category": None,
                "category_subtype": None,
            },
        ],
        "record_mesgs": [
            {"timestamp": T + timedelta(seconds=0.0), "heart_rate": 130},
            {"timestamp": T + timedelta(seconds=1.0), "heart_rate": 130},
            {"timestamp": T + timedelta(seconds=2.0), "heart_rate": 140},
            {"timestamp": T + timedelta(seconds=2.5), "heart_rate": 200},
            {"timestamp": T + timedelta(seconds=5.0), "heart_rate": 200},
            {"timestamp": T + timedelta(seconds=10.0), "heart_rate": 200},
            {"timestamp": T + timedelta(seconds=12.5), "heart_rate": 200},
        ],
        "device_info_mesgs": [
            {"source_type": "local", "device_index": 0, "garmin_product": "vivoactive5"},
        ],
    }

    sess = parse_strength_fit_from_msgs(msgs)

    assert sess.n_set_boundaries_clamped == 1
    assert sess.sets[1].hr_avg == 200.0, (
        f"hr_avg={sess.sets[1].hr_avg} — expected 200 (clamped window). "
        "If a lower value (~188), the HR query used the pre-clamp t_start "
        "and pulled in the 140-bpm record at T+2.0s."
    )
    assert sess.sets[0].t_end == sess.sets[1].t_start


# T-5: dataclass field placed last with default=0 (back-compat with kwargs callers).
def test_strength_session_field_appended_at_end_with_default():
    s = StrengthSession(
        fit_path=None,
        sport="training",
        sub_sport="strength_training",
        start_time=datetime(2000, 1, 15, 18, 30),
        local_hour=18,
        total_elapsed_time=0.0,
        device_product=None,
        sets=[],
    )
    assert s.n_set_boundaries_clamped == 0

    s2 = StrengthSession(
        fit_path=None,
        sport="training",
        sub_sport="strength_training",
        start_time=datetime(2000, 1, 15, 18, 30),
        local_hour=18,
        total_elapsed_time=0.0,
        device_product=None,
        sets=[],
        n_set_boundaries_clamped=5,
    )
    assert s2.n_set_boundaries_clamped == 5

    fields = dataclasses.fields(StrengthSession)
    assert any(
        f.name == "n_set_boundaries_clamped" and f.default == 0
        for f in fields
    ), "n_set_boundaries_clamped must exist with default=0 for kwargs back-compat"


# T-6: summary() exists, hides clamp count when 0, surfaces it when non-zero.
def test_strength_session_summary_reports_clamp_count():
    base_kwargs = dict(
        fit_path=None,
        sport="training",
        sub_sport="strength_training",
        start_time=datetime(2000, 1, 15, 18, 30),
        local_hour=18,
        total_elapsed_time=0.0,
        device_product=None,
        sets=[],
    )
    s_no_clamps = StrengthSession(**base_kwargs, n_set_boundaries_clamped=0)
    s_with_clamps = StrengthSession(**base_kwargs, n_set_boundaries_clamped=13)

    assert hasattr(s_no_clamps, "summary")
    no_summary = s_no_clamps.summary()
    with_summary = s_with_clamps.summary()

    assert isinstance(no_summary, str)
    assert "clamp" not in no_summary.lower()
    assert "13" in with_summary and "clamp" in with_summary.lower()

"""Direct unit tests for segment_strength_sets — added in /review Fix-First."""

from __future__ import annotations

import warnings

from blackswan.parse_strength_fit import StrengthSession
from blackswan.segment_strength_sets import (
    MAX_REST_GAP,
    ExerciseGroup,
    identify_exercises,
)
from tests._strength_helpers import SYNTH_START, build_session, make_active_set, make_rest_set


def test_identify_exercises_groups_consecutive_same_signature():
    sess = build_session(weights=[60, 60, 60], reps=[8, 8, 8])
    groups = identify_exercises(sess)
    assert len(groups) == 1
    assert groups[0].name == "60.0kg × 8"
    assert len(groups[0].sets) == 3


def test_identify_exercises_splits_on_signature_change():
    sess = build_session(weights=[60, 60, 80], reps=[8, 8, 5])
    groups = identify_exercises(sess)
    assert len(groups) == 2
    assert [g.name for g in groups] == ["60.0kg × 8", "80.0kg × 5"]


def test_identify_exercises_respects_max_rest_gap():
    """A run of (max_rest_gap + 1) rest sets between same (weight, reps)
    starts a new group."""
    sets = []
    cursor = SYNTH_START
    sets.append(make_active_set(set_idx=0, active_idx=0, t_start=cursor, weight=60, reps=8))
    cursor = sets[-1].t_end
    # MAX_REST_GAP+1 rest sets in a row
    for i in range(MAX_REST_GAP + 1):
        sets.append(make_rest_set(set_idx=len(sets), t_start=cursor, duration=30.0))
        cursor = sets[-1].t_end
    sets.append(make_active_set(set_idx=len(sets), active_idx=1, t_start=cursor, weight=60, reps=8))
    sess = StrengthSession(
        fit_path=None, sport="training", sub_sport="strength_training",
        start_time=SYNTH_START, local_hour=18,
        total_elapsed_time=(cursor - SYNTH_START).total_seconds(),
        device_product="vivoactive5", sets=sets,
    )
    groups = identify_exercises(sess)
    assert len(groups) == 2  # split despite same (weight, reps)


def test_identify_exercises_max_rest_gap_override():
    """Override max_rest_gap to allow longer rest gaps within a group."""
    sets = []
    cursor = SYNTH_START
    sets.append(make_active_set(set_idx=0, active_idx=0, t_start=cursor, weight=60, reps=8))
    cursor = sets[-1].t_end
    for i in range(5):
        sets.append(make_rest_set(set_idx=len(sets), t_start=cursor, duration=30.0))
        cursor = sets[-1].t_end
    sets.append(make_active_set(set_idx=len(sets), active_idx=1, t_start=cursor, weight=60, reps=8))
    sess = StrengthSession(
        fit_path=None, sport="training", sub_sport="strength_training",
        start_time=SYNTH_START, local_hour=18,
        total_elapsed_time=(cursor - SYNTH_START).total_seconds(),
        device_product="vivoactive5", sets=sets,
    )
    groups = identify_exercises(sess, max_rest_gap=10)
    assert len(groups) == 1


def test_identify_exercises_warmup_detected_by_first_group_high_reps_zero_weight():
    sess = build_session(weights=[0.0, 60, 60], reps=[15, 8, 8])
    groups = identify_exercises(sess)
    assert groups[0].name == "warmup"
    assert groups[1].name == "60.0kg × 8"


def test_identify_exercises_bodyweight_when_zero_weight_not_in_first_group():
    sess = build_session(weights=[60, 0.0], reps=[8, 12])
    groups = identify_exercises(sess)
    # Mid-session zero-weight low-rep is bodyweight, not warmup
    assert groups[0].name == "60.0kg × 8"
    assert groups[1].name == "bodyweight"


def test_identify_exercises_warns_on_active_set_missing_weight_and_reps():
    sets = [
        make_active_set(set_idx=0, active_idx=0, t_start=SYNTH_START,
                        weight=None, reps=None, hr_avg=None),
        make_active_set(set_idx=1, active_idx=1,
                        t_start=SYNTH_START.replace(minute=31),
                        weight=60, reps=8),
    ]
    sess = StrengthSession(
        fit_path=None, sport="training", sub_sport="strength_training",
        start_time=SYNTH_START, local_hour=18,
        total_elapsed_time=300, device_product="vivoactive5",
        sets=sets,
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        groups = identify_exercises(sess)
    assert any("malformed FIT export" in str(w.message) for w in captured)
    assert len(groups) == 1


def test_identify_exercises_empty_session_returns_empty_list():
    sess = build_session(weights=[], reps=[])
    assert identify_exercises(sess) == []


def test_exercise_group_dataclass_field_order():
    """Sanity check that ExerciseGroup dataclass shape didn't drift."""
    g = ExerciseGroup(name="test", sets=[])
    assert g.name == "test"
    assert g.sets == []


# Issue #5 — _group_name guard for reps=0 (any weight).
# T3: bare bodyweight ghost (0, 0) labels as "zero_reps", not "bodyweight".
def test_zero_reps_set_labels_as_zero_reps_not_bodyweight():
    """A `(weight=0, reps=0)` mid-session set previously fell through to
    "bodyweight" via the warmup-gate path. After issue #5 it must label
    as "zero_reps" — recorded intent without work performed."""
    sess = build_session(active_pattern=[(60, 8), (0, 0)], hrs=[130.0, 136.0])
    groups = identify_exercises(sess)
    assert groups[0].name == "60.0kg × 8"
    assert groups[1].name == "zero_reps"


# T4: weighted ghost (60kg, 0) labels as "zero_reps" too — broader guard.
def test_zero_reps_with_nonzero_weight_labels_as_zero_reps():
    """A failed weighted attempt `(weight>0, reps=0)` previously emitted the
    misleading label "60.0kg × 0". Broader guard makes this consistent with
    the (0, 0) case — both are zero_reps."""
    sess = build_session(active_pattern=[(60, 8), (60, 0)], hrs=[130.0, 138.0])
    groups = identify_exercises(sess)
    assert groups[0].name == "60.0kg × 8"
    assert groups[1].name == "zero_reps"

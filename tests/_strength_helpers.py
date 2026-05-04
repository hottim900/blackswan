"""Test helpers for synthetic strength sessions.

Builds in-memory ``StrengthSession`` instances and FIT-style ``msgs`` dicts
without going through Encoder/Decoder. Tests should prefer these helpers
over real FIT files (PII).

Synthetic year is 2000 to avoid colliding with the user's real timestamps
in any future PII grep.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from blackswan._time import LOCAL_TZ
from blackswan.parse_strength_fit import StrengthSession, StrengthSet
from blackswan.segment_strength_sets import identify_exercises

SYNTH_YEAR = 2000
SYNTH_START = datetime(SYNTH_YEAR, 1, 15, 18, 30, tzinfo=LOCAL_TZ)


def make_active_set(
    *,
    set_idx: int,
    active_idx: int,
    t_start: datetime,
    duration: float = 60.0,
    weight: float = 60.0,
    reps: int = 8,
    hr_avg: float | None = 130.0,
    hr_max: float | None = None,
    hr_start: float | None = None,
    hr_end: float | None = None,
    hr_next60s_avg: float | None = None,
) -> StrengthSet:
    return StrengthSet(
        set_idx=set_idx,
        active_idx=active_idx,
        set_type="active",
        t_start=t_start,
        t_end=t_start + timedelta(seconds=duration),
        duration=duration,
        weight=weight,
        reps=reps,
        raw_category=None,
        raw_category_subtype=None,
        hr_avg=hr_avg,
        hr_max=hr_max if hr_max is not None else hr_avg,
        hr_start=hr_start if hr_start is not None else hr_avg,
        hr_end=hr_end if hr_end is not None else hr_avg,
        hr_next60s_avg=hr_next60s_avg,
    )


def make_rest_set(
    *,
    set_idx: int,
    t_start: datetime,
    duration: float = 60.0,
) -> StrengthSet:
    return StrengthSet(
        set_idx=set_idx,
        active_idx=None,
        set_type="rest",
        t_start=t_start,
        t_end=t_start + timedelta(seconds=duration),
        duration=duration,
        weight=None,
        reps=None,
        raw_category=None,
        raw_category_subtype=None,
        hr_avg=None,
        hr_max=None,
        hr_start=None,
        hr_end=None,
        hr_next60s_avg=None,
    )


def build_session(
    *,
    weights: list[float] | None = None,
    reps: list[int] | None = None,
    hrs: list[float | None] | None = None,
    active_pattern: list[tuple[float, int]] | None = None,
    rest_between: float = 60.0,
    set_dur: float = 60.0,
    start_time: datetime = SYNTH_START,
    device_product: str | None = "vivoactive5",
    fit_path: Path | None = None,
) -> StrengthSession:
    """Build a StrengthSession with active sets separated by rest sets.

    Either pass ``weights`` + ``reps`` (parallel lists), or
    ``active_pattern`` (list of ``(weight, reps)`` tuples). ``hrs`` is
    parallel to active sets and provides per-set ``hr_avg``.

    Sets alternate active/rest; the first set is active, the last set is
    active (no trailing rest). All times computed from ``start_time``.
    """
    if active_pattern is not None:
        weights = [w for w, _ in active_pattern]
        reps = [r for _, r in active_pattern]
    if weights is None or reps is None:
        raise ValueError("must pass weights+reps or active_pattern")
    if len(weights) != len(reps):
        raise ValueError("weights and reps must be equal length")
    if hrs is None:
        hrs = [130.0] * len(weights)
    if len(hrs) != len(weights):
        raise ValueError("hrs must equal active-set count")
    weights = [float(w) if w is not None else None for w in weights]

    sets: list[StrengthSet] = []
    cursor = start_time
    raw_idx = 0
    active_idx = 0
    for i, (w, r, hr) in enumerate(zip(weights, reps, hrs, strict=True)):
        sets.append(
            make_active_set(
                set_idx=raw_idx,
                active_idx=active_idx,
                t_start=cursor,
                duration=set_dur,
                weight=w,
                reps=r,
                hr_avg=hr,
            )
        )
        raw_idx += 1
        active_idx += 1
        cursor += timedelta(seconds=set_dur)

        # Trailing rest after every active set except the last
        if i < len(weights) - 1:
            sets.append(
                make_rest_set(
                    set_idx=raw_idx,
                    t_start=cursor,
                    duration=rest_between,
                )
            )
            raw_idx += 1
            cursor += timedelta(seconds=rest_between)

    total_elapsed_time = (cursor - start_time).total_seconds()

    return StrengthSession(
        fit_path=fit_path,
        sport="training",
        sub_sport="strength_training",
        start_time=start_time,
        local_hour=start_time.hour,
        total_elapsed_time=total_elapsed_time,
        device_product=device_product,
        sets=sets,
    )


def build_strength_msgs(
    *,
    weights: list[float] | None = None,
    reps: list[int] | None = None,
    hrs: list[float | None] | None = None,
    active_pattern: list[tuple[float, int]] | None = None,
    rest_between: float = 60.0,
    set_dur: float = 60.0,
    start_time: datetime = SYNTH_START,
    record_mesgs: list[dict] | None = None,
    device_info_mesgs: list[dict] | None = None,
    sport: str = "training",
    sub_sport: str = "strength_training",
    session_total_elapsed_time: float | None = None,
) -> dict:
    """Build a FIT-style ``msgs`` dict matching what Decoder().read() would
    return after SDK enum/scale conversion. Feeds ``parse_strength_fit_from_msgs``."""
    if active_pattern is not None:
        weights = [w for w, _ in active_pattern]
        reps = [r for _, r in active_pattern]
    if weights is None or reps is None:
        raise ValueError("must pass weights+reps or active_pattern")
    if hrs is None:
        hrs = [130.0] * len(weights)
    weights = [float(w) if w is not None else None for w in weights]

    set_mesgs = []
    record_mesgs_built = []
    cursor = start_time
    for i, (w, r, hr) in enumerate(zip(weights, reps, hrs, strict=True)):
        set_mesgs.append({
            "start_time": cursor,
            "duration": set_dur,
            "weight": w,
            "repetitions": r,
            "set_type": "active",
            "category": None,
            "category_subtype": None,
        })
        if hr is not None:
            for sec in range(int(set_dur)):
                record_mesgs_built.append({
                    "timestamp": cursor + timedelta(seconds=sec),
                    "heart_rate": hr,
                })
        cursor += timedelta(seconds=set_dur)

        if i < len(weights) - 1:
            set_mesgs.append({
                "start_time": cursor,
                "duration": rest_between,
                "weight": None,
                "repetitions": None,
                "set_type": "rest",
                "category": None,
                "category_subtype": None,
            })
            cursor += timedelta(seconds=rest_between)

    total_elapsed = session_total_elapsed_time
    if total_elapsed is None:
        total_elapsed = (cursor - start_time).total_seconds()

    if device_info_mesgs is None:
        device_info_mesgs = [
            {"source_type": "local", "device_index": 0, "garmin_product": "vivoactive5"},
        ]

    return {
        "session_mesgs": [{
            "start_time": start_time,
            "sport": sport,
            "sub_sport": sub_sport,
            "total_elapsed_time": total_elapsed,
        }],
        "set_mesgs": set_mesgs,
        "record_mesgs": record_mesgs if record_mesgs is not None else record_mesgs_built,
        "device_info_mesgs": device_info_mesgs,
    }


def stats(session: StrengthSession):
    """One-call convenience: session → StrengthSessionStats.

    Wraps the multi-step pipeline (identify_exercises + _build_session_stats)
    so tests can write ``stats(sess)`` instead of three lines of boilerplate.
    Imported lazily to avoid a circular dependency during early TDD writes.
    """
    from blackswan.strength_metrics import _build_session_stats

    exercises = identify_exercises(session)
    return _build_session_stats(session, exercises)

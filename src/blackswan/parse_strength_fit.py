"""Parse a Garmin strength-training FIT into StrengthSet / StrengthSession.

Calibrated on n=5 vivoactive 5 sessions, single user. Cross-device behaviour
is unverified — when `device_info_mesgs` reports a non-vivoactive-5 device a
runtime warning is emitted (per V2.2 / TD-3). The parser does NOT raise on
unknown devices because the FIT structure is shared across Garmin watches;
the warning is enough to surface the calibration gap.

Authoritative set boundary: ``set.start_time`` (FIT spec field 6). On
vivoactive 5, ``set.timestamp`` is filled with ``session.start_time`` for all
sets and is useless. Cursor-accumulation reconstruction (sum of durations
from session start) drifts 0.5–3 s and mismatches ``total_elapsed_time`` on
3/5 verified sessions — do not use it.

Usage:

    from blackswan.parse_strength_fit import parse_strength_fit

    session = parse_strength_fit("path/to/strength.fit")
    print(session.start_time, len(session.sets))
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Literal

from garmin_fit_sdk import Decoder, Stream, convert_timestamp_to_datetime

from blackswan._time import LOCAL_TZ

__all__ = [
    "StrengthSet",
    "StrengthSession",
    "parse_strength_fit",
    "parse_strength_fit_from_msgs",
]

VIVOACTIVE_5 = "vivoactive5"  # canonical SDK string (no underscore)
KNOWN_SET_TYPES = ("active", "rest")

_WEIGHT_ROUND_DP = 2
"""Decimal places we round set weights to at parser exit. Garmin's FIT
weight scale is 16 (so 0.0625 kg per integer step), and float arithmetic in
the SDK can leak residual noise like 60.0 vs 60.0000001. Rounding to 2dp at
the parser gives every downstream consumer a canonical value, so weight
comparisons (greedy bucket matching, ref-set lookup, exercise grouping)
can stay on plain ``==`` without the float-equality landmine called out in
CLAUDE.md."""


@dataclass
class StrengthSet:
    """One row from ``set_mesgs``. Both active and rest sets are kept; rest
    sets carry ``active_idx=None`` so callers can filter cleanly."""

    set_idx: int
    active_idx: int | None
    set_type: Literal["active", "rest"]
    t_start: datetime
    t_end: datetime
    duration: float
    weight: float | None
    reps: int | None
    raw_category: list[str] | None
    raw_category_subtype: list[int] | None
    hr_avg: float | None
    hr_max: float | None
    hr_start: float | None
    hr_end: float | None
    hr_next60s_avg: float | None


@dataclass
class StrengthSession:
    fit_path: Path | None
    sport: str
    sub_sport: str
    start_time: datetime
    local_hour: int
    total_elapsed_time: float
    device_product: str | None
    sets: list[StrengthSet]


def _to_local(ts) -> datetime:
    """Normalise a FIT timestamp (epoch int, naive datetime, or aware
    datetime) to a timezone-aware ``LOCAL_TZ`` datetime."""
    if isinstance(ts, (int, float)):
        return convert_timestamp_to_datetime(ts).astimezone(LOCAL_TZ)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=LOCAL_TZ)
        return ts.astimezone(LOCAL_TZ)
    raise TypeError(f"unsupported FIT timestamp type: {type(ts).__name__}")


def _device_product(device_info_mesgs: list[dict]) -> str | None:
    """V2.11: prefer the local watch device, not a paired ANT+ HR strap.

    Filter to ``source_type == 'local'`` first; fall back to
    ``device_index == 0`` if no source_type is present (older FITs).
    Return the device's ``garmin_product`` if available, else None.
    """
    if not device_info_mesgs:
        return None

    # Prefer source_type == "local" (string after SDK enum conversion)
    locals_ = [d for d in device_info_mesgs if d.get("source_type") == "local"]
    if locals_:
        return locals_[0].get("garmin_product")

    # Fallback: device_index == 0 (the watch itself in older firmware)
    zeros = [d for d in device_info_mesgs if d.get("device_index") == 0]
    if zeros:
        return zeros[0].get("garmin_product")

    return None


def _hr_records_in(records: list[dict], t_start: datetime, t_end: datetime) -> list[float]:
    """Return ``heart_rate`` values whose timestamp lies in ``[t_start, t_end]``."""
    out = []
    for r in records:
        ts = r.get("timestamp")
        hr = r.get("heart_rate")
        if ts is None or hr is None:
            continue
        ts_local = _to_local(ts)
        if t_start <= ts_local <= t_end:
            out.append(float(hr))
    return out


def parse_strength_fit_from_msgs(
    msgs: dict,
    fit_path: Path | str | None = None,
) -> StrengthSession:
    """Parse pre-decoded FIT messages into a StrengthSession.

    This is the testable core. ``parse_strength_fit`` wraps Decoder around it.
    Tests can construct ``msgs`` dicts directly without writing FIT bytes.

    Validates sport / sub_sport per V2.10. Raises ValueError with
    problem+cause+fix triplet on mismatch.

    Raises:
        ValueError: empty session_mesgs, wrong sport/sub_sport, unknown
            set_type enum, missing set.start_time, overlapping sets.
    """
    sessions = msgs.get("session_mesgs") or []
    if not sessions:
        raise ValueError(
            "FIT contains no session_mesgs. "
            "Cause: file is malformed or was truncated mid-write. "
            "Fix: re-export the activity from Garmin Connect or check the "
            "source file with garmin_fit_sdk Decoder for parse errors."
        )
    sess0 = sessions[0]

    sport = sess0.get("sport")
    sub_sport = sess0.get("sub_sport")
    if sport != "training" or sub_sport != "strength_training":
        raise ValueError(
            f"Expected sport='training' / sub_sport='strength_training', "
            f"got sport={sport!r} / sub_sport={sub_sport!r}. "
            "Cause: this FIT is not a strength session — likely running, "
            "cycling, or another sport. "
            "Fix: pass a strength-training FIT, or use the appropriate "
            "blackswan parser for this sport (e.g. cc_metrics for cardio "
            "intervals)."
        )

    start_time = _to_local(sess0["start_time"])
    total_elapsed_time = float(sess0.get("total_elapsed_time") or 0.0)
    session_end = start_time + timedelta(seconds=total_elapsed_time)

    device_product = _device_product(msgs.get("device_info_mesgs") or [])
    if device_product is not None and device_product != VIVOACTIVE_5:
        warnings.warn(
            f"Strength parser was calibrated on vivoactive 5 only "
            f"(detected device_product={device_product!r}). FIT structure is "
            "shared across Garmin watches but per-set fields may differ. "
            "Verify field semantics against the FIT spec before relying on "
            "the result.",
            stacklevel=2,
        )

    set_mesgs = msgs.get("set_mesgs") or []
    record_mesgs = msgs.get("record_mesgs") or []

    sets: list[StrengthSet] = []
    active_counter = 0

    for raw_idx, raw in enumerate(set_mesgs):
        if "start_time" not in raw or raw["start_time"] is None:
            raise ValueError(
                f"set_mesgs[{raw_idx}] is missing start_time (FIT field 6). "
                "Cause: the device firmware did not record per-set start "
                "timestamps. blackswan refuses cursor-accumulation fallback "
                "because it drifts 0.5-3s and mismatches total_elapsed_time. "
                "Fix: confirm the device firmware writes set.start_time "
                "(verified on vivoactive 5); for other devices, file a "
                "blackswan issue with a synthetic FIT reproducing the gap."
            )

        set_type = raw.get("set_type")
        if set_type not in KNOWN_SET_TYPES:
            raise ValueError(
                f"set_mesgs[{raw_idx}].set_type={set_type!r} is not in "
                f"{KNOWN_SET_TYPES}. "
                "Cause: device emitted a non-spec set_type (e.g. 'warmup'). "
                "FIT spec only defines active=1 / rest=0 for set_type. "
                "Fix: file a blackswan issue with the FIT and device_product "
                "so we can decide whether to extend the enum or treat the "
                "value as a device bug."
            )

        t_start = _to_local(raw["start_time"])
        duration = float(raw.get("duration") or 0.0)
        t_end = t_start + timedelta(seconds=duration)

        if sets and t_start < sets[-1].t_end:
            raise ValueError(
                f"set_mesgs[{raw_idx}] starts at {t_start.isoformat()} which "
                f"is before previous set ended at {sets[-1].t_end.isoformat()}. "
                "Cause: the FIT contains overlapping set windows, indicating "
                "corrupted timing or a device bug. "
                "Fix: re-export the activity from Garmin Connect; if the "
                "issue persists, file an issue with a synthetic reproducer."
            )

        active_idx = None
        if set_type == "active":
            active_idx = active_counter
            active_counter += 1

        in_window = _hr_records_in(record_mesgs, t_start, t_end)
        hr_avg = mean(in_window) if in_window else None
        hr_max = max(in_window) if in_window else None
        hr_start = in_window[0] if in_window else None
        hr_end = in_window[-1] if in_window else None

        # V2.16: hr_next60s_avg clipped to session.start_time + total_elapsed_time
        next_window_end = min(t_end + timedelta(seconds=60), session_end)
        if next_window_end > t_end:
            in_next = _hr_records_in(record_mesgs, t_end, next_window_end)
            hr_next60s_avg = mean(in_next) if in_next else None
        else:
            hr_next60s_avg = None

        weight_raw = raw.get("weight")
        weight = round(weight_raw, _WEIGHT_ROUND_DP) if weight_raw is not None else None

        sets.append(
            StrengthSet(
                set_idx=raw_idx,
                active_idx=active_idx,
                set_type=set_type,
                t_start=t_start,
                t_end=t_end,
                duration=duration,
                weight=weight,
                reps=raw.get("repetitions"),
                raw_category=raw.get("category"),
                raw_category_subtype=raw.get("category_subtype"),
                hr_avg=hr_avg,
                hr_max=hr_max,
                hr_start=hr_start,
                hr_end=hr_end,
                hr_next60s_avg=hr_next60s_avg,
            )
        )

    return StrengthSession(
        fit_path=Path(fit_path) if fit_path else None,
        sport=sport,
        sub_sport=sub_sport,
        start_time=start_time,
        local_hour=start_time.hour,
        total_elapsed_time=total_elapsed_time,
        device_product=device_product,
        sets=sets,
    )


def parse_strength_fit(fit_path: Path | str) -> StrengthSession:
    """Parse a strength-training FIT file from disk.

    Pins ``Decoder().read(convert_datetimes_to_dates=False)`` per V2.7 to
    match the cardio convention. SDK defaults are used for everything else
    (apply_scale=True, convert_types_to_strings=True) so weight is in kg,
    duration in seconds, and enums are strings.

    Raises:
        FileNotFoundError: if ``fit_path`` does not exist.
        ValueError: see :func:`parse_strength_fit_from_msgs`.
    """
    fit_path = Path(fit_path)
    if not fit_path.exists():
        raise FileNotFoundError(f"FIT file not found: {fit_path}")
    msgs, _ = Decoder(Stream.from_file(str(fit_path))).read(convert_datetimes_to_dates=False)
    return parse_strength_fit_from_msgs(msgs, fit_path=fit_path)

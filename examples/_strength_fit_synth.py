"""Shared synthetic FIT builder for the two strength examples.

Internal to ``examples/``. Used by ``synthetic_strength_baseline.py`` and
``synthetic_strength_recent.py``. Produces byte-deterministic FIT output
suitable for `parse_strength_fit`.

Synthetic-year invariant: every timestamp inside the encoded FIT must be
in year 2000. The PII grep guard (``scripts/check-pii.sh``) rejects
``datetime(202[0-9]`` literals in ``examples/`` for this reason.

Manufacturer / serial fields use the FIT-spec "development" sentinel
(manufacturer id 255 / serial 0) so nothing in the output identifies the
machine that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from garmin_fit_sdk import Encoder

_FIT_EPOCH = datetime(1989, 12, 31, 0, 0, tzinfo=timezone.utc)
_DEVELOPMENT_MANUFACTURER = 255
_DEVELOPMENT_SERIAL = 0
_VIVOACTIVE_5_PRODUCT = 4426  # FIT garmin_product enum


@dataclass(frozen=True)
class SyntheticSet:
    weight: float
    reps: int
    set_type: str  # "active" or "rest"
    duration: float = 60.0
    hr_avg: float | None = 130.0


def _to_fit_seconds(dt: datetime) -> int:
    return int((dt.astimezone(timezone.utc) - _FIT_EPOCH).total_seconds())


def build_strength_fit_bytes(
    *,
    sets: list[SyntheticSet],
    start_time: datetime,
    rest_between: float = 90.0,
) -> bytes:
    """Encode a synthetic strength FIT and return the bytes.

    The session metadata is fixed: ``sport='training'``,
    ``sub_sport='strength_training'``, ``device_product='vivoactive_5'``.
    HR records are emitted at 1Hz inside each active-set window with the
    set's ``hr_avg``; rest sets emit no HR records.

    Determinism: same input → same bytes. No system clock, no machine id,
    no random data.
    """
    if start_time.year != 2000:
        raise ValueError(
            "synthetic FIT must use year=2000 timestamps "
            "(PII guard requires no real-world dates in examples/)."
        )

    e = Encoder()

    # file_id (mesg_num=0)
    e.write_mesg({
        "mesg_num": 0,
        "type": "activity",
        "manufacturer": _DEVELOPMENT_MANUFACTURER,
        "product": 0,
        "serial_number": _DEVELOPMENT_SERIAL,
        "time_created": _to_fit_seconds(start_time),
    })

    # device_info (mesg_num=23) — local watch, vivoactive 5
    # NB: FIT field is `product` (uint16); the SDK aliases it to
    # `garmin_product` on read when manufacturer == garmin.
    e.write_mesg({
        "mesg_num": 23,
        "timestamp": _to_fit_seconds(start_time),
        "device_index": 0,
        "source_type": "local",
        "manufacturer": "garmin",
        "product": _VIVOACTIVE_5_PRODUCT,
        "serial_number": _DEVELOPMENT_SERIAL,
    })

    cursor = start_time
    record_buf: list[dict] = []
    set_msgs: list[dict] = []

    for i, s in enumerate(sets):
        set_msgs.append({
            "mesg_num": 225,
            "start_time": _to_fit_seconds(cursor),
            "timestamp": _to_fit_seconds(start_time),  # vivoactive 5 quirk
            "duration": s.duration,
            "weight": s.weight if s.weight is not None else None,
            "repetitions": s.reps if s.reps is not None else None,
            "set_type": s.set_type,
            "message_index": i,
        })

        if s.set_type == "active" and s.hr_avg is not None:
            for offset in range(int(s.duration)):
                record_buf.append({
                    "mesg_num": 20,
                    "timestamp": _to_fit_seconds(cursor + timedelta(seconds=offset)),
                    "heart_rate": int(s.hr_avg),
                })

        cursor += timedelta(seconds=s.duration)
        # Trailing rest gap after every set except the last
        if i < len(sets) - 1:
            cursor += timedelta(seconds=rest_between)

    total_elapsed = (cursor - start_time).total_seconds()

    # Records first (chronological), then sets (may reference any time),
    # then session at the end (FIT canonical order).
    for r in record_buf:
        e.write_mesg(r)
    for sm in set_msgs:
        e.write_mesg(sm)

    # session (mesg_num=18)
    e.write_mesg({
        "mesg_num": 18,
        "timestamp": _to_fit_seconds(cursor),
        "start_time": _to_fit_seconds(start_time),
        "sport": "training",
        "sub_sport": "strength_training",
        "total_elapsed_time": total_elapsed,
    })

    return e.close()

"""Generate a synthetic baseline strength FIT for examples and tests.

Run this as a module to produce ``examples/data/synthetic_baseline.fit``:

    uv run python -m examples.synthetic_strength_baseline

The byte output is deterministic (verified by ``test_synthetic_strength``).
Year 2000 timestamps; no real-world serial numbers or machine identifiers.
The session profile is a 1-warmup + 6-work-set deadlift routine with a
clean HR trajectory (no artifact).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from blackswan._time import LOCAL_TZ
from examples._strength_fit_synth import SyntheticSet, build_strength_fit_bytes

OUT_PATH = Path(__file__).parent / "data" / "synthetic_baseline.fit"

BASELINE_START = datetime(2000, 1, 15, 18, 30, tzinfo=LOCAL_TZ)

BASELINE_SETS = [
    SyntheticSet(weight=40.0, reps=12, set_type="active", duration=45.0, hr_avg=110.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=90.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=120.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=125.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=128.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=130.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=132.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=135.0),
]


def build_baseline_fit() -> bytes:
    return build_strength_fit_bytes(
        sets=BASELINE_SETS,
        start_time=BASELINE_START,
        rest_between=0.0,  # rest sets explicit in BASELINE_SETS
    )


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_bytes(build_baseline_fit())
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

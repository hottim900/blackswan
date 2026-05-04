"""Generate a synthetic recent strength FIT — same routine as the baseline
but with an early-session optical-HR artifact in the first 3 work sets.

This pair drives the quickstart demo: pairing the two surfaces the detector
firing on the recent session and the warning landing in
``StrengthComparisonReport.artifact_warnings``.

Year 2000 timestamps (one month after baseline) — same PII guarantees.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from blackswan._time import LOCAL_TZ
from examples._strength_fit_synth import SyntheticSet, build_strength_fit_bytes

OUT_PATH = Path(__file__).parent / "data" / "synthetic_recent.fit"

RECENT_START = datetime(2000, 2, 15, 18, 30, tzinfo=LOCAL_TZ)

RECENT_SETS = [
    SyntheticSet(weight=40.0, reps=12, set_type="active", duration=45.0, hr_avg=95.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=90.0, hr_avg=None),
    # Early sets read suspiciously low (artifact)
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=72.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=78.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=85.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    # Late sets normalise
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=128.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=132.0),
    SyntheticSet(weight=0.0, reps=0, set_type="rest", duration=120.0, hr_avg=None),
    SyntheticSet(weight=60.0, reps=8, set_type="active", duration=50.0, hr_avg=135.0),
]


def build_recent_fit() -> bytes:
    return build_strength_fit_bytes(
        sets=RECENT_SETS,
        start_time=RECENT_START,
        rest_between=0.0,
    )


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_bytes(build_recent_fit())
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

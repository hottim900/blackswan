"""Shared helpers for Garmin sleep data interpretation.

Single source of truth for:
- The "awake is a brief arousal, not a sustained wake state" semantics
  (see parse_daily_fit.py docstring).
- sleep-all.csv / sleep-official.csv column schema (SLEEP_COLS below) —
  shared between parse_bulk_export.py (writer) and build_sleep_official.py
  (reader+writer). Changing the schema here is enough; both scripts pick
  it up automatically.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=8))


SLEEP_COLS = [
    "calendar_date", "sleep_start_gmt", "sleep_end_gmt",
    "deep_sec", "light_sec", "rem_sec", "awake_sec", "unmeasurable_sec",
    "awake_count", "restless_moment_count",
    "avg_respiration", "lowest_respiration", "highest_respiration",
    "avg_sleep_stress", "overall_score", "quality_score", "duration_score",
    "recovery_score", "deep_score", "rem_score", "light_score",
    "awakenings_count_score", "awake_time_score", "combined_awake_score",
    "interruptions_score", "restfulness_score",
    "avg_sleep_spo2", "lowest_sleep_spo2", "avg_sleep_hr",
    "sleep_measurement_start_gmt", "sleep_measurement_end_gmt",
    "breathing_disruption_severity",
    "confirmation_type", "retro",
]


def stage_at(
    t: datetime,
    transitions: Iterable[tuple[datetime, str]],
    *,
    default=None,
):
    """Return the non-awake sleep stage in effect at t.

    `transitions` must be (timestamp, level) pairs sorted ascending. Awake
    transitions are skipped — the reading inherits the most recent
    light/deep/rem/unmeasurable stage. Returns `default` if no non-awake
    stage precedes t.
    """
    current = default
    for ts, level in transitions:
        if ts > t:
            break
        if level != "awake":
            current = level
    return current

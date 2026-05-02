"""Authoritative uphill-segment extraction for interval training FITs.

For uphill interval training (repeated climbs with downhill walk-back), this
splits a session into individual climb segments using **alt min → alt max** —
the climb starts at a local low altitude (start of the push) and ends at a
local peak (top of the climb).

Validated against hand-marked training-log timestamps (≤ 0.1 CC point delta
across n=4 trials), so this matches what an analyst would mark manually if
they had to draw climb boundaries on the elevation profile.

Per trial it returns:
- timestamp range (start_time, end_time)
- duration (s), distance (m), ascent (m)
- average speed (km/h), grade (%)
- start HR, average HR, max HR
- Cardiac Cost (CC = avg HR / avg km/h)

Usage:
    from blackswan.segment_uphill import find_uphill_trials_in_lap
    from garmin_fit_sdk import Decoder, Stream

    msgs, _ = Decoder(Stream.from_file("activity.fit")).read()
    laps = msgs["lap_mesgs"]
    records = msgs["record_mesgs"]

    # If the user marks each climb with a lap button at the bottom of the climb
    # (one trial per lap), call this for each work lap:
    for lap in laps[2:8]:  # skip warm-up + cool-down
        trial = find_uphill_trials_in_lap(records, lap)
        if trial:
            print(f"  CC={trial['cc']:.2f}  avgHR={trial['avg_hr']:.1f}")

    # Or run an unsupervised pass over the whole session:
    from blackswan.segment_uphill import find_uphill_segments
    trials = find_uphill_segments(records, min_ascent=15)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

__all__ = [
    "find_uphill_trials_in_lap",
    "find_uphill_segments",
    "stats_for_window",
    "compute_cc",
]


def _records_to_pts(records: list[dict]) -> list[dict]:
    """Normalise FIT records into the {ts, alt, hr, kmh, dist} dicts used here."""
    pts: list[dict] = []
    for r in records:
        ts = r.get("timestamp")
        if not ts:
            continue
        sp = r.get("enhanced_speed") or 0
        kmh = sp * 3.6 if sp < 30 else 0  # 65.535 m/s sentinel guard
        pts.append({
            "ts": ts,
            "alt": r.get("enhanced_altitude"),
            "hr": r.get("heart_rate"),
            "kmh": kmh,
            "dist": r.get("distance"),
        })
    return pts


def stats_for_window(records: list[dict], t_start: datetime, t_end: datetime) -> Optional[dict]:
    """Per-trial stats for a fixed [t_start, t_end] window.

    Used for verifying against known-good (hand-marked) training-log timestamps.

    Returns:
        dict with keys {t_start, t_end, dur, dist, kmh, ascent, grade,
        start_hr, avg_hr, max_hr, cc}, or **None** if any of:
        - no records fall inside [t_start, t_end]
        - no HR values in the window
        - duration is zero (single-point or empty window)
        - distance is zero (CC undefined when avg speed is 0)
    """
    pts = _records_to_pts(records)
    seg = [p for p in pts if t_start <= p["ts"] <= t_end]
    if not seg:
        return None
    dur = (seg[-1]["ts"] - seg[0]["ts"]).total_seconds()
    d0 = seg[0]["dist"] or 0
    d1 = seg[-1]["dist"] or 0
    dist = d1 - d0
    kmh = (dist / dur) * 3.6 if dur else 0
    hrs = [p["hr"] for p in seg if p["hr"]]
    alts = [p["alt"] for p in seg if p["alt"] is not None]
    if not hrs or not kmh:
        return None
    avg_hr = sum(hrs) / len(hrs)
    return {
        "t_start": seg[0]["ts"],
        "t_end": seg[-1]["ts"],
        "dur": dur,
        "dist": dist,
        "kmh": kmh,
        "ascent": (max(alts) - min(alts)) if alts else 0,
        "grade": ((max(alts) - min(alts)) / dist * 100) if alts and dist else 0,
        "start_hr": hrs[0],
        "avg_hr": avg_hr,
        "max_hr": max(hrs),
        "cc": avg_hr / kmh,
    }


def find_uphill_trials_in_lap(
    records: list[dict],
    lap: dict,
    search_back_s: int = 30,
    min_ascent: float = 8.0,
) -> Optional[dict]:
    """Within a single lap, find the alt min → alt max climb sub-segment.

    Useful when the user marks each climb with the lap button at the bottom of
    the climb (one trial per lap). The sub-segment may extend slightly before
    `lap.start_time` (up to `search_back_s` seconds) to capture the true
    altitude minimum.

    Returns None if the lap doesn't contain a climb of at least `min_ascent`
    metres.
    """
    pts = _records_to_pts(records)
    t0 = lap["start_time"]
    t1 = t0 + timedelta(seconds=lap["total_timer_time"])

    window = [
        p for p in pts
        if t0 - timedelta(seconds=search_back_s) <= p["ts"] <= t1 + timedelta(seconds=10)
        and p["alt"] is not None
    ]
    if not window:
        return None

    # alt min: the lowest altitude in [t0 - search_back, t0 + 30s]
    front = [p for p in window if p["ts"] <= t0 + timedelta(seconds=30)]
    if not front:
        return None
    min_p = min(front, key=lambda p: p["alt"])

    # alt max: the highest altitude after min, before t1 + 10s
    after = [p for p in window if p["ts"] > min_p["ts"]]
    if not after:
        return None
    max_p = max(after, key=lambda p: p["alt"])

    if max_p["alt"] - min_p["alt"] < min_ascent:
        return None

    return stats_for_window(records, min_p["ts"], max_p["ts"])


def find_uphill_segments(
    records: list[dict],
    min_dur: int = 60,
    min_ascent: float = 15.0,
    min_hr_avg: float = 100.0,
) -> list[dict]:
    """Unsupervised pass: find every climb segment in the session.

    Walks the smoothed altitude trace and emits a segment whenever a sustained
    climb (>= `min_ascent` metres) is detected. Use this when laps were not
    pressed (or when the lap-button cadence is unreliable).

    Note: less reliable than `find_uphill_trials_in_lap` for unusual courses
    (zigzag climbs, multi-peak ridges) — prefer the lap-based variant if
    laps are available.
    """
    pts = _records_to_pts(records)
    pts = [p for p in pts if p["alt"] is not None]
    if len(pts) < 30:
        return []

    # 5-second rolling-average altitude (smooth GPS noise)
    alts = [p["alt"] for p in pts]
    sm: list[float] = []
    for i in range(len(alts)):
        lo = max(0, i - 5)
        hi = min(len(alts), i + 6)
        sm.append(sum(alts[lo:hi]) / (hi - lo))

    trials: list[dict] = []
    i = 0
    while i < len(pts):
        # Skip flat / descending
        while i < len(pts) - 1 and sm[i + 1] - sm[i] < 0.05:
            i += 1
        if i >= len(pts) - 1:
            break

        start_i = i
        # Walk while ascending (5-sec lookahead must still be at-or-above current)
        while i < len(pts) - 1:
            future = sm[i + 1 : i + 6]
            if not future or future[-1] - sm[i] < 0:
                break
            i += 1
        end_i = i
        if end_i <= start_i:
            i += 1
            continue

        seg_pts = pts[start_i : end_i + 1]
        ascent = sm[end_i] - sm[start_i]
        dur = (seg_pts[-1]["ts"] - seg_pts[0]["ts"]).total_seconds()
        hrs = [p["hr"] for p in seg_pts if p["hr"]]
        avg_hr = sum(hrs) / len(hrs) if hrs else 0

        if dur >= min_dur and ascent >= min_ascent and avg_hr >= min_hr_avg:
            trial = stats_for_window(records, seg_pts[0]["ts"], seg_pts[-1]["ts"])
            if trial:
                trials.append(trial)
        i += 1

    return trials


def compute_cc(avg_hr: float, kmh: float) -> float:
    """Cardiac Cost: avg HR ÷ km/h. Lower is more efficient."""
    return avg_hr / kmh if kmh else 0

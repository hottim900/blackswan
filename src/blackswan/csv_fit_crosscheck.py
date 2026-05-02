"""Cross-validate Garmin Connect lap CSV against parsed FIT lap_mesgs.

Garmin gdrive activity exports usually include both `XXX_ACTIVITY.fit` and
`activity_XXX.csv`. The CSV is the Garmin Connect server-side computation,
the FIT is the device-side raw record. Comparing them catches FIT parser
bugs and exposes systematic (non-bug) differences in two known fields.

## Expected agreement (parsing is correct)

| Field          | Tolerance        | Notes                          |
|----------------|-----------------|--------------------------------|
| duration (s)   | Δ ≤ 1           | CSV rounds, FIT has fractional |
| distance (m)   | Δ ≤ 8 (0.01 km) | CSV rounds to 0.01 km          |
| avg HR / max HR| Δ = 0           | identical                      |
| calories       | Δ = 0           | identical                      |

## Expected systematic differences (NOT bugs)

| Field      | Pattern                                                      |
|------------|--------------------------------------------------------------|
| ascent     | CSV smooths, FIT raw. Multi-bump laps (warm-up, cool-down)   |
|            | can differ by 10-25 m. Match laps with monotone climbs.      |
| descent    | Same as ascent.                                              |
| cadence    | CSV = strides/min (both feet); FIT = cycles/min (one foot).  |
|            | CSV ≈ 2 × FIT.                                               |

If you see a field mismatch outside its tolerance, suspect a FIT parser bug
or a lap-boundary disagreement.

Usage:
    from blackswan.csv_fit_crosscheck import crosscheck_lap_csv
    report = crosscheck_lap_csv("activity.fit", "activity.csv")
    for issue in report["issues"]:
        print(f"  ! {issue}")
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

__all__ = ["crosscheck_lap_csv", "parse_garmin_lap_csv"]


def _parse_dur(s: str) -> float:
    """Parse Garmin CSV duration like '19:41' or '3:04.2' → seconds (float)."""
    s = s.strip()
    parts = s.split(":")
    if len(parts) == 2:
        m, sec = parts
        return int(m) * 60 + float(sec)
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    return float(s)


def parse_garmin_lap_csv(csv_path: str | Path) -> list[dict]:
    """Parse a Garmin Connect lap-export CSV. Returns one dict per row.

    Garmin exports use Chinese column headers; this parser is robust to that
    by indexing by column position rather than name.
    """
    rows: list[dict] = []
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        next(reader)  # skip column-name row
        for row in reader:
            if len(row) < 8:
                continue
            try:
                rows.append({
                    "lap": row[0],
                    "dur_s": _parse_dur(row[1]),
                    "dist_km": float(row[3]),
                    "avg_hr": int(float(row[5])) if row[5] else None,
                    "max_hr": int(float(row[6])) if row[6] else None,
                    "ascent": int(float(row[7])) if row[7] else 0,
                    "descent": int(float(row[8])) if len(row) > 8 and row[8] else 0,
                    "cad_csv": int(float(row[9])) if len(row) > 9 and row[9] else None,
                    "cal": int(float(row[10])) if len(row) > 10 and row[10] else None,
                })
            except (ValueError, IndexError):
                # Final "Summary" row may have non-numeric format; skip silently
                continue
    return rows


def crosscheck_lap_csv(fit_path: str | Path, csv_path: str | Path) -> dict:
    """Compare parsed FIT lap_mesgs against Garmin Connect CSV.

    Returns:
        {
            "matched": [...]            # one row per lap, with per-field deltas
            "issues": [...]              # human-readable warnings
            "summary": {
                "n_laps": int,
                "max_hr_delta": float,
                "max_dur_delta": float,
                ...
            }
        }
    """
    from garmin_fit_sdk import Decoder, Stream

    msgs, _ = Decoder(Stream.from_file(str(fit_path))).read()
    fit_laps = msgs.get("lap_mesgs", [])
    csv_rows = parse_garmin_lap_csv(csv_path)

    matched: list[dict] = []
    issues: list[str] = []
    max_dur_d = 0.0
    max_hr_d = 0
    max_dist_d = 0.0

    for i, csv_row in enumerate(csv_rows):
        if i >= len(fit_laps):
            issues.append(f"CSV has lap {i+1} but FIT only has {len(fit_laps)} laps")
            break
        fit_lap = fit_laps[i]

        fit_dur = fit_lap.get("total_timer_time", 0)
        fit_dist = fit_lap.get("total_distance", 0)
        fit_aHR = fit_lap.get("avg_heart_rate")
        fit_mHR = fit_lap.get("max_heart_rate")
        fit_asc = fit_lap.get("total_ascent", 0)
        fit_desc = fit_lap.get("total_descent", 0)
        fit_cad = fit_lap.get("avg_cadence")

        d_dur = csv_row["dur_s"] - fit_dur
        d_dist = csv_row["dist_km"] * 1000 - fit_dist
        d_aHR = (csv_row["avg_hr"] - fit_aHR) if csv_row["avg_hr"] and fit_aHR else 0
        d_mHR = (csv_row["max_hr"] - fit_mHR) if csv_row["max_hr"] and fit_mHR else 0
        d_asc = csv_row["ascent"] - fit_asc

        # Tolerances
        if abs(d_dur) > 1.0:
            issues.append(f"Lap {i+1}: duration delta {d_dur:+.1f}s exceeds tolerance (≤1s)")
        if abs(d_dist) > 8.0:
            issues.append(f"Lap {i+1}: distance delta {d_dist:+.0f}m exceeds tolerance (≤8m)")
        if abs(d_aHR) > 0:
            issues.append(f"Lap {i+1}: avg HR delta {d_aHR:+}bpm (expected 0)")
        if abs(d_mHR) > 0:
            issues.append(f"Lap {i+1}: max HR delta {d_mHR:+}bpm (expected 0)")

        # Cadence: CSV is strides/min (both feet), FIT is cycles/min (one foot)
        # Expected ratio CSV/FIT ≈ 2.0; outside [1.8, 2.2] suggests a parser bug
        cad_ratio = (csv_row["cad_csv"] / fit_cad) if csv_row["cad_csv"] and fit_cad else None
        if cad_ratio is not None and not (1.8 <= cad_ratio <= 2.2):
            issues.append(
                f"Lap {i+1}: cadence ratio CSV/FIT = {cad_ratio:.2f} outside [1.8, 2.2]"
                f" (expected ≈2.0 because CSV=strides/min, FIT=cycles/min)"
            )

        matched.append({
            "lap": i + 1,
            "fit": {"dur": fit_dur, "dist": fit_dist, "aHR": fit_aHR, "mHR": fit_mHR,
                    "asc": fit_asc, "desc": fit_desc, "cad": fit_cad},
            "csv": csv_row,
            "delta": {"dur": d_dur, "dist": d_dist, "aHR": d_aHR, "mHR": d_mHR, "asc": d_asc},
            "cad_ratio_csv_over_fit": cad_ratio,
        })

        max_dur_d = max(max_dur_d, abs(d_dur))
        max_hr_d = max(max_hr_d, abs(d_aHR), abs(d_mHR))
        max_dist_d = max(max_dist_d, abs(d_dist))

    return {
        "matched": matched,
        "issues": issues,
        "summary": {
            "n_laps": len(matched),
            "max_dur_delta": max_dur_d,
            "max_hr_delta": max_hr_d,
            "max_dist_delta": max_dist_d,
            "n_issues": len(issues),
        },
    }

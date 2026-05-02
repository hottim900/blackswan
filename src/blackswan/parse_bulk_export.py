"""Parse a Garmin GDPR bulk export ZIP into history CSVs.

Garmin Connect → Account → Manage Your Data → Export Your Data. A few days
later you get a ZIP containing:
- DI_CONNECT/DI-Connect-Wellness/*sleepData.json          (one row per night)
- DI_CONNECT/DI-Connect-Wellness/*healthStatusData.json   (daily HRV/HR/SpO2/... vs baseline)
- DI_CONNECT/DI-Connect-Wellness/*fitnessAgeData.json     (daily Fitness Age + bio age components)
- DI_CONNECT/DI-Connect-Wellness/*heartRateZones.json     (current HR zone configuration)
- DI_CONNECT/DI-Connect-Aggregator/UDSFile_*.json         (daily aggregated summary)
- DI_CONNECT/DI-Connect-Metrics/MetricsMaxMetData*.json   (VO2max history)
- DI_CONNECT/DI-Connect-Fitness/*summarizedActivities.json (one row per workout/walk/hike)
- DI_CONNECT/DI-Connect-Fitness/*personalRecord.json      (Garmin auto-detected lifetime bests)
- DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_*.zip (thousands of per-day FIT)

This script extracts the JSON aggregates only (the FIT nested zip is left
untouched — use parse_daily_fit.py on per-day bundles when you need
minute-level resolution).

Usage:
    python -m blackswan.parse_bulk_export \
        garmin/bulk-exports/YYYY-MM-DD-complete-export.zip \
        garmin/timeseries/history/

Outputs (see docs/methodology.md (and src/blackswan/*.py docstrings) for full column dictionary):
    sleep-all.csv           — one row per night (stages, scores, respiration, stress, sleep SpO2)
    naps.csv                — one row per nap event
    daily-summary.csv       — one row per day (HR, SpO2, body battery, stress, calories, distance)
    body-battery-stats.csv  — one row per (day, stat_type) for HIGHEST/LOWEST/SLEEPSTART/... events
    health-status-all.csv   — one row per (day, metric) from healthStatusData
    vo2max-all.csv          — VO2max history
    activities-summary.csv  — one row per recorded workout (type, duration, HR, elevation, GPS)
    fitness-age.csv         — one row per day (chronological + bio age, vigorous days rolling window)
    hr-zones.csv            — one row per sport (current Garmin HR zone config)
    personal-records.csv    — one row per PR (steps / barbell lifts / goal streaks)
"""

from __future__ import annotations

import csv
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from blackswan._sleep import LOCAL_TZ, SLEEP_COLS


def _ms_to_local_iso(ms):
    """Unix ms (UTC) → UTC+8 ISO string, or empty for missing."""
    if ms is None:
        return ""
    return datetime.fromtimestamp(ms / 1000, LOCAL_TZ).isoformat(timespec="seconds")


# ── Sleep ──────────────────────────────────────────────────────────────────────

def _score(scores, key):
    """Unwrap a sleepScores field — old Garmin schema returns a bare int,
    new schema wraps as `{value, qualifierKey}`."""
    v = scores.get(key)
    return v.get("value") if isinstance(v, dict) else v


def parse_sleep(sleep_entries):
    """Yield one row per sleep entry."""
    for e in sleep_entries:
        if not e.get("calendarDate"):
            continue  # placeholder/nap-only entries with no main sleep
        s = e.get("sleepScores") or {}
        spo2 = e.get("spo2SleepSummary") or {}
        yield [
            e.get("calendarDate"),
            e.get("sleepStartTimestampGMT"),
            e.get("sleepEndTimestampGMT"),
            e.get("deepSleepSeconds"),
            e.get("lightSleepSeconds"),
            e.get("remSleepSeconds"),
            e.get("awakeSleepSeconds"),
            e.get("unmeasurableSeconds"),
            e.get("awakeCount"),
            e.get("restlessMomentCount"),
            e.get("averageRespiration"),
            e.get("lowestRespiration"),
            e.get("highestRespiration"),
            e.get("avgSleepStress"),
            _score(s, "overallScore"),
            _score(s, "qualityScore"),
            _score(s, "durationScore"),
            _score(s, "recoveryScore"),
            _score(s, "deepScore"),
            _score(s, "remScore"),
            _score(s, "lightScore"),
            _score(s, "awakeningsCountScore"),
            _score(s, "awakeTimeScore"),
            _score(s, "combinedAwakeScore"),
            _score(s, "interruptionsScore"),
            _score(s, "restfulnessScore"),
            spo2.get("averageSPO2"),
            spo2.get("lowestSPO2"),
            spo2.get("averageHR"),
            spo2.get("sleepMeasurementStartGMT"),
            spo2.get("sleepMeasurementEndGMT"),
            e.get("breathingDisruptionSeverity"),
            e.get("sleepWindowConfirmationType"),
            e.get("retro"),
        ]


# ── Naps ─────────────────────────────────────────────────────────────────────

NAP_COLS = ["calendar_date", "start_gmt", "end_gmt", "duration_sec"]

def parse_naps(sleep_entries):
    """Naps are embedded on sleep entries (main-sleep or nap-only) under
    `napList`. Each item carries its own calendarDate, so we iterate all
    entries regardless of whether they have a main sleep."""
    for e in sleep_entries:
        for n in e.get("napList") or []:
            yield [
                n.get("calendarDate"),
                n.get("napStartTimestampGMT"),
                n.get("napEndTimestampGMT"),
                n.get("napTimeSec"),
            ]


# ── Daily summary (UDS) ───────────────────────────────────────────────────────

UDS_COLS = [
    "calendar_date", "duration_ms", "is_vigorous_day",
    "includes_activity_data", "includes_all_day_pulse_ox", "includes_sleep_pulse_ox",
    "min_hr", "max_hr", "resting_hr", "current_day_resting_hr",
    "resting_hr_timestamp",
    "max_avg_hr", "min_avg_hr",
    "avg_spo2", "lowest_spo2", "latest_spo2", "latest_spo2_reading_time_gmt",
    "avg_waking_respiration", "highest_respiration", "lowest_respiration",
    "latest_respiration", "latest_respiration_time_gmt",
    "avg_stress_level", "max_stress_level", "stress_duration_sec",
    "awake_avg_stress", "awake_max_stress", "awake_stress_duration_sec",
    "asleep_avg_stress", "asleep_max_stress", "asleep_stress_duration_sec",
    "body_battery_charged", "body_battery_drained",
    "total_kilocalories", "active_kilocalories", "bmr_kilocalories",
    "total_steps", "daily_step_goal", "total_distance_meters",
    "moderate_intensity_minutes", "vigorous_intensity_minutes",
    "highly_active_seconds",
    "active_seconds", "sedentary_seconds", "sleeping_seconds",
    "floors_ascended", "floors_descended",
    "avg_monitoring_environment_altitude",
]

def parse_uds(entries):
    for e in entries:
        stress = e.get("allDayStress") or {}
        aggs = stress.get("aggregatorList") or []
        by_type = {a.get("type"): a for a in aggs}
        total_stress = by_type.get("TOTAL") or {}
        awake_stress = by_type.get("AWAKE") or {}
        asleep_stress = by_type.get("ASLEEP") or {}
        bb = e.get("bodyBattery") or {}
        resp = e.get("respiration") or {}
        yield [
            e.get("calendarDate"),
            e.get("durationInMilliseconds"),
            e.get("isVigorousDay"),
            e.get("includesActivityData"),
            e.get("includesAllDayPulseOx"),
            e.get("includesSleepPulseOx"),
            e.get("minHeartRate"), e.get("maxHeartRate"),
            e.get("restingHeartRate"), e.get("currentDayRestingHeartRate"),
            e.get("restingHeartRateTimestamp"),
            e.get("maxAvgHeartRate"), e.get("minAvgHeartRate"),
            e.get("averageSpo2Value"), e.get("lowestSpo2Value"), e.get("latestSpo2Value"),
            e.get("latestSpo2ValueReadingTimeGmt"),
            resp.get("avgWakingRespirationValue"),
            resp.get("highestRespirationValue"),
            resp.get("lowestRespirationValue"),
            resp.get("latestRespirationValue"),
            resp.get("latestRespirationTimeGMT"),
            total_stress.get("averageStressLevel"),
            total_stress.get("maxStressLevel"),
            total_stress.get("stressDuration"),
            awake_stress.get("averageStressLevel"),
            awake_stress.get("maxStressLevel"),
            awake_stress.get("stressDuration"),
            asleep_stress.get("averageStressLevel"),
            asleep_stress.get("maxStressLevel"),
            asleep_stress.get("stressDuration"),
            bb.get("chargedValue"), bb.get("drainedValue"),
            e.get("totalKilocalories"), e.get("activeKilocalories"),
            e.get("bmrKilocalories"),
            e.get("totalSteps"), e.get("dailyStepGoal"),
            e.get("totalDistanceMeters"),
            e.get("moderateIntensityMinutes"), e.get("vigorousIntensityMinutes"),
            e.get("highlyActiveSeconds"),
            e.get("activeSeconds"), e.get("sedentarySeconds"),
            e.get("sleepingSeconds"),
            e.get("floorsAscendedInMeters"), e.get("floorsDescendedInMeters"),
            e.get("averageMonitoringEnvironmentAltitude"),
        ]


# ── Body battery stats (per-day HIGHEST/LOWEST/… events with timestamps) ─────

BB_COLS = ["calendar_date", "stat_type", "value", "status", "stat_timestamp"]

def parse_body_battery_stats(entries):
    for e in entries:
        date = e.get("calendarDate")
        bb = e.get("bodyBattery") or {}
        for s in bb.get("bodyBatteryStatList") or []:
            yield [
                date,
                s.get("bodyBatteryStatType"),
                s.get("statsValue"),
                s.get("bodyBatteryStatus"),
                s.get("statTimestamp"),
            ]


# ── Health status (LHA — HRV/HR/SpO2/skin_temp/respiration vs baseline) ──────

HEALTH_COLS = [
    "calendar_date", "metric_type", "value",
    "baseline_upper", "baseline_lower", "status", "percentage",
]

def parse_health_status(entries):
    for e in entries:
        date = e.get("calendarDate")
        for m in e.get("metrics") or []:
            yield [
                date,
                m.get("type"),
                m.get("value"),
                m.get("baselineUpperLimit"),
                m.get("baselineLowerLimit"),
                m.get("status"),
                m.get("percentage"),
            ]


# ── VO2 max ─────────────────────────────────────────────────────────────────────

VO2_COLS = ["calendar_date", "vo2_max", "category", "max_met", "calibrated_data"]

def parse_vo2max(entries):
    for e in entries:
        if e.get("vo2MaxValue") is None:
            continue
        yield [
            e.get("calendarDate"),
            e.get("vo2MaxValue"),
            e.get("maxMetCategory"),
            e.get("maxMet"),
            e.get("calibratedData"),
        ]


# ── HR zones (current Garmin zone config, one row) ───────────────────────────

HR_ZONE_COLS = [
    "sport", "training_method", "max_hr_used", "resting_hr_used",
    "zone1_floor", "zone2_floor", "zone3_floor", "zone4_floor", "zone5_floor",
    "resting_hr_auto_update", "change_state",
]


def parse_hr_zones(entries):
    for e in entries:
        yield [
            e.get("sport"),
            e.get("trainingMethod"),
            e.get("maxHeartRateUsed"),
            e.get("restingHeartRateUsed"),
            e.get("zone1Floor"), e.get("zone2Floor"), e.get("zone3Floor"),
            e.get("zone4Floor"), e.get("zone5Floor"),
            e.get("restingHrAutoUpdateUsed"),
            e.get("changeState"),
        ]


# ── Personal records (Garmin auto-detected lifetime bests) ───────────────────

PR_COLS = [
    "record_type", "value", "pr_start_time_gmt", "created_date",
    "activity_id", "current", "confirmed", "personal_record_id",
]


def parse_personal_records(record_groups):
    for group in record_groups:
        for r in group.get("personalRecords") or []:
            yield [
                r.get("personalRecordType"),
                r.get("value"),
                r.get("prStartTimeGMT"),
                r.get("createdDate"),
                r.get("activityId"),
                r.get("current"),
                r.get("confirmed"),
                r.get("personalRecordId"),
            ]


# ── Fitness age (one row per day) ─────────────────────────────────────────────

FITNESS_AGE_COLS = [
    "as_of_date", "chronological_age", "current_bio_age",
    "healthy_all_bio_age", "healthy_bmi_fat_bio_age",
    "healthy_rhr_bio_age", "healthy_active_bio_age",
    "rhr", "bmi", "biometric_vo2_max",
    "vo2_max_for_healthy_bmi_fat", "vo2_max_for_healthy_rhr",
    "vo2_max_for_healthy_active",
    "total_vigorous_days", "total_vigorous_ims", "num_weeks_for_im",
    "weight_data_last_entry_date", "rhr_last_entry_date",
]


def parse_fitness_age(entries):
    for e in entries:
        as_of = (e.get("asOfDateGmt") or "")[:10]
        if not as_of:
            continue
        yield [
            as_of,
            e.get("chronologicalAge"),
            e.get("currentBioAge"),
            e.get("healthyAllBioAge"),
            e.get("healthyBmiFatBioAge"),
            e.get("healthyRhrBioAge"),
            e.get("healthyActiveBioAge"),
            e.get("rhr"),
            e.get("bmi"),
            e.get("biometricVo2Max"),
            e.get("vo2MaxForHealthyBmiFat"),
            e.get("vo2MaxForHealthyRhr"),
            e.get("vo2MaxForHealthyActive"),
            e.get("totalVigorousDays"),
            e.get("totalVigorousIMs"),
            e.get("numOfWeeksForIM"),
            e.get("weightDataLastEntryDate"),
            e.get("rhrLastEntryDate"),
        ]


# ── Summarized activities (one row per workout/walk/hike) ────────────────────
#
# Garmin stores distance in cm, duration in ms, elevation in cm. We convert to
# SI units at the CSV boundary so downstream queries don't have to remember.

ACTIVITY_COLS = [
    "activity_id", "start_time_local", "activity_type", "sport_type", "name",
    "duration_sec", "distance_m", "elevation_gain_m", "elevation_loss_m",
    "avg_hr", "max_hr", "min_hr", "avg_speed_mps", "max_speed_mps",
    "steps", "calories", "bmr_calories",
    "start_lat", "start_lon",
]


def _div(val, divisor):
    return val / divisor if val is not None else None


def parse_activities(entries):
    for e in entries:
        yield [
            e.get("activityId"),
            _ms_to_local_iso(e.get("beginTimestamp")),
            e.get("activityType"),
            e.get("sportType"),
            e.get("name"),
            _div(e.get("duration"), 1000),
            _div(e.get("distance"), 100),
            _div(e.get("elevationGain"), 100),
            _div(e.get("elevationLoss"), 100),
            e.get("avgHr"),
            e.get("maxHr"),
            e.get("minHr"),
            e.get("avgSpeed"),
            e.get("maxSpeed"),
            e.get("steps"),
            e.get("calories"),
            e.get("bmrCalories"),
            e.get("startLatitude"),
            e.get("startLongitude"),
        ]


# ── Orchestration ────────────────────────────────────────────────────────────

def _write(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def _dedup_by(rows, key):
    """Keep the last row per key; sort by key stringified."""
    seen = {}
    for r in rows:
        seen[key(r)] = r
    return sorted(seen.values(), key=lambda r: str(key(r) or ""))


def _load_json_glob(zf, prefix, suffix):
    """Stream JSON files out of the outer zip matching path contains prefix
    and endswith suffix. Avoids writing the 22MB nested FIT zip to disk.
    Sorted for deterministic dedup (overlapping date-range files → last wins)."""
    for name in sorted(zf.namelist()):
        if prefix in name and name.endswith(suffix):
            with zf.open(name) as f:
                try:
                    yield json.load(f)
                except json.JSONDecodeError as exc:
                    print(f"  {name}: skipped ({exc})", file=sys.stderr)


def main(zip_path: Path, out_dir: Path):
    with zipfile.ZipFile(zip_path) as zf:
        sleep_entries = [e for d in _load_json_glob(zf, "DI-Connect-Wellness/", "sleepData.json") for e in d]
        health_entries = [e for d in _load_json_glob(zf, "DI-Connect-Wellness/", "healthStatusData.json") for e in d]
        uds_entries = [e for d in _load_json_glob(zf, "DI-Connect-Aggregator/UDSFile_", ".json") for e in d]
        vo2_entries_raw = list(_load_json_glob(zf, "DI-Connect-Metrics/MetricsMaxMetData", ".json"))
        vo2_entries = [e for d in vo2_entries_raw for e in (d if isinstance(d, list) else [d])]
        activity_entries = [
            a
            for d in _load_json_glob(zf, "DI-Connect-Fitness/", "summarizedActivities.json")
            for wrap in d
            for a in (wrap.get("summarizedActivitiesExport") or [])
        ]
        fitness_age_entries = [
            e
            for d in _load_json_glob(zf, "DI-Connect-Wellness/", "fitnessAgeData.json")
            for e in d
        ]
        hr_zone_entries = [
            e
            for d in _load_json_glob(zf, "DI-Connect-Wellness/", "heartRateZones.json")
            for e in d
        ]
        pr_groups = [
            g
            for d in _load_json_glob(zf, "DI-Connect-Fitness/", "personalRecord.json")
            for g in d
        ]

    sleep_rows = _dedup_by(parse_sleep(sleep_entries), key=lambda r: r[0])
    nap_rows = _dedup_by(parse_naps(sleep_entries), key=lambda r: (r[0], r[1]))
    uds_rows = _dedup_by(parse_uds(uds_entries), key=lambda r: r[0])
    bb_rows = _dedup_by(parse_body_battery_stats(uds_entries),
                        key=lambda r: (r[0], r[1], r[4]))
    health_rows = _dedup_by(parse_health_status(health_entries), key=lambda r: (r[0], r[1]))
    vo2_rows = _dedup_by(parse_vo2max(vo2_entries), key=lambda r: r[0])
    activity_rows = _dedup_by(parse_activities(activity_entries), key=lambda r: r[0])
    fitness_age_rows = _dedup_by(parse_fitness_age(fitness_age_entries), key=lambda r: r[0])
    hr_zone_rows = _dedup_by(parse_hr_zones(hr_zone_entries), key=lambda r: r[0])
    pr_rows = _dedup_by(parse_personal_records(pr_groups), key=lambda r: r[-1])

    _write(out_dir / "sleep-all.csv", SLEEP_COLS, sleep_rows)
    _write(out_dir / "naps.csv", NAP_COLS, nap_rows)
    _write(out_dir / "daily-summary.csv", UDS_COLS, uds_rows)
    _write(out_dir / "body-battery-stats.csv", BB_COLS, bb_rows)
    _write(out_dir / "health-status-all.csv", HEALTH_COLS, health_rows)
    _write(out_dir / "vo2max-all.csv", VO2_COLS, vo2_rows)
    _write(out_dir / "activities-summary.csv", ACTIVITY_COLS, activity_rows)
    _write(out_dir / "fitness-age.csv", FITNESS_AGE_COLS, fitness_age_rows)
    _write(out_dir / "hr-zones.csv", HR_ZONE_COLS, hr_zone_rows)
    _write(out_dir / "personal-records.csv", PR_COLS, pr_rows)

    def _summary(name, rows, date_col=0):
        """Print `name: N rows (earliest → latest)`. date_col=None omits the span."""
        if not rows:
            print(f"{name:25}: empty")
            return
        if date_col is None:
            print(f"{name:25}: {len(rows):5} rows")
            return
        dates = [r[date_col] for r in rows if r[date_col]]
        span = f"{min(dates)[:10]} → {max(dates)[:10]}" if dates else "-"
        print(f"{name:25}: {len(rows):5} rows  ({span})")

    _summary("sleep-all.csv", sleep_rows)
    _summary("naps.csv", nap_rows)
    _summary("daily-summary.csv", uds_rows)
    _summary("body-battery-stats.csv", bb_rows)
    _summary("health-status-all.csv", health_rows)
    _summary("vo2max-all.csv", vo2_rows)
    _summary("activities-summary.csv", activity_rows, date_col=1)
    _summary("fitness-age.csv", fitness_age_rows)
    _summary("hr-zones.csv", hr_zone_rows, date_col=None)
    _summary("personal-records.csv", pr_rows, date_col=None)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

"""Parse a day's Garmin FIT export (unpacked zip) into clean CSVs.

Uses the OFFICIAL Garmin FIT Python SDK (`garmin-fit-sdk` on PyPI), which
handles every private message type the watch emits — no reverse-engineering.

Inputs: a directory like `garmin/raw-fit/YYYY-MM-DD/` containing files such as
    *_WELLNESS.fit, *_SLEEP_DATA.fit, *_SLEEP_DISRUPTIONS.fit,
    *_HRV_STATUS.fit, *_METRICS.fit

Outputs (written to out_dir, filenames prefixed with the folder's YYYY-MM-DD):
    {date}-hr.csv              per-minute HR (from monitoring_mesgs.heart_rate)
    {date}-stress.csv          per-minute stress_level
    {date}-respiration.csv     per-minute respiration_rate
    {date}-spo2.csv            periodic SpO2 readings (+ confidence, mode)
    {date}-activity.csv        per-minute activity_type + intensity
    {date}-hrv-5min.csv        nightly HRV every ~5 min
    {date}-hrv-summary.csv     single-row HRV status summary
    {date}-sleep-levels.csv    sleep stage transitions (see WARNING below)
    {date}-sleep-assessment.csv  single-row nightly sleep scorecard (scores
                                 only) + session window. Stage durations and
                                 awake totals: read sleep-official.csv instead
                                 (this file deliberately does not carry them;
                                 see WARNING below for why)
    {date}-sleep-disruptions.csv  disruption severity periods
    {date}-intraday-rhr.csv    intraday RHR snapshots (resting + current-day resting)
    {date}-vo2max.csv          from max_met_data_mesgs (if present)

All timestamps are converted from UTC to UTC+8 local time for
downstream human-readable analysis. Adjust `LOCAL_TZ` in `_sleep.py` for
other regions.

WARNING — sleep-levels.csv semantics:
    Each row is a *transition marker* emitted by Garmin's classifier. An
    'awake' transition is a brief arousal event (often < 1 min), NOT a
    sustained wake state filling the gap to the next transition. Naive
    transition→duration arithmetic (e.g. "time from awake-transition to
    next light-transition = 22 min awake") substantially overstates awake
    time on typical nights — see docs/sleep-validation.md for the
    distribution and `scripts/sleep_transition_vs_official.py` to
    reproduce on your own archive.

WARNING — sleep-assessment.csv no longer carries awake_total_sec / stage
durations:
    Earlier versions exported a private FIT field 16 as `awake_total_sec`,
    presented as the authoritative awake total. This was removed because
    field 16 is the raw classifier value — not the post-processed value
    Garmin Connect's UI displays. Two failure modes are documented in
    docs/sleep-validation.md:

    (a) Complex nights with many brief arousals: classifier under-counts
        awake (field 16 reads well below the Garmin UI value).

    (b) Delayed UI re-processing: Garmin Connect re-processes hours or
        days later, so the same night can read differently if it is
        re-downloaded the next morning. Field 16 is frozen at classifier-
        write time.

    There is no signal inside the FIT to predict whether a given night will
    be re-processed. So all stage durations / awake totals must come from
    Garmin's post-processed surface — sleep-official.csv (which merges
    bulk-export sleep-all.csv with manual single-day Chinese CSVs). The
    daily aggregator (`build_daily_summary`) enforces this requirement.

Usage:
    python -m blackswan.parse_daily_fit <day_dir> <out_dir>
"""

import csv
import sys
from datetime import timezone
from pathlib import Path

from garmin_fit_sdk import (
    Decoder,
    Stream,
    convert_datetime_to_timestamp,
    convert_timestamp_to_datetime,
)

from blackswan._sleep import LOCAL_TZ

# FIT event code 74 = sleep session (Garmin-private, not in the public
# profile). SLEEP_DATA.fit emits event_type=start at bedtime and
# event_type=stop at wake time.
_SLEEP_SESSION_EVENT = 74

# Sleep-assessment column schema, as (column_name, fit_field_key) pairs.
# Single source of truth — the CSV header and per-row values derive from
# this list, so reordering or inserting can't drift. String keys map to
# decoded SDK fields; integer keys (12/13) are Garmin-private extensions
# not in the public FIT profile, kept as raw values for future forensics.
# Field 16 (awake_total_sec) was previously included but removed —
# see WARNING in module docstring.
_SLEEP_ASSESSMENT_FIT_FIELDS = [
    ("overall_sleep_score", "overall_sleep_score"),
    ("sleep_quality_score", "sleep_quality_score"),
    ("sleep_duration_score", "sleep_duration_score"),
    ("sleep_recovery_score", "sleep_recovery_score"),
    ("deep_sleep_score", "deep_sleep_score"),
    ("light_sleep_score", "light_sleep_score"),
    ("rem_sleep_score", "rem_sleep_score"),
    ("sleep_restlessness_score", "sleep_restlessness_score"),
    ("interruptions_score", "interruptions_score"),
    ("combined_awake_score", "combined_awake_score"),
    ("awake_time_score", "awake_time_score"),
    ("awakenings_count_score", "awakenings_count_score"),
    ("awakenings_count", "awakenings_count"),
    ("average_stress_during_sleep", "average_stress_during_sleep"),
    ("_unknown_f12", 12),
    ("_unknown_f13", 13),
]

_SLEEP_ASSESSMENT_COLUMNS = ["session_start", "session_end"] + [
    col for col, _ in _SLEEP_ASSESSMENT_FIT_FIELDS
]


def _sleep_assessment_row(m, session):
    return [session["start"] or "", session["end"] or ""] + [
        m.get(key) for _, key in _SLEEP_ASSESSMENT_FIT_FIELDS
    ]


def _local(ts):
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(LOCAL_TZ).isoformat()


def _read(fit_path: Path):
    stream = Stream.from_file(str(fit_path))
    msgs, errors = Decoder(stream).read()
    if errors:
        print(f"  {fit_path.name}: {len(errors)} decode errors", file=sys.stderr)
    return msgs


def _write(path: Path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def parse_day(day_dir: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    date = day_dir.name

    hr, stress, resp, spo2, activity = [], [], [], [], []
    hrv_vals, hrv_summaries = [], []
    sleep_levels, sleep_asses, disruptions = [], [], []
    intraday_rhr = []
    vo2_rows = []
    sleep_session = {"start": None, "end": None}

    for fit in sorted(day_dir.glob("*.fit")):
        try:
            msgs = _read(fit)
        except Exception as exc:
            print(f"  {fit.name}: skipped ({exc})", file=sys.stderr)
            continue

        # monitoring_mesgs HR records use timestamp_16 (low 16 bits of the FIT
        # epoch). Reconstruct by substituting low bits; bump high bits when the
        # 16-bit field has wrapped (2^16 s ≈ 18.2 h). Cache prev_fit so the
        # reconstruction chain handles multi-wrap spans correctly.
        prev_fit = None
        for m in msgs.get("monitoring_mesgs", []):
            ts = m.get("timestamp")
            if ts is not None:
                prev_fit = convert_datetime_to_timestamp(ts)
            elif m.get("timestamp_16") is not None and prev_fit is not None:
                low = m["timestamp_16"]
                recon_fit = (prev_fit & ~0xFFFF) | low
                if low < (prev_fit & 0xFFFF):
                    recon_fit += 0x10000
                ts = convert_timestamp_to_datetime(recon_fit)
                prev_fit = recon_fit
            if m.get("heart_rate") is not None and ts is not None:
                hr.append((_local(ts), m["heart_rate"]))
            if m.get("activity_type") is not None and ts is not None:
                activity.append((_local(ts), m.get("activity_type"), m.get("intensity")))

        for m in msgs.get("stress_level_mesgs", []):
            stress.append((_local(m.get("stress_level_time")), m.get("stress_level_value")))
        for m in msgs.get("respiration_rate_mesgs", []):
            resp.append((_local(m.get("timestamp")), m.get("respiration_rate")))
        for m in msgs.get("spo2_data_mesgs", []):
            spo2.append((
                _local(m.get("timestamp")), m.get("reading_spo2"),
                m.get("reading_confidence"), m.get("mode"),
            ))

        for m in msgs.get("hrv_value_mesgs", []):
            hrv_vals.append((_local(m.get("timestamp")), m.get("value")))
        for m in msgs.get("hrv_status_summary_mesgs", []):
            hrv_summaries.append((
                _local(m.get("timestamp")), m.get("weekly_average"),
                m.get("last_night_average"), m.get("last_night_5_min_high"),
                m.get("baseline_low_upper"), m.get("baseline_balanced_lower"),
                m.get("baseline_balanced_upper"), m.get("status"),
            ))

        for m in msgs.get("sleep_level_mesgs", []):
            sleep_levels.append((_local(m.get("timestamp")), m.get("sleep_level")))
        for m in msgs.get("sleep_assessment_mesgs", []):
            sleep_asses.append(m)
        for m in msgs.get("sleep_disruption_severity_period_mesgs", []):
            disruptions.append((
                _local(m.get("timestamp")), m.get("message_index"), m.get("severity"),
            ))
        for m in msgs.get("sleep_disruption_overnight_severity_mesgs", []):
            disruptions.append((_local(m.get("timestamp")), "overnight", m.get("severity")))

        # Sleep session window is emitted as event=74 start/stop pairs.
        # Current exports put these in SLEEP_DATA.fit; older bulk exports use
        # TYPE49_*.fit. Scan every file — the extra iterations are cheap.
        for m in msgs.get("event_mesgs", []):
            if m.get("event") != _SLEEP_SESSION_EVENT:
                continue
            if m.get("event_type") == "start":
                sleep_session["start"] = _local(m.get("timestamp"))
            elif m.get("event_type") == "stop":
                sleep_session["end"] = _local(m.get("timestamp"))

        for m in msgs.get("monitoring_hr_data_mesgs", []):
            intraday_rhr.append((
                _local(m.get("timestamp")),
                m.get("resting_heart_rate"),
                m.get("current_day_resting_heart_rate"),
            ))

        for m in msgs.get("max_met_data_mesgs", []):
            vo2_rows.append((
                _local(m.get("update_time")), m.get("vo2_max"),
                m.get("sport"), m.get("sub_sport"), m.get("max_met_category"),
                m.get("calibrated_data"),
            ))

    def _dedupe_sort(rows):
        unique = list({tuple(r) for r in rows})
        unique.sort(key=lambda r: tuple("" if x is None else str(x) for x in r))
        return unique

    hr = _dedupe_sort(hr)
    stress = _dedupe_sort(stress)
    resp = _dedupe_sort(resp)
    spo2 = _dedupe_sort(spo2)
    activity = _dedupe_sort(activity)
    hrv_vals = _dedupe_sort(hrv_vals)
    hrv_summaries = _dedupe_sort(hrv_summaries)
    sleep_levels = _dedupe_sort(sleep_levels)
    disruptions = _dedupe_sort(disruptions)
    intraday_rhr = _dedupe_sort(intraday_rhr)
    vo2_rows = _dedupe_sort(vo2_rows)

    _write(out_dir / f"{date}-hr.csv", ["timestamp", "hr_bpm"], hr)
    _write(out_dir / f"{date}-stress.csv", ["timestamp", "stress_level"], stress)
    _write(out_dir / f"{date}-respiration.csv", ["timestamp", "respiration_rate_brpm"], resp)
    _write(out_dir / f"{date}-spo2.csv",
           ["timestamp", "spo2_percent", "confidence", "mode"], spo2)
    _write(out_dir / f"{date}-activity.csv",
           ["timestamp", "activity_type", "intensity"], activity)

    _write(out_dir / f"{date}-hrv-5min.csv", ["timestamp", "hrv_ms"], hrv_vals)
    _write(out_dir / f"{date}-hrv-summary.csv", [
        "timestamp", "weekly_avg_ms", "last_night_avg_ms", "last_night_5min_high_ms",
        "baseline_low_upper", "baseline_balanced_lower", "baseline_balanced_upper",
        "status",
    ], hrv_summaries)

    _write(out_dir / f"{date}-sleep-levels.csv", ["timestamp", "level"], sleep_levels)
    if sleep_asses:
        if len(sleep_asses) > 1:
            print(f"  warning: {len(sleep_asses)} sleep assessments, keeping first",
                  file=sys.stderr)
        _write(out_dir / f"{date}-sleep-assessment.csv",
               _SLEEP_ASSESSMENT_COLUMNS,
               [_sleep_assessment_row(sleep_asses[0], sleep_session)])
    _write(out_dir / f"{date}-sleep-disruptions.csv",
           ["timestamp", "period_index", "severity"], disruptions)

    _write(out_dir / f"{date}-intraday-rhr.csv",
           ["timestamp", "resting_hr_bpm", "current_day_resting_hr_bpm"], intraday_rhr)

    _write(out_dir / f"{date}-vo2max.csv", [
        "timestamp", "vo2_max", "sport", "sub_sport", "category", "calibrated",
    ], vo2_rows)

    print(
        f"{date}: hr={len(hr)} stress={len(stress)} resp={len(resp)} spo2={len(spo2)} "
        f"hrv_5min={len(hrv_vals)} sleep_levels={len(sleep_levels)} "
        f"disruptions={len(disruptions)} rhr_snap={len(intraday_rhr)} vo2={len(vo2_rows)}"
    )


if __name__ == "__main__":
    parse_day(Path(sys.argv[1]), Path(sys.argv[2]))

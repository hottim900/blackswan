#!/usr/bin/env python3
"""Detect optical-HR sensor failure segments in Garmin activity FITs.

Input:  Garmin activity FIT (with record_mesgs.heart_rate)
Output: list of failure segments + cleaned HR stats (after stripping flagged
        windows)

Three complementary detection pathways:

1. **Statistical outlier (local spike)**: HR > 2·MAD from 60s rolling median
   AND > 15 bpm absolute deviation. Catches local aberrations only — misses
   sustained systematic bias.

2. **Physiological implausibility (systematic bias)**: HR below the speed +
   grade-paired expected range. Simplified model:
       HR_exp = 55 + 12·speed_kmh + 1.5·max(grade_pct, 0)
   If measured HR < HR_exp − 25 bpm (and speed > 0.3 m/s) → suspected
   failure. This pathway catches optical-sensor baseline-stuck patterns
   (cold capillary perfusion, motion artifact) that the statistical
   pathway misses.

3. **Flatline (sensor stuck)**: ≥ 30 seconds at the same HR value.

The three pathways' flagged indices are merged. Short windows (< 10s) are
treated as true artifacts; long windows whose statistical deviation is
small are treated as real HR changes (not flagged).

⚠ **Detector under-flags slow-onset failures**: a single trial may hold
100–160s of artifact while this detector flags only ~80s of the most
implausible window. When integrating into trial-level analysis, escalate
per docs/confounders.md#5: if `flagged_seconds / trial_duration > 0.4`,
exclude the entire trial from cross-session comparison rather than trying
to use the unflagged portion (which is contaminated by what came before).

Usage:
    python -m blackswan.detect_hr_artifacts <fit_file> [--verbose] [--no-physio]

    --no-physio  disable physiological-plausibility pathway (statistical only)
    --verbose    list all artifact segments (default: top N)

Output (stdout):
    - HR stats (raw vs cleaned)
    - Top N artifact segments with timestamps
"""

import argparse
import sys
from pathlib import Path
from statistics import median

from garmin_fit_sdk import Decoder, Stream, convert_timestamp_to_datetime

from blackswan._sleep import LOCAL_TZ

__all__ = ["detect_artifacts", "trial_flagged_fraction"]


def fit_to_local(fit_ts):
    return convert_timestamp_to_datetime(fit_ts).astimezone(LOCAL_TZ)

def rolling_median_mad(values, window_size=60):
    """For each position, return the rolling median and MAD (window centred on index)."""
    n = len(values)
    half = window_size // 2
    medians = [0.0] * n
    mads = [0.0] * n
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        window = values[lo:hi]
        m = median(window)
        medians[i] = m
        mads[i] = median([abs(v - m) for v in window])
    return medians, mads

def expected_hr(speed_kmh, grade_pct):
    """Simplified expected-HR model for hiking-style activity.

    speed 0 → 55 (static), +12 per km/h, +1.5 per 1% ascending grade.
    Does not account for altitude or personal fitness; this is a rough
    lower-bound reference only.
    """
    return 55 + 12 * speed_kmh + 1.5 * max(grade_pct, 0)

def detect_artifacts(records, mad_multiplier=2.0, min_bpm_deviation=15,
                     mid_deviation=25, flatline_threshold=30,
                     physio_check=True, physio_deviation=25,
                     min_speed_for_physio=0.3):
    """Return a list of artifact segments:
    [{start_idx, end_idx, start_ts, end_ts, duration_s, mean_hr, reason}, ...]
    """
    hrs = []
    tss = []
    dists = []
    alts = []
    for r in records:
        hr = r.get('heart_rate')
        if hr is None: continue
        hrs.append(hr)
        tss.append(r['timestamp'])
        dists.append(r.get('distance'))
        alts.append(r.get('enhanced_altitude') or r.get('altitude'))

    if len(hrs) < 60:
        return [], [], hrs

    medians, mads = rolling_median_mad(hrs, window_size=60)

    # Per-sample is_artifact flagging
    flags = [False] * len(hrs)
    reasons = [''] * len(hrs)

    # Pathway 1: statistical outlier
    for i in range(len(hrs)):
        dev = hrs[i] - medians[i]
        abs_dev = abs(dev)
        threshold = max(mad_multiplier * mads[i], min_bpm_deviation)
        if abs_dev > threshold:
            flags[i] = True
            reasons[i] = f"stat: dev={dev:+.0f} vs median {medians[i]:.0f} (±{threshold:.0f})"

    # Pathway 2: physiological plausibility (30s rolling context)
    if physio_check:
        WINDOW = 30  # seconds
        for i in range(len(hrs)):
            # Take ± WINDOW/2 seconds around i for speed / grade
            t_mid = tss[i]
            lo_t = t_mid - WINDOW // 2
            hi_t = t_mid + WINDOW // 2
            # Find lo / hi indices for dist / alt
            lo_idx = i
            hi_idx = i
            while lo_idx > 0 and tss[lo_idx-1] >= lo_t: lo_idx -= 1
            while hi_idx < len(hrs)-1 and tss[hi_idx+1] <= hi_t: hi_idx += 1
            if hi_idx <= lo_idx: continue
            d0 = dists[lo_idx]; d1 = dists[hi_idx]
            a0 = alts[lo_idx]; a1 = alts[hi_idx]
            dt = tss[hi_idx] - tss[lo_idx]
            if None in (d0, d1, a0, a1) or dt <= 0: continue
            dd = d1 - d0
            if dd <= 0: continue  # not moving
            speed_kmh = dd / dt * 3.6
            grade = (a1 - a0) / dd * 100 if dd > 0 else 0
            speed_mps = dd / dt
            if speed_mps < min_speed_for_physio: continue  # skip when stationary
            hr_exp = expected_hr(speed_kmh, grade)
            if hrs[i] < hr_exp - physio_deviation:
                flags[i] = True
                existing = reasons[i]
                new_reason = f"physio: HR {hrs[i]} vs exp {hr_exp:.0f} (spd {speed_kmh:.1f}, grade {grade:+.1f}%)"
                reasons[i] = (existing + "; " + new_reason) if existing else new_reason

    # Pathway 3: flatline detection
    i = 0
    while i < len(hrs):
        j = i
        while j < len(hrs) - 1 and hrs[j+1] == hrs[j]:
            j += 1
        span = tss[j] - tss[i]
        if span >= flatline_threshold and j > i:
            for k in range(i, j+1):
                flags[k] = True
                if not reasons[k]:
                    reasons[k] = f"flatline HR={hrs[i]} for {span}s"
        i = j + 1

    # Group consecutive flags into segments (keep physio/flatline; stat-only
    # treated as a real artifact only if the segment is short)
    segs = []
    i = 0
    while i < len(hrs):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j < len(hrs) and flags[j]:
            j += 1
        dur = tss[j-1] - tss[i] + 1 if j > i else 1
        seg_hrs = hrs[i:j]
        seg_reasons = [reasons[k] for k in range(i, j)]
        is_physio = any('physio' in r for r in seg_reasons)
        is_flatline = any('flatline' in r for r in seg_reasons)

        # Pure statistical deviation (no physio, no flatline): a long
        # segment with small mean deviation is real HR change → unflag
        if not is_physio and not is_flatline:
            if 10 <= dur < 60:
                mean_dev = sum(abs(h - medians[i+k]) for k, h in enumerate(seg_hrs)) / len(seg_hrs)
                if mean_dev < mid_deviation:
                    for k in range(i, j): flags[k] = False
                    i = j; continue
            if dur >= 60:
                mean_dev = sum(abs(h - medians[i+k]) for k, h in enumerate(seg_hrs)) / len(seg_hrs)
                if mean_dev < 30:
                    for k in range(i, j): flags[k] = False
                    i = j; continue

        ts_start = fit_to_local(tss[i])
        ts_end = fit_to_local(tss[j-1])
        segs.append({
            'start_idx': i, 'end_idx': j-1,
            'start_ts': ts_start, 'end_ts': ts_end,
            'duration_s': dur,
            'mean_hr': sum(seg_hrs)/len(seg_hrs),
            'min_hr': min(seg_hrs),
            'max_hr': max(seg_hrs),
            'reason_first': reasons[i],
            'types': ('physio' if is_physio else '') + (' flatline' if is_flatline else ''),
        })
        i = j

    return segs, flags, hrs


def trial_flagged_fraction(segs, trial_start, trial_end) -> float:
    """Fraction of [trial_start, trial_end] covered by artifact segments.

    Per ``docs/confounders.md`` §5: when this fraction exceeds 0.4, the entire
    trial should be excluded from cross-session comparison rather than
    partially cleaned — the unflagged portion is contaminated by what came
    before. The detector itself under-flags slow-onset failures, so this
    overlap calculation is the canonical escalation gate.

    Args:
        segs: artifact segments from ``detect_artifacts()`` — each dict has
            ``start_ts`` and ``end_ts`` keys (timezone-aware datetimes).
        trial_start, trial_end: trial bounds. Must be the same type as
            ``segs[i]["start_ts"]`` — typically datetime objects matching
            ``stats_for_window()`` output. Mixing datetimes with numeric
            epochs raises TypeError on subtraction.

    Returns:
        Overlap fraction in [0, 1].

    Raises:
        ValueError: when ``trial_end <= trial_start`` (zero or inverted
            window) — silent zero-fraction would mask a caller bug as
            "trial has no artifacts, keep it".
    """
    def _sec(delta):
        return delta.total_seconds() if hasattr(delta, "total_seconds") else float(delta)

    trial_dur = _sec(trial_end - trial_start)
    if trial_dur <= 0:
        raise ValueError(f"trial_end must be > trial_start (got dur={trial_dur})")
    overlap = 0.0
    for s in segs:
        if s["start_ts"] >= trial_end or s["end_ts"] <= trial_start:
            continue
        a = max(s["start_ts"], trial_start)
        b = min(s["end_ts"], trial_end)
        overlap += _sec(b - a)
    return overlap / trial_dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fit_file', help='Path to Garmin activity FIT file')
    ap.add_argument('--verbose', '-v', action='store_true', help='List all artifact segments')
    ap.add_argument('--top', type=int, default=10, help='Top N longest artifact segments to list (default 10)')
    ap.add_argument('--no-physio', action='store_true', help='Disable physiological plausibility check')
    args = ap.parse_args()

    fp = Path(args.fit_file)
    if not fp.exists():
        print(f"File not found: {fp}", file=sys.stderr)
        sys.exit(1)

    msgs, _ = Decoder(Stream.from_file(str(fp))).read(convert_datetimes_to_dates=False)
    records = msgs.get('record_mesgs', [])

    segs, flags, hrs = detect_artifacts(records, physio_check=not args.no_physio)

    raw_n = len(hrs)
    artifact_n = sum(1 for f in flags if f)
    clean_hrs = [h for h, f in zip(hrs, flags) if not f]

    print(f"=== {fp.name} ===")
    print(f"  Total HR records: {raw_n}")
    print(f"  Artifact records: {artifact_n} ({artifact_n/raw_n*100:.1f}%)")
    print(f"  Clean records: {len(clean_hrs)} ({len(clean_hrs)/raw_n*100:.1f}%)")
    print()
    print(f"  Raw HR stats:    mean={sum(hrs)/len(hrs):.1f}  min={min(hrs)}  max={max(hrs)}")
    if clean_hrs:
        clean_mean = sum(clean_hrs)/len(clean_hrs)
        print(f"  Clean HR stats:  mean={clean_mean:.1f}  min={min(clean_hrs)}  max={max(clean_hrs)}")
        raw_mean = sum(hrs)/len(hrs)
        print(f"  Δ (clean - raw): {clean_mean - raw_mean:+.1f} bpm")

    print(f"\n=== Artifact segments: {len(segs)} total ===")
    segs_sorted = sorted(segs, key=lambda s: -s['duration_s'])
    top = args.top if not args.verbose else len(segs_sorted)
    for s in segs_sorted[:top]:
        types_tag = f"[{s.get('types','').strip()}]" if s.get('types','').strip() else ""
        print(f"  {s['start_ts'].strftime('%H:%M:%S')} - {s['end_ts'].strftime('%H:%M:%S')}  "
              f"dur {s['duration_s']:4d}s  mean HR {s['mean_hr']:5.1f}  range {s['min_hr']}-{s['max_hr']}  {types_tag}")
        print(f"    {s['reason_first']}")
    if len(segs_sorted) > top:
        print(f"  ... and {len(segs_sorted)-top} more")


if __name__ == '__main__':
    main()

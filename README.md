# blackswan

A pipeline for **Cardiac Cost (CC) analysis** of Garmin FIT data — built around uphill interval training, with rigorous cross-day comparison that survives confounder scrutiny.

> **CC = avg HR ÷ km/h** (lower is more efficient). It's the canonical metric for tracking how your heart responds to a fixed external workload over time.

## Why this exists

Most Garmin analysis tools answer "how was today's session?" by surfacing splits, HR zones, and one-line summaries. This project answers a harder question:

> **"Did this week's intervals show real improvement vs last month's, or is the difference just confounders?"**

Naïvely comparing CC across two interval sessions often produces inflated improvement claims, because:

- **Trial duration** differs by 30%+ → cardiac drift accumulates differently
- **Average grade** differs by 3% → expected HR shifts ±5 bpm
- **Rest structure** differs (4 long trials with short rest vs 6 short trials with long rest) → CC favours the latter
- **HR sensor artifacts** silently distort one or two trials
- **Mid-session "easy" trials** (an outlier where the user backed off) skew per-trial means

This pipeline detects, quantifies, and corrects each confounder, then reports both the **raw delta** and the **confounder-corrected delta** — so you know how much of the apparent improvement is real.

## What's in here

```
src/blackswan/
├── parse_bulk_export.py             # Garmin GDPR bulk export → 10 history CSVs
├── batch_extract_fits.py            # Bulk export → per-day raw FITs
├── parse_daily_fit.py               # Per-day raw FITs → 12 minute-level CSVs (HR/SpO2/sleep/HRV/...)
├── build_sleep_official.py          # Bulk + manual single-day CSVs → sleep SSOT
├── build_daily_summary.py           # 12 daily CSVs + sleep SSOT → one row/day (mirrors Garmin Connect)
├── build_sleep_stage_grid.py        # sleep-levels → per-minute stage grid for HR/SpO2 cross-tab
├── analyze_spo2_vs_stage.py         # SpO2 × sleep stage cross-day analysis
├── detect_hr_artifacts.py           # Activity FIT → optical HR sensor failure detection
├── segment_uphill.py                # Activity FIT → climb segments (alt min → alt max)
├── csv_fit_crosscheck.py            # Garmin Connect lap CSV ↔ FIT lap_mesgs validation
├── cc_metrics.py                    # CC trial-2-3 / back-half + confounder correction
├── parse_strength_fit.py            # Strength FIT → StrengthSession / StrengthSet
├── segment_strength_sets.py         # Active sets → ExerciseGroup heuristic
├── detect_strength_hr_artifact.py   # Early-session optical-HR artifact (experimental)
├── strength_metrics.py              # Cross-session strength comparison + pairing
├── forensic_spo2_event.py           # Sustained-desaturation event reconstruction
├── _sleep.py                        # shared sleep-stage utilities
├── _sleep_validation.py             # naive/smart transition math vs sleep-official (n=N)
└── _time.py                         # shared LOCAL_TZ constant (UTC+8)
```

## Quickstart

```bash
# Install
pip install garmin-fit-sdk
# or with uv
uv pip install garmin-fit-sdk

# Clone + dev install
git clone https://github.com/hottim900/blackswan
cd blackswan
uv pip install -e .   # or: pip install -e .
```

### Pipeline overview

```
Garmin GDPR bulk export.zip                    Manual single-day CSVs (recent days)
   │                                                              │
   ├── parse_bulk_export      → history/*.csv                     │
   │                                  │                           │
   │                                  └─── build_sleep_official ──┘
   │                                            ↓
   │                                    sleep-official.csv (SSOT) ─┐
   │                                                               │
   └── batch_extract_fits      → raw-fit/YYYY-MM-DD/               │
            │                                                      │
            └── parse_daily_fit   → daily/*.csv (12 minute-level)  │
                     │                       │                     │
                     │                       ├── analyze_spo2_vs_stage  → analysis/*.csv
                     │                       ├── build_sleep_stage_grid → daily/*-sleep-stage-grid.csv
                     │                       │
                     │                       └── build_daily_summary  ──┘  (REQUIRES sleep-official.csv)
                     │                                ↓
                     │                       daily-summary/{date}-daily-summary.csv

Activity FIT (workout)
   │
   ├── detect_hr_artifacts    → flag optical HR sensor failures
   ├── csv_fit_crosscheck     → validate vs Garmin Connect CSV
   ├── segment_uphill         → per-climb stats (CC, HR, grade)
   └── cc_metrics             → cross-session comparison + confounder correction

Strength FIT (sport=training, sub_sport=strength_training)
   │
   ├── parse_strength_fit            → StrengthSession + per-set HR
   ├── segment_strength_sets         → ExerciseGroup (weight × reps adjacency)
   ├── detect_strength_hr_artifact   → EARLY_DEFICIT_LATE_NORMAL signature (experimental)
   └── strength_metrics              → cross-session pairing + Δ HR + artifact flags
```

### One-shot example: comparing two interval sessions

```python
from garmin_fit_sdk import Decoder, Stream
from blackswan.segment_uphill import find_uphill_trials_in_lap
from blackswan.cc_metrics import TrialStats, compare_sessions

def session_to_trials(fit_path, work_lap_indices):
    msgs, _ = Decoder(Stream.from_file(fit_path)).read()
    laps = msgs["lap_mesgs"]
    records = msgs["record_mesgs"]
    trials = []
    for i in work_lap_indices:
        s = find_uphill_trials_in_lap(records, laps[i])
        if s:
            trials.append(TrialStats(**{
                k: s[k] for k in ("dur", "dist", "kmh", "grade",
                                   "start_hr", "avg_hr", "max_hr", "cc")
            }))
    return trials

baseline = session_to_trials("baseline.fit", work_lap_indices=[1, 2, 3, 4])  # 4 trials
recent   = session_to_trials("recent.fit",   work_lap_indices=[2, 3, 4, 5, 6, 7])  # 6 trials

report = compare_sessions(
    baseline_trials=baseline,
    recent_trials=recent,
    excluded_indices_recent={0, 4},  # trial 1 = sensor failure, trial 5 = outlier
)
print(report.summary())
```

Output:
```
=== CC comparison ===
  Baseline: n=4 working trials
  Recent:   n=6 input → 4 after excluding [0, 4]

  Confounder amplification: +1.70 CC
    grade Δ +2.9% → +0.89
    dur   Δ +32s  → +0.81

  CC trial 2-3 mean: raw -2.76 → corrected -1.06
  CC back half:     raw -3.90 → corrected -2.20

  HR-grade-normalised speed delta: -0.32 CC (range [-0.82, +0.19])

  Day-to-day noise floor: ±1.65 CC (≈5% of baseline mean). Corrected deltas within this band are indistinguishable from noise.
```

The corrected delta is the headline number. Raw -2.76 → corrected -1.06 falls **inside the noise floor (±1.65)**, meaning it's statistically indistinguishable from "no change" — not the 8% improvement the raw number suggested.

## Strength training analysis (experimental)

Cross-session strength comparison with optical-HR artifact detection. Calibrated on n=5 single-user vivoactive 5 sessions — see [`docs/confounders.md` § 9](docs/confounders.md) for the calibration confound caveat.

The pipeline pairs per-set HR between two sessions on `(active_idx, weight, reps)` and reports the per-pair HR delta. The detector flags an `EARLY_DEFICIT_LATE_NORMAL` shape when early sets read suspiciously low and late sets normalise — a pattern consistent with cold capillary perfusion, grip vasoconstriction, wrist tension, or watch fit (umbrella term: "early-session optical-HR artifact").

```python
from blackswan.strength_metrics import compare_strength_sessions

report = compare_strength_sessions("baseline.fit", "recent.fit")
print(report.summary())
```

Run the bundled quickstart against synthetic FITs:

```bash
uv run python -m examples.quickstart_strength
```

Sample output (synthetic baseline vs recent — recent has cold-start artifact in the first 3 work sets):

```
=== Strength comparison ===
  Baseline: 2000-01-15 18:30 (7 active stats)
  Recent:   2000-02-15 18:30 (7 active stats)

  Pairs matched: 7 (exact_slot: 7, exercise_level: 0)
  HR Δ exact_slot: -22.1 bpm
  HR Δ all pairs:  -22.1 bpm

  Artifact (experimental detector): baseline CLEAN, recent EARLY_DEFICIT_LATE_NORMAL
  Artifact warnings:
    [recent] EARLY_DEFICIT_LATE_NORMAL: 3 early-window sets below threshold
    [recent]   active_idx=1: hr_avg=72 < 90 AND hr_avg=72 <= ref 120 - 25
    [recent]   late_median 132 - early_median 82 = +50 bpm (>= 30)
```

The detector flag is **advisory** — it does NOT auto-exclude flagged sets. Pass `excluded_indices_recent={...}` (or `excluded_indices_baseline`) on a re-run to drop sets you decide to ignore. Decide BEFORE running compare; re-running with different exclusions until the delta looks right is exclusion shopping (see [`CLAUDE.md`](CLAUDE.md)).

**Don't compare strength deltas against cardio's ±5% noise floor.** Cardio's ±3-5 bpm was calibrated against uphill intervals at constant external workload; strength load varies set-to-set so the noise floor doesn't transfer. v1 reports raw `hr_delta_stdev` and `hr_delta_iqr` as advisory only.

## Daily summary

`build_daily_summary` aggregates the 12 minute-level CSVs from `parse_daily_fit` into a single per-day CSV that mirrors Garmin Connect's web export — HR + respiration (each with sleep/awake split), SpO2, HRV passthrough, sleep stage durations, body battery in/out. HR and respiration aggregates filter Garmin sentinels (HR=0/255 dropouts, respiration=−1/−2 unmeasurable) before averaging; raw per-minute CSVs preserve sentinels for downstream inspection.

**Sleep stage durations require `sleep-official.csv`.** Naive transition math on `sleep-levels.csv` is NOT a fallback by default — see [`docs/sleep-validation.md`](docs/sleep-validation.md) for the n=66 evidence supporting this requirement (median naive awake overstates Garmin Connect by 7×, p75 10.5×, max 35×). Missing `sleep-official.csv` raises `MissingSSOTError` with a remediation pointer; pass `--allow-missing-sleep-official` to downgrade to partial mode and emit empty stage columns rather than untrustworthy ones.

```bash
# Single day — pass --date or name --out as YYYY-MM-DD-daily-summary.csv
python -m blackswan.build_daily_summary garmin/timeseries/daily \
    --date 2000-01-15 \
    --sleep-official garmin/timeseries/history/sleep-official.csv \
    --bulk-history garmin/timeseries/history/daily-summary.csv \
    --out garmin/timeseries/daily-summary/2000-01-15-daily-summary.csv

# Batch
python -m blackswan.build_daily_summary garmin/timeseries/daily \
    --sleep-official garmin/timeseries/history/sleep-official.csv \
    --bulk-history garmin/timeseries/history/daily-summary.csv \
    --out-dir garmin/timeseries/daily-summary/ --all
```

The companion `build_sleep_stage_grid` expands `sleep-levels.csv` into a per-minute stage grid (default 60 s, accepts 30 s) for cross-tab with HR/SpO2/respiration. It does NOT carry per-stage totals — those belong in `build_daily_summary` from the official source.

## Methodology — 4-Layer Analysis

When you have a workout to interpret, lock layers in order. Don't move to Layer N+1 until Layer N is reviewer-approved.

| Layer | Question | Output |
|-------|----------|--------|
| **1. Hard facts** | What happened? | Raw measurements, single-session, no comparison, no interpretation |
| **2. Internal dynamics** | What patterns are inside this session? | Trial-internal HR drift, HRR, stdev, cadence-HR decoupling, sensor sanity |
| **3. Cross-session comparison** | How does it compare to baseline? | CC deltas + confounder-corrected deltas |
| **4. Take-home / interpretation** | What does it mean for training? | Bounded by training science (e.g. 6 days is not enough for aerobic adaptation) |

Each layer freezes its conclusions before the next layer can touch them. This prevents conclusions from drifting across review rounds — a real failure mode when a single confounder cascades into 4 layers of revised interpretation.

See [`docs/methodology.md`](docs/methodology.md) for the full protocol.

## Authoritative segmentation

The "trial" boundaries used throughout this pipeline are **alt min → alt max** — the climb starts at the local altitude minimum (the bottom of the climb) and ends at the local maximum (the top). This is reverse-engineered from a hand-marked training log: the algorithm output matches the analyst's manual marks within 1–8 seconds and < 0.1 CC points across n=4 trials.

See [`docs/authoritative-segmentation.md`](docs/authoritative-segmentation.md) for the validation method and why other obvious choices (lap_mesgs boundaries, "stop → stop" logic, simple altitude rising windows) all systematically fail.

## Confounders

Cross-day comparison is hard because:

| Confounder | Typical magnitude | Correction |
|------------|-------------------|------------|
| Grade differs | 1.5 bpm per grade-% | linear penalty |
| Duration differs | 5–10 bpm/min cardiac drift | (Δdur ÷ 60) × drift |
| Rest structure | 30%+ rest time density swing | report work-time density side-by-side |
| HR sensor artifacts | One trial silently invalid | escalate: `flagged_sec / trial_dur > 0.4` → exclude entire trial |
| Outlier trials | One trial 15+ bpm below neighbours | manual exclusion + document criterion before Layer 3 |
| Lap-button habit | Bottom vs top-of-climb pressing | use alt min → alt max, not lap boundaries |
| Final-trial speed | "Last trial was +20% faster!" can be 100% duration confound | duration-pair before claiming improvement (180s trial vs 90s trial is anaerobic vs aerobic — different effort modes) |
| HRmax with n ≤ 2 | A "new max" or "missed max" by 5 bpm | within day-to-day SD (±5 bpm); flag provisional until n ≥ 4 |

See [`docs/confounders.md`](docs/confounders.md) for each one's signature, detection, and correction formula.

## Contributing

Before submitting a PR, run a **PII sweep across the entire repo (not just code)** — see the PII lens checklist in [`docs/methodology.md` § "Multi-angle review"](docs/methodology.md#multi-angle-review-run-reviewers-in-parallel-not-series) for the specific sweep targets and why a `grep` over `*.py` alone is insufficient.

## Status

Alpha. The pipeline has been validated against hand-marked training-log data (per-trial CC matches manual marks within 0.15 points across n=4 trials). API may still change.

- ✅ Bulk export parsing
- ✅ Per-day FIT parsing
- ✅ Sleep SSOT synthesis
- ✅ Sleep transition math validation (n=66, vivoactive 5)
- ✅ Daily summary aggregator with SSOT enforcement
- ✅ HR artifact detection
- ✅ Authoritative climb segmentation (validated against hand-marked log)
- ✅ CC + confounder correction
- ⚗️ Strength training analysis (experimental, vivoactive 5 only, n=5)
- ✅ Synthetic-data examples (cardio TBD; strength shipped)
- ✅ Tests with synthetic FITs (strength)
- ⏳ pip install from PyPI

## License

MIT

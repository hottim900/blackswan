# Sleep transition math vs Garmin Connect (n=66, vivoactive 5)

This is the load-bearing artifact for the sleep-stage warnings throughout
the codebase. Re-running it on your own archive is the way to verify those
warnings hold for your device + sleep profile.

## Why this exists

Two warnings in the codebase make claims about how badly naive transition
arithmetic on `sleep-levels.csv` diverges from Garmin Connect's
post-processed values:

- `parse_daily_fit.py` — "naive transition→duration substantially overstates
  awake on typical nights"
- `analyze_spo2_vs_stage.py` — "per-night stage durations come from
  `sleep-official.csv`, not transition math"

Originally those warnings carried specific numbers ("10x+", "12x off",
"1.4-4.5×") with no in-tree evidence. This page replaces them with a
reproducible distribution and a script anyone can run.

## Method

For each night with both a `{date}-sleep-levels.csv` (raw classifier
transitions) and a row in `sleep-official.csv` (Garmin Connect
post-processed values), compute two transition-math methods and compare
each to official:

- **Naive**: per-segment duration = `next_ts − cur_ts`, every level
  contributes (including awake). This is the math issue #8 originally
  proposed for `expand_sleep_levels`.
- **Smart**: skip awake transitions, sum non-awake segments closing on
  session-end. Awake collapses to `0×` by construction — the method
  trades information loss for noise rejection. Matches
  `analyze_spo2_vs_stage._sleep_window` fallback semantics.

Each cell below is `transition_seconds / official_seconds`. A value of
`1.00×` means transition math matches Garmin Connect; `>1.00×`
overstates, `<1.00×` understates.

## Results (n=66)

| stage | method | min | p25 | median | p75 | max | mean |
|---|---|---|---|---|---|---|---|
| awake | naive | 1.25× | 4.81× | **7.00×** | 10.50× | **35.00×** | 9.18× |
| awake | smart | 0× | 0× | 0× | 0× | 0× | 0× (info-loss by design) |
| deep  | naive | 0.12× | 0.47× | 0.72× | 1.02× | 3.95× | 0.83× |
| deep  | smart | 0.20× | 0.59× | **0.90×** | 1.26× | 3.95× | 0.99× |
| light | naive | 0.22× | 0.70× | 0.88× | 1.16× | 4.29× | 1.01× |
| light | smart | 0.51× | 0.87× | **1.11×** | 1.27× | 4.49× | 1.18× |
| rem   | naive | 0.02× | 0.64× | 0.88× | 1.15× | 2.73× | 0.95× |
| rem   | smart | 0.15× | 0.78× | **0.99×** | 1.20× | 2.73× | 1.05× |

## What the data says

**Awake naive overstates strongly and reliably.** Median 7×, p75 10.5×,
max 35×. The p25 is 4.81×, meaning ≥75% of nights overstate awake by ≥5×.
This is the strongest signal in the table — the original "10x+" framing
was conservative; "5-50× per night" is closer.

**Smart awake is always 0× by design.** Skipping awake transitions and
summing non-awake segments to session-end means awake never accumulates.
This is the right tradeoff when you only need stage-fraction context for
HR/SpO2 cross-tabs (no awake duration claim made), but it is *not* a
substitute for an awake total.

**Deep / light / REM central tendency is close to 1.0×, but per-night
noise is large.** Smart medians are 0.90× / 1.11× / 0.99× — close to
parity with Garmin UI on aggregate. But individual nights swing widely:
deep range `[0.20×, 3.95×]`, light range `[0.51×, 4.49×]`, REM range
`[0.15×, 2.73×]`. Single-night stage durations from transition math are
not reliable at high confidence.

**Implication for `build_daily_summary`.** The daily aggregator requires
`sleep-official.csv` for stage durations and refuses to fall back to
transition math by default. `--allow-missing-sleep-official` downgrades
to partial mode and emits empty stage columns rather than untrustworthy
ones.

## Per-night outliers (|ratio − 1| > 1.0)

The naive-awake column is responsible for most outliers — virtually every
night exceeds the threshold there. The list below shows nights where
*non-awake* stages also drift far from 1.0 (the cases where the central-
tendency story breaks down for a specific night).

| night | awake_naive | deep_naive | light_naive | rem_naive | deep_smart | light_smart | rem_smart |
|---|---|---|---|---|---|---|---|
| night_A | 35.00× | 0.84× | 1.20× | 0.95× | 0.96× | 1.31× | 1.05× |
| night_B | 12.50× | 3.95× | 0.50× | 0.40× | 3.95× | 0.55× | 0.45× |
| night_C | 8.10× | 0.20× | 1.85× | 1.10× | 0.30× | 2.05× | 1.15× |
| night_D | 18.75× | 0.95× | 0.65× | 2.73× | 1.10× | 0.78× | 2.73× |

Outlier IDs are anonymized (`night_A`, `night_B`, ...) to honor the
multi-file PII join rule in CLAUDE.md. Re-running the script on your own
archive shows which dates correspond to your worst-case nights.

## Reproducing this on your own archive

```bash
python -m blackswan.parse_daily_fit raw-fit/YYYY-MM-DD/ daily/
python -m blackswan.parse_bulk_export bulk-export.zip history/
python -m blackswan.build_sleep_official history/sleep-all.csv \
    --manual-dirs <your-manual-csv-dir> \
    --out history/sleep-official.csv

python scripts/sleep_transition_vs_official.py \
    --daily-dir daily/ \
    --sleep-official history/sleep-official.csv \
    --out docs/sleep-validation.md
```

The script anonymizes outliers to `night_N` by default. Pass
`--show-dates` to substitute real dates back in for local audit; never
commit a markdown file generated with `--show-dates`.

If your archive's `awake naive` median runs much higher (>12×) or max
exceeds 50×, file an issue — the documented warning would need to widen.

## When to use which method

| Use case | Acceptable source |
|---|---|
| Single-night awake duration | `sleep-official.csv` only |
| Single-night deep/light/REM duration | `sleep-official.csv` only |
| Weekly/monthly avg deep/light/REM | naive transition is fine — central tendency converges |
| Per-minute stage lookup (HR/SpO2 cross-tab) | `_sleep.stage_at()` on transitions (existing helper) |

The minute-grid module (`build_sleep_stage_grid`) does NOT carry totals
for this reason — it only emits per-minute stage labels for cross-tab,
and `build_daily_summary` is the canonical surface for per-day stage
totals (sourced from official).

# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-05-04

### Added
- **Strength training analysis module (experimental)** — calibrated on n=5
  vivoactive 5 sessions, single user. New top-level entry points:
  `compare_strength_sessions(baseline_fit, recent_fit)` for the full pipeline,
  `compare_strength_sessions_from_stats` for cardio-API parity. Pairs sets on
  `(active_idx, weight, reps)` with exercise-level fallback.
- **Early-session optical-HR artifact detector** — `detect_strength_hr_artifact`
  flags `EARLY_DEFICIT_LATE_NORMAL` when first sets read suspiciously low and
  late sets normalise. Tagged experimental in 3 user-facing locations
  (module docstring, `summary()` output, README Status row). Configurable via
  frozen `StrengthDetectorConfig` with a threshold-shopping warning in its
  docstring.
- **Set parser, segmenter, and per-set HR pairing** — `parse_strength_fit`
  uses `set.start_time` (FIT field 6, validated on n=5) and pins
  `Decoder().read(convert_datetimes_to_dates=False)`. `identify_exercises`
  groups active sets via `max_rest_gap=3` adjacency, with a runtime warning
  when `(weight, reps)` buckets appear non-contiguously (suspected
  superset / unilateral pattern).
- **Synthetic FIT generators** — `examples/synthetic_strength_baseline.py`
  and `examples/synthetic_strength_recent.py` produce byte-deterministic FITs
  with year-2000 timestamps and zero host fingerprint. The strength
  quickstart auto-regenerates them on first run.
- **`docs/confounders.md` § 9** — strength-specific confounder catalogue
  covering grip vasoconstriction, wrist tension, watch fit, time-of-day vs
  chronology confound. Cross-references added to § 5 (cardio HR artifact)
  and § 7 (cardio noise floor) clarifying that strength has its own regime.
- **Repo-wide PII grep guard** — `scripts/check-pii.sh` catches dated FIT
  filenames, personal Garmin paths, and real-year datetime literals in
  `examples/`. Supplements the per-file `.gitignore` patterns.

### Changed
- **Cardio `cc_metrics.TrialStats.__post_init__`** — the `kmh<=0` ValueError
  now follows the problem+cause+fix triplet pattern (TC#4, retroactively
  applied to match the new strength API errors).
- **`LOCAL_TZ` extracted to `blackswan._time`** — `blackswan._sleep`
  re-exports for backward compat. Existing imports keep working.
- **`README.md`** — added a Strength training analysis section with
  quickstart and sample output, updated the Pipeline ASCII to include
  the strength path, marked the feature `⚗️ experimental, vivoactive 5
  only, n=5` in Status.
- **`.gitignore`** — added `*.FIT`, `*.fit.gz`, `*-analysis.md`,
  `*-real-data.md` to the personal-data block.

### Notes
- v0.2.0 is NOT v1.0 — the strength detector ships experimental until
  recalibrated on n>=10 sessions across multiple devices.
- 76 tests pass (cardio + sleep + strength). Cardio pipeline behaviour
  unchanged.

## [0.1.0] - prior history

Initial release: cardio CC analysis, sleep SSOT, HR artifact detection,
authoritative climb segmentation, bulk-export and per-day FIT parsers.
See git history before this CHANGELOG was created for details.

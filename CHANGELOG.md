# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-05-05

### Fixed
- **`parse_strength_fit` now parses real-device vivoactive 5 strength FITs.**
  Garmin watches truncate sub-second timing on `set.start_time`; the parser
  now absorbs this and counts clamps via
  `StrengthSession.n_set_boundaries_clamped`. Inversions `>= 1.0 s` still
  raise (real overlap suspected).

  Background: FIT spec precision asymmetry — `set.start_time` is uint32
  epoch seconds (second-precision) but `set.duration` is uint32 scale=1000
  (millisecond-precision). On devices that finish a set mid-second, the
  next `set.start_time` is truncated by up to 0.999 s, producing apparent
  overlap. v0.2.0 raised on every such boundary (n=5/5 in author's
  vivoactive 5 archive); v0.2.1 clamps and counts.

  See `docs/confounders.md` § 10 and `docs/methodology.md` § noise floor.

  **Behavior change for `try/except ValueError: skip` callers**:
  `parse_strength_fit` will no longer raise on real vivoactive 5 strength
  FITs. A one-shot `warnings.warn` is emitted on the first clamp per
  session so existing skip-loops see the signal. The 1.0 s tolerance
  itself is `Final` (not monkeypatchable); file an issue if you need a
  per-call tolerance knob.

- **v0.2.0 erratum**: the "validated on n=5" wording in v0.2.0 release
  notes referred to validation through `parse_strength_fit_from_msgs` with
  synthetic pre-built datetime msgs. The full Encoder → Decoder → parser
  disk path was not exercised on fractional-duration FITs in v0.2.0; the
  strength module raised on real-device input. v0.2.1 adds disk-path
  regression tests covering the truncation regime.

### Added
- `StrengthSession.n_set_boundaries_clamped: int` counter (default 0).
- `StrengthSession.summary() -> str` method (clamp count surfaced when ≠0).
- Module-level FIT-precision invariant constant
  `INVERSION_TOLERANCE_S` (1.0 s, `Final`) in `parse_strength_fit.py`.
- 9 disk-path regression tests in `test_parse_strength_fit.py` covering
  FIT precision asymmetry (sub-second clamp, ≥-tolerance raise, FP edge,
  cascade monotonic, HR window after clamp, dataclass field placement,
  summary method behavior).
- `docs/confounders.md` § 10 entry on FIT precision asymmetry.
- `docs/methodology.md` § noise floor entry for `n_set_boundaries_clamped`.

### Empirical inversion distribution (pre-merge data)

- n=5 vivoactive 5 sessions analyzed locally, single user.
- `n_set_boundaries_clamped` per session: 19, 21, 39, 24, 20 (123/143 total boundaries clamped, ~86%).
- max inversion observed: **774 ms** (well below the 1000 ms FIT-spec upper bound).
- No session showed inversion in `[0.95, 1.0)` s — the real-overlap floor
  assumption holds across this n=5 sample. v0.3 recalibration not triggered.

### Deferred (future versions)
- `blackswan inspect-strength <path>` CLI subcommand (v0.3).
- `inversion_tolerance_s` per-call kwarg (v0.3 if power users surface need).
- `clamp_inversions: list[float]` per-clamp magnitude list (v0.3 if
  debugging surface need).
- Cross-cutting `FitTimestamp` precision schema in `_time.py` (deferred
  per design doc).

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

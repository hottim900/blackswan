# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-05-11

### Added
- **Strength comparison surfaces the cross-session local-hour confounder
  (closes #1 P3, warning-only branch).** Before v0.4.0 the warning text
  was a one-line "circular diff Nh; see § 9 for the n=5 calibration
  confound caveat." v0.4.0 expands it to the 3-component contract from
  the v0.4.0 design (warning-text contract, lines 75-80):
  1. hour-diff line (preserved)
  2. quantitative reference quoting `docs/confounders.md § 9`'s n=5
     calibration (afternoon vs evening +27 bpm early sets / +11 bpm late
     sets / +19 bpm overall) — framed as artifact-favoured so a reader
     who never follows the link cannot misread the magnitudes as a
     validated circadian effect size
  3. artifact-OR-circadian attribution qualifier
     ("EARLY_DEFICIT_LATE_NORMAL signature OR circadian — both hypotheses
     consistent with the n=5 sample")

  The +27/+11/+19 numerals live in module constants
  (`N5_CALIBRATION_DELTA_EARLY_BPM`, `_LATE_BPM`, `_OVERALL_BPM`,
  `N5_CALIBRATION_N`) so the doc table + warning text + tests share one
  source of truth. Composed via `_format_local_hour_warning(...)`.
- **`StrengthComparisonReport.local_hour_correction_bpm` field
  (always-ship sidecar).** Reserved field with explicit sentinel
  semantics so consumers do not have to check which branch shipped:
    * `None` → correction not computed (the v0.4.0 default; also returned
      by the future correction branch when formula evaluation skips a
      pair, e.g. same `local_hour`)
    * `0.0` → correction computed, no adjustment needed
    * non-zero `float` → correction magnitude in bpm. Existing
      `exact_slot_mean_delta` and `pairs[].hr_delta` STAY RAW; consumers
      apply the sidecar as
      `corrected_recent_hr = recent.hr_avg - local_hour_correction_bpm`.

  The field is `kw_only=True` and defaults to `None`, so existing
  positional `StrengthComparisonReport(...)` constructions remain valid
  and `asdict()`/pickle compatibility is preserved across the field
  addition.
- **`scripts/inventory_strength_corpus.py`** — one-shot author tool that
  walks a Garmin archive, parses every strength FIT, and prints
  `AND_GATE_UNLOCKED=<bool>` against the binary unblock condition
  (`n ≥ 10` AND each time-of-day band covered in the most recent 4-week
  window). Output CSV is PII-safe (synthetic `session_id`, no fit_path,
  no exact timestamps). Fails closed (exit 2) on any unreadable
  subdirectory — a partial scan is worse than no scan.
- **`docs/confounders.md § 9.1`** — Unblock condition for circadian
  correction (Issue #1 P3). Documents the binary AND-gate, the inventory
  protocol, the v0.4.0 inventory snapshot, and the revisit trigger. § 9.1
  extends with the formula derivation + validation table when the
  correction branch ships.

### Changed
- **`docs/evolution-proposals.md`** — synthesis priority table tagged
  `ARCHIVED — superseded by issue-driven priority`. D1 full / D3 / D4 /
  D5 sections individually tagged `DEFERRED — awaiting dogfooding
  signal`. D1 minimal (README tagline + pyproject keywords) shipped.
- **`README.md`** — line 3 tagline appends industry vocabulary
  (`aerobic decoupling, Pw:Hr, cardiac drift, VAM, heart-rate decoupling,
  running power`) with an HR-only-path scope note that does not
  overclaim power-meter equivalence. Quickstart drops the dead-line
  `pip install garmin-fit-sdk` standalone — the SDK is a transitive
  dependency of `uv pip install -e .`.
- **`pyproject.toml`** — keywords expanded by 6 entries:
  `aerobic-decoupling`, `pw-hr`, `vam`, `heart-rate-decoupling`,
  `cardiac-drift`, `running-power`. PyPI
  `Topic :: Scientific/Engineering :: Medical Science Apps.` classifier
  intentionally NOT added — deferred to D1 full / first PyPI publish per
  TODOS.

### Compatibility
- `StrengthComparisonReport` gained the `local_hour_correction_bpm`
  field (append-only after `notes`, `kw_only=True`, defaults to `None`).
  Positional constructors and pickle/asdict consumers continue to work
  unchanged.
- **Re-install (`uv pip install -e .`) required** on existing checkouts
  to surface the new field — calling `report.local_hour_correction_bpm`
  on a stale install raises `AttributeError`.
- Existing 3 `test_local_hour_warning_*` regression tests remain valid;
  the warning string is longer but still contains the hour markers they
  assert on.

### Documentation
- **`docs/related-work.md`** committed alongside `evolution-proposals.md`
  as the historical synthesis record (28k-word 2026-05-11 strategic
  document). Both are retained as the archived candidate pool for future
  evolution directions; the live roadmap is now the GitHub issues
  backlog.
- **`TODOS.md`** new section `v0.4.0 deferred items` tracks the
  correction-branch unblock condition (with inventory protocol + revisit
  trigger), `_LOCAL_HOUR_WARN_THRESHOLD` re-derivation, cardio
  circadian residual recalibration (`confounders.md § 7`), D2 Rule-of-
  Three trigger, inventory script productionization, and the deferred
  PyPI `Medical Science Apps.` classifier.

## [0.3.1] - 2026-05-10

### Fixed
- **Sentinel passthrough closed for `build_daily_summary` aggregates
  (closes #10).** v0.3.0 aggregated raw `respiration_rate_brpm` values
  that included Garmin's `-1` / `-2` unmeasurable-minute sentinels and
  vivoactive 5's `hr_bpm = 0` optical-dropout values, so
  `min_respiration_brpm` was always wrong on any day with unmeasurable
  minutes and `avg_hr_bpm` ran low on dropout-heavy days.
  - Respiration is filtered at `MIN_PHYSIOLOGICAL_BRPM = 4` before all
    aggregates (min/max/avg + sleep/awake split). Drops `-1` / `-2`
    Garmin sentinels and the 0-3 brpm sub-physiological tail.
  - HR is bounded by `[MIN_PHYSIOLOGICAL_BPM = 25, MAX_PHYSIOLOGICAL_BPM
    = 220]` before all aggregates (avg + sleep/awake split + resting).
    Catches the vivoactive 5 `0` dropout, the historical `255` high
    sentinel, and sub-25 / >220 implausible values without dropping
    trained-athlete resting HR (cyclist RHR routinely sits in low 30s).
  - All-sentinel CSVs now flip `data_completeness=partial` instead of
    silently emitting `"full"` with `avg=None`.
  - Raw `{date}-hr.csv` and `{date}-respiration.csv` from
    `parse_daily_fit` are unchanged; cleansing happens at the summary
    boundary so downstream tools can still inspect sentinel rates.

### Added
- **`sleep_avg_hr_bpm` and `awake_avg_hr_bpm` columns (closes #10).**
  Mean HR within and outside the sleep session window, computed via the
  same window helper that already drives the respiration split. Empty
  session window → both `None` + `data_completeness=partial`. Column
  names describe the computation (mean within sleep window) rather than
  claiming parity with any specific Garmin Connect surface; on the
  issue-#10 4-day comparison the values land within sensor-noise
  distance of Connect's "跨日心率 / overnight HR" but no parity guarantee
  is made.
- **`scripts/spo2_audit.sh`** — one-time pre-PR helper that scans a
  user archive for SpO2 sentinel rows. If it returns hits in v0.4.0
  triage, the same per-metric filter pattern extends to SpO2 alongside
  the cross-cutting `_drop_below_floor` refactor (Approach D in TODOS).

### Changed
- **`_split_respiration_by_window` is now `_split_floats_by_window`**
  with a `val_col` kwarg so HR + respiration share the implementation.
  Function is module-private (underscore-prefixed); no compat alias is
  retained per CLAUDE.md no-compat-shim policy.
- **`n_hr_readings` and `n_respiration_readings` now reflect post-filter
  readings** (was: total CSV rows). Days with sentinel-heavy minutes
  report a smaller `n` than under v0.3.0.
- **`_split_floats_by_window` normalizes tz-naive timestamps to
  `LOCAL_TZ`** before comparing against the session window.
  `parse_daily_fit` emits tz-aware via `_local()`, but legacy or
  hand-authored CSVs may be naive and previously crashed batch builds
  with a `TypeError` on `<=`.

### Documentation
- **Module docstring documents the sentinel filter and the
  awake-respiration divergence from Garmin Connect's "清醒平均"** (closes
  #10 part 3). `awake_avg_respiration_brpm` here = mean OUTSIDE sleep
  window (includes quiet bed-rest minutes); Connect appears to apply
  additional server-side activity filtering (mechanism undocumented).
  Users seeking a Connect-aligned awake number should rely on
  `sleep_avg_respiration_brpm`, which matches Connect's sleep mean.

### Schema
- `DAILY_SUMMARY_COLS` appends `sleep_avg_hr_bpm` and `awake_avg_hr_bpm`
  AFTER the v0.3.0 prefix (append-only convention; readers iterating by
  name are unaffected). T6 schema-lock test now also asserts the v0.3.0
  prefix is unchanged so position-indexed readers do not silently shift.

### Notes
- 9 new tests (T18-T26) cover sentinel filtering, sleep/awake split with
  boundary inclusivity, all-sentinel partial-flag paths, tz-naive
  normalization, and the resting-HR fallback. T1 + T6 + T11 + T12 still
  pass with the new schema.
- `avg_hr_bpm` rename to `all_day_avg_hr_bpm` and an empirical
  reverse-engineering of Connect's awake-mean filter are deferred to
  v0.4.0 (see `TODOS.md`).
- "The Assignment" empirical validation (re-run on the 4 issue days
  before merge) is the user's pre-merge step; rollback is clean (raw
  CSVs unchanged), so the validation is a recommendation rather than a
  blocker on the PR-side.

## [0.3.0] - 2026-05-10

### Added
- **`build_daily_summary` — single-row per-day aggregate (closes #7).**
  Mirrors Garmin Connect's web-export semantics: HR avg + n_readings,
  resting HR, SpO2 avg/min/max, respiration avg/min/max + sleep/awake
  split using the sleep-assessment session window, HRV passthrough,
  sleep stage durations from `sleep-official.csv`, body battery
  charged/drained from the bulk export.
  - **`sleep-official.csv` is REQUIRED for stage durations** — missing
    date row raises `MissingSSOTError` with a remediation pointer to
    `build_sleep_official`. Pass `--allow-missing-sleep-official` to
    downgrade to partial mode and emit empty stage columns. Naive
    transition math on `sleep-levels.csv` is NOT a fallback.
  - `data_completeness` column reports `"full"` or `"partial"` so
    downstream consumers can filter on quality. Each required input
    (HR, SpO2, respiration, sleep-assessment, intraday-rhr) flips the
    flag to `"partial"` when missing or header-only; HRV-summary
    missing keeps the flag at `"full"` (HRV is optional on watches
    without an HRV-status surface). Body-battery missing flips the flag.
  - `DAILY_SUMMARY_COLS` is the schema SSOT (mirrors `_sleep.SLEEP_COLS`
    pattern). Schema is locked at v0.3.0 — additions are append-only.
  - CLI: single-day mode (`--out`) + batch mode (`--all --out-dir`).

- **`build_sleep_stage_grid` — per-minute stage grid (revised #8).**
  Expands `sleep-levels.csv` transitions into a fixed-cadence grid
  (default 60 s, accepts 30 s) using `_sleep.stage_at()`. Brief
  in-sleep arousals inherit the surrounding non-awake stage —
  matching semantics already used in `analyze_spo2_vs_stage`. Edge
  cases handled: empty/single-row sleep-levels (skip with warn),
  duplicate timestamps (latest wins), unsorted input (defensive sort),
  all-awake transitions (empty stage column + warn). Per-stage totals
  are explicitly out of scope — they belong in `build_daily_summary`
  from the official source.

- **`scripts/sleep_transition_vs_official.py` — validation script.**
  Anyone with their own daily/ + sleep-official.csv can re-run the
  validation that supports the codebase's sleep-stage warnings.
  Library form (`blackswan._sleep_validation`) is unit-testable.
  Outliers anonymize to `night_N` by default; `--show-dates` is for
  local audit only and should never produce a committed markdown.

- **`docs/sleep-validation.md` — n=66 evidence.** Replaces anecdotal
  "10x+", "12x", "1.4-4.5×" claims in `parse_daily_fit.py` and
  `analyze_spo2_vs_stage.py` docstrings with a reproducible table:
  - Naive awake median 7×, p75 10.5×, max 35× (vivoactive 5, n=66).
  - Smart awake collapses to 0× by design (info-loss tradeoff).
  - Smart deep/light/REM medians: 0.90× / 1.11× / 0.99× — central
    tendency near 1.0× but per-night noise is large (deep range
    [0.20×, 3.95×]).

### Changed
- **Docstring patches** in `parse_daily_fit.py` and
  `analyze_spo2_vs_stage.py` reference `docs/sleep-validation.md` and
  drop the unsupported "1.4-4.5× systematic divergence" framing.
- **README pipeline diagram** shows the daily-summary path with the
  `sleep-official.csv` requirement called out.
- **`scripts/check-pii.sh`** adds a real-year ISO-date guard for
  `docs/` and `tests/` (year 2000 is the only allowed date convention).

### Notes
- Body battery level-curve columns (`body_battery_min` / `_max` /
  `_delta`) are **deferred to v0.3.1** until FIT field presence on
  vivoactive 5 is smoke-tested. v0.3.0 ships only the bulk-export
  passthrough (`body_battery_charged` / `body_battery_drained` — energy
  in/out).
- 45 new tests across three files (validation, stage-grid, daily-summary)
  on top of the existing strength + cardio suites. Synthetic fixtures
  use year=2000 timestamps per repo convention.
- TODOs added: `consolidate_daily_summaries` (multi-row trend CSV),
  shared `_errors.py` for SSOT-class exceptions.

## [0.2.2] - 2026-05-07

### Fixed
- **Ghost (`reps=0`) active sets no longer pollute strength comparison
  output (issue #5).** vivoactive 5 emits `set_type='active'` rows with
  `weight=0, reps=0` (or `weight>0, reps=0`) when the user presses the
  set button but performs zero reps (failed pull-up attempt, accidental
  press). Previously these leaked into
  `StrengthComparisonReport.unmatched_baseline`, polluting match-rate
  denominators and surfacing as user-actionable mismatches that aren't
  real exercises. Now:
  - `_build_session_stats` drops `reps == 0` active sets after the
    existing `is None` filter and tracks the count on
    `StrengthSessionStats.n_zero_reps_dropped` (new internal field).
  - `compare_strength_sessions_from_stats` emits a per-side `notes` line
    when either side dropped any zero-reps sets (mirrors
    `bucket_exhausted` style — only emitted for the side(s) with drops).
  - The 0-pairs `ValueError` raise message now appends a "dropped N
    zero-reps from baseline / M from recent" note so users know the
    filter caused the empty match.
  - `segment_strength_sets._group_name` returns `"zero_reps"` for any
    `(weight, reps=0)` (broader guard, including `weight>0` failed
    weighted attempts that previously read as `"60.0kg × 0"`).
  - `detect_strength_hr_artifact` ignores ghost sets in its early-deficit
    window: two early-session button-presses at sitting HR (~80 bpm)
    previously could false-trigger `EARLY_DEFICIT_LATE_NORMAL` because
    the detector walked raw `session.sets` filtered only on
    `set_type=='active'`. The detector now also requires `reps != 0`.
  - The raw `StrengthSet` is retained in `StrengthSession.sets` for any
    future failed-attempt analysis — only the comparison-stats layer
    and the artifact detector drop them.

### Behavior change
- **`excluded_indices_baseline` / `excluded_indices_recent` now raise
  `ValueError` for stored indices that targeted ghost active sets.** The
  V2.12 anti-shopping guard validates that every index appears in
  `active_set_stats`; ghost sets are now filtered out, so a previously
  stored `{ghost_active_idx}` exclusion fails the guard. Fix: drop ghost
  active_idx values from stored exclusion sets after upgrading
  (`print stats.active_set_stats[*].active_idx` shows the post-filter
  set of valid indices).

### Added
- `StrengthSessionStats.n_zero_reps_dropped: int = 0` — count of active
  sets dropped during stats build because `reps == 0` (recorded intent
  without work performed). Internal accounting; not part of the public
  `StrengthComparisonReport` surface (revisit if a programmatic consumer
  asks).
- `"zero_reps"` returnable group name in `segment_strength_sets._group_name`
  alongside existing `"warmup"`, `"bodyweight"`, and `"{weight}kg × {reps}"`
  values.
- 9 regression tests pinning the new behavior across stats build,
  segmenter labelling, comparison pairing, notes wording, 0-pairs raise
  message, warmup invariant, the `excluded_indices_*` behavior change,
  and the artifact detector early-deficit window.

### Empirical noise-floor update (informational)
- One additional vivoactive 5 archive shows `n_set_boundaries_clamped`
  ratio 24/25 ≈ 96 %, exceeding the v0.2.1 release notes' n=5 maximum of
  39/45 ≈ 87 %. Maximum inversion in this archive remains well below
  1.0 s, so the `INVERSION_TOLERANCE_S` floor assumption is intact. No
  behavior change. See `docs/methodology.md` § noise floor.

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

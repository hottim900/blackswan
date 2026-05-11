# TODOs

Deferred work captured during V2 strength-training analysis (PR #2). Each
entry names the artifact, the reason it was deferred, and the trigger that
should make us revisit.

## Globally-closest bipartite assignment for set pairing

**Where:** `src/blackswan/strength_metrics.py` —
`compare_strength_sessions_from_stats`, Step 2 ("exercise-level fallback").

**What:** the current Step 2 is a baseline-first greedy walk: for each
unpaired baseline set, pick the recent set in the matching `(weight, reps)`
bucket whose `active_idx` is closest. This is order-dependent. With three
baseline sets at the same `(60kg, 8)` and three recent sets at the same
`(60kg, 8)` but slightly different `active_idx`, the greedy result depends
on baseline iteration order — the optimal globally-closest bipartite
matching can differ.

**Surfaced today:**

- `MatchedPair.match_quality` Literal includes `"bucket_exhausted"` as a
  reserved enum value; no runtime pair carries it.
- `StrengthComparisonReport.notes` reports `bucket_exhausted: N baseline
  set(s) had a matching (weight, reps) ...` when greedy drains a bucket
  before all baseline candidates are matched. That `N` is exactly the
  count globally-closest matching would recover.

**Why deferred:** v1 calibrated on n=5 sessions, single user. The
greedy/optimal split was never observed — every session in calibration
either had clean exact_slot matches or genuinely missing buckets. Building
the Hungarian / linear_sum_assignment scaffolding before evidence of
real-world divergence would be over-engineering for a single user.

**When to revisit:** the first session where `notes` includes
`bucket_exhausted: N` with N > 0 AND the user reports the report's deltas
disagree with their interpretation of the workout. At that point swap the
greedy block for `scipy.optimize.linear_sum_assignment` keyed on
`abs(active_idx_b - active_idx_r)`, populate one or more pairs with
`match_quality="bucket_exhausted"` to surface the recovery, and update
the docstring + tests.

**Context:** see V2 plan Choice 2 (auto-decided) at
`~/.gstack/projects/hottim900-blackswan/tim-main-design-20260503-024306.md`,
and the multi-agent verification log on PR #2.

## v0.2.1 deferred items

Captured by /autoplan during the v0.2.1 FIT precision-asymmetry patch. Each
entry names the deferral reason and the trigger that should make us revisit.

### `blackswan inspect-strength <path>` CLI subcommand

**Where:** new entry point in `pyproject.toml` `[project.scripts]` table; new
module `src/blackswan/inspect_cli.py`.

**What:** one-shot diagnostic CLI: `blackswan inspect-strength foo.fit` prints
session metadata, per-set boundaries, `n_set_boundaries_clamped`, max
inversion magnitude. Lets users debug their own FITs without writing a
script.

**Why deferred:** outside v0.2.1 blast radius (new public surface, new tests,
new docs). DX-9 in the v0.2.1 design plan.

**When to revisit:** v0.3, or first user issue asking "how do I see what the
parser does on my FIT?".

### `inversion_tolerance_s` per-call kwarg on `parse_strength_fit`

**What:** allow callers to pass a custom tolerance instead of the
module-level `INVERSION_TOLERANCE_S = 1.0`. Currently `Final` and not
monkeypatchable.

**Why deferred:** TASTE-DX-2 in the v0.2.1 plan. The 1.0 s constant is a
FIT-spec derivation, not a tunable; exposing a knob invites users to mask
real corruption with a relaxed tolerance. Defer until power users surface
a concrete need.

**When to revisit:** first user issue asking for a per-call tolerance with
a credible non-debug reason.

### `clamp_inversions: list[float]` per-clamp magnitudes on `StrengthSession`

**What:** store the inversion magnitude of each clamp (not just the count)
so users can debug FIT precision-asymmetry distributions per session.

**Why deferred:** TASTE-DX-3. The audit counter `n_set_boundaries_clamped`
is enough for the v0.2.1 use case (skip-loop callers + summary). Storing
per-clamp values doubles the audit surface for marginal benefit.

**When to revisit:** v0.3 if users report needing the distribution for
their own debugging without re-running the parser-equivalent inversion
extraction.

### Cross-cutting `FitTimestamp` precision schema in `_time.py`

**Where:** `src/blackswan/_time.py`.

**What:** a typed wrapper that encodes "this datetime came from a FIT
field with precision X" so the v0.2.1 patch's local fix in
`parse_strength_fit.py` becomes a project-wide pattern. Other parsers
(cardio, sleep, daily) gain the same protection without copy-paste.

**Why deferred:** C-wide in the v0.2.1 plan. Out of scope for a
strength-only PATCH. The local fix works; cross-cutting can wait until a
second module hits the same trap.

**When to revisit:** when a second parser surfaces a similar
precision-asymmetry bug, OR when Garmin SDK profile adds fractional
duration to `lap_mesgs` / similar.

### Upstream PR to garmin_fit_sdk

**What:** after a 30-min read of golden-cheetah's `set_mesgs` handling,
file an upstream PR that documents the FIT-spec precision-asymmetry trap
and exposes a helper for downstream parsers.

**Why deferred:** EXP-9 in the v0.2.1 plan. Low priority; v0.2.1's local
fix already serves blackswan users. Upstream contribution is a
nice-to-have.

**When to revisit:** when blackswan PRs are caught up and a quiet week
allows the SDK reading.

### Issue #1 close commit + comment

**What:** issue #1 references the v0.2.0 ship state. After v0.2.1 ships,
post a comment summarising the patch and close.

**Why deferred:** EXP-8. Housekeeping, separate from the patch itself
(D1 design choice C kept admin work isolated).

**When to revisit:** immediately after v0.2.1 tag.

### 6-month regret hedge

**What:** if v0.2.1's clamping behaviour produces a systematic bias that
only surfaces in cross-session comparison after several months of data,
revisit the 1.0 s threshold + clamp-recompute strategy.

**Why deferred:** C-8 in the v0.2.1 plan. P3b real-overlap-floor
assumption was confirmed empirically on n=5 (max 774 ms, no `[0.95, 1.0)`
hits) so the immediate risk is low.

**When to revisit:** 2026-11 (six months post-tag), or first session that
shows `n_set_boundaries_clamped` distribution with a long tail near
0.99 s.

## Issue #5 (zero-reps ghost filter) deferred items

Captured by /autoplan during the issue-#5 patch (CHANGELOG `[Unreleased]`).
Each entry names the deferral reason and the trigger that should make us
revisit.

### Parser-side `(reps=0)` coercion

**Where:** `src/blackswan/parse_strength_fit.py:366` (`raw.get("repetitions")`).

**What:** coerce `repetitions=0` to `None` at the parser instead of
preserving the FIT-faithful `reps=0` and filtering downstream. Mirrors the
v0.2.1 `n_set_boundaries_clamped` "clamp at write-asymmetry" precedent.

**Why deferred:** the v0.2.1 clamp is precision-correction (write-asymmetry
artifact), not semantic drop of valid FIT data — categories distinct.
`(reps=0)` is semantically valid FIT (recorded intent), so parser-side
coercion would conflate concerns and lose information that may be useful
for future failed-attempt analyses.

**When to revisit:** if `reps=0` observably has no consumer in the
codebase by v0.3, OR if a second device emits `(0, 0)` differently and
convergence becomes worth the schema-fidelity tradeoff.

### `include_zero_reps: bool` kwarg on `_build_session_stats`

**What:** allow callers to opt out of the new zero-reps filter (retain
ghosts in `active_set_stats`). Mirrors the deferred
`inversion_tolerance_s` knob pattern.

**Why deferred:** single-user library today; no consumer has asked. The
filter is a baseline-definition decision (Layer 2), and exposing a knob
invites the same exclusion-shopping risk that CLAUDE.md warns against.

**When to revisit:** first user request for ghost retention with a
credible non-debug reason.

### Public `n_zero_reps_dropped_baseline` / `_recent` on `StrengthComparisonReport`

**What:** expose the per-side drop counts as structured fields on the
public report, alongside `n_pairs` etc.

**Why deferred:** today's notes-string + internal
`StrengthSessionStats.n_zero_reps_dropped` field is sufficient. Consistent
with the existing `bucket_exhausted_count` notes-only pattern. Adding 2
public fields per-side (4 total) is API surface expansion.

**When to revisit:** first programmatic consumer that needs structured
drop-count access (e.g. CI dashboard, batch report aggregator).

### Naming review for the `"zero_reps"` group token

**What:** revisit whether `"zero_reps"` is the right label, or whether a
richer ghost taxonomy is needed (`failed_attempt`, `ghost`, `partial_rep`,
`recovered_artifact`).

**Why deferred:** single device, single user — no evidence that
disambiguation matters yet. Today's flat `"zero_reps"` is honest and
caller-discoverable.

**When to revisit:** when multi-device data lands and ghost-emission
patterns diverge across vendors.

## consolidate_daily_summaries (multi-row trend CSV)

**Where:** new module — `src/blackswan/consolidate_daily_summaries.py`.

**What:** today `build_daily_summary` writes one CSV per date. For trend
analysis (rolling avg HR, body battery delta over weeks) a single
multi-row CSV is more useful — stack every `{date}-daily-summary.csv` in
a directory into `daily-summaries-all.csv`.

**Why deferred:** v0.3.0's blast radius is the per-day aggregator + SSOT
enforcement. The aggregator alone is shippable; consolidation is purely
additive and the file format is already row-stable (`DAILY_SUMMARY_COLS`
locked at v0.3.0).

**When to revisit:** first downstream consumer that needs to plot or
window a metric across many days.

## Shared `_errors.py` for SSOT-class exceptions

**Where:** new module — `src/blackswan/_errors.py`.

**What:** `MissingSSOTError` lives in `build_daily_summary` today. If a
second SSOT-required surface emerges (likely candidates: HRV daily
summary, sleep-disruption daily totals), the exception type should move
to a shared module so callers can `except` the family.

**Why deferred:** premature abstraction with one consumer — the move is
a 5-minute refactor when the second consumer arrives.

**When to revisit:** the second module needs an SSOT-class exception or
external callers start `isinstance`-checking against `MissingSSOTError`.

## Schema-lock SSOT promotion for column-name constants

**Where:** new module — `src/blackswan/_schemas.py` (or extend `_sleep.py`).

**What:** column-name string lists are duplicated across modules:
`DAILY_SUMMARY_COLS` lives in `build_daily_summary.py`, the per-stage
column names (`deep_sec`, `light_sec`, `rem_sec`, `awake_sec`,
`unmeasurable_sec`) appear in three places — `_sleep.SLEEP_COLS`,
`build_daily_summary._OFFICIAL_STAGE_COLS`, and
`analyze_spo2_vs_stage._OFFICIAL_STAGE_COLS`. Promote the stage-name
list to a single SSOT and have callers import from there.

**Why deferred:** TASTE decision from autoplan (ENG-11) — bigger refactor
than v0.3.0's blast radius warranted. The current duplication is
visible-and-checkable (each list is short, lints cleanly), and the
real cost would only show up if we add a stage (e.g., `nrem_sec`).

**When to revisit:** any of these triggers — adding a new stage column,
a third consumer of the official-stage list, or a column-rename PR
that has to touch all three sites at once.

## v0.4.0 / future — daily_summary metric authority + sanity layer

Captured by /autoplan during the v0.3.1 patch (issue #10) review.

### Approach D: cross-cutting `_drop_below_floor` helper

**What:** generalize `_filter_physiological_respiration` +
`_filter_physiological_hr` into one helper `_drop_below_floor(rows, col)`
driven by a dict
`_PHYSIOLOGICAL_FLOORS = {"hr_bpm": (25, 220), "respiration_rate_brpm":
(4, None), "spo2_percent": ...}`.

**Why deferred:** v0.3.1 user choice B at the premise gate kept
per-metric helpers for narrowest patch scope. Approach D adds SpO2 in
one dict entry instead of one helper + one constant + one test, but
only pays off once SpO2 actually needs sentinel filtering.

**When to revisit:** first SpO2 sentinel finding from
`scripts/spo2_audit.sh`, or when adding a 4th physiological metric.

### `_CompletenessTracker` centralization

**What:** central tracker that the rest of `build_one` writes to (file
missing, bulk missing, session-window empty, all-sentinel CSV) and the
assembly step reads. Replaces the 4+ scattered
`completeness = "partial"` assignments.

**Why deferred:** out of scope for the v0.3.1 patch. Currently 4
scattered assignments; v0.4.0 will likely have 5+ once SpO2 / additional
sentinel filters land.

**When to revisit:** when scattered partial-flag count exceeds 6 and
review fatigue starts surfacing missed signals.

### P3 rename: `avg_hr_bpm` → `all_day_avg_hr_bpm`

**What:** rename to make the implicit "all-day" qualifier explicit, so
the `all_day_*` / `sleep_*` / `awake_*` triple has consistent
qualifier-by-name.

**Why deferred:** v0.3.1 user chose B (additive only). Rename adds
backwards-compat cost (every reader updates). Defer until a multi-user
count or a natural v1.0.0 schema-redesign moment.

**When to revisit:** v1.0.0 / first non-self user / cross-pipeline
schema migration.

### P5 empirical Issue #3: reverse-engineer Connect's awake-mean filter

**What:** afternoon-scale empirical investigation using
`{date}-activity.csv` (`activity_intensity` already in parser output) to
test whether Connect's "清醒平均" excludes minutes with `intensity == 0`.
Either fix the gap or document with empirical evidence instead of
speculation.

**Why deferred:** v0.3.1 user chose B (doc-only stays). Investigation
ROI is uncertain — possible mechanisms include `activity_intensity`,
HR-variability gating, or the Sleep tab vs CSV column source diverging.

**When to revisit:** if the next 4-day comparison shows the awake gap is
worth fixing in user's eyes, OR when v0.4.0 metric-authority work
surfaces it.

### Mechanical gate for "The Assignment"

**What:** either a `scripts/validate_daily_summary_against_archive.py`
that runs the 4 issue days and prints pass/fail, OR a PR template that
requires pasting the output. Make pre-PR validation a hard gate, not a
suggestion.

**Why deferred:** process not code. User discretion. /autoplan flagged
the soft-blocker risk but rollback is clean (raw CSVs unchanged).

**When to revisit:** if "The Assignment" is skipped on this PR and a
post-merge surprise surfaces.

### Metric-authority model (codex CEO reframe)

**What:** define per-column metadata: source (raw FIT vs Connect-derived
vs blackswan-aggregated), window (all-day / sleep-window / awake),
filter policy (sentinel-floor / Connect-equivalence / unfiltered), and
Connect-equivalence status. Either as docstring schema, sidecar JSON,
or column-name encoding.

**Why deferred:** product-strategy work, not patch scope. Codex flagged
that every bugfix smuggles product strategy into column names; v0.3.1
confirms the risk class but doesn't resolve it.

**When to revisit:** v0.4.0 design phase / when adding a 5th aggregate
metric / when first non-self consumer lands.

## v0.4.0 deferred items (issue-#1-P3 warning-only branch)

### Strength HR circadian correction (issue #1 P3, correction branch)

**Where:** `src/blackswan/strength_metrics.py` —
`StrengthComparisonReport.local_hour_correction_bpm` field already exists
with sentinel semantics (`None` = correction not computed; `0.0` =
computed/no adjustment; non-zero `float` = bpm sidecar). v0.4.0 ships
warning-only so the field is `None` for every report.

**What:** populate `local_hour_correction_bpm` with a formula derived
against an n ≥ 10 corpus where time-of-day is decoupled from chronology.
Formula candidates (v0.4.0 design Open Q #2): linear
(`β × |hour - 15|`), 2-band split (afternoon-vs-evening flat offset), or
sinusoidal (`A × cos(2π × (hour - φ) / 24)`). Linear or 2-band is the
defensible call for n ≈ 10-30 single-user data.

**Unblock condition (binary AND-gate per `confounders.md § 9.1`):**

1. Corpus has **n ≥ 10** strength_training FIT files.
2. Each time-of-day band — morning (<11h) / afternoon (11–17h) / evening
   (>17h) — has at least one session within the **same 4-week window**
   (chronology decoupled from time-of-day per `§ 9` calibration confound).

**How to inspect:** run `scripts/inventory_strength_corpus.py --root
<archive>`. The script prints `AND_GATE_UNLOCKED=<bool>`. Output CSV is
PII-safe (synthetic session ids, no fit_path, no exact timestamps).

**Revisit trigger:** every 3 months, or whenever a new strength session
lands in a previously empty band-week cell.

**Owner:** hottim900. **Last inventory run:** 2026-05-11
(`n_total=0` on the development machine — the documented n=5 calibration
sample from `confounders.md § 9` lived on a different host; AND-gate
locked by both clauses).

### `_LOCAL_HOUR_WARN_THRESHOLD` re-examination (3 h hardcoded)

**Where:** `src/blackswan/strength_metrics.py` —
`_LOCAL_HOUR_WARN_THRESHOLD = 3` (circular hour diff above which
`local_hour_warning` is emitted).

**What:** the 3-hour boundary is a v1 guess. Once the inventory unlocks
(above) and a formula lands in `confounders.md § 9.1`, the threshold
should be re-derived from the formula's noise floor rather than left at
3.

**Why deferred:** out of v0.4.0 scope per the warning-only branch
decision; v0.4.0 design Decision Audit Trail #8.

**When to revisit:** with the correction-branch ship.

### Cardio circadian residual recalibration (`confounders.md § 7`)

**What:** `§ 7` currently lumps time-of-day into the cardio ±3-5 bpm
noise floor. If the strength formula (when it ships) shows a much larger
circadian effect than 3-5 bpm, the cardio assumption may need
recalibration too. Out of v0.4.0 scope (strength-only) but worth
revisiting symmetrically.

**Why deferred:** v0.4.0 design Open Q #5; flagged as out-of-scope.

**When to revisit:** with the correction-branch ship, OR a separately
filed cardio-side issue showing the residual matters.

### D2 framework abstraction (Rule of Three trigger)

**Where:** would live as `src/blackswan/_compare.py` (new module
extracting `compare_*_sessions` pattern from `cc_metrics` +
`strength_metrics`).

**What:** the strength circadian correction (when it ships) is the 2nd
use case of the confounder-correction pattern. A third would trigger
CLAUDE.md "rule of three" and justify the extraction. v0.4.0 design L1
(Decision Audit Trail #13) makes this explicit.

**Trigger:** the moment a third comparator (`sleep_metrics` cross-session,
or NP cross-session, or any new module) is about to write the same
exclusion-shopping guard + delta-accumulation + noise-floor reporting
scaffolding for the third time.

### Inventory script productionization

**Where:** `scripts/inventory_strength_corpus.py`.

**What:** if the inventory becomes a recurring need (re-run quarterly
per the unblock revisit trigger), the script earns:

- typed return value (currently prints + `sys.exit(...)` only)
- unit test against a temp dir of synthetic FITs
- a thin `blackswan inventory-strength` CLI subcommand when D4 ships

**Why deferred:** one-shot author tool today; productionizing before the
second use case would be over-engineering.

**When to revisit:** on the second invocation, OR when D4 (CLI) ships.

### PyPI `Topic :: Scientific/Engineering :: Medical Science Apps.` classifier

**Where:** `pyproject.toml` `classifiers` list.

**What:** add the `Medical Science Apps.` classifier per
`docs/evolution-proposals.md § D1` (explicit `Medical / sport science`
discoverability surface). Excluded from v0.4.0 to keep the D1-minimal
surface tight; would be part of D1-full.

**Why deferred:** D1 full is "DEFERRED — awaiting dogfooding signal"
per `docs/evolution-proposals.md`. Same trigger.

**When to revisit:** with D1 full, OR before first PyPI publish.

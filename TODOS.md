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

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

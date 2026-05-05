# 4-Layer Analysis Methodology

A protocol for analysing a Garmin interval workout (or any session-level training data) without conclusions drifting across review rounds.

## The problem

Single-pass analysis tends to mix raw facts, internal patterns, cross-session comparisons, and training interpretation in one go. When a reviewer challenges any one of those, the entire chain unravels — because there's no way to know which level the challenge applies to. Concretely:

- "The CC dropped 4 points!" is a **comparison-layer claim**.
- "That improvement is meaningful" is an **interpretation-layer claim**.
- "But trial 5's HR sensor was bad" is a **fact-layer challenge**.

If you don't separate these layers, a fact-layer challenge can invalidate the interpretation-layer claim through pure confusion, even if the comparison-layer claim was actually fine.

The fix: lock layers in order, agent-review each one before moving up.

## The 4 layers

### Layer 1 — Hard Facts (single-session, no comparison, no interpretation)

What you record:

- Session summary (duration, distance, calories, avg/max HR, cadence)
- Per-lap raw values (FIT lap_mesgs)
- Per-trial canonical values (alt min → alt max segmentation)
- HR zone distribution under your personal HRmax
- HR sensor artifact ranges (`detect_hr_artifacts`)
- GPS / altitude bounds
- Recovery durations
- Plan vs actual structure (purely descriptive)

What you **don't** record:

- Comparisons against any prior session
- Words like "improvement", "regression", "consistent with"
- Subjective interpretation of patterns

Authority: every value here should be cross-checkable against the Garmin Connect lap CSV (`csv_fit_crosscheck`). Δ duration ≤ 1s, Δ HR = 0, Δ distance ≤ 8m. If any of these fails, your FIT parser has a bug.

Note: `csv_fit_crosscheck` is a **parser-validation cross-check** (FIT vs the Garmin server's computation of the same session) — not a cross-session comparison. It belongs in Layer 1 because it's verifying "did we read this session correctly?" — exactly the fact-layer question. Cross-session comparison is Layer 3.

For the general protocol behind this style of validation (algorithm vs ground-truth comparison with delta-vs-noise-floor decision rule), see [`authoritative-segmentation.md` § "The general protocol: reverse-engineering algorithm validation"](authoritative-segmentation.md#the-general-protocol-reverse-engineering-algorithm-validation).

### Layer 2 — Internal Dynamics (single-session, internal patterns only)

Now you can describe patterns within this session, but still not compare to others:

- HR drift per trial (bpm/min)
- HRR 60s per trial (note: non-standard if recovery is walking, not stationary)
- Per-trial HR standard deviation (low stdev + high cadence/speed = sensor suspicion)
- Cadence ↑ + speed ↑ + HR ↓ = decoupling (sensor or efficiency, can't tell from data alone)
- HR profile time-series (3-min buckets)
- Outlier trial detection (see explicit rules below)

What stays out: any "vs last week" or "this is an improvement" language.

#### Distinguishing progressive warm-up from sensor failure

Both produce a "low-CC trial 1" reading, but they're different things:

- **Real progressive warm-up** (RPE ≤ 6 by design): start_HR → max_HR span ≥ 30 bpm across the trial. The user is ramping intensity; HR responds.
- **Sensor failure** (optical HR baseline-stuck): start_HR → max_HR span < 15 bpm across the entire trial. The HR readout is locked, can't track the actual climb.

Rule: **if a trial reads low CC AND mHR − sHR < 15 bpm, suspect sensor before claiming a planned easy effort**. Verify by checking: is the cadence and speed consistent with the surrounding trials (real climb)? If yes → sensor failure; if cadence/speed also low → genuine easy effort.

#### Subjective + objective signal coexistence

When the user says "I felt easy on that trial" AND the data says "HR stdev was anomalously low + cadence/speed rose but HR didn't" — both pointing to a low-effort or low-strain reading — **do not collapse to a single explanation**. The two signals can reflect:

- (a) the user really did back off (subjective true, sensor true, simple low effort)
- (b) the user pushed normally but the sensor under-read (subjective true to perception, sensor lying)
- (c) genuine short-term efficiency improvement (subjective true, sensor true, real adaptation — but unlikely on small timeframes; see Layer 4 timeline check)

Without a third independent signal (lactate, RPE matched against breath rate, RR variability, etc.), you can't disambiguate. **The right Layer 2 record is "ambiguous, requires more samples" — exclude from Layer 3 if disambiguation matters; carry the subjective note forward to Layer 4 as soft evidence only.** Don't pick (a) just because it's the simplest narrative; don't pick (c) just because it's the most flattering.

#### Trial exclusion criteria (decide in Layer 2, lock before Layer 3)

This is where you decide which trials to exclude from Layer 3 comparison. **Document the criterion before looking at cross-session deltas — do not re-decide exclusions after seeing the comparison numbers** (that's "exclusion shopping", see drift patterns below).

- **Sensor failure trial**: `detect_hr_artifacts` flagged duration / total trial duration > 0.4 (a single trial may hold 100–160s of artifact even when `detect_hr_artifacts` itself only flags ~80s — the detector under-flags slow-onset baseline-stuck patterns). Or: mHR − sHR < 15 bpm in a context where the trial should be high-intensity.
- **Outlier trial**: max_HR ≥ 1 stdev below the trial-max-HR mean of the other working trials, **AND** speed/cadence consistent with neighbours (no external workload reduction). Confirm with subjective report when possible ("yeah I was looking at the view"). If max_HR is low but speed/cadence is also low, that's a genuine easy effort, not an outlier.
- **Cool-down / warm-up**: avg HR < 130 with declared intent.

Re-deciding after seeing Layer 3 numbers contaminates the comparison.

### Layer 3 — Cross-session Comparison (with confounder correction)

Only here do you compare to baseline. Use the authoritative metrics:

- **CC trial-2-3 mean** — most stable, fixed 2-trial average, ignores warm-up trial 1
- **CC back-half mean** — trials 3 and onwards, sensitive to fatigue accumulation
- **HR-grade-normalised pair** — pick the trial with closest avg HR to baseline trial 2, normalise its CC to baseline's grade. The most confounder-robust signal.

For each metric, report:

1. **Raw delta** (no correction)
2. **Confounder amplification** (grade penalty + duration penalty)
3. **Corrected delta** = raw + amplification
4. **Day-to-day noise floor** (≈ 5% of CC, typically ±1.5–2.0 points)

If `|corrected delta| < noise floor`, the result is "indistinguishable from noise" — not "improvement" or "regression".

#### Coefficient sensitivity is part of the uncertainty

The grade-coefficient (1.5 bpm/grade-%) and the cardiac-drift rate (default 7.5 bpm/min) are empirical defaults with literature ranges of roughly ±0.5 each. `compare_sessions` exposes this via `hr_normalised_range` (a tuple bracketing the HR-grade-normalised delta under coef ∈ {1.0, 1.5, 2.0}).

**Decision rule**: if `|corrected delta|` is smaller than the spread of `hr_normalised_range`, the correction itself isn't tight enough to declare a direction. Treat as "ambiguous". Only when both:

1. `|corrected delta| > noise floor`, AND
2. `|corrected delta| > spread of hr_normalised_range`

…can you defensibly speak of "directional change". Otherwise the apparent delta lives inside two independent uncertainty bands.

### Layer 4 — Take-home / Interpretation (bounded by training science)

The interpretive layer. **This is where most analyses go wrong** because the temptation is to declare improvement on any negative CC delta. Don't.

#### The conservative prior (default)

For any short-timeline delta (< 4 weeks between sessions, ≤ a handful of training stimuli in between), the prior is **"no change"**. Improvement is what you have to prove with affirmative evidence; *absence of contrary evidence is not evidence of improvement*. A delta you can't account for via confounders, noise, learning, or sensor doesn't promote to "improvement" — it stays as "unexplained, hold conservative".

Adopt this prior **before** running the time-axis check below; the prior is what the gate is enforcing.

#### Hard constraints from training science

- **Aerobic capacity (VO2max) adaptation**: 4–8 weeks for measurable change (5–10%). See: Bompa & Buzzichelli, *Periodization* (6th ed.); Seiler, "What is best practice for training intensity and duration distribution in endurance athletes?" *Int J Sports Physiol Perform* 5(3), 2010; Laursen & Buchheit (eds.), *Science and Application of HIIT*, 2019.
- **Cardiovascular adaptation (stroke volume, capillary density)**: weeks to months
- **Neuromuscular learning** (movement economy): days, but typically ±2–5%
- **Day-to-day noise**: ±5% on most metrics, including CC. Empirical observation across endurance training literature; Buchheit & Laursen call out HR-based metrics' day-to-day CV at 3–5% under controlled lab conditions (more in field).
- **Personal HRmax with n ≤ 2 observations**: ±5 bpm uncertainty (within day-to-day SD). Don't anchor zone boundaries on n=2 — flag as provisional until n ≥ 4 across varied conditions. A "new max HR" 5 bpm above the prior best, observed once, is noise; a "missed max HR" 5 bpm below the prior best, observed once, is also noise.

So if you see a -3 CC point delta after 6 days with 2 cardio sessions, the prior probability is **not** "real improvement". It's far more likely:

1. Confounders (duration, grade, rest structure)
2. Day-to-day noise
3. Neuromuscular learning effect (small, reversible)
4. Sensor artifacts in one of the trials

The interpretation should default to "no change" and require strong evidence to claim improvement. Strong evidence = corrected delta exceeds 2× noise floor on multiple independent metrics, **and** the timeline is consistent with the adaptation in question.

#### Time-axis sanity check (before writing any take-home)

Run this gate **before** writing your interpretation:

```
days_between_sessions = N
sessions_of_target_adaptation = M

For aerobic capacity:    requires N ≥ 28 (4 weeks) and M ≥ 8
For cardiovascular:      requires N ≥ 14 and M ≥ 6
For neuromuscular:       N ≥ 3 acceptable, expect ≤ 5% effect
For day-to-day variance: any N, any M, expect ≤ 5% effect
```

If your N and M are below the threshold for the adaptation you want to claim, the corresponding adaptation is **not available** as an explanation. The remaining candidates are noise, confounders, learning, or sensor — all of which default to "no real change in fitness".

Concrete: a -3 CC delta after 6 days with 2 cardio sessions cannot be attributed to aerobic capacity (timeline forbids), so the take-home cannot say "aerobic improvement". It must say "within-noise variation, possibly mild neuromuscular learning, awaiting confirmation across additional sessions".

This gate is the difference between honest analysis and confirmation-biased analysis.

#### What to write in this layer

- **Concise headline**: ✅ holding / ⏸️ unclear / ⬆️ improved / ⬇️ regressed
- **Each take-home with explicit caveat** (not just "improved" but "improved by X under Y assumptions")
- **Implications for next session/cycle**: with concrete protocol (time of day, readiness threshold, etc.)
- **Uncertainties listed explicitly**: parser caveats, n=1 limits, coefficient sensitivity

#### What to never write

- Generic "trending in the right direction" without numbers
- "Significant improvement" when n=1 (you can't claim significance from one comparison)
- Anything that requires aerobic adaptation in <2 weeks

## Agent review protocol

### Reviewer commitment rule

A review that ends in "let me know if you'd like me to fix these" or "do you want me to revise?" is a **failed review**. The reviewer's job is to commit a verdict, not to bounce the decision back to the author.

Every finding must end with one of three states:

- **pass**: lock in, no change required
- **warning**: document the caveat, then lock in
- **serious-issue**: revise — and the reviewer should propose the specific revision, not ask whether to revise

This applies equally to LLM-agent reviewers (where this failure mode is most common: the agent lists problems and ends with "happy to fix any of these") and to human reviewers (who do the same with "thoughts?"). When you're the reviewer, commit. When you're the author receiving a review, reject any output that punts the decision back.

### The brief

After locking each layer, send it to an independent reviewer (or LLM agent) with this brief:

> Independently review this {Layer N} report. Question every claim. The prior is that I'm overstating the signal. For each finding, give: pass / warning / serious-issue, and a one-line justification. Don't endorse — challenge. **End every finding with a committed verdict; do not ask whether I want you to revise.**

What to provide the reviewer:

1. **Necessary context** (true facts the reviewer can't know): the user's per-session lap-button habit, the trial count, any subjective reports, the FIT path so they can verify
2. **The layer's claims** (the report itself)
3. **Specific challenge questions** (e.g. "is this metric fair given the sample sizes differ?")

Then **act on the review**:

- If finding is "serious-issue", revise. Don't argue.
- If finding is "warning", document the caveat.
- If finding is "pass", lock in.

Iteration cap: 2 rounds per layer. If you can't lock by round 2, the data is inconclusive — say so in Layer 4 and stop.

### Multi-angle review (run reviewers in parallel, not series)

A single reviewer can only catch what they're looking for. Send the same artifact to **multiple reviewers in parallel**, each with a distinct lens:

| Lens | What it catches | Sweep targets |
|------|-----------------|---------------|
| **PII / privacy** | identifying details that survive code-only grep | `*.py` + `*.md` + validation tables / docstring examples / magic-number comments / cross-document references / locale tells (timezone names, language tells) |
| **Domain methodology** | training-science violations, missed confounders, misapplied formulas | docs claims + per-metric formulas + decision rules + sample sizes |
| **Code / API consistency** | imports that don't exist, docstring claims that don't match code, broken examples, dataclass field-order issues, syntax errors | docstring examples vs `__all__` exports + signatures vs documented params + dataclass defaults order + ast-parse all `*.py` |

In our experience, each lens caught issues invisible to the others (e.g. a docs reviewer caught hand-marked timestamps in a validation table; the code reviewer caught a docstring referencing a non-existent function; the PII reviewer caught a date that the domain reviewer didn't even see as identifying). **Run them concurrently — don't iterate serially**. The cost is low; the catches are independent.

#### Integrating findings across lenses

Three rules for combining results:

1. **A finding flagged by one reviewer but not the others is still real**. Different lenses see different things. Do not down-weight a single-lens finding because only one reviewer caught it. List it as **must-resolve** and don't demote to "polish" just because the other two reviewers didn't flag it.

2. **Conflicting recommendations across lenses go to author tie-break with explicit reasoning**. If the code lens says "exclude this trial" and the methodology lens says "include with caveat", neither auto-wins — the author commits a choice and documents *why one lens's framing applies more in this context*. Don't pick the simpler option; pick the one whose lens is doing the right work for the actual question.

3. **Concordant shrinkage across lenses is the strongest convergence signal**. If all three lenses independently produce findings that narrow your claim in the same direction, you've crossed the bar where the original claim was wrong by a wide margin. Lock the most conservative version that any lens produced (see Conclusion convergence test below) — and unlike single-lens shrinkage, you don't need to wait three rounds; concordant cross-lens shrinkage in **one** round is sufficient.

## Common drift patterns to watch for

- **"Improvement" reframed each round**: from "+21% speed" → "+14-19% speed" → "robust improvement" → "trend". Each rephrasing softens the claim without rebasing the underlying calculation. **Fix**: every claim must have an exact number with explicit confounder accounting.
- **Outlier exclusion shopping**: "exclude trial 5 → -4.71" vs "include trial 5 → -3.08". **Fix**: report both, document exclusion criteria once, don't re-decide.
- **n=1 over-generalisation**: one session showing "high stress + good performance" → "ANS perturbation doesn't affect performance". **Fix**: n=1 observations are observations, not generalisations.

### Conclusion convergence test

When your conclusion shrinks across review rounds — e.g. "+21% improvement" → "+14-19%" → "modest improvement" → "within noise" — that monotonic deflation is itself diagnostic: **the original claim was overstated by approximately the total amount it shrank**.

The fix is not to settle on the *average* of the rounds, nor on the most recent round, but on **the most conservative conclusion that any round produced**. Reasoning: each shrinking round was driven by a real challenge from the reviewer; if you stop short of the bottom, you're still keeping some unchallenged assertion that the next round would have caught.

Practical rule: if you've gone through ≥ 3 review rounds and each round narrowed the claim, lock the most conservative version and stop iterating. The data isn't supporting a stronger claim.

**Cross-lens shortcut**: when [Multi-angle review](#multi-angle-review-run-reviewers-in-parallel-not-series) is in use, you don't need to wait for ≥ 3 rounds — if the three lenses (PII / domain / code) each independently produce shrinkage in the same direction within a single round, that concordance is equivalent evidence to a 3-round serial deflation. Lock the most conservative version immediately.

## Iterative fix workflow (when reviewers find many issues)

When a review surfaces 15+ findings (mix of critical, completeness gaps, API issues, polish), don't try to fix everything in one pass. Use phased correction with review gates:

| Phase | Scope | What goes here |
|-------|-------|----------------|
| **A** | Critical / blocking | PII leaks, broken imports, factually wrong code, anything that prevents publication or breaks usage |
| **B** | Completeness gaps | Missing concepts, undocumented edge cases, failure modes the user reported but the docs don't mention |
| **C** | API improvements | New fields surfacing internal state, additional reporting, signal-to-noise improvements |
| **D** | Documentation polish | Cross-links, citations, deprecated syntax, naming consistency |

> **Analysis-only context note**: in pure-analysis settings (no code to revise — e.g. a finished training-analysis report), Phase C usually collapses into Phase D. Don't force a 4-phase split on a 2-phase reality; the structure exists to keep critical from being delayed by polish, not to manufacture phases.

Rules:

1. **Each phase has its own review pass** — don't bundle. Phase A's fixes should be independently reviewed before Phase B starts. This catches regressions and gives each phase a clean lock. **Each phase's review pass should itself use [Multi-angle review](#multi-angle-review-run-reviewers-in-parallel-not-series)** — single-lens review at phase boundaries reproduces the original problem.
2. **Don't escalate scope mid-phase**. If during Phase A you notice something that looks like Phase C work, write it down and do it in Phase C. Mixing scope produces confused diffs and incomplete reviews.
3. **The review of phase N can surface findings for phase N+1**. That's expected. Add them to N+1's task list, don't sneak them into N.
4. **Phase D may have sub-rounds**. Documentation polish reviews often surface additional polish (e.g. fixing one cross-link reveals two others that should also be added). Cap at 2 sub-rounds.

### Phase-end gate criteria (when is a phase "done")

A phase is locked when **all** of these hold:

- Every finding in the phase's task list is resolved (pass / warning-with-caveat-documented / serious-issue-revised), with no "let me know if you want me to fix" outputs (see Reviewer commitment rule above).
- The phase's review pass produces zero new findings of severity ≥ that phase's threshold (e.g. Phase A is locked when its review surfaces no further critical issues — completeness gaps belong to Phase B).
- Cross-link audit: any new section added in this phase is referenced from at least one other section that should point to it (orphaned sections get re-discovered and contradicted later).

If the phase's review surfaces findings *of the phase's own severity* (e.g. Phase A's review finds another critical), the phase isn't done — re-fix and re-review. If it surfaces lower-severity findings, those go to subsequent phases as planned.

This is the workflow that turned 23 review findings (across 3 reviewers in 3 angles) into a clean release without cascading regressions.

## Comparison sequencing — lock A before looking at B

When comparing session A to session B, **lock A's standalone Layer 1 and Layer 2 before looking at B at all**. Specifically:

- Run Layer 1 on A → review → lock
- Run Layer 2 on A → review → lock
- *Only then* fetch B and start its Layer 1 / 2

Reason: if you analyse A and B in parallel (or worse, look at B first because it's the "interesting" session), A's Layer 1-2 conclusions get unconsciously edited to support whatever narrative B is going to need. The contamination is hard to detect because it happens at the framing level — you'll write A's "trial 5 was an outlier" note differently if you've already seen B's matching trial.

The locking sequence forces A to be analysed *as if B didn't exist*. When B is later analysed and the comparison surprises you (e.g. A's trial-5 outlier status looks different in light of B), that surprise is **information** — preserved precisely because A wasn't pre-shaped to absorb it.

This applies equally to (a) cross-session comparisons in this framework and (b) any "compare X to Y" workflow elsewhere — code review of two implementations, A/B test results, two competing designs. Lock the standalone analyses first.

## When two independent runs disagree

Sometimes the same algorithm, run twice on the same input, produces different outputs (random initialisation, non-determinism in upstream tools, two reviewers reaching different conclusions on the same data). The instinct to **average them is wrong**.

Protocol:

1. **Reproduce both runs**. Confirm the disagreement is real and not a transcription error.
2. **Isolate the divergent step**. Walk both runs until you find the first decision where they diverged. The disagreement lives there.
3. **Find an external ground truth at that step** — see [the reverse-engineering protocol](authoritative-segmentation.md#the-general-protocol-reverse-engineering-algorithm-validation). Hand-mark the input, consult the source data (FIT vs Garmin server), or request a third independent run from a different process.
4. **Adopt the run consistent with ground truth**; the other run has a bug, a non-determinism source you can document, or a mistaken assumption.
5. **If no ground truth is reachable**, the result is genuinely ambiguous — report both, do not collapse to a single number, and document the irreducible uncertainty.

Averaging discordant results actively hides bugs: the bug stays in the codebase, masked by a "it's probably about right" output. Don't.

## Noise floor: `n_set_boundaries_clamped`

**Metric.** `StrengthSession.n_set_boundaries_clamped` (introduced v0.2.1).

**Ground truth.** Every fractional-duration adjacent-set boundary on a device that truncates `set.start_time` to integer seconds. For a session with `N - 1` adjacent boundaries (between `N` sets) where `K` boundaries are fractional-duration (i.e. `set.duration` is not an integer second), the expected clamp count is `K`.

**Noise floor.** `0`. The counter is incremented only when an actual sub-second clamp occurs; integer-aligned boundaries do not increment it (verified by test `test_back_to_back_integer_boundary_does_not_clamp` in the v0.2.1 test plan).

**Upper bound (FIT-spec derivation).** Every inversion that increments the counter is strictly less than 1.0 s. Integer-second truncation cannot lose `>= 1` s (see `parse_strength_fit.INVERSION_TOLERANCE_S`). An inversion of `>= 1.0 s` raises `ValueError` instead, distinguishing the truncation regime from the device-corruption regime.

**Calibration.** `n=5` vivoactive 5 sessions, single user. The CHANGELOG v0.2.1 "Empirical inversion distribution" sub-bullet records per-session clamp counts and max inversion observed. If across `n>=10` sessions the distribution shows a long tail near 0.99 s, the real-overlap floor assumption is fragile and v0.3 must recalibrate.

**Cross-reference.** `docs/confounders.md` § 10 (the domain confounder catalogue entry); `parse_strength_fit.py` module docstring (conclusion-first version of this entry).

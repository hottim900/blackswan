# Evolution Proposals: Five Directions for blackswan

Companion document to [`related-work.md`](related-work.md), which surveyed the open-source ecosystem and identified five evolution directions. Each direction below was produced as a separate concrete proposal by a specialist agent, then synthesised here with cross-direction interactions and a recommended sequence.

> **STATUS (post v0.4.0).** The priority table below is **ARCHIVED — superseded by issue-driven priority**. The audience-reframe at v0.4.0 office-hours established that blackswan's audience is the author (dogfooder); the only hard demand evidence in the backlog points to issue #1 P3, which the synthesis did not address. v0.4.0 shipped issue #1 P3 (warning-only branch) + D1 minimal (README tagline + pyproject keywords). Direction-level status tags appear inline on each direction section below. The new gate for shipping D1-full / D3 / D4 / D5 is **a dogfooding-derived GitHub issue** (per P7 in the v0.4.0 design), not the synthesis's effort-tier table.

## Synthesis: priority and sequence

> ⚠ **ARCHIVED.** The table below reflects the pre-v0.4.0 synthesis priority. It was superseded by the v0.4.0 issue-driven plan on the same day it was written. Kept for historical context — do not use as a current roadmap.

| Tier | Direction | Effort | When | Why |
|---|---|---|---|---|
| **P1** | D1 — vocabulary alignment (README tagline edit only) | 30 min | **Now** | Zero risk, zero dependency, single line. Captures most of the discovery value. |
| **P1** | D1 (full) + D3 — Aerobic Decoupling module | 11.5 h | This iteration | Ship together. D3's discoverability depends on D1's vocabulary alignment. v0.4.0 release. |
| **P2** | D4 — CLI MVP (`compare` only) | 11.5 h | Next iteration | Lowers the evaluation barrier described in the field-survey. Ship before D2 to avoid CLI-flag contract drift during refactor. v0.5.0 release. |
| **P3** | D5 v0.1 — synthetic-only benchmark on Zenodo | 5–7 days | This quarter, parallel track | Separate repo (`blackswan-bench/`), no blackswan code dependency. Plants citable-DOI position before any competitor. |
| **P4** | D2 — confounder framework abstraction | 11 h (or 5 h scoped) | **Defer** | Only two use cases today; CLAUDE.md "rule of three" applies. Trigger when a third use case (e.g. NP comparison or sleep efficiency) is in active development. |

**Strategic one-liner** (archived): ship D1+D3 to plant the flag in the field's natural vocabulary; ship D4 to lower the evaluation barrier; ship D5 v0.1 to claim the benchmark position; defer D2 until forced by genuine code duplication.

**Cross-direction interactions**:

- **D1 → D3**: D3 is a new module whose primary value is discoverability via "aerobic decoupling" search vocabulary. D1's README tagline edit is the highest-leverage discovery move. Ship D1's tagline before D3 lands.
- **D3 → D2 trigger**: D3 adds a new metric whose cross-session comparison naturally fits the same confounder pattern as cardiac cost. If D3 ships, the cross-session aerobic-decoupling comparator may become the third use case that triggers Rule of Three for D2.
- **D4 ← cc_metrics stability**: D4 freezes a CLI flag contract derived from `compare_sessions()` arguments. If D2 refactors `cc_metrics` first, D4's contract drifts. Land D4 before D2.
- **D5 ← independence**: D5 ships in a sibling repo with frozen synthetic data. It doesn't depend on any blackswan API change and can run in a parallel track without blocking D1/D3/D4.

---

## Direction 1 — Industry-vocabulary alignment

> **STATUS (v0.4.0).** D1 minimal — README tagline + pyproject keywords (6 entries: `aerobic-decoupling, pw-hr, vam, heart-rate-decoupling, cardiac-drift, running-power`) — **SHIPPED**. D1 full (docstring updates, glossary, methodology table, confounders-table additions, PyPI `Topic :: Scientific/Engineering :: Medical Science Apps.` classifier) is **DEFERRED — awaiting dogfooding signal**. Trigger: a GitHub issue from real dogfooding use that the missing D1-full content would have prevented.

**Goal**: cross-reference blackswan's private terms (Cardiac Cost, uphill segment) with industry terms (Pw:Hr / Aerobic Decoupling, VAM) so the project surfaces in keyword searches.

**Effort**: 2.5 hours total. **Quick win**: 30 minutes for the README tagline edit alone.

### Concrete edits

**README.md tagline (line 3)** — append to existing line:

> A pipeline for **Cardiac Cost (CC) analysis** of Garmin FIT data — built around uphill interval training, with rigorous cross-day comparison that survives confounder scrutiny. **CC is an HR-only proxy for the Pw:Hr / Aerobic Decoupling family used by sauce4strava and GoldenCheetah; uphill segments are auto-detected on the VAM (climbing speed) axis.**

This single edit puts `Aerobic Decoupling`, `Pw:Hr`, `sauce4strava`, `VAM` into GitHub's first-paragraph index weighting where it matters most.

**README.md** — add a new subsection between line 5 and line 7 (between blockquote and "Why this exists") explaining the HR-only relationship in three sentences. Defends the niche while flagging the alias.

**README.md methodology table (lines 219–224)** — add an "Industry analogue" column. Layer 3 row gains "Pw:Hr / Aerobic Decoupling delta + correction"; Layer 1 gains "VAM, splits, time-in-zones".

**README.md confounders table (lines 240–249)** — append `Cardiac drift (industry: HR-only Aerobic Decoupling) | 5–10 bpm/min | (Δdur ÷ 60) × drift`.

**pyproject.toml line 9** — add six keywords to the existing six:

```toml
keywords = ["garmin", "fit", "cardiac-cost", "interval-training", "training-analysis", "uphill",
            "aerobic-decoupling", "pw-hr", "vam", "heart-rate-decoupling", "cardiac-drift", "running-power"]
```

Add classifier `"Topic :: Scientific/Engineering :: Medical Science Apps."` for PyPI category browse.

**Docstrings** — touch only two modules:

- `cc_metrics.py` module docstring: "Cardiac Cost (CC) trial metrics + cross-session confounder correction. CC ≈ HR-only proxy for Pw:Hr / Aerobic Decoupling (sauce4strava, GoldenCheetah)."
- `segment_uphill.py` module docstring: "Authoritative uphill segmentation (alt min → alt max). Industry analogue: VAM-segment auto-detection."

Skip parsers, sleep modules, artifact detectors — no industry analogue, forced cross-references add noise.

**New `docs/glossary.md`** (~80 lines):

1. blackswan ↔ industry term table (expanded from related-work.md §1)
2. Why we kept private terms (CC is HR-only and watch-native; Pw:Hr implies a power meter the user does not have)
3. Where blackswan has no industry equivalent: confounder-corrected delta, noise floor as first-class output, EARLY_DEFICIT_LATE_NORMAL, alt min → alt max segmentation. Reinforces the moat.

### Tone-drift mitigation

Three rules to preserve blackswan's academic voice:

- Aliases appear once per surface, then revert to blackswan vocabulary
- Always disambiguate "HR-only" — never let users believe blackswan reads power
- Industry vocabulary enters as nouns (`Pw:Hr`, `VAM`), never as marketing adjectives

---

## Direction 2 — Confounder correction as a generic framework

**Goal**: extract the cross-session comparison pattern from `cc_metrics.py` so it works for arbitrary metrics (NP, strength HR, sleep efficiency).

**Decision**: **Defer until a third concrete use case is active, not hypothetical.**

**Justification**: CLAUDE.md states "three similar lines is better than a premature abstraction." Today there are exactly two implementations: `cc_metrics.py` and `strength_metrics.py`. The Rule of Three says n=3 is the trigger, not n=2. Their internals diverge significantly — cardio uses mean-of-trial slicing; strength uses per-set greedy matching with exact-slot and exercise-level fallback tiers. A generic `compare()` that subsumes both without distorting either is non-trivial to design correctly.

The correct trigger: when a third module (`sleep_metrics.py`, `np_metrics.py`, or similar) is being written and its author is about to duplicate the exclusion-filtering and delta-accumulation logic for the third time, **then** extract `_compare.py` from actual code, not designed speculatively.

### If forced: minimum scoped extraction (~5 hours)

Extract only:

- `ExclusionSet(baseline: frozenset[int], recent: frozenset[int])` — immutable dataclass that prevents mutation after the Layer 2 lock point. This single piece is genuinely cross-cutting and currently not encoded at all.
- The 10-15 lines of delta-accumulation arithmetic (raw_delta = corrected_delta + Σ penalties).

Leave metric functions, confounder formulas, report types, and noise-floor formulas in their current modules. The abstraction surface stays narrow enough that a wrong guess on the generic type can be corrected without breaking either use case.

### If forced: full design sketch (~11 hours)

Protocol-based generic API:

```python
# src/blackswan/_compare.py

T = TypeVar("T")  # the per-trial/set/unit type

class Confounder(Protocol[T]):
    name: str
    def penalty(self, baseline: list[T], recent: list[T]) -> float: ...

@dataclass(frozen=True)
class ExclusionSet:
    baseline: frozenset[int]
    recent: frozenset[int]

@dataclass
class ComparisonResult(Generic[T]):
    raw_delta: float
    penalty_breakdown: dict[str, float]
    corrected_delta: float
    noise_floor: float | None

def compare(
    baseline_units: list[T],
    recent_units: list[T],
    *,
    metric_fn: Callable[[list[T]], float],
    confounders: list[Confounder[T]],
    exclusions: ExclusionSet,
    noise_floor_fn: Callable[[list[T]], float] | None = None,
) -> ComparisonResult[T]: ...
```

`cc_metrics.compare_sessions` keeps its public signature; internally constructs `GradeConfounder`, `DurationConfounder`, calls `_compare.compare()`, wraps result in `ComparisonReport` (which keeps CC-specific fields: `hr_normalised_delta`, `cc_noise_floor`, `summary()`). Same for `strength_metrics.compare_strength_sessions_from_stats`.

### Risks

- **Premature abstraction with n=2**: the generic `list[T]` may not survive the third use case if "unit" turns out to mean something materially different.
- **Protocol typing fights**: generic `Protocol[T]` with concrete invariant dataclasses is brittle in mypy/pyright. Developer-experience tax.
- **Worked-example clarity loss**: `cc_metrics.py` is currently self-contained and readable as a methodology tutorial. After migration, readers must follow `_compare.py` to understand the delta arithmetic.

### What stays cardiac-cost-specific permanently

- `TrialStats` and its `kmh > 0` invariant
- `compute_confounders()` defaults (grade coefficient, drift rate — empirical, cardio-specific)
- `cc_trial_2_3_mean()` and `cc_back_half_mean()` (CC-specific slicing)
- HR-grade-normalised speed comparison (entirely CC-specific, no analog elsewhere)
- The 5%-of-baseline-mean noise floor (calibrated on uphill intervals; explicitly not transferable to strength per `docs/confounders.md` §9)

---

## Direction 3 — Aerobic Decoupling (Pw:Hr) module

> **STATUS (v0.4.0).** **DEFERRED — awaiting dogfooding signal.** Trigger: a GitHub issue filed from real dogfooding use where the missing Aerobic Decoupling module blocked the author from answering a training-analysis question they actually had on their own data. Until such an issue exists, this is hypothetical-audience work and v0.4.0's P7 deferral rule applies.

**Goal**: provide the standard sport-science cardiac-drift measure as a first-class output, fillling the "no Python implementation of HR-only Aerobic Decoupling" gap.

**Effort**: 9 hours.

**Decision**: **Ship before D2, simultaneously with D1.** Net-new module (no API breakage risk); discoverability gap is time-sensitive.

### Module location

`src/blackswan/aerobic_decoupling.py`. The name `aerobic_decoupling` is the academic search term. Reject `pwhr.py` (implies power) and `cardiac_drift.py` (collides with internal `cc_metrics` concept).

### Public API

```python
def trial_decoupling(
    records: list[dict],
    t_start: datetime,
    t_end: datetime,
    split: Literal["time", "distance"] = "time",
    speed_field: Literal["kmh", "ms"] = "kmh",
) -> DecouplingResult | None: ...

def session_decoupling(
    trials: list[DecouplingResult],
    aggregate: Literal["median", "mean", "per_trial"] = "median",
) -> SessionDecoupling | None: ...
```

`DecouplingResult` (frozen dataclass): `decoupling_pct`, `first_ratio`, `second_ratio`, `first_half_dur`, `second_half_dur`, `split_method`, `n_first`, `n_second`.

`SessionDecoupling`: aggregate value + per-trial vector + `provisional` flag (true if n<4 trials).

**Calling convention** matches `stats_for_window` in `segment_uphill.py:70-109` — takes raw `records` plus a `(t_start, t_end)` window. Caller may source the window from `find_uphill_trials_in_lap` but is not required to. The function works on arbitrary windows (tempo runs, flat repeats).

**Cross-session comparison is NOT in this module.** A `compare_decoupling_sessions` analog of `compare_sessions` would belong in D2's generic framework. Keep this module focused on the per-trial/per-session computation; defer cross-session to D2.

**Dependency promotion**: `_records_to_pts` in `segment_uphill.py:51-67` is currently underscore-prefixed (private). Promote to `__all__` so `aerobic_decoupling.py` reuses it instead of duplicating normalisation. Already used by three internal callers; promotion has zero cost.

### Edge cases (must all return None, never silently default)

1. Trial < 60 seconds → halves are physiologically noise-dominated
2. < 5 valid speed+HR pairs in either half (FIT speed sentinel = 65.535 m/s filtered)
3. HR sensor artifact during second half (caller must run `detect_hr_artifacts` first; out of scope here)
4. Activity pause → time-split midpoint lands in a gap
5. Flat segment → speed near-constant, both ratios converge, decoupling reads ~0% even with HR drift (HR-only proxy limitation; document explicitly)
6. `first_half_ratio ≤ 0` → guard before division
7. Single-trial session → return SessionDecoupling with `provisional = True` (matches HRmax with n≤2 pattern in `confounders.md:112`)

### Validation

- **Numerical**: synthetic time series with known 8% drift → expect ~8% output; flat synthetic → expect ~0%. Hand-calculated reference values, deterministic unit tests.
- **Physiological plausibility**: hand-marked agreement table against user subjective effort reports (same protocol as `docs/authoritative-segmentation.md`). Standard is directional agreement, not numeric precision — there is no external oracle for HR-only decoupling on uphill trails.

### Documentation

New file `docs/aerobic-decoupling.md`. Must address:

- Formula derivation, half-split convention
- Explicit statement: "this implementation uses speed as a proxy for power — comparable to Pw:Hr decoupling only when speed is a good proxy for external workload, which is truest on uniform-grade climbs and least true on flat terrain"
- Reference thresholds (<5%, 5-10%, >10%) with caveat that thresholds come from power-based literature; transfer to HR-only is not empirically validated
- Confounder summary (short trial → less drift → lower apparent decoupling)

### Naming caveat

Public API uses `trial_decoupling` / `session_decoupling`. Module is `aerobic_decoupling`. **No public function uses `pwhr`** — that name is misleading for users without power meters.

The module docstring includes the alias string "Aerobic Decoupling (also: Pw:Hr decoupling, cardiac drift ratio, first-half / second-half decoupling)" so grep and docs search surface it.

### Risks

- **Small-n high variance**: 90s trial, 45s halves; ±3 bpm noise event swings decoupling 2-3%. Users will see "well-paced 6%" vs "hard 4%" and conclude metric is broken. Mitigation: `provisional` flag at n<4, prominent noise-floor reporting in `summary()`.
- **Negative-decoupling on negative-split**: physically valid, counterintuitive; users will report bugs. Mitigation: docstring explicitly explains.
- **Confusion with power-based output**: users running same session in sauce4strava (Strava-uploaded) will see different numbers and file bugs. Mitigation: prominent docstring warning + link to `docs/aerobic-decoupling.md`.

---

## Direction 4 — CLI

> **STATUS (v0.4.0).** **DEFERRED — awaiting dogfooding signal.** Trigger: a GitHub issue from the author hitting Python-boilerplate friction during their own routine analysis (i.e. the author writes the same 10-line `compare_strength_sessions(...)` invocation enough times that they file the issue). Until then, the existing Python API is the primary surface and v0.4.0's P7 deferral rule applies.

**Goal**: lower the evaluation barrier — let new users run `blackswan compare baseline.fit recent.fit` instead of writing Python.

**Effort**: 11.5 hours for `compare`-only MVP. 18.5 hours for full surface.

**Decision**: **Ship `compare`-only MVP immediately.** Defer the full subcommand surface and `compare-strength`.

### Entry point

Single binary `blackswan` with subcommands. Multiple binaries (`blackswan-compare`, `blackswan-parse`) impose a discovery problem and are only justified when subcommands come from separate packages.

```toml
# pyproject.toml
[project.scripts]
blackswan = "blackswan._cli:main"
```

`_cli.py` is internal (underscore prefix, not in `__all__`).

### Subcommand surface

| Subcommand | Disposition | Reason |
|---|---|---|
| `compare` | **MVP v0.1** | The headline feature |
| `compare-strength` | Defer to v0.2 | Experimental (n=5, vivoactive 5 only); shipping it conflates "working CLI" with "experimental feature" |
| `parse-bulk` | Include in v0.2 | `batch_extract_fits.main()` already argparse-complete; thin wrapper |
| `parse-daily` | Include in v0.2 | Currently uses bare `sys.argv`; needs argparse cleanup anyway |
| `sleep-official`, `daily-summary` | Defer to v0.2 | Pipeline plumbing; existing users already invoke as modules |
| `detect-artifacts` | Defer | No `__main__` block today; output format contract not specified |

### `compare` subcommand spec

```bash
blackswan compare BASELINE.fit RECENT.fit \
    --baseline-laps 1,2,3,4 \
    --recent-laps 2,3,4,5,6,7 \
    [--exclude-recent 0,4] \
    [--exclude-baseline INDEX,...] \
    [--grade-coef 1.5] \
    [--drift FLOAT] \
    [--output {text,json}] \
    [--out PATH] \
    [--overrides PATH]
```

- **FIT paths positional** (baseline first, recent second). Communicates comparison order; shorter shell one-liners.
- **Lap indices comma-separated** (`1,2,3,4`). Avoids the `nargs="+"` ambiguity with digit-prefix flags.
- **Exclusions comma-separated** (`--exclude-recent 0,4`). Pre-locked at Layer 2.
- **Output formats**: `text` (default; prints `report.summary()`) or `json` (full `ComparisonReport`). No CSV — output is a scalar report.
- **Confounder corrections always on**. Cannot be disabled — disabling produces the raw delta which CLAUDE.md explicitly warns against as a decision signal. Users wanting raw read JSON's `raw_delta` field.
- **`--grade-coef` range guard**: error outside [0.5, 3.0]; advisory outside [1.0, 2.0] (literature range).
- **`--overrides PATH`** for pre-existing Layer 2 notes JSON. Conflicts with `--exclude-recent` → clear error.

### CLI library

**argparse**. Already used in `batch_extract_fits` and `build_sleep_official`. Adding click/typer/pydantic introduces dependencies a v0.3.1-alpha project does not need. fire is wrong fit (project has strong opinions about flag shape).

### Migration of existing scripts

**Mixed approach, fully backwards-compatible.** `python -m blackswan.parse_bulk_export` keeps working. `blackswan parse-bulk` calls the same `main()`. `parse_bulk_export` and `parse_daily_fit` use bare `sys.argv` today and need argparse cleanup as part of the work — a forced positive cleanup.

### Methodology enforcement in help text

The CLI is a methodology surface, not a thin shell wrapper. Specific behaviours:

- `--exclude-recent` prints a stderr warning **on every invocation** (not suppressible): `"[warn] Exclusion set passed. This must have been decided in Layer 2 before running compare. If you are re-running with different exclusions after seeing the delta, that is exclusion shopping (see docs/methodology.md)."` Persistent low-friction reminder.
- Error messages are specific (file path + index, not tracebacks). `--verbose` enables full tracebacks for debugging.

### Hard exclusions from CLI scope

- **No interactive prompts** — batch scripts cannot have stdin blocked
- **No network calls** — fully offline; no Garmin Connect API, no telemetry, no update checks
- **No `--plot` / `--chart`** — that is the GUI-ambition trap from related-work.md
- **No auto-discover-work-laps** — silently amplifies the exclusion-shopping problem
- **No interactive wizard mode**

### Risks

- **API contract freeze before library stable**: README warns "API may still change." If `compare_sessions` signature shifts, CLI flags must shift. Mitigation: mark all flags as subject to change in v0.1 help text; do not publish to PyPI until v1.0.
- **Lap-index discovery gap**: CLI requires user to know lap indices, which itself requires inspecting the FIT. Mitigation: a future `blackswan inspect FIT` subcommand prints lap numbers (deferred to v0.3).
- **argparse subparser default behaviour**: `add_subparsers` silently exits 0 with no output if no subcommand is given. Mitigation: `subparsers.required = True` and a custom error handler.

### Why ship MVP not full surface

The `compare` subcommand is the only thing that closes the barrier described in the problem statement — someone who finds blackswan via README can run one command and see the headline output. The other subcommands (`parse-bulk`, `parse-daily`, `sleep-official`) provide pipeline plumbing that current users already invoke as modules and that new evaluators do not need in the first encounter.

---

## Direction 5 — Public benchmark dataset

> **STATUS (v0.4.0).** **DEFERRED — awaiting dogfooding signal.** Trigger: a third-party project (or the author's separate analysis script) re-implementing cardiac-cost / aerobic-decoupling against blackswan's outputs would mark the moment a benchmark has actual users to validate. Until that exists, a benchmark in a sibling repo would be solving a hypothetical-user problem. v0.4.0's P7 deferral rule applies.

**Goal**: a citable benchmark for cardiac-cost / aerobic-decoupling implementations — fixed test corpus + ground-truth + evaluation harness.

**Effort**: 5–7 working days for v0.1 MVP (synthetic-only, Zenodo DOI, harness, baseline).

**Decision**: **Ship v0.1 MVP this quarter as a sibling repo `blackswan-bench/`.** Defer real opt-in data to v1; defer leaderboard to v2 if traction warrants.

### What is in v0.1

`blackswan-bench v0.1`: a benchmark for cardiac-cost / aerobic-decoupling implementations — not user training data.

- **8 synthetic uphill-trial sessions** (4 baseline + 4 recent pairs, two distinct user personas) covering: clean signal, HR sensor failure trial, mid-session outlier trial, grade confounder, duration confounder, rest-structure confounder, walk-back-no-stop pattern, intermediate-peak climb.
- **0 real FITs in v0.1**.
- **Ground-truth annotations** (one JSON sidecar per FIT):
  - Trial boundaries: `[(t_start_unix, t_end_unix, label)]` where `label ∈ {work, warmup, cooldown, sensor_fail, outlier}`
  - Per-trial canonical CC value (computed from synthesis spec — the synth IS ground truth)
  - Per-trial confounders: `grade_pct`, `duration_s`, `expected_drift_bpm`
  - Sensor-artifact flag ranges
- **Three evaluation tasks**:
  - **T1_segment**: given records+laps, return trial windows. Score: per-trial Δstart, Δend (seconds).
  - **T2_cc**: given trial windows, return per-trial CC. Score: max |ΔCC|.
  - **T3_compare**: given baseline+recent FIT pair, return corrected CC delta. Score: |Δcorrected − ground_truth_corrected| vs synthesised noise floor.

### Synthetic vs real trade-off

**100% synthetic in v0.1, opt-in real in v1, never required.**

The synth pattern in `examples/_strength_fit_synth.py` already produces byte-deterministic FITs with the FIT-spec dev-mode sentinel (manufacturer=255). Sufficient to express every confounder. Real data adds two costs v0.1 cannot afford: (a) PII review burden per file, (b) loss of ground truth — real trials have *latent* CC values, not *known* ones.

### Hosting

- **GitHub** (`hottim900/blackswan-bench`): primary dev surface. Synthetic FITs <100 KB each — fit comfortably in git.
- **Zenodo release on each tagged version**: free DOI, GitHub-Zenodo auto-publish on tag. Citable. Matches GoldenCheetah/OpenData precedent (DOI 10.17605/OSF.IO/6HFPZ).
- **Not OSF** — redundant given Zenodo + GitHub; only worth it if a collaborating academic group prefers OSF workflow.
- **Not HuggingFace Datasets** — over-targeted at NLP/CV; FIT bytes don't fit its abstractions. Skip until v2 if ever.
- **Not GitHub Releases alone** — no DOI, no academic legibility.

### Repo layout

Sibling repo, **not in-tree**. Reasons: dataset versioning decoupled from code releases; license differences (CC0 data, MIT code) become local; `blackswan` stays a library while `blackswan-bench` becomes the benchmark.

```
blackswan-bench/
├── README.md
├── CITATION.cff
├── LICENSE-DATA              # CC0-1.0 for FITs+annotations
├── LICENSE-CODE              # MIT for harness
├── DATASHEET.md              # provenance, demographics, known biases
├── data/v0.1/synthetic/
│   ├── 001_clean_baseline.fit
│   ├── 001_clean_recent.fit
│   ├── 001_clean_baseline.gt.json
│   └── ... (8 sessions × {fit, gt.json})
│   └── manifest.json         # fit→gt mapping, sha256 per file
├── harness/
│   ├── evaluate.py           # public entry
│   ├── tasks.py              # T1/T2/T3
│   ├── baselines/blackswan_baseline.py
│   └── synth/builder.py      # vendored from blackswan/examples
└── tests/
```

### Evaluation harness

```python
def evaluate(
    implementation: Callable[[Path, Path | None], dict],
    dataset_dir: Path,
    tasks: Iterable[str] = ("T1_segment", "T2_cc", "T3_compare"),
) -> BenchReport: ...
```

`implementation` returns dict per session (`trials`, `cc_per_trial`, `corrected_delta`). `BenchReport` carries: per-task aggregate (mean, p95, max), per-session diff table, pass/fail vs noise-floor decision rule from `docs/authoritative-segmentation.md`. Ship `blackswan_baseline.py` that calls current blackswan API — should pass everything by construction. That is the harness self-test.

### Versioning strategy

**Frozen dataset versions, rolling harness.** Once v0.1 is on Zenodo, those FITs and ground-truth files never change — fixes go via v0.2, v0.3 (each new DOI). Harness code evolves continuously. Contract: `evaluate(impl, "v0.1")` always reproduces v0.1 numbers regardless of harness version. PhysioNet pattern: data frozen, code rolling.

### PII pipeline (for v1 opt-in real data only — not v0.1)

blackswan's existing PII discipline prevents *committing* real data. A public release needs an outbound de-identification stage that does not yet exist:

- **Date shifting**: subtract per-session random N-day offset; preserve within-session relative gaps; encode as 2000-01-01 + offset
- **Geographic blurring**: strip `position_lat`/`position_long` from `record_mesgs` entirely; keep `altitude` and `distance` (segmentation only needs these)
- **Device fingerprint stripping**: rewrite `manufacturer=255`, `serial_number=0`, `garmin_product=0`; strip `device_info_mesgs` beyond the local watch
- **Cross-file join attack** (CLAUDE.md flags this): include only one session-pair per anonymised donor; no multi-session timelines
- **HR quantisation**: optionally round to 5-bpm bins to defeat HR-fingerprinting

One script (`scripts/deidentify.py`) gated by `check-pii.sh` extended with new rules. Three-lens review (PII / domain / code from `methodology.md § Multi-angle review`) per donor session.

### Synthesis pipeline

Pattern already exists: `examples/_strength_fit_synth.py` (strength) and `examples/data/synthetic_baseline.fit` + `synthetic_recent.fit` (cardio). Extend by:

- Vendor `_strength_fit_synth` and the cardio equivalent into `blackswan-bench/harness/synth/builder.py` (decoupled lifecycle)
- Add a `CardioFitSynthesizer` parameterised on `(grade_profile, hr_profile, sensor_fault_kind, sensor_fault_window)`
- No external "FIT synthesizer library" needed — `garmin-fit-sdk` Encoder is sufficient

### Risks

- **Goodhart's law / score gaming**: low-bar curve-fitting beats the benchmark. Mitigation: T3 scoring includes the noise-floor check — pure curve-fitting cannot beat the synthesised noise floor.
- **Synthetic FIT license ambiguity**: synthesis output derives from `garmin-fit-sdk` field definitions. Mitigation: synthetic FITs use FIT dev-mode sentinels and contain no Garmin trademarks. CC0-1.0 for FITs, MIT for harness.
- **PII review burden balloons in v1**: cap real-data corpus at 5 sessions, frozen forever; if review too costly, ship v1 synthetic-only.
- **Maintainer burnout**: explicit "issues triaged best-effort, dataset frozen so urgent fixes are rare" in README.
- **Cross-publication re-identification**: a donor whose anonymised data appears here AND in OpenData can be re-identified by joining. Mitigation: `DATASHEET.md` requires donors to declare prior releases.
- **Dataset staleness as Garmin rolls new device formats**: scope is "cardiac-cost benchmark", not "current Garmin device parser". v0.1 anchors on vivoactive 5 fields; new devices extend via v0.2.

### Effort breakdown

- **(a) MVP synthetic-only release** (v0.1, Zenodo DOI, harness, baseline, 8 sessions): **5–7 working days**. Synth machinery exists; mostly assembly + DATASHEET + Zenodo setup.
- **(b) v1 with real opt-in data** (5 anonymised sessions, de-identification pipeline, three-lens review per donor): **+10–14 working days**. PII pipeline is the cost driver.
- **(c) Full evaluation harness with leaderboard** (GitHub Pages + YAML schema for submissions, continuous deployment): **+15–20 working days**.

### Why ship v0.1 now

The synthesis pattern, PII guard script, and ground-truth methodology (alt min → alt max with hand-marked validation) are already in the repo. The MVP is largely assembly. v0.1 synthetic-only **avoids** the highest-cost item (PII de-identification of real data) while still claiming the citable-DOI position before any competing project does. A stalled v0.1 doesn't damage blackswan; a half-shipped real-data release would. Reversibility is on our side.

---

## Appendix — agent assignments

This document was produced by five specialist agents running in parallel, each with a self-contained brief and read-only access to the repository:

| Direction | Agent type | Output length |
|---|---|---|
| D1 vocabulary alignment | general-purpose | ~700 words |
| D2 framework abstraction | feature-dev:code-architect | ~1,400 words |
| D3 Aerobic Decoupling | feature-dev:code-architect | ~1,500 words |
| D4 CLI design | feature-dev:code-architect | ~1,500 words |
| D5 benchmark dataset | general-purpose | ~1,300 words |

Agent outputs have been condensed and reframed for cross-direction coherence; the recommendations and effort estimates are theirs.

# Related Work: Garmin FIT / Training-Analysis Ecosystem

A survey of comparable open-source projects, the lessons we extract from them, and the strategic gaps that define blackswan's unique position. Conducted via `gh search` over multiple keyword fronts, followed by close reading of 11 README files.

> Genre note: this is a competitive-landscape document, not a methodology spec. It exists so that future scope decisions on blackswan can be made against the actual state of the field, not against assumptions.

## 1. The naming-island finding

`gh search repos "cardiac cost"` returns **zero** results other than blackswan itself. The same is true for `running cardiac drift heart rate decoupling` and `aerobic decoupling power heart`.

This is a double-edged signal:

- **Bad**: the project is invisible to the field's natural search vocabulary.
- **Good**: the methodological niche we occupy — *cross-session comparison with confounder correction* — has no direct competitor.

The metric we call "Cardiac Cost (CC)" already has industry-standard cousins:

| blackswan term | Industry term | Source |
|---|---|---|
| Cardiac Cost (HR ÷ km/h) | Pw:Hr / Aerobic Decoupling (HR-only proxy) | sauce4strava, GoldenCheetah |
| Uphill segment | VAM (climbing speed) | sauce4strava, GoldenCheetah |
| Trial intensity | NP / IF / TSS | TrainingPeaks (industry standard, replicated by python-fitanalysis) |
| Cardiac drift | Aerobic decoupling first-half / second-half ratio | sauce4strava |

## 2. Five-family taxonomy

| Family | Representative projects | Star range | Position relative to blackswan |
|---|---|---|---|
| **Training-science suite** | GoldenCheetah (2.1k) | 2k+ | Covers TRIMP, Critical Power, Banister, PMC, W'bal, Virtual Elevation. Has Python/R runtimes for user metrics. **Crucially: all metrics are raw — no cross-session confounder correction.** |
| **Data pipeline** | GarminDB (3.1k), python-garminconnect (2.3k), garmin-grafana (3.2k), open-wearables (1.6k) | 1.6k–3.2k | Move data from Garmin Connect → SQLite/InfluxDB → Jupyter/Grafana. Methodology is left to the user. |
| **Desktop / dashboard app** | ActivityLog2 (370), choochoo (249), fitly (226), fit-dashboard (123), elevate (1.4k) | 100–1.4k | UI-first. choochoo's author publicly admits the project is "too complex" — three Docker images required. |
| **Browser overlay** | sauce4strava (269) | 269 | Adds Pw:Hr decoupling, NP, TSS, VAM, W'balance to strava.com pages. Goes to where users already are. |
| **Personal showcase** | running\_page (4.4k) | 4k+ | Static site builder for one's own runs. Highest star count in the survey, but no analysis. Stars track aesthetic, not methodology. |
| **Methodology / academic** | python-fitanalysis (66), blackswan (this repo) | <100 | python-fitanalysis is the only prior work that explicitly compares its outputs against TrainingPeaks/Garmin/Strava in the README. blackswan extends that ethos to *cross-session* comparison. |

## 3. Curated repository list

Each entry is one paragraph: link, position, what blackswan can learn or reject.

### GoldenCheetah/GoldenCheetah — 2,124 stars, C++/Qt
<https://github.com/GoldenCheetah/GoldenCheetah>
The de facto open-source training-science suite for cyclists, triathletes, and coaches. Includes BikeStress/TRIMP/RPE, Critical Power, W'bal, Banister, PMC, Virtual Elevation. Embeds Python and R runtimes so users can write their own metrics. Topic tags: `science`. **Lesson**: this is the most comprehensive prior art in the field, and it does not do cross-session confounder correction. blackswan's methodology layer is the gap.

### GoldenCheetah/OpenData — 44 stars, Python
<https://github.com/GoldenCheetah/OpenData>
> "It aims to create an open access database of endurance exercise data for use by amateurs, academics and professionals … published to OSF (DOI 10.17605/OSF.IO/6HFPZ)."

A long-running effort to turn anonymised user contributions into a citable research dataset. **Lesson**: blackswan's PII discipline (CLAUDE.md PII section, PR sweep checklist) is already OpenData-compatible — there is a clear upgrade path from "personal tool" to "benchmark dataset provider".

### tcgoetz/GarminDB — 3,075 stars, Python
<https://github.com/tcgoetz/GarminDB>
Downloads Garmin Connect data into SQLite and exposes it through Jupyter notebooks. Has a plugin system for third-party Connect IQ data fields. **Lesson**: SQLite-first is a more scalable substrate than the CSV-per-day pattern blackswan currently uses. If blackswan ever needs to process N years of data, GarminDB-style storage is the precedent to adopt — but it is not a methodology project, so we do not need to compete on coverage.

### arpanghosh8453/garmin-grafana — 3,160 stars, Python + Grafana + InfluxDB
<https://github.com/arpanghosh8453/garmin-grafana>
Containerised pipeline that pulls Garmin Connect data and renders dashboards in Grafana. Heavy on visualisation, light on methodology. **Lesson**: outsource visualisation to existing stacks rather than build dashboards in blackswan. If we expose a Pandas DataFrame, users can already plug into Grafana / Jupyter / Streamlit themselves.

### the-momentum/open-wearables — 1,626 stars, FastAPI + React
<https://github.com/the-momentum/open-wearables>
> "Open-source platform that unifies wearable device data from multiple providers."

Multi-provider unifier (Garmin, Whoop, Apple Health, Samsung). FastAPI backend + Postgres + Celery + React. **Lesson**: this is *the opposite* of blackswan's strategy. open-wearables solves "many sources, one API"; blackswan solves "one source, deep methodology". Both are valid product positions but they cannot be combined without losing focus.

### thomaschampagne/elevate — 1,416 stars, TypeScript / Electron
<https://github.com/thomaschampagne/elevate>
Desktop app + browser extension for Strava. Tracks fitness trends, peak power/HR/speed, time-in-zones, year-over-year volume. **Lesson**: dual-distribution (desktop + extension) doubles maintenance burden. blackswan should remain a single-artifact Python package.

### SauceLLC/sauce4strava — 269 stars, JavaScript
<https://github.com/SauceLLC/sauce4strava>
Browser extension that augments strava.com pages with Pw:Hr / Aerobic Decoupling, NP, TSS, IF, VAM, W'balance, Performance Predictor. **Lesson**: this is the *closest functional cousin* of blackswan's cardiac-drift correction — but in JavaScript, on Strava pages, with no Python implementation. blackswan can claim "the Python implementation of HR-only Aerobic Decoupling, with confounder correction" and that claim is currently uncontested.

### mtraver/python-fitanalysis — 66 stars, Python
<https://github.com/mtraver/python-fitanalysis>
> "My impetus for this project was to better understand how platforms like TrainingPeaks analyze power and heart rate data."

The only prior project that puts a comparison table in its README, validating its NP/IF/TSS calculations against TrainingPeaks/Garmin/Strava (errors typically <1%). **Lesson**: blackswan's `docs/authoritative-segmentation.md` already validates against hand-marked data — but that validation lives in `docs/`, not in the README. python-fitanalysis demonstrates the value of putting validation tables on the project's front page.

### andrewcooke/choochoo — 249 stars, Python
<https://github.com/andrewcooke/choochoo>
> "Currently it requires three Docker images running in parallel … this project will be more difficult to use … it's clearly not sustainable in its current form."

Training diary with Postgres + Bokeh + Jupyter. **Lesson**: a vivid public failure of the over-engineering trap. The author's own README is the warning. blackswan must hold the line at `uv pip install -e .` and resist any drift toward Docker Compose.

### ethanopp/fitly — 226 stars, Python (Plotly Dash)
<https://github.com/ethanopp/fitly>
Plotly Dash dashboard with seven data-source integrations: Strava, Oura, Withings, Stryd, Peloton, Fitbod, Spotify. **Lesson**: the integration-count strategy. The README is dominated by configuration steps, not analysis. blackswan must hold the line at "Garmin FIT only" and refuse new sources unless they unlock a methodology that single-source cannot reach.

### alex-hhh/ActivityLog2 — 370 stars, Racket
<https://github.com/alex-hhh/ActivityLog2>
Cross-discipline (swim/bike/run) desktop app written in Racket. **Lesson**: language choice can be a moat or a tax. Racket gives the project a distinctive identity but limits contributions. blackswan's choice of plain Python is the better default for a methodology project that wants academic readership.

### arpanghosh8453/fit-dashboard — 123 stars, Rust + DuckDB + React
<https://github.com/arpanghosh8453/fit-dashboard>
Tauri desktop + Docker web. Modern stack (Rust parser, DuckDB store, ECharts). **Lesson**: the polished-UI route. Achieves visual quality blackswan will not match, and that is fine — the audiences differ. Methodology readers do not pick tools by sidebar aesthetics.

### roznet/connectstats — 81 stars, Objective-C / Swift
<https://github.com/roznet/connectstats>
iOS app on the App Store, plus a macOS FitFileExplorer companion, plus a separate FitFileParser library. **Lesson**: even small projects can fragment into multiple repos. blackswan should resist splitting until the core API is stable.

### adriangibbons/php-fit-file-analysis — 128 stars, PHP
<https://github.com/adriangibbons/php-fit-file-analysis>
PHP class for FIT parsing with Power Analysis and Quadrant Analysis demos. **Lesson**: language ecosystems matter — the PHP audience is small in this domain, but the library has held 128 stars by being the only player. Single-language single-purpose packages outlive multi-stack platforms.

## 4. Five lessons from prior work

### Lesson 1 — Over-engineering kills projects (choochoo)

choochoo's README contains its own warning: three Docker images, install too complex, project not sustainable. The original install-as-pip-package goal was abandoned because the dependency surface grew faster than the user base.

**Apply to blackswan**: hold `uv pip install -e .` as the single supported install path. Resist Docker Compose, multi-service architectures, and PostgreSQL-by-default. The only justified Docker dependency is downstream visualisation (Grafana), and that should remain a user choice, not a project requirement.

### Lesson 2 — Validation tables belong in the README, not in `docs/` (python-fitanalysis)

python-fitanalysis's first-page comparison table — fitanalysis vs TrainingPeaks vs Garmin Connect vs Strava — is the single most credibility-creating move in the survey. blackswan's hand-marked validation (n=4 trials, error <0.15 CC) is mentioned in prose in the README but the actual numbers live in `docs/authoritative-segmentation.md`.

**Apply to blackswan**: lift the validation table into `README.md` so the first impression includes evidence, not claims.

### Lesson 3 — Source-integration is a treadmill (fitly)

fitly's README spends more space on configuring seven integrations than on what the analysis does. Each new source adds OAuth flows, schema drift, deprecation risk. fitly's seven sources reflect seven engineering commitments, not seven product features.

**Apply to blackswan**: refuse new input sources unless they unlock a methodology that the current single-source pipeline cannot achieve. The bar is not "would users like it" but "is the result analytically distinct from what we can already produce".

### Lesson 4 — Industry vocabulary is the search-engine entry point (sauce4strava)

sauce4strava's feature list uses the exact phrases users search for: Pw:Hr, Aerobic Decoupling, VAM, NP, TSS, IF. blackswan's README uses "Cardiac Cost", "uphill trial", "confounder correction" — terms that do not appear in any other project's vocabulary.

**Apply to blackswan**: cross-reference our private terms with industry standards in the README. We are not renaming our metrics; we are adding aliases so the project surfaces in keyword searches.

### Lesson 5 — Personal data can become research infrastructure (GoldenCheetah OpenData)

OpenData turned anonymised user contributions into a DOI-bearing OSF dataset that academic papers can cite. The PII handling required for this is non-trivial; blackswan already has it (CLAUDE.md PII section, PR sweep checklist).

**Apply to blackswan**: synthetic + opt-in real trials, packaged with ground-truth annotations, would let third parties evaluate cardiac-cost-style implementations against a common benchmark. This is a long-horizon move but the foundation is in place.

## 5. Where blackswan is the only player

After the full survey, these are the methodological positions where no comparable prior art was found:

1. **Cross-session confounder correction**: the explicit decomposition `raw_delta = corrected_delta + grade_penalty + duration_penalty + …`. GoldenCheetah, sauce4strava, and python-fitanalysis all report raw metrics; none decompose the cross-session delta into its causal components.
2. **Noise floor as a first-class output**: the line `Day-to-day noise floor: ±1.65 CC … Corrected deltas within this band are indistinguishable from noise.` has no precedent in any surveyed README.
3. **Hand-marked authoritative segmentation**: `alt min → alt max` validated against analyst marks within 1–8 seconds. Other projects either accept device lap markers or use heuristics that the project itself acknowledges are approximate.
4. **HR sensor artifact escalation rule**: `flagged_sec / trial_dur > 0.4` → exclude entire trial. sauce4strava detects aerobic decoupling but does not detect sensor failure. blackswan does both.
5. **Strength training HR-artifact detection**: the `EARLY_DEFICIT_LATE_NORMAL` signature for cold-start optical-HR errors. Strength FIT analysis is mostly absent from the field; cycling is overrepresented.

## 6. Five evolution directions

These are derived from gaps identified in §5 and lessons in §4. Specific design proposals for each direction are produced in companion documents (one per direction).

### Direction 1 — Industry-vocabulary alignment (lowest cost, highest reach)

Add aliases: Cardiac Cost ≡ HR-only Aerobic Decoupling proxy; segment_uphill ≡ VAM-segment auto-detector; cardiac drift correction ≡ Pw:Hr decoupling penalty (HR-only). Update README, docstrings, keywords. No code changes required.

### Direction 2 — Confounder correction as a generic framework

Extract `confounder_correct(metric, baseline, recent, confounders=[...])` from `cc_metrics.py` so it works for NP, strength HR, sleep efficiency, etc. The 4-layer methodology, exclusion-shopping protection, and noise-floor reporting all generalise. blackswan's framing changes from "a cardiac-cost tool with methodology" to "a methodology framework with cardiac-cost as the worked example".

### Direction 3 — Aerobic Decoupling (Pw:Hr) computation

A small new module that produces the standard first-half / second-half decoupling ratio for any segment. About 100 LOC. Makes blackswan discoverable to the existing aerobic-decoupling user base, who currently have to use sauce4strava (Strava-only) or GoldenCheetah (cycling-only).

### Direction 4 — CLI

`blackswan compare baseline.fit recent.fit --work-laps 1,2,3,4 vs 2,3,4,5,6,7 --exclude-recent 0,4`. Most similar projects have a CLI; blackswan currently requires Python knowledge to use. Lowers the barrier without expanding scope.

### Direction 5 — Public benchmark dataset

A `blackswan-bench` artifact: 5–10 synthetic uphill trial sets + 1–2 opt-in anonymised real sets + a validation harness. Distributed via Zenodo or OSF for a citable DOI. Long-horizon, but turns blackswan into research infrastructure rather than a personal tool.

## 7. Three traps to avoid (already paid for by others)

| Trap | Evidence | How blackswan avoids it |
|---|---|---|
| Docker Compose creep | choochoo's three-image setup, declared unsustainable by its own author | Maintain `uv pip install -e .` as the only install path |
| Source-integration sprawl | fitly's seven-source configuration burden | Reject new input sources unless methodologically necessary |
| Desktop GUI ambition | ActivityLog2 (Racket), elevate (Electron), fit-dashboard (Tauri) all carry GUI maintenance overhead | Stay library-first; downstream visualisation belongs to Grafana / Jupyter / Streamlit |

## 8. Conclusion

blackswan occupies a strategically unusual position: it is the most methodologically rigorous Garmin-analysis project in the open-source field, and simultaneously invisible to that field's natural search vocabulary. The highest-leverage near-term move is vocabulary alignment (Direction 1) — restoring blackswan to the conversation without changing its core. The highest-leverage long-term move is generalising the confounder framework (Direction 2) so that the methodology can survive beyond cardiac cost. Three traps — Docker creep, source sprawl, GUI ambition — have been pre-paid by choochoo, fitly, and ActivityLog2 respectively, and we have explicit licence to refuse them.

## Appendix A — Search methodology

Searches executed with `gh search repos`, sorted by stars, multiple keyword fronts:

- `garmin fit`, `fit file parser python heart rate`, `fitfile python`
- `cardiac cost` (zero results outside blackswan)
- topic queries: `garmin`, `strava`, `fitness + python`, `running + analysis`
- domain queries: `running power heart rate analysis`, `cycling power efficiency`, `interval training analysis`, `training load TSS python`, `endurance running analysis python`, `running cardiac drift heart rate decoupling`, `aerobic decoupling power heart`, `training load CTL ATL`, `running economy efficiency analysis`, `garmin sleep analysis stages`, `wearable data benchmark validation`, `VAM watt per kg climb cycling`, `stryd running power`, `vo2max estimation analysis`, `FTP threshold detection running`, `garmin connect activity api python`, `personal health analytics quantified self`, `GoldenCheetah`, `fit segment matching algorithm`, `fit file segment uphill climb`

READMEs read in full (or to length where the README ended): GoldenCheetah, GoldenCheetah/OpenData, GarminDB, garmin-grafana, open-wearables, elevate, sauce4strava, python-fitanalysis, choochoo, ActivityLog2, fitly, fit-dashboard, connectstats, php-fit-file-analysis.

## Appendix B — What was deliberately out of scope

- **Closed-source competitors** (TrainingPeaks, Garmin Connect itself, WKO5, Final Surge): they shape the market but cannot be inspected for methodology.
- **Papers**: this survey reads code and READMEs, not the sport-science literature. blackswan's `docs/methodology.md` already cites primary sources where relevant.
- **Non-FIT input formats**: GPX, TCX, KML — out of scope because blackswan's input contract is FIT.

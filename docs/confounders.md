# Confounders in Cross-Session CC Comparison

When you compare Cardiac Cost (CC) across two interval sessions to claim improvement, you're implicitly assuming the only thing that changed is the user's fitness. That's almost never true. This document catalogues the confounders we've identified, with detection methods and correction formulas.

## Why this matters

A naïve comparison of "session A had CC 35, session B had CC 31, ergo a 4-point improvement" is wrong roughly half the time. We've seen real cases where:

- Half the apparent improvement came from session B having shorter trials (less drift accumulation)
- A third came from session B having flatter average grade (lower expected HR)
- The remainder was noise

Without confounder correction, every cross-session comparison drifts toward "I'm getting better" because users tend to (a) shorten trials when fresh, (b) pick easier routes when not feeling great, and (c) press the lap button differently. The confounders compound.

## Confounder catalogue

### 1. Trial duration

**Effect**: Cardiac drift (HR rising over time at constant external workload) accumulates during a trial. A 90-second trial accumulates roughly half the drift of a 180-second trial. Shorter trials have lower CC.

**Magnitude**: 5–10 bpm/min of drift is typical for hill intervals. A 30-second duration shortening cuts ~3 bpm from average HR, ~0.7 CC points off (at 4.5 km/h).

**Detection**: compare per-trial duration (FIT `total_timer_time`) across sessions.

**Correction**:
```
hr_penalty = (dur_baseline - dur_recent) / 60 × drift_bpm_per_min
cc_penalty = hr_penalty / avg_kmh
```

`drift_bpm_per_min` should ideally be measured from the baseline session's working trials (endpoint method: last-30s avg HR minus first-30s avg HR, divided by trial duration in minutes). If you can't measure, default to 7.5 bpm/min.

> ⚠ **See also: final-trial speed warning.** A common reading-error is "the last trial was +20% faster, so I improved" — but if that final trial is also 30%+ shorter (90s vs 180s), the speed advantage can be entirely a duration confound (anaerobic vs aerobic effort modes). Always pair-by-duration before claiming end-of-session improvement.

### 2. Average grade

**Effect**: Steeper grade requires more cardiac output at the same speed. Expected HR rises with grade.

**Magnitude**: empirical coefficient ≈ 1.5 bpm per grade-percentage-point (literature range 1.0–2.0). A 3% grade reduction reduces expected HR by ~4.5 bpm.

**Detection**: compute per-trial grade as `ascent / horizontal_distance × 100`. Compare cross-session.

**Correction**:
```
hr_penalty = (grade_baseline - grade_recent) × 1.5
cc_penalty = hr_penalty / avg_kmh
```

### 3. Rest structure (work-time density)

**Effect**: 4 long trials with short rest accumulates more residual fatigue than 6 short trials with long rest. Two sessions with the same total work time can have very different CC profiles purely from rest pattern.

**Magnitude**: Hard to model with one coefficient — it interacts with cardiac drift and recovery rate. A worked-but-not-fatigued user has a flatter HR drift; a fully fatigued user shows accelerating drift.

**Detection**: compute `work_time / total_session_time` for both sessions. We've seen 30% vs 16%.

**Correction**: don't try to model it. Report both densities side-by-side in Layer 3; mention in Layer 4 take-home that the comparison is "intervals + long rest" vs "longer intervals + short rest" and CC necessarily favours the former.

### 4. Lap-button pressing habit

**Effect**: Some users press at the bottom of the climb (lap content = uphill + walk-back), others at the top (lap content = walk-back + uphill). lap_mesgs-based metrics get contaminated by walk-back HR (much lower than uphill HR), distorting CC.

**Magnitude**: walk-back HR ≈ 100-110 bpm vs uphill HR ≈ 145-165 bpm. Including 100s of walk-back in a 180s "trial" drops avg HR by 20+ bpm → CC drops by 4+ points.

**Detection**: ask the user about their habit, or detect by checking whether lap.start_time aligns with altitude minima or maxima.

**Fix**: don't use lap_mesgs boundaries for CC computation. Use **alt min → alt max** segmentation (see [`authoritative-segmentation.md`](authoritative-segmentation.md)).

### 5. HR sensor artifacts (optical wrist HR)

**Effect**: optical HR sensors can lock to a baseline value during cold capillary perfusion (typical first 5–10 minutes of activity in cool weather) or during high motion. The recorded HR can be 30+ bpm below true.

**Magnitude**: A trial with 80s of physio-implausibly-low HR (e.g. 110 bpm at 5 km/h on 25% grade where expected is 145+) reads CC ~26 instead of ~32. That's a 6-point distortion that looks like a great workout.

**Detection**: `detect_hr_artifacts.py` flags segments where measured HR < expected by physiologically implausible amounts (uses speed × grade × cadence baseline).

**⚠ Important — the detector under-flags slow-onset failures**: a single trial may hold 100–160s of artifact while `detect_hr_artifacts` only flags ~80s of it. The detector catches the most-implausible window (e.g. mid-trial when speed × grade is highest), but misses the leading and trailing edges where the sensor is gradually re-acquiring or has been baseline-stuck since before the climb started.

**Escalation rule (the right fix)**:

1. If `flagged_seconds / trial_duration > 0.4` → exclude the entire trial from cross-session comparison
2. If max_HR − start_HR < 15 bpm in a trial that should be high-intensity (work trial with grade ≥ 15%) → suspect sensor across the whole trial, exclude
3. If neither rule fires but you see a one-off 80s flagged window in a 200s trial, exclude the trial conservatively rather than trying to use the unflagged 120s — the unflagged section is contaminated by what came before

Don't try to "correct" partial-trial artifacts — the underlying HR data is unrecoverable, and a partial exclusion of bad seconds inside the trial leaves a CC computed against artificially-low data anyway.

### 6. Outlier trials (mid-session "easy" trial)

**Effect**: Sometimes the user backs off on one trial mid-session (chatting with someone, looking at scenery, not feeling it). The trial reads with low avg HR and low max HR, but normal speed and grade. Mean-CC across all trials is dragged down.

**Detection**: a trial with `max_hr` 15+ bpm below the trial-max-HR mean of neighbouring trials, with no corresponding speed or grade reduction, is suspicious.

**Fix**: exclude with a documented criterion. Subjective confirmation from the user is gold ("yeah, I was looking at the view on that one").

Don't make outlier exclusion a free parameter — pick a rule before looking at data ("exclude any trial with max_hr more than 1 stdev below neighbours") and stick to it. Otherwise you're shopping for the version of the data that supports your conclusion.

### 7. Day-to-day biological noise

**Effect**: Sleep, hydration, ambient temperature, time-of-day, food intake all shift HR by 3–5 bpm at the same external workload. Two sessions taken on the same fitness can read 5% different in CC.

**Magnitude**: ±5% on CC. For CC = 33, that's ±1.6 points.

**Fix**: this is the **noise floor**. Any corrected delta smaller than this is statistically indistinguishable from "no change". Don't claim improvement (or regression) within ±5%.

`compare_sessions()` computes this automatically as `cc_noise_floor` and prints it in the report — you don't need to compute it by hand.

### 8. HRmax with low-n observations

**Effect**: A single new "max HR" observation 5 bpm above prior best, or a "missed max" 5 bpm below, is within day-to-day SD — not a real change.

**Magnitude**: ±5 bpm uncertainty when n ≤ 2 observations.

**Fix**: see [`methodology.md` Layer 4 hard constraints](methodology.md). Treat HRmax-derived zone boundaries as **provisional until n ≥ 4** observations across varied conditions.

## Composite correction example

From a real comparison:

| Confounder | Per-confounder CC penalty |
|------------|---------------------------|
| Grade -2.9% × 1.5 bpm/% = -4.4 bpm aHR penalty / 4.96 kmh | +0.89 |
| Duration -32s × 7.5 bpm/min = -4.0 bpm aHR penalty / 4.96 kmh | +0.81 |
| **Total amplification** | **+1.70** |

Raw CC delta: -2.76 (looks like a 2.76-point improvement)
Confounder amplification: +1.70 (the baseline reads higher because trials were longer and steeper)
Corrected delta: -2.76 + 1.70 = **-1.06**

Day-to-day noise floor: ±1.65 (≈ 5% of CC=33).

`|corrected delta| = 1.06 < noise floor = 1.65` → indistinguishable from noise. **Not improvement**.

This is the canonical "raw-looks-like-improvement, corrected-looks-like-nothing" case.

## What goes in the report

For every cross-session metric, report:

1. **Raw value** for each session
2. **Per-confounder breakdown** (grade penalty, duration penalty)
3. **Total amplification**
4. **Corrected delta**
5. **Noise floor for context**

The reader should be able to see exactly how much of the apparent change is structural vs real.

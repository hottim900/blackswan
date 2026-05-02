# Authoritative Trial Segmentation: alt min → alt max

The hardest single technical decision in cross-session interval analysis is **where the trial boundaries are**. This document explains why we use **alt min → alt max** and how it was validated.

## The problem

Three obvious choices for "what counts as a trial" all fail:

### Choice 1: lap_mesgs boundaries
Use the device's lap markers (set by the lap button or auto-1km).

**Failure mode**: Users press the lap button at different points across sessions. Some press at the bottom of the climb (lap = uphill + walk-back), others at the top (lap = walk-back + uphill). The lap content shifts depending on the pressing habit, contaminating CC because the walk-back has a wildly different cardiac cost from the uphill.

Even worse: across two sessions of the same user, the habit can change. We saw a user press at the top in session A and the bottom in session B — making lap_mesgs based comparison unfair.

### Choice 2: stop → stop logic
Detect when the user stops moving (speed < 1 km/h for ≥ 3s) and treat each "movement segment" as a trial.

**Failure mode**: Many users don't stop between trials. They walk back down the climb at 4–6 km/h, never dropping below 1 km/h. The algorithm finds zero stops and produces zero trials.

This is what happened in our validation: a session with 4 hand-marked climbs produced 0 stops detected (algorithm broken), because the user walked the entire trial-to-trial recovery at 5 km/h.

### Choice 3: simple altitude rising windows
Find every period of monotonically increasing altitude.

**Failure mode**: GPS altitude is noisy (±1m oscillations even on a true monotone climb). Naïve "rising = climb" emits 50+ tiny segments. With smoothing, you go too far the other way: a real climb that has a brief plateau in the middle gets split into two, or one with a 5m descent in the middle gets cut short.

We had a real case where one trial's max-HR section (the actual peak effort) was cut from the segmentation because the algorithm hit a 1m descent and gave up.

## The fix: alt min → alt max

For each lap (lap_mesgs entry):

1. Search the previous 30 seconds for the **lowest altitude** (the bottom of the climb)
2. Search forward through the lap for the **highest altitude** (the top of the climb)
3. The trial is the interval between those two timestamps

This works because:

- The user always climbs from low to high (regardless of where the lap button was pressed)
- The "alt minimum 30s before lap start" handles users who press the button slightly after starting to climb (a common case)
- A single climb with a brief plateau or 1m descent stays as one trial (we look at min and max, not local extrema)
- A lap that doesn't contain a real climb (e.g. a walk-back lap) produces no trial (alt min ≈ alt max)

It also works without lap markers via the unsupervised `find_uphill_segments` mode, but lap-anchored is more reliable.

## Validation

The training log we reverse-engineered from contained the analyst's hand-marked trial boundaries (timestamps recorded to the second, computed CC values rounded to 0.01). Comparing our algorithm's output against those marks for n=4 trials:

| Trial | Hand-marked length | Algorithm Δ start | Algorithm Δ end | Δ CC |
|-------|--------------------|-------------------|-----------------|------|
| 1 | 155s | -1s | 0s | -0.06 |
| 2 | 134s | -1s | 0s | -0.02 |
| 3 | 132s | -1s | 0s | -0.11 |
| 4 | 149s | +1s | +8s | +0.02 |

Across the 4 trials: **all Δ CC < 0.15 points**. The algorithm matches what an analyst would mark by eye on the elevation profile.

The end-time +8s discrepancy on trial 4 is the algorithm extending slightly past where the analyst stopped (the analyst clipped at the moment the user stopped pushing; the algorithm continues until the altitude max, which can be a few seconds later as the user coasts over the top). This minor over-extension produces only +0.02 CC drift — within day-to-day noise.

## API

```python
# Lap-anchored: one trial per work lap
from blackswan.segment_uphill import find_uphill_trials_in_lap
trial = find_uphill_trials_in_lap(records, lap, search_back_s=30, min_ascent=8)

# Unsupervised: every climb in the session
from blackswan.segment_uphill import find_uphill_segments
trials = find_uphill_segments(records, min_dur=60, min_ascent=15, min_hr_avg=100)

# Validate against a hand-marked window
from blackswan.segment_uphill import stats_for_window
trial = stats_for_window(records, t_start, t_end)
```

## When this method fails

- **No GPS altitude**: indoor activities, watch had GPS off
- **Pure flat-ground intervals**: no altitude min/max signal — use a different metric (pace × HR for treadmill repeats)
- **Climbs longer than the lap window**: if a user marked one big lap covering 5 climbs, the algorithm finds the highest peak and cuts off the others. Either re-lap manually, or use unsupervised mode.
- **Routes with intermediate peaks**: a climb-then-down-then-climb pattern within one trial confuses the unsupervised mode (it splits into two trials at the intermediate peak). Use lap-anchored mode.

## The general protocol: reverse-engineering algorithm validation

The validation method above generalises beyond climb segmentation. Whenever you have a candidate algorithm and an unclear answer to "is this right?", apply this protocol:

1. **Find ground truth**. In our case, a hand-marked training log existed. Other cases: a paper's published reference outputs, a manual analyst's records, a sensor with known accuracy, a controlled lab measurement. The ground truth doesn't need to be many cases — n=4 was enough here — but it must be **independent of the algorithm being tested**.

2. **Run the algorithm against the same inputs the ground truth used**. Record per-case outputs (start, end, derived metrics).

3. **Compute per-case deltas in domain-meaningful units** (here: Δ CC points, Δ seconds at boundaries). Don't just look at "did it find the same thing" — look at "by how much does it disagree".

4. **Compare delta to the day-to-day noise floor of the metric being computed**. If `max |delta| < noise floor`, the algorithm matches ground truth within the precision the metric supports — declare the algorithm authoritative for downstream use.

5. **If `delta > noise floor`, investigate**. Either the algorithm has a bug, the ground truth was computed differently, or the algorithm is making a defensible choice the analyst wouldn't (e.g. our trial-4 +8s extension to the alt max).

6. **Document the validation case in the docs**, including the deltas. A future user must be able to audit "is this algorithm trustworthy?" without rerunning the validation.

Ranges this generalises to: SpO2 desat detection vs polysomnography ground truth, sleep staging vs PSG, HR artifact detection vs hand-cleaned labels, lap-trial assignment vs analyst marks. Anywhere you'd otherwise just trust an algorithm by default — apply the protocol instead.

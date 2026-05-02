"""Cardiac Cost (CC) cross-day comparison metrics with confounder correction.

Comparing CC across two interval sessions (e.g. "did this week's intervals
show improvement vs last month's?") is non-trivial — duration, grade, and
rest structure all systematically affect CC. This module:

1. Computes the canonical training-log metrics (`cc_trial_2_3_mean`,
   `cc_back_half_mean`).
2. Quantifies the duration and grade confounders.
3. Reports both raw and confounder-corrected deltas.
4. Reports the HR-grade-normalised speed comparison (the most confounder-
   robust signal: "at the same HR, how much faster?").

## Why correction matters

Without correction, a "shorter trial + flatter route + longer rest" session
will systematically read as having lower CC than a "long trial + steep + short
rest" session — because per-trial cardiac drift accumulates less and there's
more recovery between trials. The net "improvement" can be entirely confounder.

## Coefficients used (empirical)

- grade penalty: 1.5 bpm per grade-percentage-point (literature 1.0–2.0)
- duration penalty: per-trial cardiac drift in bpm/min (default: measure from
  the baseline session's working trials, endpoint method)

These coefficients are sensitive — `ComparisonReport.hr_normalised_range`
returns the ±range so you can decide if the corrected delta is within noise.

## Recommended decision rule

If `cc_trial_2_3_mean` corrected delta is within day-to-day noise (CC × 5%,
typically ±1.5–2.0 points) and HR-grade-normalised delta is also small, then
the two sessions are statistically indistinguishable — not "improvement",
just within-noise variation.

Usage:
    from blackswan.cc_metrics import compare_sessions
    report = compare_sessions(
        baseline_trials=[...],   # list of stats_for_window() results
        recent_trials=[...],
        excluded_indices_recent={0, 4},  # 0=invalid sensor, 4=outlier
    )
    print(report.summary())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

__all__ = ["TrialStats", "ComparisonReport", "compare_sessions", "cc_trial_2_3_mean",
           "cc_back_half_mean", "compute_confounders"]


@dataclass
class TrialStats:
    """Per-trial summary as returned by `segment_uphill.stats_for_window`."""
    dur: float
    dist: float
    kmh: float
    grade: float
    start_hr: float
    avg_hr: float
    max_hr: float
    cc: float


def cc_trial_2_3_mean(trials: list[TrialStats]) -> float | None:
    """Mean CC of trials 2 and 3 (1-indexed).

    This is the canonical training-log metric: trial 1 is typically a
    progressive warm-up (RPE ≤ 6) that reads as low CC and skews averages.
    """
    if len(trials) < 3:
        return None
    return (trials[1].cc + trials[2].cc) / 2


def cc_back_half_mean(trials: list[TrialStats]) -> float | None:
    """Mean CC of trial 3 onwards. Sensitive to fatigue accumulation."""
    if len(trials) < 3:
        return None
    return mean(t.cc for t in trials[2:])


@dataclass
class Confounders:
    """Confounder amplification: CC points the baseline reads HIGHER due to
    structural differences (longer trials, steeper grades). Subtract these
    from the raw delta to get a confounder-corrected delta."""
    grade_penalty_cc: float
    duration_penalty_cc: float
    avg_kmh: float
    grade_diff: float
    dur_diff: float
    drift_used: float
    work_time_density_baseline: float | None = None
    work_time_density_recent: float | None = None

    @property
    def total_cc_penalty(self) -> float:
        return self.grade_penalty_cc + self.duration_penalty_cc


def compute_confounders(
    baseline_trials: list[TrialStats],
    recent_trials: list[TrialStats],
    grade_coef_bpm_per_pct: float = 1.5,
    drift_bpm_per_min: float | None = None,
    baseline_total_session_dur: float | None = None,
    recent_total_session_dur: float | None = None,
) -> Confounders:
    """Quantify the grade + duration confounders + work-time density.

    `drift_bpm_per_min`: cardiac drift rate from the baseline session. If
    None, defaults to 7.5 — a typical hiking-interval rate. Best practice
    is to measure from baseline session's working trials (endpoint method:
    last30s_avg - first30s_avg over duration in minutes).

    `*_total_session_dur`: total session duration in seconds (warm-up +
    work + rest + cool-down). Used to compute work-time density (work /
    total). If either is None, density is reported as None and the
    information must be carried separately into Layer 4.
    """
    grade_b = mean(t.grade for t in baseline_trials)
    grade_r = mean(t.grade for t in recent_trials)
    grade_diff = grade_b - grade_r

    dur_b = mean(t.dur for t in baseline_trials)
    dur_r = mean(t.dur for t in recent_trials)
    dur_diff = dur_b - dur_r

    kmh_avg = mean(t.kmh for t in recent_trials)

    if drift_bpm_per_min is None:
        drift_bpm_per_min = 7.5

    hr_pen_grade = grade_diff * grade_coef_bpm_per_pct
    hr_pen_dur = (dur_diff / 60) * drift_bpm_per_min

    work_b = sum(t.dur for t in baseline_trials)
    work_r = sum(t.dur for t in recent_trials)
    density_b = (work_b / baseline_total_session_dur) if baseline_total_session_dur else None
    density_r = (work_r / recent_total_session_dur) if recent_total_session_dur else None

    return Confounders(
        grade_penalty_cc=hr_pen_grade / kmh_avg if kmh_avg else 0,
        duration_penalty_cc=hr_pen_dur / kmh_avg if kmh_avg else 0,
        avg_kmh=kmh_avg,
        grade_diff=grade_diff,
        dur_diff=dur_diff,
        drift_used=drift_bpm_per_min,
        work_time_density_baseline=density_b,
        work_time_density_recent=density_r,
    )


@dataclass
class ComparisonReport:
    baseline_trials: list[TrialStats]
    recent_trials: list[TrialStats]
    excluded_recent: set[int]
    confounders: Confounders

    raw_delta_2_3: float
    raw_delta_back: float
    corrected_delta_2_3: float
    corrected_delta_back: float

    hr_normalised_delta: float
    hr_normalised_range: tuple[float, float]

    cc_noise_floor: float

    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        n_recent_input = len(self.recent_trials) + len(self.excluded_recent)
        lines = [
            "=== CC comparison ===",
            f"  Baseline: n={len(self.baseline_trials)} working trials",
            f"  Recent:   n={n_recent_input} input → {len(self.recent_trials)} after "
            f"excluding {sorted(self.excluded_recent)}",
            "",
            f"  Confounder amplification: +{self.confounders.total_cc_penalty:.2f} CC",
            f"    grade Δ {self.confounders.grade_diff:+.1f}% → +{self.confounders.grade_penalty_cc:.2f}",
            f"    dur   Δ {self.confounders.dur_diff:+.0f}s  → +{self.confounders.duration_penalty_cc:.2f}",
        ]
        if self.confounders.work_time_density_baseline is not None and \
           self.confounders.work_time_density_recent is not None:
            lines.append(
                f"    work-time density: baseline {self.confounders.work_time_density_baseline:.0%}"
                f" / recent {self.confounders.work_time_density_recent:.0%}"
                f" (NOT corrected — surface in Layer 4)"
            )
        lines += [
            "",
            f"  CC trial 2-3 mean: raw {self.raw_delta_2_3:+.2f} → "
            f"corrected {self.corrected_delta_2_3:+.2f}",
            f"  CC back half:     raw {self.raw_delta_back:+.2f} → "
            f"corrected {self.corrected_delta_back:+.2f}",
            "",
            f"  HR-grade-normalised speed delta: {self.hr_normalised_delta:+.2f} CC "
            f"(range [{self.hr_normalised_range[0]:+.2f}, {self.hr_normalised_range[1]:+.2f}])",
            "",
            f"  Day-to-day noise floor: ±{self.cc_noise_floor:.2f} CC (≈5% of baseline mean)."
            f" Corrected deltas within this band are indistinguishable from noise.",
        ]
        if self.notes:
            lines.append("")
            lines.append("  Notes:")
            for n in self.notes:
                lines.append(f"    - {n}")
        return "\n".join(lines)


def compare_sessions(
    baseline_trials: list[TrialStats],
    recent_trials: list[TrialStats],
    excluded_indices_recent: set[int] | None = None,
    excluded_indices_baseline: set[int] | None = None,
    grade_coef_bpm_per_pct: float = 1.5,
    drift_bpm_per_min: float | None = None,
    baseline_total_session_dur: float | None = None,
    recent_total_session_dur: float | None = None,
) -> ComparisonReport:
    """Compare two interval sessions with confounder correction.

    Args:
        baseline_trials: list of TrialStats from the older session
        recent_trials: list of TrialStats from the newer session
        excluded_indices_recent: 0-indexed trial numbers to exclude from
            recent (e.g. INVALID HR sensor failure, outlier behaviour).
            Decide these in Layer 2 BEFORE running this function — do not
            re-decide after seeing the deltas (that's "exclusion shopping").
        excluded_indices_baseline: same for baseline
        grade_coef_bpm_per_pct: HR penalty per grade-% (default 1.5,
            literature range 1.0-2.0)
        drift_bpm_per_min: cardiac drift rate from baseline session. If
            None, defaults to 7.5 (typical hiking-interval rate).
        baseline_total_session_dur, recent_total_session_dur: total session
            seconds (warm-up + work + rest + cool-down). Used for work-time
            density. None → density not reported.

    Returns ComparisonReport with raw / corrected deltas, HR-normalised
    comparison, and cc_noise_floor (≈5% of baseline mean CC; corrected
    deltas within this band are indistinguishable from noise).

    HR-grade-normalised pairing convention:
        - Baseline anchor: trial index 1 (the first "true" work trial,
          assuming trial 0 is a progressive warm-up).
        - Recent pair: the trial in `recent_trials[1:]` (excluding any
          warm-up at index 0) with avg_hr closest to baseline anchor.
        - If your sessions don't have a warm-up trial 0, prepend a
          placeholder or pre-filter so trial 1 is the work-trial anchor.
    """
    excluded_indices_recent = excluded_indices_recent or set()
    excluded_indices_baseline = excluded_indices_baseline or set()

    b_filtered = [t for i, t in enumerate(baseline_trials) if i not in excluded_indices_baseline]
    r_filtered = [t for i, t in enumerate(recent_trials) if i not in excluded_indices_recent]

    if len(b_filtered) < 3 or len(r_filtered) < 3:
        raise ValueError("Need at least 3 trials in each session for trial-2-3 metric")

    confounders = compute_confounders(
        b_filtered, r_filtered,
        grade_coef_bpm_per_pct=grade_coef_bpm_per_pct,
        drift_bpm_per_min=drift_bpm_per_min,
        baseline_total_session_dur=baseline_total_session_dur,
        recent_total_session_dur=recent_total_session_dur,
    )

    cc23_b = cc_trial_2_3_mean(b_filtered)
    cc23_r = cc_trial_2_3_mean(r_filtered)
    back_b = cc_back_half_mean(b_filtered)
    back_r = cc_back_half_mean(r_filtered)

    raw_d_2_3 = cc23_r - cc23_b
    raw_d_back = back_r - back_b
    corrected_d_2_3 = raw_d_2_3 + confounders.total_cc_penalty
    corrected_d_back = raw_d_back + confounders.total_cc_penalty

    # HR-grade-normalised: pair trials with closest avg HR, normalise the
    # recent trial's HR to baseline's grade
    pair_b = b_filtered[1]  # trial 2 of baseline = "first true work trial"
    # Pick the recent trial with closest avg_hr to pair_b (skip recent
    # trial 0 to avoid pairing with a warm-up trial)
    pair_r = min(r_filtered[1:], key=lambda t: abs(t.avg_hr - pair_b.avg_hr))

    grade_b = pair_b.grade
    grade_r = pair_r.grade
    cc_b = pair_b.cc

    cc_normalised_pts = []
    for coef in (grade_coef_bpm_per_pct - 0.5, grade_coef_bpm_per_pct, grade_coef_bpm_per_pct + 0.5):
        adj_aHR = pair_r.avg_hr + (grade_b - grade_r) * coef
        cc_normalised_pts.append(adj_aHR / pair_r.kmh - cc_b if pair_r.kmh else 0)

    hr_normalised_delta = cc_normalised_pts[1]
    hr_normalised_range = (min(cc_normalised_pts), max(cc_normalised_pts))

    notes = []
    if excluded_indices_recent or excluded_indices_baseline:
        notes.append("Excluded trials should be documented (sensor failure, outlier, etc.)")
    if abs(confounders.total_cc_penalty) > abs(raw_d_2_3) * 0.5:
        notes.append("Confounder accounts for ≥50% of the raw delta — "
                     "treat the corrected delta as the primary signal.")

    cc_noise_floor = (mean(t.cc for t in b_filtered)) * 0.05

    return ComparisonReport(
        baseline_trials=b_filtered,
        recent_trials=r_filtered,
        excluded_recent=excluded_indices_recent,
        confounders=confounders,
        raw_delta_2_3=raw_d_2_3,
        raw_delta_back=raw_d_back,
        corrected_delta_2_3=corrected_d_2_3,
        corrected_delta_back=corrected_d_back,
        hr_normalised_delta=hr_normalised_delta,
        hr_normalised_range=hr_normalised_range,
        cc_noise_floor=cc_noise_floor,
        notes=notes,
    )

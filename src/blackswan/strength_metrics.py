"""Cross-session strength comparison: pairing, deltas, artifact reporting.

The strength counterpart of ``cc_metrics.compare_sessions``. Differences from
cardio:

* Sets vary in load and exercise within a session, so pairing is per-set
  (matched on ``(active_idx, weight, reps)``) rather than session-mean.
* "Noise floor" is NOT directly comparable to cardio's ±5% (calibrated on
  uphill intervals at constant external workload). v1 ships the raw stdev /
  IQR as advisory; do NOT compare against ±3-5 bpm. See
  ``docs/confounders.md`` § 9.
* Optical-HR artifact detection runs on both sessions; warnings surface in
  the report. Flagged sets are NOT auto-excluded — exclusion is the user's
  decision.

Supersets / unilateral exercises are NOT disambiguated (no exercise-name
metadata in FIT); when they are detected the report's ``notes`` flag the
ambiguity so the caller can re-interpret the deltas.

Usage:

    from blackswan.strength_metrics import compare_strength_sessions
    report = compare_strength_sessions("baseline.fit", "recent.fit")
    print(report.summary())

    # If you already parsed:
    from blackswan.strength_metrics import compare_strength_sessions_from_stats
    report = compare_strength_sessions_from_stats(baseline_stats, recent_stats)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean, quantiles, stdev
from typing import Literal

from blackswan.detect_strength_hr_artifact import (
    DEFAULT_DETECTOR_CONFIG,
    StrengthDetectorConfig,
    StrengthHRArtifactSignature,
    detect_strength_hr_artifact,
)
from blackswan.parse_strength_fit import (
    StrengthSession,
    parse_strength_fit,
)
from blackswan.segment_strength_sets import ExerciseGroup, identify_exercises

__all__ = [
    "MatchedPair",
    "StrengthComparisonReport",
    "StrengthSessionStats",
    "StrengthSetStats",
    "compare_strength_sessions",
    "compare_strength_sessions_from_stats",
]

_LOCAL_HOUR_WARN_THRESHOLD = 3
"""Circular hour-diff above which local_hour_warning is emitted. See
docs/confounders.md § 9 — calibration confound caveat."""


@dataclass
class StrengthSetStats:
    """Per-set summary used for cross-session pairing. Built only for
    active sets with ``hr_avg`` and ``(weight, reps)`` all set."""

    active_idx: int
    weight: float
    reps: int
    duration: float
    hr_avg: float
    hr_max: float
    hr_start: float
    hr_end: float
    hr_next60s_avg: float | None


@dataclass
class StrengthSessionStats:
    """Session-level aggregate used as input to comparison.

    ``source_session`` is the parsed ``StrengthSession``; comparison uses it
    to run the artifact detector. The ``artifact_signature`` lives on
    ``StrengthComparisonReport`` (per UC#5), not here, because v1 detector
    is most informative when given a reference session for relative
    thresholds."""

    fit_path: Path | None
    start_time: datetime
    local_hour: int
    total_dur: float
    warmup_avg_hr: float | None
    active_set_stats: list[StrengthSetStats]
    source_session: StrengthSession


@dataclass
class MatchedPair:
    """Sign convention: ``hr_delta = recent.hr_avg - baseline.hr_avg``.
    Positive = recent HR higher (could indicate fatigue, lower fitness, or
    recovered-sensor artifact; interpretation requires the report's
    ``artifact_warnings``)."""

    baseline: StrengthSetStats
    recent: StrengthSetStats
    hr_delta: float
    match_quality: Literal["exact_slot", "exercise_level"]


@dataclass
class StrengthComparisonReport:
    baseline: StrengthSessionStats
    recent: StrengthSessionStats

    pairs: list[MatchedPair]
    unmatched_baseline: list[StrengthSetStats]
    unmatched_recent: list[StrengthSetStats]

    exact_slot_mean_delta: float | None
    exercise_level_mean_delta: float | None

    artifact_warnings: list[str]
    baseline_artifact_signature: StrengthHRArtifactSignature
    recent_artifact_signature: StrengthHRArtifactSignature
    local_hour_warning: str | None

    hr_delta_stdev: float | None
    hr_delta_iqr: float | None
    noise_floor_provisional: None
    n_pairs: int
    n_sessions_calibrated: int

    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=== Strength comparison ===",
            f"  Baseline: {self.baseline.start_time:%Y-%m-%d %H:%M} "
            f"({len(self.baseline.active_set_stats)} active stats)",
            f"  Recent:   {self.recent.start_time:%Y-%m-%d %H:%M} "
            f"({len(self.recent.active_set_stats)} active stats)",
            "",
            f"  Pairs matched: {self.n_pairs} "
            f"(exact_slot: {sum(1 for p in self.pairs if p.match_quality == 'exact_slot')}, "
            f"exercise_level: {sum(1 for p in self.pairs if p.match_quality == 'exercise_level')})",
            f"  Unmatched: baseline {len(self.unmatched_baseline)}, "
            f"recent {len(self.unmatched_recent)}",
            "",
        ]
        if self.exact_slot_mean_delta is not None:
            lines.append(f"  HR Δ exact_slot: {self.exact_slot_mean_delta:+.1f} bpm")
        if self.exercise_level_mean_delta is not None:
            lines.append(f"  HR Δ all pairs:  {self.exercise_level_mean_delta:+.1f} bpm")
        if self.hr_delta_stdev is not None:
            lines.append(f"  stdev:           {self.hr_delta_stdev:.1f} bpm (advisory)")
        if self.hr_delta_iqr is not None:
            lines.append(f"  IQR:             {self.hr_delta_iqr:.1f} bpm (n>=4)")
        lines += [
            "",
            f"  Artifact (experimental detector): "
            f"baseline {self.baseline_artifact_signature.value.upper()}, "
            f"recent {self.recent_artifact_signature.value.upper()}",
        ]
        if self.artifact_warnings:
            lines.append("  Artifact warnings:")
            for w in self.artifact_warnings:
                lines.append(f"    {w}")
        if self.local_hour_warning:
            lines.append("")
            lines.append(f"  Time-of-day: {self.local_hour_warning}")
        if self.notes:
            lines.append("")
            lines.append("  Notes:")
            for n in self.notes:
                lines.append(f"    - {n}")
        return "\n".join(lines)


def _build_session_stats(
    session: StrengthSession,
    exercises: list[ExerciseGroup],
) -> StrengthSessionStats:
    """Assemble ``StrengthSessionStats`` from a parsed session + grouped
    exercises. Drops active sets that lack any of ``hr_avg``, ``weight``,
    or ``reps`` — pairing requires all three."""
    active_set_stats: list[StrengthSetStats] = []
    for s in session.sets:
        if s.set_type != "active":
            continue
        if s.active_idx is None or s.hr_avg is None or s.weight is None or s.reps is None:
            continue
        # parser guarantees hr_max/hr_start/hr_end are set together with hr_avg
        active_set_stats.append(
            StrengthSetStats(
                active_idx=s.active_idx,
                weight=s.weight,
                reps=s.reps,
                duration=s.duration,
                hr_avg=s.hr_avg,
                hr_max=s.hr_max,
                hr_start=s.hr_start,
                hr_end=s.hr_end,
                hr_next60s_avg=s.hr_next60s_avg,
            )
        )

    warmup_avg_hr: float | None = None
    for grp in exercises:
        if grp.name == "warmup":
            hrs = [s.hr_avg for s in grp.sets if s.hr_avg is not None]
            warmup_avg_hr = mean(hrs) if hrs else None
            break

    return StrengthSessionStats(
        fit_path=session.fit_path,
        start_time=session.start_time,
        local_hour=session.local_hour,
        total_dur=session.total_elapsed_time,
        warmup_avg_hr=warmup_avg_hr,
        active_set_stats=active_set_stats,
        source_session=session,
    )


def _count_ambiguous_groupings(stats_list: list[StrengthSetStats]) -> int:
    """Return the number of ``(weight, reps)`` keys whose occurrences in
    ``active_set_stats`` are non-contiguous — a marker for supersets or
    unilateral interleaving."""
    by_key: dict[tuple[float, int], list[int]] = {}
    for i, s in enumerate(stats_list):
        by_key.setdefault((s.weight, s.reps), []).append(i)
    count = 0
    for indices in by_key.values():
        if len(indices) > 1 and (max(indices) - min(indices)) > len(indices) - 1:
            count += 1
    return count


def _circular_hour_diff(a: int, b: int) -> int:
    diff = abs(a - b)
    return min(diff, 24 - diff)


def compare_strength_sessions_from_stats(
    baseline_stats: StrengthSessionStats,
    recent_stats: StrengthSessionStats,
    *,
    excluded_indices_recent: set[int] | None = None,
    excluded_indices_baseline: set[int] | None = None,
    detector_config: StrengthDetectorConfig = DEFAULT_DETECTOR_CONFIG,
) -> StrengthComparisonReport:
    """Compare two pre-built ``StrengthSessionStats`` and return a
    ``StrengthComparisonReport``.

    Mirrors ``blackswan.cc_metrics.compare_sessions`` for cardio-strength
    API parity. The full-pipeline ``compare_strength_sessions`` wraps
    parser + segmenter + this function.

    Args:
        baseline_stats: stats from the older session (anchor).
        recent_stats: stats from the newer session.
        excluded_indices_recent: ``active_idx`` values to drop from recent
            before pairing. Decide BEFORE running — see CLAUDE.md
            "exclusion shopping" warning. Out-of-range indices raise
            ``ValueError`` (V2.12 anti-shopping guard).
        excluded_indices_baseline: same for baseline.
        detector_config: thresholds for the strength HR artifact detector.

    Returns:
        ``StrengthComparisonReport``. Call ``.summary()`` for a
        human-readable report.

    Raises:
        ValueError: out-of-range exclusion index, or 0 set pairs after
            matching (V2.8). On ``n_pairs == 1``, returns the report with
            ``hr_delta_stdev=None`` and ``hr_delta_iqr=None`` rather than
            raising.

    Caveats:
        Supersets and unilateral exercises (e.g. left-then-right single-arm
        rows) read as separate ``(weight, reps)`` slots that the matcher
        cannot disambiguate. When detected, the report's ``notes`` flag the
        ambiguity. The numeric deltas at those slots are still produced —
        treat them as advisory.
    """
    excluded_indices_recent = set(excluded_indices_recent or set())
    excluded_indices_baseline = set(excluded_indices_baseline or set())

    valid_b = {s.active_idx for s in baseline_stats.active_set_stats}
    valid_r = {s.active_idx for s in recent_stats.active_set_stats}
    invalid_b = excluded_indices_baseline - valid_b
    invalid_r = excluded_indices_recent - valid_r
    if invalid_b:
        raise ValueError(
            f"excluded_indices_baseline={sorted(excluded_indices_baseline)} contains "
            f"{sorted(invalid_b)} not found in baseline active sets {sorted(valid_b)}. "
            "Cause: index typo, or set was already dropped (no HR coverage / "
            "missing weight or reps). "
            "Fix: print baseline_stats.active_set_stats[*].active_idx and pass "
            "only valid indices."
        )
    if invalid_r:
        raise ValueError(
            f"excluded_indices_recent={sorted(excluded_indices_recent)} contains "
            f"{sorted(invalid_r)} not found in recent active sets {sorted(valid_r)}. "
            "Cause: index typo, or set was already dropped (no HR coverage / "
            "missing weight or reps). "
            "Fix: print recent_stats.active_set_stats[*].active_idx and pass "
            "only valid indices."
        )

    b_sets = [s for s in baseline_stats.active_set_stats
              if s.active_idx not in excluded_indices_baseline]
    r_sets = [s for s in recent_stats.active_set_stats
              if s.active_idx not in excluded_indices_recent]

    # Step 1: exact-slot pass on (active_idx, weight, reps)
    recent_by_key = {(s.active_idx, s.weight, s.reps): s for s in r_sets}
    pairs: list[MatchedPair] = []
    matched_b: set[int] = set()
    matched_r: set[int] = set()
    for b in b_sets:
        key = (b.active_idx, b.weight, b.reps)
        r = recent_by_key.get(key)
        if r is not None:
            pairs.append(MatchedPair(
                baseline=b, recent=r,
                hr_delta=r.hr_avg - b.hr_avg,
                match_quality="exact_slot",
            ))
            matched_b.add(b.active_idx)
            matched_r.add(r.active_idx)

    # Step 2: exercise-level fallback (greedy, baseline-first)
    unpaired_b = [b for b in b_sets if b.active_idx not in matched_b]
    unpaired_r = [r for r in r_sets if r.active_idx not in matched_r]
    recent_buckets: dict[tuple[float, int], list[StrengthSetStats]] = {}
    for r in unpaired_r:
        recent_buckets.setdefault((r.weight, r.reps), []).append(r)

    for b in unpaired_b:
        bucket = recent_buckets.get((b.weight, b.reps))
        if not bucket:
            continue
        chosen = min(bucket, key=lambda r: abs(r.active_idx - b.active_idx))
        bucket.remove(chosen)
        pairs.append(MatchedPair(
            baseline=b, recent=chosen,
            hr_delta=chosen.hr_avg - b.hr_avg,
            match_quality="exercise_level",
        ))
        matched_b.add(b.active_idx)
        matched_r.add(chosen.active_idx)

    unmatched_baseline = [b for b in b_sets if b.active_idx not in matched_b]
    unmatched_recent = [r for r in r_sets if r.active_idx not in matched_r]

    n_pairs = len(pairs)
    if n_pairs == 0:
        raise ValueError(
            "0 set pairs after matching. "
            "Cause: baseline and recent have no shared (weight, reps) slots, "
            "or one or both sessions had insufficient HR coverage / missing "
            "weight or reps so all sets were dropped at stats build. "
            "Fix: confirm both sessions parsed successfully "
            "(len(active_set_stats) > 0 each); if routines are genuinely "
            "disjoint, comparison is not meaningful. "
            "Note: this also fires when both sides have no HR records at all."
        )

    deltas = [p.hr_delta for p in pairs]
    exact_deltas = [p.hr_delta for p in pairs if p.match_quality == "exact_slot"]
    exact_slot_mean_delta = mean(exact_deltas) if exact_deltas else None
    exercise_level_mean_delta = mean(deltas) if deltas else None

    hr_delta_stdev: float | None = None
    if n_pairs >= 2:
        hr_delta_stdev = stdev(deltas)

    hr_delta_iqr: float | None = None
    if n_pairs >= 4:
        cuts = quantiles(deltas, n=4)
        hr_delta_iqr = cuts[2] - cuts[0]

    baseline_sig, baseline_warns = detect_strength_hr_artifact(
        baseline_stats.source_session, config=detector_config,
    )
    recent_sig, recent_warns = detect_strength_hr_artifact(
        recent_stats.source_session,
        reference=baseline_stats.source_session,
        config=detector_config,
    )

    artifact_warnings: list[str] = []
    for w in baseline_warns:
        artifact_warnings.append(f"[baseline] {w}")
    for w in recent_warns:
        artifact_warnings.append(f"[recent] {w}")
    if artifact_warnings:
        artifact_warnings.insert(
            0,
            "Note: the detector inspects raw session sets including those without HR. "
            "Triggered active_idx values may not appear in pairs[] when the parser "
            "dropped them for missing HR / weight / reps.",
        )

    hour_diff = _circular_hour_diff(
        baseline_stats.local_hour, recent_stats.local_hour
    )
    local_hour_warning: str | None = None
    if hour_diff > _LOCAL_HOUR_WARN_THRESHOLD:
        local_hour_warning = (
            f"baseline {baseline_stats.local_hour}:00 vs recent "
            f"{recent_stats.local_hour}:00 (circular diff {hour_diff}h). "
            "Time-of-day variation may add residual; see docs/confounders.md "
            "§ 9 for the n=5 calibration confound caveat."
        )

    notes: list[str] = []
    n_exercise_level = sum(1 for p in pairs if p.match_quality == "exercise_level")
    if n_exercise_level:
        notes.append(
            f"Exercise-level fallback used for {n_exercise_level} pair(s) "
            "(matched (weight, reps) but different active_idx)."
        )
    if excluded_indices_recent or excluded_indices_baseline:
        notes.append(
            "Excluded sets should be documented (sensor failure, outlier). "
            "Decide BEFORE running compare — see CLAUDE.md exclusion-shopping warning."
        )

    n_ambiguous = (
        _count_ambiguous_groupings(baseline_stats.active_set_stats)
        + _count_ambiguous_groupings(recent_stats.active_set_stats)
    )
    if n_ambiguous:
        notes.append(
            f"ambiguous grouping: {n_ambiguous} (weight, reps) bucket(s) appeared "
            "non-contiguously across active sets — suspected superset / unilateral "
            "pattern. Pairing still produced numeric deltas but treat them as advisory."
        )

    return StrengthComparisonReport(
        baseline=baseline_stats,
        recent=recent_stats,
        pairs=pairs,
        unmatched_baseline=unmatched_baseline,
        unmatched_recent=unmatched_recent,
        exact_slot_mean_delta=exact_slot_mean_delta,
        exercise_level_mean_delta=exercise_level_mean_delta,
        artifact_warnings=artifact_warnings,
        baseline_artifact_signature=baseline_sig,
        recent_artifact_signature=recent_sig,
        local_hour_warning=local_hour_warning,
        hr_delta_stdev=hr_delta_stdev,
        hr_delta_iqr=hr_delta_iqr,
        noise_floor_provisional=None,
        n_pairs=n_pairs,
        n_sessions_calibrated=2,
        notes=notes,
    )


def compare_strength_sessions(
    baseline_fit: Path | str,
    recent_fit: Path | str,
    *,
    excluded_indices_recent: set[int] | None = None,
    excluded_indices_baseline: set[int] | None = None,
    detector_config: StrengthDetectorConfig = DEFAULT_DETECTOR_CONFIG,
) -> StrengthComparisonReport:
    """Parse + segment + detect + compare in one call.

    When ``baseline_fit`` and ``recent_fit`` resolve to the same path the
    file is parsed once and the same stats object is used for both sides
    (Eng H1).

    Args / behavior identical to ``compare_strength_sessions_from_stats``;
    see that function for full docstring.
    """
    bp = Path(baseline_fit)
    rp = Path(recent_fit)
    if bp.resolve() == rp.resolve():
        sess = parse_strength_fit(bp)
        stats = _build_session_stats(sess, identify_exercises(sess))
        return compare_strength_sessions_from_stats(
            stats, stats,
            excluded_indices_recent=excluded_indices_recent,
            excluded_indices_baseline=excluded_indices_baseline,
            detector_config=detector_config,
        )

    baseline_session = parse_strength_fit(bp)
    recent_session = parse_strength_fit(rp)
    baseline_stats = _build_session_stats(
        baseline_session, identify_exercises(baseline_session)
    )
    recent_stats = _build_session_stats(
        recent_session, identify_exercises(recent_session)
    )
    return compare_strength_sessions_from_stats(
        baseline_stats, recent_stats,
        excluded_indices_recent=excluded_indices_recent,
        excluded_indices_baseline=excluded_indices_baseline,
        detector_config=detector_config,
    )

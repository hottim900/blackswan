"""EXPERIMENTAL — strength HR artifact detection.

Calibrated on n=5 sessions, single user, vivoactive 5 only. P3 confidence
5-6: time-of-day x chronology completely confounded in calibration sample
(3 evening sessions all 3-6 weeks earlier than 2 afternoon sessions). Treat
detector output as a hint, not authoritative diagnosis. Recalibrate when
n>=10 sessions accumulated across multiple devices.

The detector flags ``EARLY_DEFICIT_LATE_NORMAL`` — early sets read
suspiciously low while late sets read normal once perfusion recovers. This
shape is consistent with cold capillary perfusion, grip vasoconstriction,
wrist tension, or watch fit (umbrella term: "early-session optical-HR
artifact"). The detector is shape-based and does not distinguish causes.

See ``docs/confounders.md`` § 9 for the full catalogue.

Usage:

    from blackswan.detect_strength_hr_artifact import (
        detect_strength_hr_artifact,
        StrengthHRArtifactSignature,
    )

    signature, warnings = detect_strength_hr_artifact(session)
    # In comparison mode: pass a reference session for relative thresholds
    sig_recent, warns_recent = detect_strength_hr_artifact(
        recent_session, reference=baseline_session
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

from blackswan.parse_strength_fit import StrengthSession, StrengthSet

__all__ = [
    "DEFAULT_DETECTOR_CONFIG",
    "StrengthDetectorConfig",
    "StrengthHRArtifactSignature",
    "detect_strength_hr_artifact",
]


class StrengthHRArtifactSignature(StrEnum):
    CLEAN = "clean"
    EARLY_DEFICIT_LATE_NORMAL = "early_deficit_late_normal"


@dataclass(frozen=True)
class StrengthDetectorConfig:
    """Thresholds for ``detect_strength_hr_artifact``.

    Defaults are calibrated on n=5 vivoactive 5 sessions, single user. They
    are chosen to flag the contaminated sessions in our calibration sample
    without flagging the clean ones.

    DO NOT tune these to make a specific session flag or unflag — that is
    threshold shopping (CLAUDE.md anti-pattern), and any apparent
    "improvement" from re-tuning on the same data is fitting noise. If a
    session is mis-flagged, document the case and accumulate evidence
    across more sessions before adjusting; ideally re-calibrate from a
    larger pool (n>=10) with held-out validation.
    """

    early_max_count: int = 4
    early_window_seconds: float = 600.0
    early_absolute_low: float = 90.0
    early_relative_deficit: float = 25.0
    late_absolute_high: float = 115.0
    late_minus_early: float = 30.0
    early_deficit_count_threshold: int = 2


DEFAULT_DETECTOR_CONFIG = StrengthDetectorConfig()


def _active_sets(session: StrengthSession) -> list[StrengthSet]:
    """Active sets the detector treats as real exercises.

    Excludes ``reps == 0`` ghost sets (recorded intent without work
    performed): a sitting button-press at low HR is not an exercise and
    must not feed the early-deficit window — otherwise two ghosts at the
    start of a session can false-trigger ``EARLY_DEFICIT_LATE_NORMAL``.
    Sets with ``reps is None`` remain included (raw schema fidelity, no
    semantic decision encoded yet).
    """
    return [s for s in session.sets if s.set_type == "active" and s.reps != 0]


def _ref_lookup(reference: StrengthSession | None, target: StrengthSet) -> float | None:
    """Return the reference session's matching set's ``hr_avg``, or None."""
    if reference is None or target.active_idx is None:
        return None
    for r in _active_sets(reference):
        if (
            r.active_idx == target.active_idx
            and r.weight == target.weight
            and r.reps == target.reps
        ):
            return r.hr_avg
    return None


def _median_or_none(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return median(clean) if clean else None


def detect_strength_hr_artifact(
    session: StrengthSession,
    *,
    reference: StrengthSession | None = None,
    config: StrengthDetectorConfig = DEFAULT_DETECTOR_CONFIG,
) -> tuple[StrengthHRArtifactSignature, list[str]]:
    """Detect early-session optical-HR artifact in a strength session.

    Operates on the parsed ``StrengthSession`` (not stats) so the detector
    can use raw set-level HR even when stats drop None-HR sets.

    Modes:

    * ``reference=None`` — single-session mode, absolute thresholds only.
    * ``reference=<other StrengthSession>`` — comparison mode. Adds the
      relative-to-reference threshold (recent set ``hr_avg <= ref_hr_avg
      - early_relative_deficit``) to ``early_deficit_count``.

    Decision rule:

    * ``early_window`` = first ``min(early_max_count, k)`` active sets, where
      ``k`` is the number of active sets within ``early_window_seconds`` of
      ``session.start_time``.
    * ``late_window`` = active sets from ``ceil(n_active / 2)`` onward.
    * ``early_deficit_count`` = active sets in ``early_window`` whose
      ``hr_avg`` falls below ``early_absolute_low`` OR (if reference given)
      ``hr_avg <= ref_hr_avg - early_relative_deficit``.
    * ``late_normal`` = at least one late set has ``hr_avg >=
      late_absolute_high``, OR ``late_median - early_median >=
      late_minus_early``.

    If ``early_deficit_count >= early_deficit_count_threshold`` AND
    ``late_normal``, return ``EARLY_DEFICIT_LATE_NORMAL`` with human-
    readable warnings naming the triggering sets. Otherwise return
    ``CLEAN`` with an empty warnings list.

    Edge cases:

    * Sessions with 0 or very few active sets → CLEAN (no signal).
    * All late sets have ``hr_avg=None`` → ``late_median`` is None and no
      late set passes ``late_absolute_high``, so ``late_normal=False`` →
      CLEAN. The detector never crashes on missing HR.
    """
    active = _active_sets(session)
    n_active = len(active)
    if n_active < 4:
        # Detector splits active sets into early window (first <=4) and a
        # late window starting at ceil(n/2). With n<4 the two windows
        # overlap (at n=2 both contain active_idx=1) or are degenerate, so
        # the early-vs-late comparison is not meaningful. Return CLEAN
        # explicitly rather than relying on the threshold rules to
        # accidentally produce CLEAN via short circuits.
        return StrengthHRArtifactSignature.CLEAN, []

    # Build early window: first min(early_max_count, k) active sets where
    # k counts active sets within early_window_seconds of session start.
    early_eligible: list[StrengthSet] = []
    for s in active:
        offset = (s.t_start - session.start_time).total_seconds()
        if offset <= config.early_window_seconds:
            early_eligible.append(s)
        else:
            break  # active sets are time-ordered; stop at first late set
    early_window = early_eligible[: config.early_max_count]

    late_start = math.ceil(n_active / 2)
    late_window = active[late_start:]

    early_median = _median_or_none([s.hr_avg for s in early_window])
    late_median = _median_or_none([s.hr_avg for s in late_window])

    early_deficit_count = 0
    early_deficit_notes: list[str] = []
    for s in early_window:
        if s.hr_avg is None:
            continue
        is_absolute_deficit = s.hr_avg < config.early_absolute_low
        ref_hr = _ref_lookup(reference, s)
        is_relative_deficit = (
            ref_hr is not None
            and s.hr_avg <= ref_hr - config.early_relative_deficit
        )
        if is_absolute_deficit or is_relative_deficit:
            early_deficit_count += 1
            why = []
            if is_absolute_deficit:
                why.append(f"hr_avg={s.hr_avg:.0f} < {config.early_absolute_low:.0f}")
            if is_relative_deficit:
                why.append(
                    f"hr_avg={s.hr_avg:.0f} <= ref {ref_hr:.0f} - {config.early_relative_deficit:.0f}"
                )
            early_deficit_notes.append(
                f"  active_idx={s.active_idx}: " + " AND ".join(why)
            )

    late_normal_high_count = sum(
        1 for s in late_window
        if s.hr_avg is not None and s.hr_avg >= config.late_absolute_high
    )
    late_normal_jump = (
        late_median is not None
        and early_median is not None
        and (late_median - early_median) >= config.late_minus_early
    )
    late_normal = late_normal_high_count >= 1 or late_normal_jump

    triggered = (
        early_deficit_count >= config.early_deficit_count_threshold
        and late_normal
    )
    if not triggered:
        return StrengthHRArtifactSignature.CLEAN, []

    warnings_out = [
        f"EARLY_DEFICIT_LATE_NORMAL: {early_deficit_count} early-window sets "
        f"below threshold (required >={config.early_deficit_count_threshold}):",
    ]
    warnings_out.extend(early_deficit_notes)
    if late_normal_high_count >= 1:
        warnings_out.append(
            f"  late window: {late_normal_high_count} set(s) with hr_avg >= "
            f"{config.late_absolute_high:.0f}"
        )
    if late_normal_jump:
        warnings_out.append(
            f"  late_median {late_median:.0f} - early_median {early_median:.0f} "
            f"= {late_median - early_median:+.0f} bpm (>= {config.late_minus_early:.0f})"
        )
    return StrengthHRArtifactSignature.EARLY_DEFICIT_LATE_NORMAL, warnings_out

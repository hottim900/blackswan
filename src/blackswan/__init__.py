"""blackswan — Garmin FIT analysis for cardio + strength training.

Public API surface. Internal modules (``_sleep``, ``_time``, parsers used
only by binaries) are not re-exported here.
"""

from __future__ import annotations

from blackswan.cc_metrics import (
    ComparisonReport,
    TrialStats,
    cc_back_half_mean,
    cc_trial_2_3_mean,
    compare_sessions,
)
from blackswan.detect_strength_hr_artifact import (
    DEFAULT_DETECTOR_CONFIG,
    StrengthDetectorConfig,
    StrengthHRArtifactSignature,
    detect_strength_hr_artifact,
)
from blackswan.parse_strength_fit import (
    StrengthSession,
    StrengthSet,
    parse_strength_fit,
)
from blackswan.segment_strength_sets import (
    ExerciseGroup,
    identify_exercises,
)
from blackswan.strength_metrics import (
    MatchedPair,
    StrengthComparisonReport,
    StrengthSessionStats,
    StrengthSetStats,
    compare_strength_sessions,
    compare_strength_sessions_from_stats,
)

__all__ = [
    # cardio
    "ComparisonReport",
    "TrialStats",
    "cc_back_half_mean",
    "cc_trial_2_3_mean",
    "compare_sessions",
    # strength — entry points
    "compare_strength_sessions",
    "compare_strength_sessions_from_stats",
    "parse_strength_fit",
    "identify_exercises",
    "detect_strength_hr_artifact",
    # strength — dataclasses
    "StrengthSet",
    "StrengthSession",
    "StrengthSetStats",
    "StrengthSessionStats",
    "StrengthComparisonReport",
    "ExerciseGroup",
    "MatchedPair",
    # strength — config / enums
    "StrengthHRArtifactSignature",
    "StrengthDetectorConfig",
    "DEFAULT_DETECTOR_CONFIG",
]

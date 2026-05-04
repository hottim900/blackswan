"""Group strength-training sets into logical exercises.

A `StrengthSession.sets` list mixes active and rest sets in chronological
order. We want logical groupings like "5 sets of 60kg x 8 reps". This module
applies a heuristic: walk the sets in order; group adjacent active sets with
the same ``(weight, reps)``, where adjacent means "separated only by rest
sets, with at most ``max_rest_gap`` rest sets between".

The heuristic is designed for routine-style sessions (do all sets of one
exercise, rest, move to next exercise). It splits supersets / unilateral
work — e.g. ``(60kg x 8) -> (40kg x 10) -> (60kg x 8) -> ...`` returns six
groups, not two — because there is no exercise-name signal in the FIT to
disambiguate.

Usage:

    from blackswan.parse_strength_fit import parse_strength_fit
    from blackswan.segment_strength_sets import identify_exercises

    session = parse_strength_fit("strength.fit")
    for group in identify_exercises(session):
        print(group.name, len(group.sets))
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from blackswan.parse_strength_fit import StrengthSession, StrengthSet

__all__ = ["ExerciseGroup", "MAX_REST_GAP", "identify_exercises"]

MAX_REST_GAP = 3
"""Default maximum rest-set count between two active sets to consider them
the same exercise. Calibrated on n=5 vivoactive 5 sessions: typical rest
pattern is 1-3 rest mesgs between active sets of the same exercise; >3
indicates an exercise change or atypical session pause. Frozen here to
avoid exclusion-shopping (CLAUDE.md). Override via the ``max_rest_gap``
parameter to ``identify_exercises`` only with documented rationale."""


@dataclass
class ExerciseGroup:
    """One logical exercise = 1+ active sets at the same ``(weight, reps)``,
    grouped by adjacency in the source session. ``sets`` contains active
    sets only; rest sets between them are not included."""

    name: str
    sets: list[StrengthSet]


def _group_name(weight: float | None, reps: int | None, is_first_group: bool) -> str:
    """Derive a human-readable name for a group given its ``(weight, reps)``.

    - ``weight=None`` or (``weight=0`` AND ``reps>=10`` AND first group) → "warmup"
    - ``weight=0`` and ``reps>0`` (not warmup) → "bodyweight"
    - ``weight>0`` → ``f"{weight}kg x {reps}"``
    """
    if weight is None:
        return "warmup"
    if weight == 0:
        if reps is not None and reps >= 10 and is_first_group:
            return "warmup"
        return "bodyweight"
    return f"{weight}kg x {reps}"


def identify_exercises(
    session: StrengthSession,
    *,
    max_rest_gap: int = MAX_REST_GAP,
) -> list[ExerciseGroup]:
    """Group active sets in ``session`` into ``ExerciseGroup`` instances.

    Walk ``session.sets`` in order. Maintain a running count of consecutive
    rest sets. When an active set ``S`` is encountered:

    - If it has the same ``(weight, reps)`` as the previously-grouped active
      set AND the rest-set gap between them is ``<= max_rest_gap``, append
      ``S`` to the current group.
    - Otherwise, start a new group containing ``S``.

    Active sets with ``weight=None`` AND ``reps=None`` are dropped with a
    warning (malformed exports — observed but rare in n=5).

    ``max_rest_gap`` defaults to ``MAX_REST_GAP=3``. The default was
    calibrated on n=5 vivoactive 5 sessions (typical rest pattern 1-3 rest
    mesgs between sets of the same exercise). Override only with documented
    rationale — see CLAUDE.md "exclusion shopping" warning.

    Returns:
        Ordered list of ``ExerciseGroup``. Empty if ``session`` has no
        usable active sets.
    """
    groups: list[ExerciseGroup] = []
    rest_gap = 0
    last_signature: tuple[float | None, int | None] | None = None

    for s in session.sets:
        if s.set_type == "rest":
            rest_gap += 1
            continue

        if s.weight is None and s.reps is None:
            warnings.warn(
                f"set_idx={s.set_idx}: dropping active set with weight=None and reps=None "
                "(malformed FIT export).",
                stacklevel=2,
            )
            rest_gap = 0
            continue

        sig = (s.weight, s.reps)
        if (
            groups
            and last_signature == sig
            and rest_gap <= max_rest_gap
        ):
            groups[-1].sets.append(s)
        else:
            name = _group_name(s.weight, s.reps, is_first_group=not groups)
            groups.append(ExerciseGroup(name=name, sets=[s]))

        last_signature = sig
        rest_gap = 0

    return groups

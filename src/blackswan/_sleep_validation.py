"""Naive vs smart transition math validation against sleep-official.csv.

Computes per-stage ratios `transition_seconds / official_seconds` for each
night, aggregates across nights, and detects per-night outliers. Library
form so unit tests can pin the math; the thin CLI wrapper at
`scripts/sleep_transition_vs_official.py` produces the markdown artifact.

Why both naive and smart:
- Naive: per-segment duration `next_ts - cur_ts`, every level included.
  Brief in-sleep awake arousals inflate the awake total — the failure
  mode the codebase warns about.
- Smart: skip awake transitions, sum non-awake segments closing on the
  session-end timestamp. Matches `analyze_spo2_vs_stage._sleep_window`
  fallback semantics. Awake collapses to 0 by design (info-loss tradeoff).

Both methods compared against `sleep-official.csv` (Garmin Connect
post-processed values) — see docs/sleep-validation.md for the per-night
aggregate table this script renders.

PII: outlier rows default to anonymized `night_N` IDs (1-based row order
in input). The `anonymize=False` path emits real dates and is intended
for local audit only — never commit a docs/sleep-validation.md generated
with real dates per CLAUDE.md cross-file join rule.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean

__all__ = [
    "STAGES",
    "NightRow",
    "StageStats",
    "naive_durations",
    "smart_durations",
    "compute_ratios",
    "collect_nights",
    "aggregate",
    "find_outliers",
    "render_markdown",
]

STAGES = ("awake", "deep", "light", "rem")


@dataclass(frozen=True)
class NightRow:
    """One night's transition-vs-official ratios for all four stages."""

    night_id: int  # 1-based, assigned in `collect_nights` iteration order
    date: str
    naive_ratios: dict[str, float | None]
    smart_ratios: dict[str, float | None]


@dataclass(frozen=True)
class StageStats:
    """Aggregate distribution of ratios across nights for one (stage, method)."""

    n: int
    min: float | None
    p25: float | None
    median: float | None
    p75: float | None
    max: float | None
    mean: float | None


def naive_durations(transitions: list[tuple[datetime, str]]) -> dict[str, float]:
    """Per-segment durations: each transition contributes (next_ts - cur_ts)
    seconds to its level. Last transition contributes 0 (no successor)."""
    out = {s: 0.0 for s in STAGES}
    for i in range(len(transitions) - 1):
        ts0, lvl0 = transitions[i]
        ts1, _ = transitions[i + 1]
        if lvl0 in out:
            out[lvl0] += (ts1 - ts0).total_seconds()
    return out


def smart_durations(
    transitions: list[tuple[datetime, str]], end_ts: datetime
) -> dict[str, float]:
    """Skip awake; sum non-awake segments closing on `end_ts`.

    Awake collapses to 0 by construction — the method merges brief arousals
    into the surrounding non-awake stage.
    """
    out = {s: 0.0 for s in STAGES}
    non_awake = [(ts, lvl) for ts, lvl in transitions if lvl != "awake"]
    for i, (ts0, lvl0) in enumerate(non_awake):
        ts1 = non_awake[i + 1][0] if i + 1 < len(non_awake) else end_ts
        if lvl0 in out:
            out[lvl0] += (ts1 - ts0).total_seconds()
    return out


def compute_ratios(
    transition_durs: dict[str, float], official_durs: dict[str, float | None]
) -> dict[str, float | None]:
    """Per-stage `transition / official` ratio.

    Returns None when official is missing or 0 — no defined ratio.
    """
    out: dict[str, float | None] = {}
    for s in STAGES:
        off = official_durs.get(s)
        trans = transition_durs.get(s, 0.0)
        if off is None or off == 0:
            out[s] = None
        else:
            out[s] = trans / off
    return out


def _load_sleep_levels(path: Path) -> list[tuple[datetime, str]]:
    out: list[tuple[datetime, str]] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            ts_str = (row.get("timestamp") or "").strip()
            level = (row.get("level") or "").strip()
            if not ts_str or not level:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            out.append((ts, level))
    out.sort(key=lambda r: r[0])
    return out


def _load_official(path: Path) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            date = (row.get("calendar_date") or "").strip()
            if not date:
                continue
            stages: dict[str, float | None] = {}
            for s in STAGES:
                val = (row.get(f"{s}_sec") or "").strip()
                if not val:
                    stages[s] = None
                else:
                    try:
                        stages[s] = float(val)
                    except ValueError:
                        stages[s] = None
            out[date] = stages
    return out


def collect_nights(
    daily_dir: Path, sleep_official_path: Path
) -> list[NightRow]:
    """Walk daily_dir for *-sleep-levels.csv; pair each with the matching
    sleep-official.csv row; compute naive + smart ratios.

    Skips dates with <2 transitions (no sleep window) or no official row.
    """
    official = _load_official(sleep_official_path)
    nights: list[NightRow] = []
    night_id = 0
    for path in sorted(daily_dir.glob("*-sleep-levels.csv")):
        date = path.name[: -len("-sleep-levels.csv")]
        if date not in official:
            continue
        transitions = _load_sleep_levels(path)
        if len(transitions) < 2:
            continue
        end_ts = transitions[-1][0]
        naive = naive_durations(transitions)
        smart = smart_durations(transitions, end_ts)
        off = official[date]
        night_id += 1
        nights.append(
            NightRow(
                night_id=night_id,
                date=date,
                naive_ratios=compute_ratios(naive, off),
                smart_ratios=compute_ratios(smart, off),
            )
        )
    return nights


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile (numpy default)."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * q
    lo = int(idx)
    hi = lo + 1 if lo + 1 < len(sorted_vals) else lo
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def aggregate(nights: list[NightRow]) -> dict[tuple[str, str], StageStats]:
    """Per (stage, method) → distribution stats across nights."""
    out: dict[tuple[str, str], StageStats] = {}
    for stage in STAGES:
        for method in ("naive", "smart"):
            ratios: list[float] = []
            for n in nights:
                src = n.naive_ratios if method == "naive" else n.smart_ratios
                r = src[stage]
                if r is not None:
                    ratios.append(r)
            ratios.sort()
            if not ratios:
                out[(stage, method)] = StageStats(0, None, None, None, None, None, None)
                continue
            out[(stage, method)] = StageStats(
                n=len(ratios),
                min=ratios[0],
                p25=_quantile(ratios, 0.25),
                median=_quantile(ratios, 0.5),
                p75=_quantile(ratios, 0.75),
                max=ratios[-1],
                mean=mean(ratios),
            )
    return out


def find_outliers(
    nights: list[NightRow], *, threshold: float = 1.0
) -> list[NightRow]:
    """A night is an outlier if any (stage, method) ratio differs from 1.0
    by more than `threshold`. Default threshold matches the design doc's
    per-night outlier criterion."""
    out: list[NightRow] = []
    for n in nights:
        for source in (n.naive_ratios, n.smart_ratios):
            if any(r is not None and abs(r - 1.0) > threshold for r in source.values()):
                out.append(n)
                break
    return out


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}×"


def render_markdown(
    nights: list[NightRow],
    aggregates: dict[tuple[str, str], StageStats],
    outliers: list[NightRow],
    *,
    anonymize: bool = True,
) -> str:
    """Render the validation table as markdown. Default anonymizes outlier
    IDs to `night_N` — never set anonymize=False before committing."""
    lines: list[str] = []
    lines.append(
        f"# Naive vs smart transition math vs sleep-official.csv (n={len(nights)})"
    )
    lines.append("")
    lines.append(
        "Each cell is `transition_seconds / official_seconds`. "
        "1.00× means the transition method matches Garmin Connect's "
        "post-processed value; >1.00× overstates, <1.00× understates."
    )
    lines.append("")
    lines.append("| stage | method | n | min | p25 | median | p75 | max | mean |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for stage in STAGES:
        for method in ("naive", "smart"):
            s = aggregates[(stage, method)]
            lines.append(
                f"| {stage} | {method} | {s.n} | {_fmt(s.min)} | {_fmt(s.p25)} | "
                f"{_fmt(s.median)} | {_fmt(s.p75)} | {_fmt(s.max)} | {_fmt(s.mean)} |"
            )
    lines.append("")
    if outliers:
        lines.append(
            f"## Per-night outliers (|ratio − 1| > 1.0, n={len(outliers)})"
        )
        lines.append("")
        lines.append(
            "| night | awake_naive | deep_naive | light_naive | rem_naive | "
            "deep_smart | light_smart | rem_smart |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for n in outliers:
            ident = f"night_{n.night_id}" if anonymize else n.date
            lines.append(
                f"| {ident} | {_fmt(n.naive_ratios['awake'])} | "
                f"{_fmt(n.naive_ratios['deep'])} | "
                f"{_fmt(n.naive_ratios['light'])} | "
                f"{_fmt(n.naive_ratios['rem'])} | "
                f"{_fmt(n.smart_ratios['deep'])} | "
                f"{_fmt(n.smart_ratios['light'])} | "
                f"{_fmt(n.smart_ratios['rem'])} |"
            )
        lines.append("")
    else:
        lines.append("## Per-night outliers")
        lines.append("")
        lines.append("None.")
        lines.append("")
    return "\n".join(lines)

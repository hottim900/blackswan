"""End-to-end strength training quickstart.

Run:

    uv run python -m examples.quickstart_strength

If ``examples/data/synthetic_baseline.fit`` and ``synthetic_recent.fit`` are
missing the script regenerates them by invoking
``synthetic_strength_baseline.py`` and ``synthetic_strength_recent.py``.

Replace the synthetic paths with your own FITs and re-run for your data.
"""

from __future__ import annotations

from pathlib import Path

from blackswan.strength_metrics import compare_strength_sessions
from examples.synthetic_strength_baseline import OUT_PATH as BASELINE_PATH
from examples.synthetic_strength_baseline import build_baseline_fit
from examples.synthetic_strength_recent import OUT_PATH as RECENT_PATH
from examples.synthetic_strength_recent import build_recent_fit


def _ensure_fixtures() -> tuple[Path, Path]:
    """V2.23: auto-regenerate synthetic FITs when absent. Mandatory — the
    quickstart must run from a clean checkout without manual setup."""
    if not BASELINE_PATH.exists():
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_bytes(build_baseline_fit())
        print(f"  generated {BASELINE_PATH}")
    if not RECENT_PATH.exists():
        RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECENT_PATH.write_bytes(build_recent_fit())
        print(f"  generated {RECENT_PATH}")
    return BASELINE_PATH, RECENT_PATH


def main() -> None:
    print("=== Strength quickstart ===")
    print("Loading synthetic FITs (auto-generated if absent)...")
    baseline_path, recent_path = _ensure_fixtures()

    print(f"\nBaseline: {baseline_path}")
    print(f"Recent:   {recent_path}")

    print("\n=== Comparison ===")
    report = compare_strength_sessions(baseline_path, recent_path)
    print(report.summary())

    print("\n=== Replace with your own data ===")
    print(
        "  Drop two strength FITs into examples/data/ as synthetic_baseline.fit "
        "+ synthetic_recent.fit (or edit this file's paths) and re-run."
    )


if __name__ == "__main__":
    main()

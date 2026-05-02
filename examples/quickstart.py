"""End-to-end quickstart example.

Replace the FIT paths with your own and run:
    python examples/quickstart.py

This example assumes:
- baseline.fit: 4 work laps (laps 1-4), no warm-up lap
- recent.fit: 6 work laps (laps 2-7), with lap 0 as warm-up and lap 8 as cool-down
- baseline trial 0 = first work trial (no exclusions)
- recent trial 0 = HR sensor failure (exclude), trial 4 = mid-session outlier (exclude)
"""

from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

from blackswan.cc_metrics import TrialStats, compare_sessions
from blackswan.segment_uphill import find_uphill_trials_in_lap


def session_to_trials(fit_path: Path, work_lap_indices: list[int]) -> list[TrialStats]:
    """Read a FIT, segment specific laps into trials (alt min → alt max)."""
    msgs, _ = Decoder(Stream.from_file(str(fit_path))).read()
    laps = msgs["lap_mesgs"]
    records = msgs["record_mesgs"]

    trials: list[TrialStats] = []
    for i in work_lap_indices:
        s = find_uphill_trials_in_lap(records, laps[i])
        if s is None:
            print(f"  ! lap {i}: no climb segment found (skipping)")
            continue
        trials.append(TrialStats(
            dur=s["dur"], dist=s["dist"], kmh=s["kmh"], grade=s["grade"],
            start_hr=s["start_hr"], avg_hr=s["avg_hr"], max_hr=s["max_hr"], cc=s["cc"],
        ))
        print(f"  lap {i}: dur={s['dur']:.0f}s dist={s['dist']:.0f}m "
              f"kmh={s['kmh']:.2f} aHR={s['avg_hr']:.1f} mHR={s['max_hr']} CC={s['cc']:.2f}")
    return trials


def main() -> None:
    baseline_path = Path("examples/data/baseline.fit")
    recent_path = Path("examples/data/recent.fit")

    if not baseline_path.exists() or not recent_path.exists():
        print(f"Place your FITs at {baseline_path} and {recent_path}")
        print("Then re-run.  See examples/README.md for setup.")
        return

    print("=== Baseline session ===")
    baseline = session_to_trials(baseline_path, work_lap_indices=[0, 1, 2, 3])

    print("\n=== Recent session ===")
    recent = session_to_trials(recent_path, work_lap_indices=[1, 2, 3, 4, 5, 6])

    print("\n=== Comparison ===")
    report = compare_sessions(
        baseline_trials=baseline,
        recent_trials=recent,
        excluded_indices_recent={0, 4},  # adjust based on your sensor-artifact / outlier analysis
    )
    print(report.summary())


if __name__ == "__main__":
    main()

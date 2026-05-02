"""Single-event forensic alignment: pull HR / respiration / stress directly
from FIT + CSV sources for a specific SpO2 desat window, with a ±10 min
context buffer. Used to decide whether a sustained desat event looks
obstructive (HR rise / arousal), central (rate drop / pause), or artifact.

This bypasses `parse_daily_fit.py` for HR because the current parser's
timestamp_16 reconstruction has a Unix/FIT epoch mix-up that drops sleep-
period HR from the CSV. Here we use the simpler fallback (`prev_ts`
inheritance) that the Garmin SDK already walks correctly.

Usage:
    python -m blackswan.forensic_spo2_event \\
        garmin/raw-fit/YYYY-MM-DD/ \\
        garmin/timeseries/daily/ \\
        YYYY-MM-DDThh:mm:ss+08:00 \\
        YYYY-MM-DDThh:mm:ss+08:00 \\
        > out.txt
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

from blackswan._sleep import LOCAL_TZ, stage_at


def _local(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(LOCAL_TZ)


def extract_hr(day_dir: Path) -> list[tuple[datetime, int]]:
    """Pull HR from monitoring_mesgs using lenient prev_ts inheritance.

    This is the behaviour we want for sleep HR: when a HR event carries
    only timestamp_16 and the Garmin SDK did not populate `timestamp`,
    fall back to the last known good timestamp (usually the preceding
    activity_type event a few seconds earlier)."""
    rows = []
    for fit in sorted(day_dir.glob("*.fit")):
        try:
            msgs, _ = Decoder(Stream.from_file(str(fit))).read()
        except Exception as exc:
            print(f"# skip {fit.name}: {exc}", file=sys.stderr)
            continue
        prev_ts = None
        for m in msgs.get("monitoring_mesgs", []):
            ts = m.get("timestamp") or prev_ts
            if ts:
                prev_ts = ts
            hr = m.get("heart_rate")
            if hr is not None and ts is not None:
                rows.append((_local(ts), hr))
    seen = {}
    for t, v in rows:
        seen[t.replace(second=0, microsecond=0)] = v
    return sorted(seen.items())


def load_csv_ts(path: Path, value_cols: list[str]) -> list[tuple[datetime, tuple]]:
    out = []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            ts = row.get("timestamp")
            if not ts:
                continue
            out.append((datetime.fromisoformat(ts),
                        tuple(row.get(c) for c in value_cols)))
    return out


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        return 1
    day_dir = Path(sys.argv[1])
    daily_csv_dir = Path(sys.argv[2])
    start = datetime.fromisoformat(sys.argv[3])
    end = datetime.fromisoformat(sys.argv[4])
    date = day_dir.name  # YYYY-MM-DD

    hr = [(t, v) for t, v in extract_hr(day_dir) if start <= t <= end]

    spo2 = [(t, v) for t, v in load_csv_ts(
        daily_csv_dir / f"{date}-spo2.csv",
        ["spo2_percent", "confidence"]) if start <= t <= end]
    resp = [(t, v) for t, v in load_csv_ts(
        daily_csv_dir / f"{date}-respiration.csv",
        ["respiration_rate_brpm"]) if start <= t <= end]
    stress = [(t, v) for t, v in load_csv_ts(
        daily_csv_dir / f"{date}-stress.csv",
        ["stress_level"]) if start <= t <= end]
    levels = [(ts, lvl) for ts, (lvl,) in load_csv_ts(
        daily_csv_dir / f"{date}-sleep-levels.csv", ["level"])]

    # merge by minute
    minutes: dict[datetime, dict] = {}
    for rows, key in [(hr, "hr"), (spo2, "spo2"), (resp, "resp"), (stress, "stress")]:
        for t, v in rows:
            m = t.replace(second=0, microsecond=0)
            d = minutes.setdefault(m, {})
            if key == "spo2":
                d["spo2"], d["conf"] = v
            elif key == "hr":
                d["hr"] = v
            elif key == "resp":
                d["resp"] = v[0]
            else:
                d["stress"] = v[0]

    print(f"# Forensic timeline for {start.isoformat()} → {end.isoformat()}")
    print("# stage timeline: "
          + ", ".join(f"{ts.strftime('%H:%M')} {lvl}" for ts, lvl in levels
                      if start - timedelta(minutes=30) <= ts <= end + timedelta(minutes=30)))
    print()
    print(f"{'time':5} {'stage':8} {'SpO2':>5} {'conf':>4} "
          f"{'HR':>4} {'resp':>5} {'stress':>6}")
    print("-" * 55)
    for m in sorted(minutes):
        d = minutes[m]
        t = m.strftime("%H:%M")
        stg = stage_at(m, levels, default="-")
        spo = d.get("spo2") or "-"
        conf = d.get("conf") or "-"
        hr_v = d.get("hr") or "-"
        rp = f"{float(d['resp']):.1f}" if d.get("resp") else "-"
        st = d.get("stress") or "-"
        mark = ""
        try:
            if int(spo) < 85:
                mark = " *"
        except (ValueError, TypeError):
            pass
        print(f"{t:5} {stg:8} {str(spo):>5} {str(conf):>4} "
              f"{str(hr_v):>4} {rp:>5} {str(st):>6}{mark}")

    # Summary stats for desat period (<85% only)
    desat = [d for m, d in minutes.items()
             if d.get("spo2") and int(d["spo2"]) < 85]
    if desat:
        hrs = [d["hr"] for d in desat if d.get("hr")]
        rps = [float(d["resp"]) for d in desat if d.get("resp")]
        sts = [int(d["stress"]) for d in desat if d.get("stress")]
        print()
        print(f"# Desat window (<85%): {len(desat)} minutes")
        if hrs:
            print(f"#   HR:         min={min(hrs)}  max={max(hrs)}  mean={sum(hrs)/len(hrs):.1f}")
        if rps:
            print(f"#   resp (brpm): min={min(rps):.1f}  max={max(rps):.1f}  "
                  f"mean={sum(rps)/len(rps):.1f}  SD={(sum((x-sum(rps)/len(rps))**2 for x in rps)/len(rps))**0.5:.2f}")
        if sts:
            print(f"#   stress:      min={min(sts)}  max={max(sts)}  mean={sum(sts)/len(sts):.1f}")

    # Pre vs during vs post comparison
    def _avg(rows, getter):
        vals = [getter(d) for d in rows if getter(d) is not None]
        return sum(vals) / len(vals) if vals else None

    pre = [d for m, d in minutes.items()
           if d.get("spo2") and int(d["spo2"]) >= 90 and m < min(
               (k for k, v in minutes.items() if v.get("spo2") and int(v["spo2"]) < 85),
               default=end)]
    post = [d for m, d in minutes.items()
            if d.get("spo2") and int(d["spo2"]) >= 90 and m > max(
                (k for k, v in minutes.items() if v.get("spo2") and int(v["spo2"]) < 85),
                default=start)]
    if pre and post and desat:
        print()
        print(f"# Pre ({len(pre)} min) vs Desat ({len(desat)} min) vs Post ({len(post)} min):")
        for label, getter, fmt in [
            ("HR", lambda d: int(d["hr"]) if d.get("hr") else None, ".1f"),
            ("resp", lambda d: float(d["resp"]) if d.get("resp") else None, ".1f"),
            ("stress", lambda d: int(d["stress"]) if d.get("stress") else None, ".1f"),
        ]:
            pa, da, poa = _avg(pre, getter), _avg(desat, getter), _avg(post, getter)
            if pa and da and poa:
                print(f"#   {label:6}: pre={pa:{fmt}}  desat={da:{fmt}}  post={poa:{fmt}}  "
                      f"Δ_during-pre={da - pa:+.1f}  Δ_post-pre={poa - pa:+.1f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One-shot inventory: strength FIT corpus by time-of-day band x recent weeks.

Aggregate output only (no fit_path, no exact start_time). PII-safe — the CSV
is shareable as evidence; the path-bearing scan happens only in memory.

Decides the v0.4.0 issue-#1-P3 branch:

    AND_GATE_UNLOCKED = (n_total >= 10) AND (each of morning/afternoon/evening
                        has >= 1 session within the most recent 4-week window)

    True  -> ship correction branch (local_hour_correction_bpm formula).
    False -> ship warning-only branch (expand warning text + TODOS unblock).

Usage:

    uvx --with pandas python scripts/inventory_strength_corpus.py \
        --root /path/to/your/garmin/archive

Fails closed on any unreadable directory: if even one dir under --root errors
during walk, the script exits 2 and you must NOT trust the count.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

from blackswan._time import LOCAL_TZ
from blackswan.parse_strength_fit import parse_strength_fit


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path, help="Root dir to scan for *.fit")
    p.add_argument("--out", default=Path("strength-inventory.csv"), type=Path)
    args = p.parse_args()

    unreadable_dirs: list[str] = []

    def _onerror(err: OSError) -> None:
        # OSError.__str__ embeds the offending path, which under --root may
        # encode workout dates / device IDs / etc. Keep the OS message only.
        unreadable_dirs.append(err.strerror or "I/O error")

    fit_paths: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(args.root, onerror=_onerror):
        for fn in filenames:
            if fn.lower().endswith(".fit"):
                fit_paths.append(Path(dirpath) / fn)

    if unreadable_dirs:
        print(
            f"FAIL-CLOSED: {len(unreadable_dirs)} unreadable dir(s) under --root; "
            "do NOT trust this inventory.",
            file=sys.stderr,
        )
        # De-duplicated OS messages — no paths.
        for msg in sorted(set(unreadable_dirs)):
            print(f"  {msg}", file=sys.stderr)
        sys.exit(2)

    rows = []
    for i, fit_path in enumerate(fit_paths):
        try:
            sess = parse_strength_fit(fit_path)
        except Exception as e:
            # OSError covers FileNotFoundError + PermissionError; ValueError
            # covers parse_strength_fit's structured raises; broad Exception
            # is intentional — the inventory is a one-shot scan and a single
            # corrupt FIT must not stop the count for the remaining N-1 files.
            # KEEP PII OFF stderr: OSError.__str__ includes the offending path,
            # so we strip to .strerror for OSError and to the type name for
            # everything else.
            if isinstance(e, OSError):
                detail = e.strerror or "I/O error"
            elif isinstance(e, ValueError):
                detail = str(e)  # parse_strength_fit raises carry no path
            else:
                detail = "unexpected parser error"
            print(f"[skip] {type(e).__name__}: {detail}", file=sys.stderr)
            continue
        local = sess.start_time.astimezone(LOCAL_TZ)
        rows.append({
            "session_id": f"sess_{i:04d}",
            "local_date": local.date().isoformat(),
            "local_hour": local.hour,
        })

    if not rows:
        print(f"WARN: zero strength FITs parseable under {args.root}", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(rows)
    df["local_date"] = pd.to_datetime(df["local_date"])
    df["band"] = pd.cut(
        df["local_hour"],
        bins=[0, 11, 17, 24],
        labels=["morning", "afternoon", "evening"],
        right=False,
    )
    df["week_offset"] = (df["local_date"].max() - df["local_date"]).dt.days // 7

    latest = df["local_date"].max()
    recent_4wk = df[df["local_date"] >= latest - pd.Timedelta(days=28)]
    bands_covered_recent = recent_4wk["band"].value_counts().reindex(
        ["morning", "afternoon", "evening"], fill_value=0
    )
    n_total = len(df)
    decoupled = bool(bands_covered_recent.ge(1).all())
    unlocked = n_total >= 10 and decoupled

    out_df = df[["session_id", "band", "week_offset"]]
    out_df.to_csv(args.out, index=False)
    print(
        f"n_total={n_total}, "
        f"recent_4wk_bands={dict(bands_covered_recent)}, "
        f"decoupled={decoupled}, "
        f"AND_GATE_UNLOCKED={unlocked}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

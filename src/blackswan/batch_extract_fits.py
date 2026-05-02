"""Extract per-day FITs from a Garmin GDPR bulk export and organise by date.

The bulk export stores 7000+ per-day FITs inside a nested zip at
`DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_*.zip`, with filenames like
`<account>_<random_id>.fit` — no date in the name. This script opens
each FIT, reads `file_id_mesgs.time_created`, buckets by UTC+8 local date, and
writes them to `garmin/raw-fit/YYYY-MM-DD/<type>_<id>.fit` — ready for
`parse_daily_fit.py`.

Usage:
    python -m blackswan.batch_extract_fits \\
        garmin/bulk-exports/YYYY-MM-DD-complete-export.zip \\
        garmin/raw-fit/ \\
        [--dates YYYY-MM-DD,YYYY-MM-DD,...]    # only these dates
        [--range YYYY-MM-DD,YYYY-MM-DD]        # date range inclusive
        [--all]                                 # every date seen in the export

One of --dates / --range / --all is required. Files already present (same name)
are skipped so re-runs are cheap.
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

from blackswan._sleep import LOCAL_TZ


def _local_date(ts: datetime) -> date:
    """Convert a tz-aware or naive UTC datetime to UTC+8 local date."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(LOCAL_TZ).date()


def _parse_date_list(s: str) -> set[date]:
    return {date.fromisoformat(x.strip()) for x in s.split(",") if x.strip()}


def _parse_range(s: str) -> set[date]:
    start, end = (date.fromisoformat(x.strip()) for x in s.split(","))
    if start > end:
        raise ValueError(f"--range start ({start}) must be ≤ end ({end})")
    days = (end - start).days
    return {start + timedelta(days=i) for i in range(days + 1)}


def _rename(original: str, fid: dict) -> str:
    """Give the file a human-readable name: `{time_created_hhmm}_{TYPE}.fit`.

    Garmin's raw names (`{email}_{id}.fit`) carry no information. We keep the
    ID suffix for uniqueness but prefix with type so the folder is glanceable."""
    stem = original.split("/")[-1].replace("@", "_")
    # Strip .fit so we can append a type tag
    if stem.endswith(".fit"):
        stem = stem[:-4]
    fit_type = fid.get("type")
    if isinstance(fit_type, str):
        tag = fit_type.upper()
    else:
        tag = f"TYPE{fit_type}"
    return f"{tag}_{stem}.fit"


def extract(bulk_zip: Path, out_dir: Path, target: set[date] | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_dates: Counter[date] = Counter()
    written: defaultdict[date, int] = defaultdict(int)
    skipped_existing = 0
    skipped_not_target = 0
    decode_errors = 0

    with zipfile.ZipFile(bulk_zip) as outer:
        inner_names = [
            n for n in outer.namelist()
            if "DI-Connect-Uploaded-Files/UploadedFiles" in n and n.endswith(".zip")
        ]
        if not inner_names:
            print("No UploadedFiles_*.zip in bulk export — nothing to do.",
                  file=sys.stderr)
            return

        for inner_name in inner_names:
            print(f"Scanning {inner_name.split('/')[-1]}...")
            with outer.open(inner_name) as f:
                inner_bytes = f.read()
            with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
                fits = inner.namelist()
                print(f"  {len(fits)} FIT files")
                for i, name in enumerate(fits, 1):
                    if i % 500 == 0:
                        print(f"  progress {i}/{len(fits)}")
                    with inner.open(name) as f:
                        data = f.read()
                    try:
                        msgs, _ = Decoder(Stream.from_byte_array(data)).read()
                    except Exception as exc:
                        decode_errors += 1
                        print(f"  decode fail {name}: {exc}", file=sys.stderr)
                        continue
                    fid = (msgs.get("file_id_mesgs") or [{}])[0]
                    tc = fid.get("time_created")
                    if tc is None:
                        decode_errors += 1
                        continue
                    d = _local_date(tc)
                    seen_dates[d] += 1
                    if target is not None and d not in target:
                        skipped_not_target += 1
                        continue
                    day_dir = out_dir / d.isoformat()
                    day_dir.mkdir(parents=True, exist_ok=True)
                    out_path = day_dir / _rename(name, fid)
                    if out_path.exists():
                        skipped_existing += 1
                        continue
                    out_path.write_bytes(data)
                    written[d] += 1

    print()
    print(f"Scanned {sum(seen_dates.values())} FITs across {len(seen_dates)} days.")
    if seen_dates:
        print(f"  date range: {min(seen_dates)} → {max(seen_dates)}")
    print(f"Wrote {sum(written.values())} new files into {len(written)} day folders.")
    if target is not None:
        missing = target - set(seen_dates)
        if missing:
            print(f"WARN: {len(missing)} requested dates had no FITs: "
                  f"{sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}")
    if skipped_existing:
        print(f"  skipped {skipped_existing} already-present files")
    if skipped_not_target:
        print(f"  skipped {skipped_not_target} out-of-target-range files")
    if decode_errors:
        print(f"  {decode_errors} decode errors (see stderr)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bulk_zip", type=Path)
    p.add_argument("out_dir", type=Path)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dates", type=_parse_date_list,
                   help="Comma-separated YYYY-MM-DD dates")
    g.add_argument("--range", dest="date_range", type=_parse_range,
                   help="YYYY-MM-DD,YYYY-MM-DD inclusive range")
    g.add_argument("--all", action="store_true")
    args = p.parse_args()

    if args.all:
        target = None
    elif args.dates:
        target = args.dates
    else:
        target = args.date_range

    extract(args.bulk_zip, args.out_dir, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())

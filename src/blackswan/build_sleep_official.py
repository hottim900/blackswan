"""Build sleep-official.csv — SSOT for sleep stage durations and overnight metrics.

Merges bulk-export-derived sleep-all.csv with manually-downloaded Garmin Connect
single-day Chinese CSVs (*睡眠.csv, garmin/sleep/YYYY-MM-DD.csv) to cover dates
newer than the last bulk export.

Why this exists: Garmin FIT files emit raw classifier output; Garmin Connect UI
shows post-processed values. sleep-all.csv already carries the UI-authoritative
stage durations (deep_sec/light_sec/rem_sec/awake_sec), but a single bulk export
lags by months. Manual single-day downloads from the Connect web UI fill the gap.

Resolution rules:
- Bulk wins for overlapping dates (bulk = ENHANCED_CONFIRMED_FINAL authority).
  Manual row with same date is skipped; key fields compared and warn on >1min /
  >1 score diff.
- Between two manual files for the same date: if byte-identical, drop duplicate;
  otherwise newer mtime wins (user likely re-downloaded to correct).
- confirmation_type column reused to signal manual provenance: value "MANUAL_CSV"
  (distinct from existing ENHANCED_CONFIRMED_FINAL / MANUALLY_CONFIRMED).

Usage:
    uvx python -m blackswan.build_sleep_official \\
        garmin/timeseries/history/sleep-all.csv \\
        --manual-dirs <repo-root> <repo-root>/garmin/sleep \\
        --out garmin/timeseries/history/sleep-official.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from datetime import date
from pathlib import Path

from blackswan._sleep import SLEEP_COLS

SENTINEL = "睡眠分數 1 天"

# Note the subscript inconsistency in Garmin's own Chinese CSV keys:
#   '平均 SpO₂' uses Unicode subscript 2 (U+2082)
#   '最低 SpO2'      uses plain ASCII 2
CHINESE_KEY_MAP = {
    "深層睡眠持續時間": "deep_sec",
    "淺層睡眠持續時間": "light_sec",
    "REM 持續時間": "rem_sec",
    "清醒時間": "awake_sec",
    "睡眠分數": "overall_score",
    "壓力 平均": "avg_sleep_stress",
    "不安穩狀況": "restless_moment_count",
    "平均跨日心率": "avg_sleep_hr",
    "呼吸變動": "breathing_disruption_severity",
    "平均 SpO₂": "avg_sleep_spo2",
    "最低 SpO2": "lowest_sleep_spo2",
    "平均呼吸速率": "avg_respiration",
    "最低呼吸": "lowest_respiration",
}

# Keys the parser sees but deliberately doesn't collect — either derivable
# (睡眠持續時間 = deep+light+rem) or owned by another history CSV.
CHINESE_KEYS_IGNORED = {
    "日期",
    "睡眠持續時間",
    "品質",
    "靜止心率",
    "身體能量指數變化",
    "平均夜間HRV",
    "7 天平均 HRV",
    "睡眠分數 1 天",
    "睡眠分數因素",
    "睡眠時間軸指標",
}

BREATHING_MAP = {
    "很少": "NONE",
    "一些": "LOW",
    "較多": "MEDIUM",
    "明顯": "HIGH",
}

_HM_RE = re.compile(r"(?:(\d+)時\s*)?(\d+)\s*分")


def parse_hm_to_sec(val, zero_on_dash=False):
    """Parse '1時 21分' / '21分' / '--' / '' to seconds.

    zero_on_dash=True for 清醒時間 (Garmin's '--' convention = 0 awake, matches
    bulk's awake_sec=0 for same nights). zero_on_dash=False everywhere else so
    we preserve the 'not measured' signal for partial-data nights.
    """
    val = val.strip() if val else ""
    if not val:
        return None
    if val == "--":
        return 0 if zero_on_dash else None
    m = _HM_RE.match(val)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mm = int(m.group(2))
    return h * 3600 + mm * 60


def parse_suffixed(val, suffix="", *, cast=int):
    val = val.strip() if val else ""
    if not val or val == "--":
        return None
    if suffix:
        val = val.removesuffix(suffix).strip()
    try:
        return cast(val)
    except ValueError:
        return None


def parse_chinese_single_day(path, warnings):
    """Parse a single Chinese single-day sleep CSV.

    Returns (calendar_date, row_dict) or None on failure.
    """
    try:
        with path.open(encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    except Exception as exc:
        warnings.append(f"{path.name}: read failed ({exc})")
        return None

    if not rows or not rows[0]:
        warnings.append(f"{path.name}: empty or malformed")
        return None

    if rows[0][0].strip() != SENTINEL:
        warnings.append(
            f"{path.name}: sentinel check failed "
            f"(expected {SENTINEL!r}, got {rows[0][0]!r})"
        )
        return None

    kv = {}
    for row in rows:
        if not row or len(row) < 2:
            continue
        key = row[0].strip()
        if not key:
            continue
        val = row[1].strip()
        if key not in kv:
            kv[key] = val

    date_str = kv.get("日期", "").strip()
    if not date_str:
        warnings.append(f"{path.name}: missing 日期 row")
        return None
    try:
        date.fromisoformat(date_str)
    except ValueError:
        warnings.append(f"{path.name}: bad 日期 format: {date_str!r}")
        return None

    row_dict = {col: "" for col in SLEEP_COLS}
    row_dict["calendar_date"] = date_str

    for ckey, cval in kv.items():
        if ckey in CHINESE_KEYS_IGNORED:
            continue
        mapped = CHINESE_KEY_MAP.get(ckey)
        if not mapped:
            warnings.append(f"{path.name}: unknown key {ckey!r} (val={cval!r}), skipped")
            continue

        if mapped == "awake_sec":
            v = parse_hm_to_sec(cval, zero_on_dash=True)
        elif mapped in ("deep_sec", "light_sec", "rem_sec"):
            v = parse_hm_to_sec(cval, zero_on_dash=False)
        elif mapped in ("overall_score", "restless_moment_count"):
            v = parse_suffixed(cval)
        elif mapped == "avg_sleep_stress":
            v = parse_suffixed(cval, cast=float)
        elif mapped == "avg_sleep_hr":
            v = parse_suffixed(cval, "bpm")
        elif mapped == "breathing_disruption_severity":
            stripped = cval.strip()
            if not stripped or stripped == "--":
                v = None
            else:
                v = BREATHING_MAP.get(stripped)
                if v is None:
                    warnings.append(f"{path.name}: unknown 呼吸變動 value {cval!r}")
        elif mapped in ("avg_sleep_spo2", "lowest_sleep_spo2"):
            v = parse_suffixed(cval, "%")
        elif mapped == "avg_respiration":
            v = parse_suffixed(cval, "brpm", cast=float)
        elif mapped == "lowest_respiration":
            v = parse_suffixed(cval, "brpm")
        else:
            v = cval

        if v is not None:
            row_dict[mapped] = v

    row_dict["confirmation_type"] = "MANUAL_CSV"
    row_dict["retro"] = "False"

    return date_str, row_dict


def _file_sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _collect_manual_files(dirs):
    """Single-day Chinese CSVs only: 0*睡眠.csv or YYYY-MM-DD.csv.

    monthly-*.csv excluded (tabular format — sentinel would reject anyway,
    but skipping here saves a read+warn per run).
    """
    files = []
    ymd_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.csv$")
    for d in dirs:
        dp = Path(d)
        if not dp.is_dir():
            continue
        for p in dp.iterdir():
            if not p.is_file() or p.suffix != ".csv":
                continue
            name = p.name
            if name.startswith("monthly-"):
                continue
            if "睡眠" in name or ymd_pattern.match(name):
                files.append(p)
    return files


def _normalize_row(row):
    return ",".join(" ".join((v or "").split()) for v in row.values())


def build(sleep_all_path, manual_dirs, out_path):
    warnings = []

    by_date = {}
    bulk_dup_detected = 0
    with sleep_all_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        if header != SLEEP_COLS:
            print(
                "ERROR: sleep-all.csv header mismatch\n"
                f"  expected: {SLEEP_COLS}\n"
                f"  got:      {header}",
                file=sys.stderr,
            )
            return 1
        for row in reader:
            date = row["calendar_date"]
            if date in by_date:
                bulk_dup_detected += 1
                if _normalize_row(by_date[date]) == _normalize_row(row):
                    print(
                        f"info: bulk duplicate row for {date}, identical content, skipping",
                        file=sys.stderr,
                    )
                else:
                    warnings.append(
                        f"bulk has conflicting duplicate for {date}, keeping first"
                    )
                continue
            by_date[date] = row

    bulk_n = len(by_date)

    manual_files = _collect_manual_files(manual_dirs)

    parsed_by_date = {}
    manual_parse_fail = 0
    manual_skip_dup_exact = 0
    manual_conflict_resolved = 0

    for p in sorted(manual_files):
        result = parse_chinese_single_day(p, warnings)
        if result is None:
            manual_parse_fail += 1
            continue
        date, row_dict = result
        fh = _file_sha256(p)
        mtime = p.stat().st_mtime

        if date not in parsed_by_date:
            parsed_by_date[date] = (p, row_dict, fh, mtime)
            continue

        prev_path, prev_row, prev_fh, prev_mtime = parsed_by_date[date]
        if fh == prev_fh:
            print(
                f"info: exact duplicate file {p.name} == {prev_path.name} "
                f"(date {date}), skipping",
                file=sys.stderr,
            )
            manual_skip_dup_exact += 1
            continue

        if mtime > prev_mtime:
            warnings.append(
                f"conflict for {date}: {p.name} (mtime newer) replaces {prev_path.name}"
            )
            parsed_by_date[date] = (p, row_dict, fh, mtime)
        else:
            warnings.append(
                f"conflict for {date}: keeping {prev_path.name} (mtime newer), "
                f"skipping {p.name}"
            )
        manual_conflict_resolved += 1

    manual_new = 0
    manual_skip_bulk = 0
    for date, (path, row_dict, _, _) in sorted(parsed_by_date.items()):
        if date in by_date:
            bulk = by_date[date]
            for col in ("deep_sec", "light_sec", "rem_sec", "awake_sec", "overall_score"):
                m_val = row_dict.get(col, "")
                b_val = bulk.get(col, "")
                if m_val == "" or b_val == "":
                    continue
                try:
                    m_num = int(float(m_val))
                    b_num = int(float(b_val))
                except ValueError:
                    continue
                if col.endswith("_sec"):
                    if abs(m_num - b_num) > 60:
                        warnings.append(
                            f"{date} {col}: manual={m_num}s vs bulk={b_num}s (>1min diff)"
                        )
                else:
                    if abs(m_num - b_num) > 1:
                        warnings.append(
                            f"{date} {col}: manual={m_num} vs bulk={b_num} (>1 diff)"
                        )
            manual_skip_bulk += 1
        else:
            by_date[date] = row_dict
            manual_new += 1

    out_rows = [by_date[d] for d in sorted(by_date)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SLEEP_COLS)
        writer.writeheader()
        writer.writerows(out_rows)

    print(
        f"bulk={bulk_n} bulk_dup_detected={bulk_dup_detected} "
        f"manual_new={manual_new} manual_skip_bulk={manual_skip_bulk} "
        f"manual_skip_dup_exact={manual_skip_dup_exact} "
        f"manual_conflict_resolved={manual_conflict_resolved} "
        f"manual_parse_fail={manual_parse_fail} "
        f"warns={len(warnings)} output_rows={len(out_rows)}"
    )
    for w in warnings:
        print(f"  warn: {w}", file=sys.stderr)

    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("sleep_all", type=Path,
                   help="path to sleep-all.csv (bulk export output)")
    p.add_argument("--manual-dirs", nargs="+", type=Path, required=True,
                   help="dirs to scan for single-day Chinese CSVs")
    p.add_argument("--out", type=Path, required=True,
                   help="output path for sleep-official.csv")
    args = p.parse_args()
    return build(args.sleep_all, args.manual_dirs, args.out)


if __name__ == "__main__":
    sys.exit(main())

"""T-FIT-1: synthetic FIT generator determinism + PII guard.

Per V2.18 / TD-7: garmin_fit_sdk Encoder output must be byte-identical
across runs and must not leak host fingerprints (machine name, home dir,
real serial numbers).
"""

from __future__ import annotations

import os
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

from examples.synthetic_strength_baseline import build_baseline_fit
from examples.synthetic_strength_recent import build_recent_fit


def test_baseline_fit_is_deterministic():
    """Same input → byte-identical output, no clock / random / machine id."""
    bytes1 = build_baseline_fit()
    bytes2 = build_baseline_fit()
    assert bytes1 == bytes2


def test_recent_fit_is_deterministic():
    bytes1 = build_recent_fit()
    bytes2 = build_recent_fit()
    assert bytes1 == bytes2


def test_synthetic_fits_carry_no_host_fingerprint():
    """No nodename, no home dir, no /home/* path leaks into the FIT bytes."""
    blob = build_baseline_fit() + build_recent_fit()
    fit_str = blob.decode("latin-1", errors="ignore")

    nodename = os.uname().nodename
    if nodename:
        assert nodename not in fit_str

    home = os.path.expanduser("~")
    if home and home != "/":
        assert home not in fit_str

    # Catches any /home/<user>/ path on any machine, not just the author's.
    assert "/home/" not in fit_str


def test_synthetic_fits_use_year_2000_timestamps():
    """Synthetic timestamps must be in year 2000 (PII guard)."""
    blob = build_baseline_fit()
    msgs, _ = Decoder(Stream.from_byte_array(blob)).read(convert_datetimes_to_dates=False)

    # session start_time is a raw FIT epoch int with convert_datetimes_to_dates=False
    sess = msgs.get("session_mesgs", [{}])[0]
    raw_start = sess.get("start_time")
    assert raw_start is not None
    # FIT epoch = 1989-12-31 UTC; year 2000 = ~315532800 + 31536000 ≈ 320000000
    # Year 2000 inclusive range: ~315532800 (Jan 1) - 347155200 (Dec 31)
    assert 315_000_000 <= raw_start <= 348_000_000


def test_synthetic_fits_use_development_serial():
    """No real device serial leaks via device_info — for both generators."""
    for build in (build_baseline_fit, build_recent_fit):
        blob = build()
        msgs, _ = Decoder(Stream.from_byte_array(blob)).read(convert_datetimes_to_dates=False)
        for d in msgs.get("device_info_mesgs", []):
            sn = d.get("serial_number")
            assert sn in (None, 0), f"{build.__name__}: serial_number={sn}"


def test_baseline_and_recent_differ_by_design():
    """The two synthetic sessions must differ — they exercise the cold-start
    artifact pair. If they collide, the demo loses its point."""
    assert build_baseline_fit() != build_recent_fit()


def test_synthetic_baseline_roundtrips_to_strength_session(tmp_path: Path):
    """Bytes → file → parse_strength_fit → StrengthSession with active sets."""
    from blackswan.parse_strength_fit import parse_strength_fit

    p = tmp_path / "baseline.fit"
    p.write_bytes(build_baseline_fit())

    sess = parse_strength_fit(p)
    assert sess.sport == "training"
    assert sess.sub_sport == "strength_training"
    assert sess.device_product == "vivoactive5"
    active = [s for s in sess.sets if s.set_type == "active"]
    assert len(active) >= 6  # 1 warmup + ≥5 work sets

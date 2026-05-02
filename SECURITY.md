# Security Policy

## Reporting a vulnerability

Email **hottim900@gmail.com** with details. Do **not** open a public
issue for vulnerabilities involving personal data, credentials, or
exploits. Expect a first reply within ~7 days.

## Personal data hygiene

This pipeline parses Garmin GDPR exports and per-day FIT files that
contain identifiable health data (HR series, GPS tracks, sleep windows,
HRV, weight, age). **Do not paste FIT files, CSV exports, or analysis
output into issues or PR descriptions** — even redacted excerpts often
retain GPS coordinates, sleep windows, or HR signatures that uniquely
identify a person.

If you need to share an example to reproduce a bug:

- Use the synthetic-data quickstart in `examples/quickstart.py`
- Or paste only the structural shape (column names, field types, row
  counts) — never values
- Or email to share data privately

`.gitignore` blocks `*.fit`, `*.csv`, `garmin/`, and `examples/data/`
from accidental commits, and `.claude/hooks/scan-pii.sh` (mirrored as
`.git/hooks/pre-commit`) scans staged diffs for date / time / email /
data-file leaks. Both are local-only — contributors are responsible
for their own working copy.

## Supported versions

Alpha. Only the current `main` branch receives fixes.

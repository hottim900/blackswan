# Examples

Real Garmin FIT files contain personal data (GPS, HR, HRV, weight, age, biometric trends) — they don't go in this public repo. The examples here use **synthetic data only** or **public demo FITs** with no personal information.

## Files in this directory

- `quickstart.py` — End-to-end usage example with placeholder FIT paths. Replace the paths with your own to run.

## Adding your own data

Create a `examples/data/` directory (gitignored) and put your FITs there:

```
examples/
└── data/             # gitignored, never committed
    ├── baseline.fit
    └── recent.fit
```

Then run:

```bash
python examples/quickstart.py
```

## Future

- `synthetic_fit_demo.py` — generate a fake FIT with known ground truth, run the full pipeline, verify outputs match. Useful for testing the segmentation algorithm without exposing personal data.
- `pipeline_walkthrough.ipynb` — Jupyter notebook walking through bulk export → daily → analysis.

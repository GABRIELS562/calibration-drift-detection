# Calibration Drift Detection

Analytical instruments drift. A gas sensor that was calibrated and validated in
January will, by the following year, produce readings whose statistical
character has quietly shifted — not enough to trip a hard fault, but enough that
a model trained against the original behaviour is now making decisions on data
it has never really seen. In an accredited laboratory (ISO 17025, GAMP 5) this
is not a modelling nuisance. It means results may already have been reported to
clients from a measurement system that changed without anyone noticing.

This project builds the governance around that problem rather than a clever
model. It watches production sensor batches against a committed reference
distribution, quantifies drift per feature with defensible thresholds, and —
when drift is detected — trains a *candidate* replacement model that cannot
promote itself. Every evaluation, candidate, approval and rejection is recorded
in an append-only audit trail, and every prediction traces back through model
version → training dataset → reference distribution → approval record. The
model is deliberately simple; the approval gate, traceability chain and
architecture decision records in `docs/adr/` are the deliverable.

## The data

[UCI Gas Sensor Array Drift](https://archive.ics.uci.edu/dataset/224/gas+sensor+array+drift+dataset)
— 13,910 measurements from 16 metal-oxide gas sensors, collected over 36 months
and grouped into 10 chronological batches. Six gases at varying concentrations.
The sensors genuinely degraded over the collection period, which is why this
dataset and not a synthetic one.

Format is svmlight: `<label> 1:<v> 2:<v> … 128:<v>`. The loader in
`src/drift/data.py` names the 128 features `s01_f1 … s16_f8` (sensor-major).
Per sensor, the eight features are: steady-state resistance change (`f1`),
normalised steady-state (`f2`), and six exponential-moving-average transients
(`f3–f5` rising, `f6–f8` falling).

What the profile shows, and what it means for drift detection:

| Finding | Consequence |
|---|---|
| All 128 features are continuous (444–445 distinct values in 445 rows), no NaNs | KS / PSI apply to every feature. Chi-square is needed only for the **label**. |
| `f1` is on the order of 10⁵; the transients are on the order of 10¹ | Logistic regression needs feature scaling; random forest does not. |
| Batch sizes range from 161 (batch 4) to 3,613 (batch 7) | Small batches make p-values noisy — PSI is the more stable signal there. |
| Toluene is absent from batches 3–5; batch 10 is perfectly balanced (600 per gas) | **Label drift** exists independently of feature drift and must be tested separately. |
| Sensor 1 steady-state mean falls from ~125,000 (batch 1) to ~2,000 (batch 8) | The instrument drift is large and visible even before any statistical test. |

Batch 1 is the reference distribution. Batches 2–10 are treated as production
windows arriving over time. Reference statistics are computed from Batch 1
alone and committed to `data/reference/`.

## Layout

| Path | Purpose |
|---|---|
| `src/drift/` | Application code (training, drift detection, serving) |
| `docs/adr/` | Architecture decision records — start here |
| `data/raw/` | UCI Gas Sensor Array Drift dataset (gitignored, not redistributed) |
| `data/reference/` | Baseline statistics from Batch 1 — committed, part of validated state |
| `notebooks/` | Exploratory work, kept out of production code |
| `tests/` | pytest |

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is fetched automatically.

```bash
uv sync
uv run pytest
uv run ruff check .
```

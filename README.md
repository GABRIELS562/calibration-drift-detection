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

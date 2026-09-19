# ADR-0002: Dataset, reference split and baseline model

## Status

Accepted — 2026-09-19

## Context

Phase 1 needs three things before drift detection can begin: data that
exhibits genuine instrument drift, a fixed definition of "normal" to detect
drift against, and a model whose behaviour on that data can be tracked.
Each is a choice with consequences for everything downstream.

Profiling the data (README, "The data") established: 128 continuous
features, no missing values, no categorical features; feature `f1`
(steady-state response) on the order of 10⁵ while the transient features
are on the order of 10¹; batch sizes from 161 to 3,613 rows; and class
mix that changes between batches independently of the sensors.

## Decision

**Dataset: UCI Gas Sensor Array Drift (id 224).** 13,910 measurements from
16 metal-oxide sensors over 36 months in 10 chronological batches. The
sensors physically degraded during collection, so the drift is real
instrument drift rather than injected noise. The raw files are gitignored
and not redistributed.

**Reference: Batch 1 only.** Batch 1 is the earliest data — the instrument
as commissioned. Reference statistics are computed from it alone;
`compute_reference_stats` raises if given more than one batch, and the
resulting `data/reference/baseline_stats.json` records the source file and
its SHA-256. Batches 2–10 are production windows and are never read during
training or reference computation.

**Reference statistics are committed.** `baseline_stats.json` (per-feature
mean, std, min, max, 10-bin histogram; label counts; provenance) is part of
the validated system state. It is version-controlled so any change is a
reviewable diff, and it carries the same dataset hash as the registered
model so the two are provably derived from the same bytes.

**Model: untuned random forest.** 200 trees, unlimited depth, seed 42,
stratified 75/25 split of Batch 1. Chosen over logistic regression because
trees are scale-invariant: the 10⁵ vs 10¹ feature ranges would otherwise
require a fitted scaler — a second artefact to version, hash and validate.
No hyperparameter tuning is done or planned; the model is not the subject.

**Metrics: accuracy and macro-F1.** Batch 1 has 30 acetaldehyde samples
against 98 ethylene. Macro-F1 weights every class equally and exposes a
model that neglects the small classes; accuracy alone would not.

**Serialisation: skops, with the forest's tree type declared trusted.**
MLflow 3 defaults to skops for sklearn models and refuses undeclared types.
The alternative, pickle, executes arbitrary code on load, which would make
the served model file a code-execution vector. A validated system should
not depend on a model artefact being trustworthy by assumption.

**Tracking store: SQLite locally, `MLFLOW_TRACKING_URI` in deployment.**
The model registry requires a database backend; the plain file store cannot
register versions. The environment variable lets the same code target a
server on the cluster in Phase 5.

## Consequences

**Easy:**
- The traceability chain is short: prediction → model version (MLflow) →
  `dataset_sha256` tag → `batch1.dat` → `baseline_stats.json` with the same
  hash. No scaler, no tuning run, no preprocessing artefact to account for.
- The model trains in about a second, so retraining candidates in Phase 3
  costs nothing and the approval gate is the only slow step — as it should be.
- MLflow captured the full `uv.lock` environment with the model, so the
  registered version records library versions as well as data and parameters.

**Hard / accepted costs:**
- 445 reference rows is small. Ten equal-width histogram bins on a
  right-skewed feature such as `s01_f1` put 219 of 445 samples in the first
  bin, which blunts PSI sensitivity. Quantile bins would be better for PSI;
  equal-width was chosen as the simplest correct option and Evidently
  performs its own binning in Phase 2. Revisit if PSI proves insensitive.
- Batches 4, 5 and 8 have under 300 rows. Statistical tests on them will be
  noisier than on batches 6, 7 and 10. Thresholds (ADR-0003) must account
  for this rather than assume uniform batch size.
- Class mix varies by batch — toluene is absent from batches 3–5, batch 10
  is artificially balanced. Label drift must be tested separately from
  feature drift or the two will be conflated.
- The model's 0.964 accuracy / 0.935 macro-F1 are on held-out **Batch 1**
  data. They say nothing about later batches. That is deliberate: the gap
  between these numbers and performance on batches 2–10 is the drift.

## Options considered

- **Synthetic drift (inject noise or shift into a static dataset).**
  Rejected: the thresholds in ADR-0003 have to be defended against real
  instrument behaviour, and synthetic drift proves only that the code
  detects the drift you injected.
- **Batches 1–3 as reference for a larger sample.** Rejected: it would hide
  drift that occurred within those three batches and would no longer
  represent the instrument at validation. Sample size is an accepted cost.
- **Logistic regression.** Rejected on the scaling problem above, not on
  accuracy. It would be an equally acceptable model with a longer
  traceability chain.
- **Gradient boosting or a neural network.** Rejected: draws attention from
  the governance layer and adds nothing to it (ADR-0001).
- **Pickle / cloudpickle serialisation.** Rejected: works without ceremony
  but makes the model artefact executable content.
- **MLflow file store (`./mlruns`) as in the plan's `mlflow server`
  command.** Rejected: cannot register model versions, which the approval
  gate depends on.

## Related

- ADR-0001 — project purpose and scope
- ADR-0003 — drift thresholds
- README, "The data" — profile findings referenced above

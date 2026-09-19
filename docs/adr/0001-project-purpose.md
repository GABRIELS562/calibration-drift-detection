# ADR-0001: Project purpose and scope

## Status
Accepted

## Context
Analytical instruments drift over their service life. A model validated
against an instrument's behaviour at commissioning is, months later, operating
on data whose distribution has shifted. In an ISO 17025 accredited laboratory
a measurement system that changes without a documented, approved change is an
unvalidated system, and any results it has reported are suspect.

Most machine-learning drift tutorials stop at "detect drift, retrain
automatically". That is precisely the behaviour a regulated laboratory cannot
accept: an unattended retrain is an uncontrolled change. The gap this project
addresses is not the detection — the statistics are well understood — but the
governance that has to surround it.

This is a portfolio project built in roughly 13 weeks at 4–6 hours a week,
alongside AWS SAP-C03 study. Scope discipline matters more than completeness.

## Decision
Build a drift-detection pipeline for the UCI Gas Sensor Array Drift dataset
in which:

1. A deliberately simple baseline model is trained on Batch 1 and registered
   in MLflow with its parameters, metrics and dataset hash.
2. Reference statistics from Batch 1 are committed to the repository as part
   of the validated system state.
3. Batches 2–10 are treated as production windows and scored for drift per
   feature, with thresholds justified in writing against the asymmetric cost
   of false positives versus missed detections.
4. Drift above threshold produces a *candidate* model registered as
   `pending-approval`. Promotion requires an explicit, recorded human action.
   A candidate that performs worse is still registered, with its rejection
   reason.
5. Every evaluation, candidate, approval and rejection is written to an
   append-only audit log, and a traceability statement documents the chain
   prediction → model version → training data → reference → approval.
6. The target-state AWS design (multi-account, migration, resilience, cost)
   is written as documents, not built.

**Definition of done:** the service running on the home K3s cluster with drift
scores in Grafana, an approval gate that demonstrably blocks auto-promotion,
and a written architecture case study. Not a better model. Not a paper.

## Consequences
- **Easy:** the governance story is legible because the model is boring. A
  reader is never distracted by modelling choices.
- **Easy:** every artefact is reviewable in a pull request — reference
  statistics, thresholds, prompts and ADRs all live in version control.
- **Hard:** the approval gate adds friction to every retrain. That friction is
  the point, but it means the demo requires a human in the loop.
- **Given up:** any claim to state-of-the-art detection or model accuracy.
  Batches 5–10, model cards, and the platform deployment are explicitly on the
  cut list if time runs short; ADR-0003 (thresholds), ADR-0005 (staying
  validated while retraining), the AWS multi-account design and the
  architecture case study are not.

## Options considered
- **Auto-retrain on drift.** Rejected: an unattended change to a measurement
  system is unvalidated under ISO 17025 / GAMP 5. Recorded in full in
  ADR-0004.
- **Synthetic drift dataset.** Rejected: the UCI dataset contains genuine
  sensor degradation over 36 months, which makes the drift real and the
  thresholds defensible against real instrument behaviour.
- **Complex model (gradient boosting, neural network).** Rejected: it would
  shift a reader's attention from architecture to modelling and add nothing
  to the governance argument. Recorded in ADR-0002.
- **Build the AWS target state rather than design it.** Rejected on time
  budget; the design documents evidence architect judgement that a build of
  a fifth app on an existing cluster would not.

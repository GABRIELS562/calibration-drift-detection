# ADR-0001: Project purpose and scope

## Status

Accepted — 2026-09-19

## Context

> **Rewrite this section in your own words before Phase 1.** What follows is scaffolding. The version that matters describes drift the way you saw it in an accredited laboratory: an instrument quietly moving out of tolerance, results reported to a client before anyone noticed, what the recalibration decision actually cost, and who had to sign it off. That paragraph is the part nobody else writing this ADR can produce, and it is the reason this project is worth reading.

Machine learning models degrade in production for the same reason measuring instruments do: the world they were calibrated against stops resembling the world they are measuring. In an accredited laboratory this is a managed risk — calibration intervals, control charts, tolerance limits, documented recalibration, and an audit trail proving which method produced which result.

Production ML systems generally have none of that. Models are deployed, they drift, and the drift is discovered either by a monitoring dashboard nobody reads or by a downstream consumer noticing the outputs are wrong. Where retraining is automated, it is frequently unattended — the system changes itself, and no record exists of what changed, why, or who accepted it.

That is tolerable for a recommendation engine. It is not tolerable for a system producing measurements that inform decisions, because an unattended retrain is an unvalidated change to a measurement system. Under ISO 17025 a laboratory cannot report results from a method it cannot demonstrate is still valid, and "the model retrained itself overnight" is not a demonstration.

This project builds the missing layer: drift detection with defensible thresholds, retraining that produces a candidate rather than a replacement, human approval as a gate rather than a notification, and an audit trail that traces any prediction back to the model version, training data and approval record behind it.

## Decision

Build a drift detection and gated retraining system for instrument sensor data, using the UCI Gas Sensor Array Drift dataset, deployed on a self-hosted Kubernetes cluster, with an accompanying AWS target-state architecture design.

The project is scoped as a **portfolio artefact demonstrating architecture judgement**, not as a production system or a research contribution. Specifically:

- The model is deliberately simple. A logistic regression or random forest is sufficient, and a complex model would draw attention away from the subject.
- The governance layer is the subject. Approval gates, audit trail, traceability and validation reasoning are where the effort goes.
- The written artefacts — this ADR, ADR-0003 on threshold selection, ADR-0005 on validating a self-changing system, and the architecture case study — are deliverables in their own right, not documentation of the code.

**Done means:** drift detected and quantified across the dataset's production batches, a retraining path that cannot promote without human approval, a traceability statement an auditor could follow, the system running on the cluster with drift scores visible in Grafana, and the architecture case study written.

**Done does not mean:** state-of-the-art detection methods, a production-grade model, or full coverage of every batch and feature.

## Consequences

**Makes easy:**

- Demonstrating design reasoning in a domain most portfolios do not touch
- A concrete answer to "how do you validate a system that changes itself", which is an open question in the field rather than a solved one
- Reusing the regulated-environment framing across other work, since the governance patterns generalise

**Makes hard:**

- The project is less visually impressive than a dashboard-heavy or model-heavy alternative. A reader skimming for screenshots will underrate it.
- The most valuable output is prose, which takes longer to produce than code and is easier to postpone
- Scope creep toward "make the model better" is a constant pull and must be actively resisted

**Accepted costs:**

- Roughly 55–65 hours across 11 weeks, at one hour a day
- The simple model means the project says nothing about modelling skill. That is a deliberate trade, and it is stated in the README so it does not read as an omission.

## Options considered

**A production-grade ML system on a richer dataset.** Rejected: more time in modelling, less in governance, and the governance is the differentiator. The dataset chosen contains genuine instrument drift across 36 months, which synthetic or static alternatives do not.

**A pure architecture paper with no implementation.** Rejected: design documents unsupported by a working system are easy to write and hard to trust. The implementation is what makes the reasoning credible, even though the reasoning is the point.

**Automated retraining with no approval gate.** Rejected on the merits, not on effort — this is the decision the project exists to argue against, and it is examined properly in ADR-0004.

**A generic MLOps demo — train, deploy, monitor.** Rejected: that project already exists in thousands of repositories and says nothing a reader cannot get elsewhere. The regulated framing is the only part of this work that is scarce.

## Related

- ADR-0002 — dataset, model class and reference split
- ADR-0003 — drift thresholds and their justification
- ADR-0004 — gated promotion
- ADR-0005 — validating a continuously retraining system

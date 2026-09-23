# Control mapping

Each control implemented in this project against the concept it satisfies in
GAMP 5 and ISO/IEC 17025:2017. Clause references are indicative, not a
certified gap assessment.

| # | Control | Implementation | ISO 17025 | GAMP 5 |
|---|---|---|---|---|
| 1 | Only validated methods are used for reported results | Model reaches `production` only via human approval | 7.2.1 Method selection and validation | Validation before release |
| 2 | Changes to a method are authorised, recorded and traceable | `approve()` requires actor + reason; recorded on the version, in the audit log, and in the GitHub deployment | 7.2.1.5, 8.5 Change control | Change management |
| 3 | Segregation of the change requester from the change approver | Pipeline registers candidates; only a named reviewer (GitHub environment rule) promotes | 6.2 Personnel, impartiality | Separation of duties |
| 4 | Measurement traceability — results link to the method that produced them | `dataset_sha256` binds version → training data → reference distribution | 6.5 Metrological traceability | Data integrity (ALCOA+) |
| 5 | Records are attributable, legible, contemporaneous, original, accurate | Hash-chained append-only `audit/audit.jsonl`, actor + UTC timestamp per entry | 7.5, 8.4 Control of records | ALCOA+ |
| 6 | Records cannot be altered without detection | SHA-256 chain; `verify_chain()` names any broken entry | 8.4.2 | Audit trail integrity |
| 7 | Quality control monitoring of results | Westgard multirules per sensor per analyte, every batch | 7.7 Ensuring validity of results | Ongoing performance verification |
| 8 | Defined action on out-of-control conditions | Reject rules trigger a candidate; warning rules trigger investigation only (ADR-0003) | 7.7.3 | Deviation handling |
| 9 | Nonconforming work is identified and acted on | Rejected sensors named per batch with rule and analyte in the trigger record | 7.10 Nonconforming work | Deviation / CAPA input |
| 10 | Reversion to a known-good state | `rollback()` restores the previous approved version in one step, measured at 2.2 s | 7.10.2 | Rollback / contingency |
| 11 | Software is under configuration control and reproducible | `uv.lock` pins all 137 dependencies by hash; MLflow stores the environment with each model | 7.11 Control of data and information management | Configuration management |
| 12 | The validated state is version-controlled and reviewable | `data/reference/baseline_stats.json` and all thresholds are committed; changes require a pull request | 7.11.3 | Configuration items |
| 13 | Model artefacts cannot execute arbitrary code on load | skops serialisation with declared trusted types, not pickle (ADR-0002) | 7.11.3 system protection | System security |
| 14 | Decisions are documented with their rationale | ADRs 0001–0005, each recording options considered and rejected | 8.3 Control of documents | Design documentation |
| 15 | Fitness for purpose and known limitations are stated | Generated model cards per version, including an explicit "not a reportable method" statement | 7.8 Reporting results | Intended use statement |
| 16 | Periodic review of continued validity | Every batch re-evaluated against the reference; evaluation recorded whether or not it triggers | 7.7.1 | Periodic review |

## Gaps — deliberately stated

| Gap | Consequence | Where it is addressed |
|---|---|---|
| Audit log is local and single-writer | Tamper-evident, not tamper-proof | Phase 6: object-lock storage, cross-account log archive |
| No per-prediction record | Chain begins at the model version, not the individual result | Phase 5: serving version returned and logged per request |
| Single approver role | No separation between reviewer and administrator of the registry | Phase 6: account boundaries and SCPs |
| No periodic re-validation schedule | Re-evaluation is event-driven (a batch arrives), not calendar-driven | Would need a defined calibration interval |
| Raw data not retained in the repository | Only the hash is committed | Accepted: licensing and size |

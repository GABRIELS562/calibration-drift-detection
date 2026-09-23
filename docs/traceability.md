# Traceability statement

_What an assessor asks for: given a prediction, show me everything behind it._

## The chain

```
prediction
  └── model version              MLflow registry, alias `production`
        ├── approval record      version tags: approved_by, approval_reason, approved_at
        │     └── audit entry    audit/audit.jsonl, hash-chained
        ├── MLflow run           parameters, metrics, uv.lock environment
        ├── training dataset     dataset_sha256 on both the run and the version
        │     └── raw batches    data/raw/batchN.dat, SHA-256 verifiable
        └── reference dist.      data/reference/baseline_stats.json (same hash, in git)
              └── control limits per gas, per sensor — the drift verdict that caused this version
```

Every link is a recorded value, not an inference. None of it is reconstructed
after the fact.

## Walking it, for the version currently in production

**1. Which model served this prediction?**

```bash
uv run python -m drift.cli status
```
The alias `production` points at exactly one version. A prediction served by
the API (Phase 5) returns that version alongside its result.

**2. Who approved it, when, and why?**

The version tags carry `approved_by`, `approval_reason`, `approved_at`. The
same decision appears in `audit/audit.jsonl` as an `approved` event, and in
the GitHub deployment record for the `promote` workflow run — three systems,
independently written, naming the same person.

**3. What was it trained on?**

The version's `dataset_sha256` tag and the run's `training_batches`
parameter. Re-hash the raw files to confirm they are the same bytes:

```bash
uv run python -c "
from drift.data import RAW_DIR
from drift.reference import sha256_of_file
print(sha256_of_file(RAW_DIR / 'batch7.dat'))"
```

**4. What was 'normal' when the decision was made?**

`data/reference/baseline_stats.json` — committed, so `git log` shows every
change to it and who made it. It carries the dataset hash of batch 1, which
is the hash on baseline model version 1.

**5. Why was this version produced at all?**

The `trigger` tag states the batch, the sensors rejected, the analyte, the
z-score and the rule that fired. The corresponding `drift_evaluated` audit
entry holds the full verdict for that batch, written before the candidate
existed.

**6. Was anything rejected along the way?**

`uv run python -m drift.cli status` lists every version, including
`rejected` and `rolled-back` ones, with the actor and reason. Candidates
that performed worse than the incumbent were registered too.

**7. Has the record been altered?**

```bash
uv run python -c "
from drift.audit import AUDIT_LOG_PATH, verify_chain
print(verify_chain(AUDIT_LOG_PATH), 'entries verified')"
```
Each entry carries the hash of the entry before it. Editing, deleting or
reordering any entry breaks the chain, and the error names the entry.

## Worked example

The trail for the current repository state, top to bottom:

| # | Event | Actor | What it establishes |
|---|---|---|---|
| 1 | `baseline_registered` | train | v1 exists, trained on `batch1.dat` (hash recorded) |
| 2 | `approved` | jgabriels | v1 promoted — with a reason, by a person |
| 3 | `drift_evaluated` | pipeline | batch 3 in control, no action |
| 4 | `drift_evaluated` | pipeline | batch 5: 4 sensors under warning (4₁ₛ, acetaldehyde) |
| 5 | `drift_evaluated` | pipeline | batch 7: 5 sensors rejected on toluene |
| 6 | `candidate_registered` | pipeline | v2 created, pending, incumbent 0.547 vs candidate 0.995 |
| 7 | `approved` | jgabriels | v2 promoted after sensor replacement |

Entry 3 matters as much as entry 5: the record shows the batches where the
system decided *not* to act, and why. A trail containing only the alarms
cannot demonstrate that the system was watching in between.

## What this does not yet establish

- **Predictions are not individually logged.** The chain runs from a
  prediction to its model version only once the API records the serving
  version per request (Phase 5). Until then it starts at the model version.
- **The audit log is local and single-writer.** Tamper-evident, not
  tamper-proof: someone who can rewrite the whole file can rebuild a
  consistent chain. Anchoring it (an external timestamp, or a
  write-once/object-lock store) is the AWS-side answer in Phase 6.
- **The raw dataset is not committed**, by choice. Its hash is, so a
  re-download can be verified — but the bytes themselves live outside the
  repository.

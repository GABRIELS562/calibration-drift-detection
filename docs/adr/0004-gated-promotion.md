# ADR-0004: Gated promotion

## Status

Accepted — 2026-09-23

## Context

ADR-0003 settled when a batch is out of control. This decides what happens
next. The conventional MLOps answer is a closed loop: drift is detected, a
model retrains, the new model replaces the old one, and a dashboard records
that it happened. The loop runs unattended, which is the point of it.

A measurement system operating under ISO 17025 cannot work that way. The
laboratory reports results to clients, and it must be able to demonstrate
that the method producing those results was valid at the time. A model that
replaced itself overnight is a change to the measurement system for which
no one holds a record, no one performed a verification, and no one signed.
"The system retrained itself" is not a demonstration of validity; at an
assessment it is a finding.

The tension is real rather than rhetorical. Drift is a reason to change the
model. Changing the model is a reason to revalidate. A system that changes
itself faster than it can be revalidated is, by construction, unvalidated
most of the time.

## Decision

**Retraining produces a candidate. Only a human produces a deployment.**

The mechanism, in the code:

1. **Trigger.** Any sensor rejected under the Westgard rules (1₃ₛ or 2₂ₛ)
   triggers retraining. Warnings (4₁ₛ, 10ₓ) do not: they open an
   investigation, and a human may run the pipeline manually if they judge
   it warranted. `drift.pipeline` exits 10 when a candidate is waiting,
   which is what the CI job keys off.

2. **Candidate training.** The candidate trains on the reference batch plus
   every production batch seen so far, and is evaluated on held-out data
   from that combined set. The incumbent — whatever currently holds the
   `production` alias — is scored on the *same* held-out rows, so the
   comparison is like-for-like.

3. **Registration is unconditional.** The candidate is registered in the
   MLflow model registry with `approval_status=pending-approval`, the
   trigger text, the dataset SHA-256, and the metric comparison against the
   incumbent. **A candidate that performs worse is registered too**, tagged
   `regression=true` with the comparison recorded. Where there is no
   incumbent, that is recorded explicitly rather than left blank.

4. **Nothing in the training path can promote.** `register_candidate` never
   touches an alias. `approve` is the only function that moves the
   `production` alias, it requires a named actor and a reason, and it
   refuses any version that is not currently pending — so a version cannot
   be approved twice, and a rejected version cannot be resurrected.

5. **The baseline is not exempt.** The first model registers as
   pending-approval like every candidate and requires the same explicit
   promotion. The initial deployment of a measurement system is a change to
   it.

6. **Rollback is one step.** `rollback` points the alias back at the
   previously approved version, tags the version it displaced as
   `rolled-back`, and records who and why. Measured at **2.2 seconds**.

**The gate is implemented as a GitHub Actions environment protection rule.**
The `promote` and `rollback` workflows both declare `environment:
production`, which has a required-reviewer rule. The job pauses until a
named reviewer approves the deployment in GitHub; `github.actor` is passed
through as `DRIFT_ACTOR` and written to the model version as `approved_by`.
The GitHub deployment record and the MLflow registry therefore name the
same person for the same decision, from two independent systems.

> **Deployment note.** The protection rule is repository configuration, not
> code: Settings → Environments → `production` → Required reviewers.
> Without it the workflow runs unattended and this ADR describes something
> that is not true. This is the one control in the project that a reader
> cannot verify from the source alone, and it is stated here for that reason.

## Consequences

**Easy:**
- Any prediction traces to an approved version, and that version names the
  person who approved it, when, and why.
- Rejected candidates are as visible as approved ones. The registry records
  what was considered and declined, not only what shipped.
- Rollback is fast enough (2.2 s) that reverting is never the slow option
  in an incident.
- The trigger is legible to a laboratory: "sensors 1, 9, 10 rejected on
  toluene" rather than "drift score exceeded 0.25".

**Hard / accepted costs:**
- Promotion is as slow as the reviewer. A genuine degradation persists
  until someone acts. That is the intended trade: a wrong model in service
  is recoverable, a silent unvalidated change is not.
- The reviewer needs enough context to decide. The comparison tag helps but
  is not a validation report; Phase 4's model cards are the intended
  remedy.
- A backlog of pending candidates is possible if the pipeline runs more
  often than reviewers review. The pending count is a Phase 5 metric for
  exactly this reason.
- The gate's strength depends on repository configuration that lives
  outside the repository, and on GitHub's own access controls.
- The candidate trains on all batches seen so far, which assumes older
  production data remains representative. A windowing strategy would be a
  defensible alternative and is not implemented.

## Options considered

- **Automatic promotion on improvement (the conventional loop).** Rejected:
  an unattended change to a measurement system is unvalidated by
  definition. It is also the decision this project exists to argue against
  (ADR-0001). Practitioner guidance outside regulated settings reaches a
  weaker form of the same conclusion — alert on drift, do not auto-retrain
  until the signal is trusted.
- **Shadow deployment.** The candidate runs alongside production on live
  traffic and is promoted on accumulated evidence. Rejected here for two
  reasons: it needs ground-truth labels in production, which a calibration
  setting does not have promptly; and the promotion criterion still has to
  be defined and approved, which returns to this decision one step later.
  It would be a reasonable addition *before* the gate, never instead of it.
- **Champion/challenger with automatic cut-over on a threshold.** Rejected
  for the same reason as automatic promotion: the threshold becomes the
  approver, and a threshold cannot hold a signature.
- **Promotion by pull request** — the served version is a value in a config
  file, and promotion is a reviewed merge. Genuinely attractive: the
  approval is a commit, the diff is the change record, and it works with no
  environment configuration. Rejected as the primary mechanism because the
  approval record would then live in git while the model version lives in
  MLflow, with nothing binding them; the environment rule writes the
  approver into the registry itself. Worth revisiting in Phase 5, where the
  served version becomes part of a Helm values file and a PR is the natural
  deployment path anyway.
- **Approval recorded only in MLflow, with no CI gate.** Rejected: the
  `approve` CLI would then be runnable by anyone with registry credentials,
  and the actor would be self-asserted rather than authenticated.

## Related

- ADR-0001 — project purpose and scope
- ADR-0003 — drift thresholds and the decision rule (the trigger)
- ADR-0005 — validating a continuously retraining system
- `src/drift/registry.py` — the gate
- `src/drift/retrain.py` — trigger and candidate training
- `.github/workflows/promote.yml` — the environment-protected approval job

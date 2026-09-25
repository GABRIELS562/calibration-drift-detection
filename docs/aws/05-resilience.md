# Target state 5 — Resilience

_Design only._

## The requirement is not one requirement

The usual move is to pick an RTO and an RPO for "the system". That is wrong
here, and noticing why is the whole of this section.

This system has **two components with opposite recovery profiles**:

| | Serving and evaluation | The audit trail and approval record |
|---|---|---|
| If it is unavailable for a day | Nothing is wrong. The instrument still measures; drift is simply not being evaluated that day. Batches arrive weekly. | Nothing is wrong either — nobody is reading it. |
| If it loses a day of data | Nothing is lost that cannot be recomputed. Evaluation is a pure function of the reference and the batch; re-run it. | **A record of who approved what no longer exists.** It cannot be recomputed, because the fact it records is a human decision, not a derivation. |

So:

| Component | RTO | RPO | Why that number |
|---|---|---|---|
| Serving API | **4 hours** | n/a (stateless) | Predictions are not on a reporting critical path; a lab does not stop because a classifier is down. |
| Drift evaluation | **1 week** | n/a (recomputable) | It runs weekly. Missing one run delays detection by one cycle, which the control rules already tolerate — 4₁ₛ needs four consecutive runs regardless. |
| Model registry | **8 hours** | **15 minutes** | Losing a registered candidate costs a retraining run. Losing an *approval* costs the ability to demonstrate validity. |
| **Audit trail** | 24 hours | **zero** | This is the number that matters. |

**RPO zero for the audit trail is not ambition, it is the requirement.** ISO
17025 asks a laboratory to demonstrate that results came from a valid method.
If the record of the approval that made a model valid is gone, every result
that model produced becomes unsupportable — retrospectively, for as long as
that model was in service. There is no recovery procedure for that, which is
why the design makes the loss impossible rather than recoverable: a
synchronous write to S3 with Object Lock in compliance mode, cross-region
replication on, versioning on.

Contrast the serving API's four hours. It would be easy to design both for
four hours and feel rigorous. It would also be expensive and would miss the
point: the thing that must never be lost is a few kilobytes of JSON, and the
thing that can be down for half a day is the part with all the compute in it.

## Multi-AZ

Yes, and it is nearly free at this size:

- EKS control plane is multi-AZ by default.
- Node group across 3 AZs. The workload is one serving pod and a weekly job;
  the cost is a few small instances, not a doubled bill.
- EBS is zonal — the one real consideration. Anything on EBS (an MLflow PVC,
  if MLflow is retained) pins a pod to an AZ. Mitigations in preference
  order: don't keep state on EBS (use S3 and the managed registry); or accept
  an AZ-scoped restore from snapshot.
- S3 and the managed services are regional already.

## Multi-region

**No, and this is the interesting refusal.**

The instinct in a regulated context is that multi-region is the responsible
choice. Work it through:

- **What would it protect?** A region-wide failure lasting longer than the
  RTOs above. For serving, that is 4 hours of a non-critical classifier. For
  evaluation, a week — and AWS regional outages of a week have not happened.
- **What does it cost?** Roughly double the compute footprint, cross-region
  data transfer, a second set of endpoints, and — the real cost — **a second
  place where laboratory data lives**, which is a data-residency question
  (SCP-3) and therefore a compliance conversation, not an architecture one.
- **What does it complicate?** The registry becomes multi-master or
  active/passive with a promotion procedure. The approval gate now has to
  answer "which region's registry is authoritative" at exactly the moment
  everyone is stressed.

So the answer is: **multi-AZ for everything, and cross-region replication for
the audit bucket only.** The audit trail is the one thing with an RPO of zero
and a footprint of kilobytes, so replicating it is cheap and eliminates the
only unrecoverable loss. Everything else stays in one region and accepts a
regional outage as downtime.

That is a defensible, cheaper answer than symmetric multi-region, and the
reason it is defensible is that the recovery objectives were derived
per-component from what failure actually costs, rather than assumed uniform.

## Backup

| What | How | Restore tested? |
|---|---|---|
| Audit trail | S3 versioning + Object Lock + CRR | **Must be** — reconstruct the chain from S3 alone and run `verify_chain` |
| Model artefacts | S3 versioning, lifecycle to IA after 90 days | Load an archived version and reproduce a known prediction |
| Registry metadata | AWS Backup on the managed service | Yes |
| Reference statistics | Already in git, which is already replicated | Implicitly |
| Raw batches | S3, Glacier after a year | Rarely, but the hash must still match |

The reference distribution needs no backup design because it is committed to
the repository — a consequence of the Phase 1 decision to version it rather
than store it, which is worth noticing as a design dividend.

## Weaknesses

- **None of these restores has been performed.** ADR-0004 can claim a 2.2
  second rollback because it was measured. Nothing on this page has been.
  Until a restore is rehearsed, the RTOs are estimates.
- **RPO 15 minutes for the registry is asserted**, not derived from a
  measured replication lag.
- **No game day.** The plan has no scheduled failure exercise, which is how
  you find out that the runbook references a role nobody has any more.

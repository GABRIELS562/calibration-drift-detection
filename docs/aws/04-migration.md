# Target state 4 — Migration plan

_Design only._

## What moves, and what never does

**Never moves:** the instrument, its acquisition software, and the first
write of raw data. A gas sensor array is physical, sits in a laboratory, and
its capture path must keep working when the internet does not. A design that
makes measurement depend on a WAN link has made the laboratory less capable,
not more. Raw data is written locally, then shipped.

**Moves last, if at all:** the operator's workstation tooling. `drift.cli`
against a remote registry is the same command against a different URL.

**Moves:** everything else — evaluation, registry, serving, monitoring, the
audit trail.

## Ordering principle

Move the thing whose current implementation is weakest first, not the thing
that is easiest to lift. By that test the order is forced:

1. The **audit trail** is the weakest control in the system today. It is
   tamper-evident but not tamper-proof, single-writer, on one disk, backed up
   by nothing (`docs/traceability.md`). S3 Object Lock fixes the most
   important gap in the whole design.
2. The **registry** is next: approval is enforced by application code and a
   GitHub setting, and SCP-1 replaces both.
3. **Serving and monitoring** are already fine. They move because the rest
   moved, not because they are deficient.

This ordering is also the riskiest-first ordering, which is the opposite of
the usual advice to start with something low-stakes. It is correct here
because each phase is independently valuable: if the money runs out after
phase 2, the two controls that most needed strengthening are strengthened,
and the system still runs.

## Phases

### Phase 0 — Landing zone (no workload)

Organizations, seven accounts, SCPs, CloudTrail organisation trail, Config,
GuardDuty, Security Hub, IAM Identity Center. VPCs and endpoints.

- **Cutover criteria:** an SCP denial is demonstrated, not assumed — attempt
  `UpdateModelPackage → Approved` from a Workloads-Prod role and capture the
  `AccessDenied`. That screenshot is the control evidence.
- **Rollback:** nothing to roll back; no workload has moved.

### Phase 1 — Audit trail to S3 Object Lock

The application gains a second audit sink: it continues writing
`audit.jsonl` locally **and** writes each entry to S3. Run both for a defined
period.

- **Cutover criteria:** every local entry for the period has a matching S3
  object; the hash chain verifies when reconstructed from S3 alone; a delete
  attempt against the bucket is denied for every role including Log Archive
  root.
- **Rollback:** stop writing to S3. The local log never stopped being
  authoritative during the parallel run, which is what makes this phase safe.
- **Note:** the chain design survives this unchanged — entries are
  self-verifying, so the storage medium is not load-bearing for integrity.

### Phase 2 — Registry to SageMaker Model Registry

The interesting phase, and the one with a real migration problem: **the
existing audit trail references MLflow model versions.** Those references
must remain resolvable after the registry changes, or the traceability chain
breaks at the cutover — which would be a self-inflicted wound on the exact
property the project exists to demonstrate.

Approach: migrate model versions into package groups preserving creation
order, and write a **one-time, immutable mapping object** (MLflow version →
model package ARN) into the Object Lock bucket, referenced by the
traceability statement. The mapping is itself an audit record.

- **Cutover criteria:** for three historical predictions, walk the full chain
  end to end using only AWS-side records plus the mapping object. If any link
  requires the old MLflow instance to still be running, the phase is not done.
- **Rollback:** MLflow stays running read-only for one release cycle.
  Promotion switches back by pointing `approve` at MLflow again.

### Phase 3 — Compute to EKS

Serving API, evaluation CronJob, Argo CD. The chart already exists and is the
same chart; `values.yaml` changes (image repository to ECR, storage class,
ingress instead of NodePort).

- **Cutover criteria:** blue/green at the DNS layer with the on-premises
  service still warm. Run both for a week with traffic mirrored to EKS and
  compare predictions **on identical input** — the model is deterministic
  given a fixed version, so any divergence is an environment fault and must
  be explained before cutover, not after.
- **Rollback:** DNS back to the on-premises service. Keep the K3s cluster for
  one month.

### Phase 4 — Monitoring to AMP/AMG

Last, because it is the least deficient and because losing monitoring mid-
migration would be the worst possible time to lose it.

- **Cutover criteria:** every alert in `deploy/chart/templates/prometheusrule.yaml`
  fires in the new stack under a deliberately induced condition. An alert that
  has never fired in its new home is an untested alert.
- **Rollback:** the self-hosted stack stays deployed until this passes.

## Decommissioning

Nothing on-premises is deleted until the phase that replaced it has run for a
full evaluation cycle **and** an audit walk has been completed against the new
system only. The K3s cluster costs nothing to leave running; a premature
delete costs the ability to answer a question about a historical result.

## What this plan is weak on

- **It has never been rehearsed.** Every cutover criterion above is written
  from first principles, not from a practice run. The first phase to be
  executed will find something this document did not anticipate — most likely
  in phase 2, because data migrations always find it.
- **"A defined period" in phase 1 is not defined.** It should be a number of
  evaluation cycles agreed with whoever signs the validation, and I have not
  agreed it with anyone.
- **No cost gate.** The plan does not say what happens if phase 3 lands and
  the EKS bill is three times the estimate. Phase 7 produces the model; this
  plan should carry a stop-and-review checkpoint after phase 3 and does not.

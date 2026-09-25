# ADR-0006: Build versus buy for the ML platform

## Status

Accepted — 2026-09-25 (target-state design; not built)

## Context

Moving to AWS forces a choice that the self-hosted build never had to make:
run the ML platform ourselves on EKS, or buy SageMaker.

The regulated framing genuinely cuts both ways, and most write-ups of this
decision only show one side. Both are set out below before the decision,
because a reviewer should be able to see the argument that lost.

**The case for buying (SageMaker).** A managed service is validated
infrastructure you did not have to validate. The supplier maintains it,
patches it, and — the part that matters here — **the approval state becomes
an IAM-controlled API**. `sagemaker:UpdateModelPackage` with
`ModelApprovalStatus=Approved` is an action a Service Control Policy can deny
organisation-wide (SCP-1). Today the same gate is a GitHub environment
protection rule plus a tag write, and ADR-0004 admits its strength rests on
repository configuration living outside the repository. Under GAMP 5's
category framing, a configured commercial product carries a lighter
validation burden than bespoke software, and that is not a loophole — it is
the intended economics of the standard.

**The case for building (EKS + MLflow).** Validation means demonstrating that
a system does what it is specified to do, and you cannot inspect SageMaker.
You are accepting supplier assurance for a component inside the compliance
boundary, which means supplier qualification, and the supplier will not
submit to your change control: AWS changes the service on its own schedule,
and a behaviour change in a validated system that you did not authorise is
precisely the problem ADR-0005 exists to reason about. Self-hosted MLflow is
pinned in `uv.lock` and in a chart; it changes when we change it. There is
also lock-in — a model package group is AWS-only, while MLflow runs anywhere,
including back on the K3s box if the cloud project is cancelled.

## Decision

**Buy the registry. Build the rest.**

- **SageMaker Model Registry** for model packages and approval state.
- **EKS** for serving, drift evaluation, Argo CD and Prometheus.
- **MLflow retained on EKS** for experiment tracking (runs, parameters,
  metrics), if the tracking/registry split proves awkward — see Consequences.
- **Not** SageMaker Training, Pipelines, Endpoints or Feature Store. The
  model trains in about a second on 445 rows; a managed training service
  would add a service boundary to a problem that does not have one.

The deciding argument is narrow and worth stating precisely: **the registry
is the only component where buying changes what the system can enforce rather
than who operates it.** Everywhere else, SageMaker replaces something that
already works with something that works similarly and costs more. In the
registry, buying converts the separation-of-duties control from *application
code plus CI configuration* into *an organisation-level policy the workload
cannot reach*. That is a capability we cannot build ourselves at any
reasonable cost, because we cannot build an IAM control plane.

## Consequences

**Easy:**
- SCP-1 becomes possible, which is the strongest single control in the target
  state (Section 1).
- The approval action appears in CloudTrail in a separate account, so the
  registry and the audit trail name the approver from two independent
  systems.
- No SQLite, no single RWO volume, no `Recreate` strategy — the operational
  limitations named in `docs/deployment.md` disappear for the registry.

**Hard / accepted costs:**
- **Supplier qualification** is now required for SageMaker, and AWS will not
  accept our change control. The mitigation is the two-layer argument in
  ADR-0005: the validated thing is the process, and a supplier change is a
  change to the process that must be assessed — which means someone has to
  watch the service's release notes, and nobody is assigned to that.
- **Tracking and registry split into two systems.** Today one artefact
  carries params, metrics, the dataset hash and approval state, and the
  traceability chain is one walk. Across two services the link becomes a
  convention. If that proves fragile in Phase 2 of the migration, keep
  MLflow on EKS for tracking — accepting a self-managed component to keep
  the chain structural.
- **Lock-in on the registry specifically.** Accepted deliberately: it is the
  component whose AWS-native behaviour we are buying. The migration plan
  writes an immutable MLflow-version → package-ARN mapping precisely so that
  history survives, and the same mapping would serve a migration away.
- **Two platforms to operate.** EKS *and* a managed service, rather than one
  of each. The estate is larger than "all SageMaker" or "all self-hosted".

## Options considered

- **All SageMaker** — Pipelines, Training, Endpoints, Feature Store.
  Rejected: it buys managed operation of components that are not difficult to
  operate, at a considerably higher bill, and it puts far more of the system
  behind a supplier boundary that must then be qualified. The validation
  burden of a managed service is not zero; it is transferred, and it grows
  with surface area.
- **All self-hosted on EKS** — MLflow for everything, as today.
  Rejected on the single argument above: the approval gate stays enforced by
  application code, and no SCP can defend it. This is the option that loses
  by the narrowest margin, and if SCP-1 turned out to be unavailable it would
  win.
- **Stay on K3s on-premises; do not migrate at all.** Genuinely defensible on
  cost, and it is what the plan's cut list recommends for the build. Rejected
  for the *design*, because the controls that most need strengthening —
  audit immutability and separation of duties — are exactly the ones a cloud
  control plane provides and a single box cannot.
- **A third-party ML platform** (Databricks, W&B, Neptune). Not seriously
  assessed. It would add a second supplier to qualify and a second data
  residency conversation for a system with one instrument.

## Related

- ADR-0004 — gated promotion (the control this strengthens)
- ADR-0005 — validating a changing system (the supplier-change problem)
- ADR-0007 — inference hosting
- `docs/aws/01-multi-account.md` — SCP-1
- `docs/aws/02-service-mapping.md` — what each move costs

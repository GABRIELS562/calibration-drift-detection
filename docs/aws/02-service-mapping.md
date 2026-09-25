# Target state 2 — Service mapping

_Design only. Prices are list, us-east-1, checked September 2026; verify
before quoting._

The right-hand column is the one to read. Anyone can list what a component
becomes in AWS. What it costs you to make that move is the part that shows
whether the decision was actually thought about.

## The mapping

| Today | AWS | What you gain | **What you lose** |
|---|---|---|---|
| K3s on one box | **EKS** | Managed control plane, real HA, IRSA for per-pod identity, autoscaling | ~$73/mo per cluster before a single workload runs, and **$0.60/hr — 6× — the moment a version falls out of standard support**. K3s upgrades are a `curl`; EKS upgrades are a project with a deadline attached to a price rise. |
| MLflow on a PVC | **SageMaker Model Registry** | Approval state becomes an IAM-controlled API, so SCP-1 can enforce separation of duties. Managed, backed up, no SQLite. | Portability. MLflow runs anywhere; a model package group is AWS-only. Also a **migration of the approval history itself** — the existing audit trail references MLflow versions, and that mapping has to be preserved or the chain breaks at the cutover. |
| MLflow tracking (runs, params, metrics) | **SageMaker Experiments**, or keep MLflow on EKS | Same | The registry and the tracking store split in two. Today one `dataset_sha256` tag ties a run to a version; across two services that link becomes a convention you maintain rather than a property you get. |
| No secrets manager | **Secrets Manager** | Rotation, audit, IAM-scoped access | Nothing — there is nothing to lose because there is nothing there yet. This is where MLflow authentication should be introduced (`docs/deployment.md` limitation 2). |
| Prometheus (self-hosted) | **Amazon Managed Prometheus** | No storage to operate, scales past one node | Per-sample billing. A 10-node cluster at 1,000 metrics/node/30s is ~$81/mo; 50 nodes ~$405/mo. Self-hosted Prometheus on an existing node is effectively free. **Cardinality becomes a line item**, so `drift_model_info{version,dataset_sha256}` — a label set that grows with every model version — is now a cost decision as well as a design one. |
| Grafana (self-hosted) | **Amazon Managed Grafana** | SSO, no upgrades | $9/editor/month, $5/viewer/month. For 3 people that is trivial; it is also a per-seat model where the incumbent was per-cluster and free. Dashboards ship as ConfigMaps in the chart today (Argo CD owns them); AMG wants them provisioned differently, so **that GitOps property has to be rebuilt or given up**. |
| GitHub Actions | **Retain GitHub Actions** | — | — |
| Argo CD on the cluster | **Argo CD on EKS** (keep) | — | — |
| `ghcr.io` | **ECR** | Same-account IAM, scanning, lifecycle policies | Public pullability. The image is public today, which is part of the point of a portfolio repo. |
| `local-path` PVCs | **EBS gp3** + **S3** for artefacts | Snapshots, durability, size beyond one disk | Cost per GB-month on volumes that currently cost nothing, and S3 request charges on artefact reads. |
| Weekly CronJob | **EKS CronJob** (keep) or **EventBridge → Batch** | Batch removes the need for cluster capacity between runs | A second execution model to reason about. The evaluation runs *weekly for minutes*; the compute saving is real but small, and the complexity is permanent. |

## Two decisions I would not make the obvious way

**Keep GitHub Actions. Do not move to CodePipeline.**

The reflex answer for an AWS target state is to move CI into AWS. Here it is
the wrong call, and the reason is a security property, not a preference.
GitHub Actions builds the image and pushes it to a registry. **It holds no
cluster credentials at all** — Argo CD pulls. A compromised CI run cannot
deploy. Moving to CodePipeline either preserves that (in which case you have
changed tool for no gain) or replaces it with a push model where the pipeline
*does* hold deploy rights, which is strictly worse for a system whose whole
argument is that deployment requires an approval. The only genuine reason to
move would be a requirement that the build itself run inside the compliance
boundary — that is a real requirement in some laboratories, and if it appears,
CodeBuild in Shared Services is the answer.

**Keep Argo CD. Do not move to a push-based deploy.**

Same reasoning, and it is worth saying because it is the pattern this project
already argues for in a different context: pull beats push when the thing
being protected is "what is running matches what was approved".

## What SageMaker Model Registry actually buys

It is the only mapping on this page that changes what the system *is* rather
than who operates it.

Today the approval gate is a GitHub environment protection rule plus a tag
write, and ADR-0004 is honest that the strength of the gate rests on
repository configuration living outside the repository. On AWS, approval
becomes `sagemaker:UpdateModelPackage` with
`ModelApprovalStatus=Approved` — an IAM action, denied by SCP-1 everywhere
except the ML Registry account. The control moves from *application code and
CI configuration* into *the cloud control plane*, where the workload cannot
reach it.

That is the single strongest argument for this migration, and it is worth
more than the managed-service convenience of everything else on the page
combined.

## The mapping I am least sure about

Splitting tracking from the registry (row 3). Today, one artefact carries
params, metrics, the dataset hash and the approval state, and
`docs/traceability.md` walks a single chain. SageMaker's split is defensible
and the managed registry is what makes SCP-1 possible — but it converts a
structural guarantee into a bookkeeping discipline, and bookkeeping
disciplines fail quietly. The alternative is to run MLflow on EKS for
tracking and use SageMaker only as the registry, which keeps the strong
approval control and accepts a self-managed component. ADR-0006 takes this up
properly.

**Sources:** [EKS pricing](https://aws.amazon.com/eks/pricing/) ·
[AMP costs](https://docs.aws.amazon.com/prometheus/latest/userguide/AMP-costs.html) ·
[Managed Grafana pricing](https://aws.amazon.com/grafana/pricing)

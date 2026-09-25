# Target state 6 — Security

_Design only._

## Encryption

**At rest.** Everything, with customer-managed KMS keys rather than AWS-managed
ones — not because AES-256 differs, but because a CMK has a key policy, and a
key policy is a second, independent place to deny access. Two keys that matter
can be denied at the key even if an IAM policy is wrong.

**In transit.** TLS 1.2 minimum everywhere; bucket policies deny
`aws:SecureTransport = false`. Inside the VPC, traffic to AWS services rides
interface endpoints (Section 3), so it is both encrypted and off the public
network.

## KMS key hierarchy

Four keys, separated by who must be able to use them and who must never:

| Key | Encrypts | Usable by | Notable policy |
|---|---|---|---|
| `audit-cmk` | Audit bucket, CloudTrail, Config | Workload roles: **Encrypt only**. Auditor role: Decrypt. | No principal has both Decrypt and any delete path. Deletion and rotation-disable denied by SCP-4. |
| `model-cmk` | Model artefacts, registry metadata | Training role: Encrypt/Decrypt. Serving role: **Decrypt only**. | The serving pod can read an approved model and cannot write one. |
| `data-cmk` | Raw batches, reference statistics | Evaluation role: Decrypt. Ingest: Encrypt. | — |
| `secrets-cmk` | Secrets Manager | The specific roles that need the secret | — |

The pattern worth naming: **asymmetric grants on symmetric keys.** The
workload that produces audit records can encrypt but not decrypt them; the
workload that serves models can decrypt but not encrypt them. Each role holds
exactly the direction its job requires, so a compromised serving pod cannot
forge a model and a compromised evaluation pod cannot read back or alter the
audit trail. This is the same asymmetry as the `s3:PutObject`-only grant in
Section 3, expressed at the key.

## IAM boundaries

- **IRSA** — every pod gets its own role via a service account; no node
  instance profile shared across workloads, so a compromise of one pod does
  not inherit another's rights.
- **Permissions boundaries** on every role that a human or a pipeline can
  create, capping the maximum grant regardless of what policy is attached.
- **No long-lived access keys.** IAM Identity Center for people, IRSA for
  pods, OIDC for GitHub Actions — and GitHub Actions' role can push to ECR
  and nothing else (Section 2: CI holds no deploy rights by design).
- **Session tags** carrying the human identity through to CloudTrail, so
  `approved_by` in the registry and the CloudTrail event name the same person
  from two independent systems.

## How an auditor proves a prediction came from an approved model

This is the question the whole design is arranged to answer, so it should be
answerable in a sequence of concrete steps, with no step requiring trust in
the application.

**Given:** a prediction, its timestamp, and the `model_version` and
`dataset_sha256` the API returned with it (the serving API already returns
both — `src/drift/api.py`).

1. **The version served.** Application logs in CloudWatch record the version
   per request. Independently, `drift_model_info{version,dataset_sha256}` in
   the metrics store carries the same pair as a time series, so the version in
   service at that timestamp can be established **without trusting the
   application log**, from a second system that was written to concurrently.
2. **That version is approved.** `DescribeModelPackage` shows
   `ModelApprovalStatus=Approved` with `ApprovedBy` and a timestamp.
3. **Only a permitted principal could have approved it.** SCP-1 denies
   `UpdateModelPackage → Approved` from every account outside ML Registry.
   The denial is an organisation-level control the workload cannot alter, so
   "the code would not do that" is not part of the argument.
4. **Who actually did.** The CloudTrail event for that API call, in the Log
   Archive account, under Object Lock. Session tags name the human.
5. **The record has not been altered.** Object Lock in compliance mode: the
   object cannot be deleted or overwritten before retention expires, by any
   principal including root. Separately, the application's own hash chain
   verifies (`verify_chain`), which is an independent integrity check on the
   same facts.
6. **What it was trained on.** `dataset_sha256` on the package → the raw
   batch object in S3 → re-hash it and compare. Bytes, not metadata.
7. **What "normal" meant at the time.** The reference statistics carrying the
   same hash, in git, with the commit that introduced them.
8. **Why that version existed at all.** The `trigger` field: batch, sensors
   rejected, analyte, z-score, rule — and the `drift_evaluated` audit entry
   written *before* the candidate existed.

Steps 1, 4 and 5 come from systems the workload cannot write to. That is the
difference between this and the current implementation, where every link is
produced by the same process that produced the prediction.

## Threat model — what this stops, and what it does not

**Stops:**
- A compromised serving pod promoting a model (SCP-1; Decrypt-only on `model-cmk`).
- A compromised pipeline erasing evidence (PutObject-only; Object Lock; SCP-2).
- An operator quietly rewriting history (compliance-mode lock; CloudTrail in
  a separate account).
- A compromised CI run deploying (CI holds no cluster credentials).

**Does not stop:**
- **An authorised approver approving something bad.** The gate records the
  decision; it does not evaluate the judgement. This is the load-bearing
  residual risk of the entire design and it is unchanged from ADR-0004.
- **The Organization administrator**, who can rewrite the SCPs. Mitigated
  procedurally (Section 1), not technically.
- **A compromised training pipeline poisoning a candidate.** It would still
  have to pass a human review, which is a weaker control than it sounds if
  the reviewer only reads the metric comparison — which is exactly what the
  model card is for.
- **Collusion** between an approver and anyone able to alter records. Nothing
  in a single-organisation design stops this.

## Two things I would push back on if asked

**Compliance-mode Object Lock is irreversible.** An object written with a
ten-year retention cannot be removed for ten years, by anyone, for any
reason — including after a mistake, and including if it contains something it
should not (personal data written by accident). Governance mode is
recoverable by a privileged role and is the right default unless the
regulatory requirement is explicit. Choosing compliance mode should be a
decision someone signs, not a default someone copied.

**Customer-managed keys everywhere is a real operational cost.** Key policies
are a second place for access to be wrong, and a misconfigured key policy
fails in ways that are harder to diagnose than an IAM denial. The two keys
where it earns its keep are `audit-cmk` and `model-cmk`; on the others,
AWS-managed keys would be defensible.

# Target state 1 — Multi-account design

_Design only. Nothing in this document is built._

## The idea this rests on

Most multi-account designs answer an organisational question: separate teams,
separate budgets, separate blast radius. Those are good reasons and they apply
here too. But this system has a stronger driver, and it is the one worth
leading with.

**ISO 17025 requires that the person who performs work is not the only person
who authorises it**, and that records of that authorisation cannot be altered
by the people the records are about. In the current build (ADR-0004) both
controls exist, but both are enforced by *convention and application code*:
`approve()` refuses a non-pending version because the Python says so, and the
audit log is append-only because nothing in the codebase opens it for
truncation. Anyone with credentials to the MLflow database can promote a model
without an approval; anyone with write access to the host can rewrite
`audit.jsonl` and re-chain it (`docs/traceability.md` says so explicitly).

An AWS account boundary is the strongest isolation primitive AWS offers, and a
Service Control Policy cannot be overridden by any principal inside the
account it applies to — **including that account's root user**. That is a
materially stronger statement than "the code does not do that".

So: **map separation of duties onto account boundaries, and enforce it with
SCPs.** The compliance requirement chooses the topology, not an org chart.

## Accounts

| Account | Holds | Why it is its own account |
|---|---|---|
| **Management** | AWS Organizations, SCPs, billing. No workloads. | The account that writes the rules must not also run the things the rules constrain. |
| **Security** | Delegated admin for GuardDuty, Security Hub, Config, IAM Access Analyzer. Read-only into every account. | Detection must survive compromise of what it watches. |
| **Log Archive** | CloudTrail organisation trail, Config history, application audit trail. S3 Object Lock in compliance mode. | **The core control.** No workload principal has any path to it. |
| **ML Registry** | SageMaker Model Registry, model artefacts, the approval action. | **The separation-of-duties boundary.** Training happens elsewhere; promotion happens only here. |
| **Workloads — Prod** | EKS, serving API, drift evaluation, Prometheus. | Runs the method. Cannot approve it. |
| **Workloads — NonProd** | Dev and test. Synthetic or de-identified data only. | Keeps experimentation away from anything reportable. |
| **Shared Services** | ECR, CI/CD runners, artefact storage, private DNS. | One supply chain, auditable in one place. |

Seven accounts is more than a system this size needs for operational reasons.
Five of the seven exist to make a compliance statement enforceable rather than
asserted. That is the justification, and it should be stated that plainly —
a reviewer who thinks the accounts are there for tidiness will think it is
over-engineered, and they would be right if that were the reason.

## Service Control Policies — the four that matter

Written as intent; the policy documents follow from these.

**SCP-1 — Only the ML Registry account may approve a model.**

```
Deny sagemaker:UpdateModelPackage
  when  sagemaker:ModelApprovalStatus = "Approved"
  for   every account outside ou=ml-registry
```

The training job in Workloads-Prod registers a package as `PendingManualApproval`
and is *denied by the organisation* from setting it to `Approved`. Not
"the code does not call that API" — denied, at a layer the workload cannot
reach. This is the AWS equivalent of Phase 3's gate, with teeth.

**SCP-2 — Nobody can alter or delete the audit record.**

```
Deny s3:DeleteObject, s3:DeleteObjectVersion, s3:PutBucketObjectLockConfiguration,
     s3:PutLifecycleConfiguration, s3:PutBucketPolicy
  on  the log-archive buckets
  for every principal in the organisation, including the Log Archive account root
Deny cloudtrail:StopLogging, cloudtrail:DeleteTrail, cloudtrail:UpdateTrail
  for every account
Deny config:DeleteConfigurationRecorder, config:StopConfigurationRecorder
```

With Object Lock in compliance mode, an object cannot be deleted before its
retention expires *by anyone, including AWS*. This is the control that turns
"tamper-evident" into "tamper-resistant" and closes the gap named in
`docs/traceability.md`.

**SCP-3 — Data residency is a boundary, not a preference.**

```
Deny  every action outside the approved regions
Allow global services (IAM, Organizations, CloudFront, Route 53) only
```

Laboratory data leaving an approved jurisdiction is a compliance event
(Section 7 returns to this for inference). A region SCP makes it impossible
rather than discouraged.

**SCP-4 — Protect the controls themselves.**

```
Deny kms:ScheduleKeyDeletion, kms:DisableKeyRotation on the audit and model CMKs
Deny iam:DeleteRole, iam:PutRolePolicy on the approval and audit roles
Deny guardduty:Delete*, securityhub:Disable*
Deny every action by the root user except those that require it
```

## Who can do what

| Role | Train | Register a candidate | Approve | Read the audit trail | Alter the audit trail |
|---|---|---|---|---|---|
| Pipeline (Workloads-Prod) | yes | yes, as pending | **denied by SCP-1** | write-only | **denied by SCP-2** |
| Approver (ML Registry) | no | no | yes | yes | **denied by SCP-2** |
| Auditor (Security) | no | no | no | yes, all accounts | **denied by SCP-2** |
| Platform admin (Workloads) | yes | yes | **denied by SCP-1** | no | **denied by SCP-2** |
| Organisation admin (Management) | no | no | no | yes | can change SCPs — see below |

The residual risk is the last row: whoever administers the Organization can
rewrite the SCPs. That is irreducible, and the mitigation is procedural rather
than technical — Management account access behind a break-glass process, every
`organizations:*` call landing in the Log Archive under Object Lock, and an
alert on any SCP change. **Say this out loud in a review.** A design that
claims no residual risk has not been examined.

## What this does not solve

- **Approval fatigue** — the failure mode ADR-0004 names. An approver who
  clicks through without reading is indistinguishable from automatic
  promotion, and no account boundary detects it. The mitigations remain the
  model card and the metric comparison.
- **A single person holding two roles.** In a small laboratory the analyst and
  the approver may be the same human. The accounts make the *actions*
  distinguishable in the record, which is what an assessor asks for, but they
  cannot manufacture a second person.
- **Cost and friction.** Seven accounts means seven sets of baseline controls
  and a landing zone to maintain. Section 4 puts this in the migration plan;
  Phase 7 puts a number on it.

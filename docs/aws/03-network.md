# Target state 3 — Network topology

_Design only._

## Requirement first

Two network requirements come from the compliance argument rather than from
throughput or latency:

1. **The audit trail must cross account boundaries without traversing the
   public internet.** A record whose integrity is the whole point should not
   depend on TLS to an internet endpoint for its delivery path.
2. **Laboratory data must not leave the approved region**, and that must be
   enforceable rather than configured (SCP-3 handles the API surface; the
   network must not offer a route around it).

Everything below follows from those two and from ordinary practice.

## Shape

One VPC per workload account, three tiers, three AZs.

| Subnet tier | Contains | Route to internet |
|---|---|---|
| Public | NAT gateways, ALB | Internet Gateway |
| Private — app | EKS nodes, serving pods, evaluation jobs | via NAT, **egress-filtered** |
| Private — data | RDS/EBS-backed state, VPC endpoints | **none** |

Three AZs because EKS control-plane HA expects it and the cost is subnet
sprawl rather than money. Nodes in two AZs is a defensible saving at this
size (Section 5 weighs it).

## VPC endpoints — the part that does the work

Every AWS service the workload touches is reached through an endpoint, so the
traffic stays on the AWS network:

| Endpoint | Type | Why |
|---|---|---|
| S3 | Gateway | Model artefacts, audit objects. Free, no NAT charges. |
| DynamoDB | Gateway | If used for state. Free. |
| ECR API + ECR DKR | Interface | Image pulls without NAT |
| CloudWatch Logs | Interface | Log delivery off the public path |
| SageMaker API + Runtime | Interface | **Registry calls never leave the VPC** |
| Secrets Manager | Interface | Credential fetch |
| KMS | Interface | Every decrypt call |
| STS | Interface | IRSA token exchange |
| Bedrock Runtime | Interface | Section 7 — the summariser, if Bedrock is chosen |

Interface endpoints cost roughly $7–8/month each plus data processing, so
this list is about $60–70/month before traffic. That is a real number and it
buys two things: NAT data-processing charges avoided on the highest-volume
paths (S3 and ECR are gateway/interface rather than NAT), and — the reason
that matters here — **an `aws:SourceVpce` condition available in every
resource policy**, so a bucket can require that access arrives through a named
endpoint.

## How the audit trail crosses accounts

```
Workloads-Prod                       Log Archive
  pod (IRSA role)
    └─ s3:PutObject ──► S3 Gateway Endpoint ──► audit bucket
                         (never leaves AWS)      Object Lock, compliance mode
                                                 bucket policy:
                                                   Deny unless aws:PrincipalOrgID matches
                                                   Deny unless aws:SourceVpce = <endpoint>
                                                   Deny s3:DeleteObject* to everyone
```

The workload role is granted `s3:PutObject` only — no `Get`, no `List`, no
`Delete`. It can write a record and cannot read back, amend or remove one.
Reading is the auditor's role in the Security account. That asymmetry is the
network-and-IAM expression of "append-only", and it is stronger than the
current file-based implementation, where the same process that writes the log
can also read and rewrite it.

CloudTrail uses its own organisation trail into the same account, which is
standard and not the interesting part.

## Egress

The serving pod's NetworkPolicy already restricts egress to MLflow and DNS
(`deploy/chart/templates/networkpolicy.yaml`), and that intent carries over:

- Security groups: the app tier may reach the data tier on specific ports and
  the endpoints; nothing else.
- NAT exists for OS and package updates on nodes, not for application traffic.
  If the application needs the internet, that is a design question, not a
  routing one.
- The **one exception worth naming**: the drift evaluation CronJob currently
  downloads the UCI dataset from `archive.ics.uci.edu` on every run. In a
  target state that dataset is in S3 and the job has no internet egress at
  all. Leaving that download in place would mean a scheduled job in the
  compliance boundary reaching an arbitrary external host weekly, which is
  not acceptable and is easy to miss because it works fine.

## Connectivity to the laboratory

The instrument and the people are not in AWS.

- **Site-to-Site VPN** to begin with: an hour to stand up, adequate for
  batches of a few thousand rows, and it fails in ways people understand.
- **Direct Connect** only if a real requirement appears — sustained volume,
  or a latency budget, or a contractual objection to traffic over the
  internet even when encrypted. At this data volume it would be bought for
  assurance, not for performance, and that should be said openly rather than
  dressed up as a technical need.
- Private DNS through Route 53 Resolver so the laboratory resolves the
  private endpoints.

## What I would get wrong first

Endpoint sprawl. The list above is nine interface endpoints per VPC, per
account that needs them — and the instinct when something fails to connect is
to add another. At $7–8 each it is not the money, it is that an endpoint per
service in an account nobody audits becomes an undocumented network surface.
The discipline is to add an endpoint when a policy requires `aws:SourceVpce`,
not when a connection times out.

# Target state 7 — Inference architecture for the summariser

_Design only. List prices, us-east-1, September 2026._

## What is actually being served

The Phase 4b summariser: one call per drift evaluation, turning a structured
verdict into ≤120 words for a laboratory manager. It is **advisory only** —
nothing reads its output (`docs/model-cards/summariser.md`).

Two properties shape everything below and are easy to skip past:

- **The volume is tiny.** One evaluation per batch, batches arrive weekly.
  Real demand is ~4 calls a month, not 4 a second. The 1,000/day and
  100,000/day cases below are hypotheticals for an estate of many
  instruments, and should be labelled as such rather than presented as this
  system's load.
- **The payload contains no client results.** The input is
  `{batch, sensor, analyte, z-score, rules}` — aggregate instrument
  statistics. No sample identifiers, no client identity, no reportable
  measurements. This materially weakens the data-residency argument against a
  managed API, and pretending otherwise would be dishonest.

## Token profile

Measured from the deployed system's actual prompt and a real batch-7 payload:

| | tokens |
|---|---|
| System prompt (`drift_summary.v1.md`) | ~500 |
| Drift report JSON (5 rejected, 2 warned) | ~300 |
| **Input total** | **~800** |
| Output, ≤120 words plus low-effort thinking | **~360** |

## The three options

### A. Bedrock on-demand

- **Cold start:** none. First token in hundreds of milliseconds.
- **Scaling trigger:** none to operate; it is a per-call API.
- **Data residency:** stays in-region; reached through a
  `bedrock-runtime` interface endpoint so traffic never leaves the AWS
  network (Section 3). Region pinned by SCP-3.
- **Cost per 1,000 summaries** — 0.8 MTok in, 0.36 MTok out:

| Model tier | In $/MTok | Out $/MTok | **per 1,000 summaries** |
|---|---|---|---|
| Opus-tier (Claude Opus 4.6) | 5 | 25 | 0.8×5 + 0.36×25 = **$13.00** |
| Sonnet-tier (Claude Sonnet 5, to 31 Aug 2026) | 2 | 10 | **$5.20** |
| Haiku 4.5 | 1 | 5 | **$2.60** |

  Batch inference halves these; prompt caching cuts the ~500-token system
  prompt substantially, and it is identical on every call.

### B. SageMaker real-time endpoint

- **Cold start:** minutes to provision; then always warm because it is always
  on, and always billed.
- **Scaling trigger:** instance count on invocations-per-instance or a custom
  metric. Scale-out is minutes, so it is provisioning for peak, not tracking
  it.
- **Data residency:** strongest of the three — the endpoint is in your VPC on
  your instances.
- **Cost:** `ml.g5.2xlarge` at **$1.52/hour** = ~$1,110/month, whether or not
  a single request arrives.

| Demand | Summaries/month | Cost per 1,000 |
|---|---|---|
| 10/day | 300 | **$3,700** |
| 1,000/day | 30,000 | **$37** |
| 100,000/day | 3,000,000 | **$0.37** (if one instance sustains 1.2 req/s) |

### C. Self-managed on EKS with llm-d

**Why llm-d rather than "EKS with GPU nodes".** That older phrasing means
vLLM behind a plain Kubernetes Service, load-balanced without regard to where
the KV cache lives. llm-d is the orchestration layer above vLLM: it separates
**prefill and decode onto independent GPU pools** (monolithic vLLM saturates
prefill GPUs under concurrent decode), moves KV cache between them over the
vLLM NIXL connector, and routes **cache-aware** through the Kubernetes
Gateway API Inference Extension. It was donated to the CNCF Sandbox on
**24 March 2026**, founded by Red Hat, Google Cloud, IBM Research, CoreWeave
and NVIDIA. The Red Hat lineage makes it directly relevant to the OpenShift
estate this design's author works in.

- **Cold start:** worst. Node provisioning plus model load — tens of minutes
  from cold, and scale-to-zero is not realistic.
- **Scaling trigger:** your own, on queue depth or GPU utilisation, with
  prefill and decode pools scaling independently — which is the point, and
  also two things to tune instead of one.
- **Data residency:** total. Nothing leaves your nodes.
- **Cost:** `g5.2xlarge` EC2 on-demand ~$1.21/hour ≈ $885/month per node,
  plus $73/month EKS control plane, plus the operational cost of Gateway,
  EPP and InferencePool. Below saturation it is strictly worse than option B;
  above it, cache-aware routing and disaggregation raise tokens per GPU-hour,
  and that is where it wins.

## Where the line falls

| Demand | Choice | Why |
|---|---|---|
| **10/day** (this system, ×100) | **Bedrock** | $4/month against $1,110. Not close. Any dedicated capacity is idle 99.9% of the time. |
| **1,000/day** | **Bedrock**, probably on a smaller model | $390/month at Opus-tier, $78 at Haiku, against $1,110 for an always-on endpoint. A dedicated endpoint only wins here if the GPU is already bought for something else. |
| **100,000/day** | **Self-managed**, and this is where llm-d earns its keep | Bedrock at Opus-tier is ~$39,000/month; Haiku ~$7,800. A few g5 nodes are $2,600–5,000. The saving pays several engineers, which is the test for whether self-hosting is worth its operational load. |

**Crossover is somewhere between 10,000 and 30,000 summaries/day**, depending
on model size and how much batching is tolerable. That range is wide because
it is an estimate, and the honest way to narrow it is to measure — which
brings us to the limitation.

## The measurement I do not have

The plan for this project anticipated substituting measured tokens-per-second,
memory occupancy and cost-per-1,000-tokens from a GPU exercise on the
homelab. **That is not possible on this hardware.** The GPU in `server1` is an
NVIDIA MX450 with 2 GB of VRAM — it cannot hold a usefully sized model, let
alone demonstrate prefill/decode disaggregation, which needs at least two
GPUs to mean anything.

So every figure in option C is vendor-published or arithmetic from list
prices, and **none of it is measured**. A cost comparison built on one
measured data point and two published figures would be far more defensible
than three estimates, and this is three estimates. Saying so is more useful
than implying otherwise: the recommendation at 10/day and 1,000/day does not
depend on the missing measurement, and the recommendation at 100,000/day
does — which is exactly the case this system does not have.

## The maturity caveat

llm-d has been a CNCF Sandbox project only since March 2026. Sandbox is the
earliest tier — it signals interest, not production maturity. The Gateway,
Endpoint Picker and InferencePool components are real operational surface
against a plain Kubernetes Service, and each is a thing that can fail at 3am
in a way a Service cannot.

Recommending it **with** that caveat is judgement. Recommending it without
reads as having read a launch post. For a regulated workload specifically,
the additional question is validation burden: a fast-moving Sandbox project
changes its own behaviour between releases, and every change to the serving
path is a change to a validated system (ADR-0005).

## Recommendation

**Bedrock, on the smallest model that passes the eval harness.**

The eval harness already exists and already gates prompt changes
(`.github/workflows/eval.yml`), so "smallest model that passes" is a
measurable claim rather than a guess — run the suite against Haiku and read
the scores. At this system's real volume the whole line item is a few dollars
a month, the payload carries no client data, and an interface endpoint keeps
traffic on the AWS network.

Revisit only if one of three things changes: volume crosses ~10,000/day; the
payload starts carrying reportable results; or a regulator requires inference
inside the account boundary. ADR-0007 records what would have to be true for
that last one.

**Sources:** [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) ·
[SageMaker pricing](https://aws.amazon.com/sagemaker/ai/pricing/) ·
[llm-d](https://github.com/llm-d/llm-d) ·
[EKS pricing](https://aws.amazon.com/eks/pricing/)

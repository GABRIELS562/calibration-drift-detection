# ADR-0007: Inference hosting for the summariser

## Status

Accepted — 2026-09-25 (target-state design; not built)

## Context

The Phase 4b summariser calls a large language model to turn a drift verdict
into a written finding. Hosting it raises a question that sounds like it has
an obvious regulated answer — *keep it in the account* — and does not.

Three facts constrain the decision, and the first two are usually the ones
people skip:

1. **The component is advisory.** It decides nothing. The retraining trigger
   reads the Westgard verdict; the gate reads a human decision; the audit
   record is written independently. No code path imports the summariser
   (`docs/model-cards/summariser.md`).
2. **The payload carries no reportable data.** It is
   `{batch, sensor, analyte, z-score, rules}` — aggregate instrument
   statistics. No sample identifiers, no client identity, no measurements
   that were or could be reported.
3. **The real volume is about four calls a month**, because evaluations
   follow batches and batches arrive weekly.

## Decision

**Use Bedrock on-demand, on the smallest model that passes the eval harness,
reached through a `bedrock-runtime` interface endpoint with the region pinned
by SCP-3.**

"Smallest model that passes" is measurable rather than rhetorical: the eval
suite exists (`src/drift/eval/`), 33 golden cases, seven deterministic
scorers with negative tests, a readability judge and a committed baseline.
Running it against a cheaper model is a CI job, and the answer is a number.

**Deterministic fallback remains mandatory.** If Bedrock is unavailable, the
template renders the same facts. This is unchanged and non-negotiable: the
record cannot depend on a third party's uptime — which is why the fallback,
not the model, is the default path in the current repository.

## Why a managed API can be defensible for a regulated workload

This is the question an interviewer reaches for the moment they see an LLM in
a regulated pipeline, so the answer should be structural rather than
reassuring.

The usual objection — "our data leaves our boundary" — is an argument about
**what** leaves, not about **whether** a managed service was used. Here, what
leaves is a handful of z-scores about instrument behaviour. It contains
nothing a laboratory would be obliged to protect, and no result that was ever
reported. If the payload changed — if a future version summarised sample
results rather than sensor statistics — this decision would have to be made
again, and would probably come out differently. The decision is contingent on
the payload, and that contingency is the honest part of it.

The second objection — "a non-deterministic component in a validated system"
— is real and is answered by *position*, not by hosting. A component that
decides nothing cannot invalidate a decision. Moving it inside the VPC would
not change that; it would only change who operates the GPU. Self-hosting to
address a validation concern that hosting does not cause is a category error,
and an expensive one.

## What would be needed from the provider to prove it

If challenged by an assessor, these are the things that must be obtainable.
They are the actual acceptance criteria for "a managed API is acceptable
here", and they are worth listing because most people asked this question
answer with a feeling instead:

1. **A contractual statement that inputs are not used to train models**, and
   that they are not retained beyond what is needed to serve the request.
2. **Regional processing guarantees** — that a request submitted in-region is
   processed in-region — enforceable from our side by SCP-3 and verifiable in
   CloudTrail.
3. **An audit trail of every call from our side**: CloudTrail for the API
   invocation, plus our own record of prompt version, model identifier, token
   counts and which path served the response (model or fallback). The
   `Summary` object already carries `prompt_version`, `model`, `source` and
   token counts, so this exists.
4. **Model version identification and change notice.** This is the weakest
   link. A managed endpoint can change behind a stable name, and under
   ADR-0005 that is a change to a validated system made by someone else. Two
   mitigations, both required: pin an explicit versioned model identifier
   rather than a floating alias, and **run the eval harness on a schedule,
   not only on prompt changes** — so a silent provider-side change shows up
   as a score regression rather than as a quiet degradation nobody notices.
5. **Compliance attestations** for the provider covering the relevant scope.
6. **A documented fallback** whose output is acceptable on its own, which we
   have, and which is deterministic, which matters more than it sounds.

Point 4 is the one that deserves a sentence in any review: **the eval harness
is what makes a managed model acceptable.** Without it, "the provider might
have changed the model" is unanswerable. With it, it is a build that goes red.

## Consequences

**Easy:**
- Effectively free at this volume: a few dollars a month, no idle capacity.
- No GPU nodes, no scaling policy, no model-server upgrades inside a
  validated boundary.
- The existing fallback and eval harness carry over unchanged.

**Hard / accepted costs:**
- **A supplier can change the model.** Mitigated by pinned identifiers and
  scheduled evals; not eliminated.
- **The decision is payload-contingent.** If the summariser is ever pointed
  at richer data it must be revisited, and nothing in the code enforces that
  — it is a documentation dependency, which is a weak kind.
- **No self-hosting expertise is developed.** At an estate of many
  instruments this decision reverses, and the team would be starting from
  zero.
- **Crossover is estimated, not measured** (Section 7). The homelab GPU is a
  2 GB MX450 and cannot host a usable model, so the self-hosting figures are
  vendor-published arithmetic rather than measurement.

## Options considered

- **SageMaker real-time endpoint.** Strongest data-residency story: your VPC,
  your instances. Rejected on economics at this volume — ~$1,110/month of
  always-on capacity for roughly four calls, i.e. about $3,700 per thousand
  summaries at the real rate. It becomes the right answer if the payload ever
  carries reportable data and Bedrock's contractual position is judged
  insufficient.
- **Self-managed on EKS with llm-d.** The most interesting option and the
  wrong one here. It wins decisively above roughly 10,000–30,000
  summaries/day, where cache-aware routing and prefill/decode disaggregation
  raise tokens per GPU-hour enough to pay for the operational load. At four
  calls a month it is pure cost. It also carries a validation consideration
  specific to this context: llm-d has been a CNCF Sandbox project only since
  March 2026, Sandbox is the earliest maturity tier, and a fast-moving
  component in the serving path is a recurring change to a validated system.
- **No LLM at all — ship the deterministic template only.** Genuinely
  defensible, and it is what runs today. Rejected because the plain-language
  finding is the part a laboratory manager actually reads, and because the
  eval harness that gates it is the artefact that demonstrates how to run a
  non-deterministic component responsibly. If the eval harness were cut, this
  option would become correct.
- **A self-hosted small model on CPU.** Avoids GPU cost entirely. Not
  assessed seriously; at four calls a month the saving over Bedrock is
  measured in single dollars and the quality risk is unquantified.

## Related

- ADR-0004 — gated promotion (why an advisory component must stay advisory)
- ADR-0005 — validating a changing system (the provider-change problem)
- ADR-0006 — build versus buy for the ML platform
- `docs/aws/07-inference.md` — the three-way comparison and the arithmetic
- `docs/model-cards/summariser.md` — the advisory statement and limitations

# ADR-0005: Validating a system that changes itself

## Status

Accepted — 2026-09-23

## Context

This is the tension the project exists to examine, and it does not have a
settled answer in the field.

Validation, as a laboratory means it, is a statement about a fixed thing:
*this method, in this configuration, produces results fit for this purpose,
and here is the evidence.* The evidence is gathered once, the configuration
is then frozen, and any change re-opens the question. The whole apparatus —
change control, revalidation, periodic review — exists to keep the frozen
thing and the validated claim in agreement.

A drift-responsive ML system is the opposite by design. Its value is that
it changes when the world changes. If the sensors degrade and the model
does not follow, the model is wrong; if the model follows, the validated
artefact no longer exists. Retrain often enough and the system is
unvalidated more of the time than it is validated.

Neither discipline resolves this for the other. The MLOps literature treats
retraining as an operational event and validation as a test suite. The
regulated-laboratory literature (GAMP 5, ISO 17025, FDA computer software
assurance) was written for systems whose behaviour changes only when
someone changes it, and its advice — freeze it, control the change — is
correct but assumes changes are rare and human-initiated.

## Decision

**Validate the process that produces models, not each model as a separate
system. Then validate each model against the process.**

Two layers, with different lifetimes:

**Layer 1 — the validated system, which does not change often.** The
pipeline: how a reference distribution is computed, which control rules
apply and at what limits, what triggers a candidate, how a candidate is
evaluated against the incumbent, what an approval requires, how a rollback
works. This is what ADRs 0002–0004 define, what the 88 tests exercise, and
what a pull request is required to change. It is frozen in the sense
validation requires — it changes only by a reviewed, recorded, deliberate
act.

**Layer 2 — the model version, which changes as often as drift demands.**
A model version is not a new system. It is an *output* of the validated
system, in the way a result is an output of a validated method. It carries
its own evidence — training data hash, metrics against the incumbent on
identical held-out data, the drift verdict that caused it, and an approval
record naming a person — but it does not require the system to be
revalidated, because the system did not change.

**The human approval is what joins the two layers.** It is not a
formality standing in for automation that was too hard to write. It is the
point at which a person asserts that this particular output of the
validated process is fit to release — the same assertion an analyst makes
signing off a run. Automation can establish that the process ran correctly.
It cannot assert fitness for purpose, because fitness is a claim about the
world, not about the code.

**Consequently:**

1. **The trigger is evidence, not a decision.** Westgard rules say the
   instrument is out of control. They do not say the model should be
   replaced — a rejected sensor may mean the sensor needs replacing, and
   retraining on its degraded output would encode the fault as normal. The
   candidate is prepared so a human has something concrete to judge; the
   judgement remains theirs.

2. **Rejected candidates are part of the validation record.** A process
   that only records its successes cannot demonstrate it was working. The
   batches where the system declined to act (entries 3 and 4 of the audit
   trail) evidence the rules were applied continuously, not selectively.

3. **The reference distribution is a validated artefact and changes only by
   pull request.** It is the definition of "normal"; if it could be
   regenerated automatically, drift could be made to disappear by moving
   the goalposts. This is the single most important freeze in the design.

4. **Revalidation is required when Layer 1 changes**, not when a model
   version changes. Changing a control limit, the trigger condition, the
   reference, or the model class is a change to the validated system and
   needs the full argument again — which is why each lives in an ADR.

5. **The system states what it is not.** Every model card says the model is
   not a released measurement method and its outputs are not reportable
   results. The honest position for a system in this posture is to be
   explicit about the boundary rather than to imply a validation it does
   not hold.

## Consequences

**Easy:**
- Retraining is frequent without the validated state being in doubt: the
  process is what is validated, and the process did not change.
- A change to the *rules* is loud — a pull request, a new ADR — while a
  change to a *model* is routine. The two are separated by design, which is
  how a laboratory separates method development from running a method.
- The argument extends to Phase 4b's prompt: version-controlled, changed by
  pull request, gated by an eval harness. Same structure, non-deterministic
  component.

**Hard / accepted costs:**
- The claim "the process is validated" is only as strong as the tests and
  the review of the process. Eighty-eight tests and a handful of ADRs is
  evidence, not a validation package; a real one would include a
  requirements specification, a traceability matrix from requirement to
  test, and independent review.
- The approver becomes the load-bearing control. Approval fatigue is the
  realistic failure mode — an approver who promotes without looking is
  indistinguishable from automatic promotion, and nothing in the system
  detects it. Model cards and the metric comparison are mitigations, not
  remedies.
- There is no defined revalidation interval. Re-evaluation is event-driven
  (a batch arrives), and a system that is never triggered is never
  re-examined. A calendar-driven periodic review would be the laboratory
  answer and is not implemented.
- Two-layer validation is an argument, not a citation. No standard states
  it in these terms. It is defensible and consistent with both bodies of
  practice, but presenting it as established would be false.

## Options considered

- **Validate each model version as a separate system.** The literal reading
  of the standards. Rejected: revalidation per retrain is either
  prohibitively slow or becomes a rubber stamp, and a rubber stamp is worse
  than an honest process claim because it looks like a control.
- **Freeze the model permanently and handle drift by recalibrating the
  instrument instead.** Genuinely the right answer in some settings, and
  worth saying so: if the instrument can be brought back into tolerance,
  the model does not need to change. Rejected as the general answer because
  sensors age irreversibly; eventually the instrument's in-tolerance
  behaviour is not the behaviour the model was trained on.
- **Continuous validation — an automated test suite as the release gate.**
  Rejected as sufficient, retained as necessary. Tests establish the
  process ran correctly, which is a claim about the code, not about
  fitness for purpose. It is the automation-only position this ADR argues
  against, and it is exactly the shape of Phase 4b's eval harness: gating,
  not deciding.
- **Shadow mode indefinitely — never promote, always advise.** Rejected:
  it avoids the question rather than answering it, and a model nobody relies
  on has no validation requirement because it has no consequence.

## Related

- ADR-0001 — project purpose and scope
- ADR-0003 — drift thresholds and the decision rule
- ADR-0004 — gated promotion (the mechanism this justifies)
- `docs/traceability.md` — the evidence chain
- `docs/control-mapping.md` — controls against GAMP 5 / ISO 17025

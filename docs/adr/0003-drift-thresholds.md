# ADR-0003: Drift thresholds and the decision rule

## Status

Accepted — 2026-09-23

> **Cost figures below are generic regulated-laboratory reasoning, not this
> author's documented incident history.** They are stated as assumptions so
> the argument can be checked. Replacing them with real numbers from a real
> laboratory — investigation cost, lookback scope, recall volume — would
> strengthen the ADR and change none of its conclusions.

## Context

Phase 2 must decide when a production batch is different enough from the
reference to act on. Three things have to be settled: which statistic, what
threshold, and what unit the verdict is expressed in (feature, sensor, or
instrument).

The plan's starting points were the field-standard ones: KS with p < 0.05,
PSI with the credit-risk bands (< 0.1 stable, 0.1–0.25 moderate, > 0.25
significant). Both were run against all nine production batches with Batch 1
as reference. The results are committed in `docs/drift-summary.md`.

**KS is unusable on this data.** It flags 126–128 of 128 features on every
batch, including batch 2.

| batch | rows | KS p < 0.05 | PSI > 0.25 |
|---|---|---|---|
| 2 | 1,244 | 128/128 | 82/128 (64%) |
| 3 | 1,586 | 128/128 | 121/128 |
| 4 | 161 | 127/128 | 128/128 |
| 7 | 3,613 | 126/128 | 112/128 |
| 10 | 3,600 | 127/128 | 109/128 |

This is not a defect in KS. With a 445-row reference against batches of
1,000–3,600 rows, KS has enough power to resolve differences far smaller
than anything of practical consequence. A p-value answers "is there a
difference?"; at this sample size the answer is always yes. The question
worth asking is "is the difference big enough to act on?", which is a
question about effect size, not significance.

**PSI grades the drift but still breaches everywhere.** At the textbook
0.25 per feature with a 50%-of-features share rule, every batch from 2
onward triggers. A detector that fires on the first production window and
never stops is indistinguishable from no detector at all: the failure mode
is not missed detection, it is that nobody reads the alerts by month three.

**Both share a deeper problem: the unit of judgement is wrong.** "64% of
features drifted" is not a finding anyone can act on. It does not say which
sensor, and it conflates two different phenomena — the sensors degrading,
and the gas mix under test changing between batches (toluene is absent from
batches 3–5; batch 10 is artificially balanced at 600 samples per gas). A
share-of-features rule is a construct borrowed from credit scoring, where
features are independent predictors. Here the 128 features are 16 physical
devices × 8 derived measures, and the physical device is the thing that
gets repaired.

## Decision

**Adopt Westgard multirules as the decision rule, applied per sensor per
analyte.** This is the control framework used for analytical runs in
accredited laboratories, and the mapping to this problem is direct:

| Westgard | Here |
|---|---|
| Analyte | Gas class (6) |
| Control material | The reference batch's samples of that gas |
| Run | A production batch |
| Control statistic | Batch mean of a sensor's steady-state response for that gas |
| Limits | Reference within-gas mean and SD for that sensor |

**Rules, and what each catches:**

| Rule | Condition | Action | Failure mode it catches |
|---|---|---|---|
| 1₃ₛ | current point beyond 3 SD | **reject** | sudden excursion |
| 2₂ₛ | two consecutive beyond 2 SD, same side | **reject** | sustained shift |
| 4₁ₛ | four consecutive beyond 1 SD, same side | **warn** | slow systematic drift |
| 10ₓ | ten consecutive on one side of the mean | **warn** | trend within limits |

Single-point rules miss slow drift; trend rules miss sudden excursions.
Both are required, which is the same conclusion the KS-versus-PSI
comparison reaches from the statistical side.

**Warning limits and action limits, not one line.** 4₁ₛ and 10ₓ open an
investigation; 1₃ₛ and 2₂ₛ stop the run. A single threshold forces every
signal to be either an alarm or nothing, and the cost asymmetry below is
not symmetric enough to support that.

**Per-sensor verdict; no share-of-features rule.** A sensor is *rejected*
when a reject rule fires on any of its six analyte charts, *warned* when
only investigate rules fire. Sixteen verdicts per batch, each naming the
chart that triggered it. A violation on one analyte does not condemn the
other fifteen sensors, exactly as a Westgard violation on one analyte does
not condemn the whole run.

**Control charts run on the steady-state feature (`f1`) only** — 96 charts
(16 sensors × 6 gases) rather than 768. `f1` is the sensor's measured
response, the analogue of the reported result; the six transient features
describe the shape of the response curve and are diagnostic detail shown
once a sensor is flagged. Charting all eight would multiply the alert
surface eightfold for information that does not change the verdict.

**PSI is retained, demoted.** It stays in the Evidently reports as a
per-feature distribution diagnostic, because it sees something the mean
chart cannot: a change in distribution shape at a stable mean (variance
collapse, bimodality). It does not drive the verdict and it does not
trigger retraining.

**Absent analytes break consecutive sequences.** Toluene is not tested in
batches 3–5. Those gaps break 2₂ₛ, 4₁ₛ and 10ₓ runs rather than counting as
in-control points. An untested analyte is not a passing analyte.

### What this produces

Committed in `docs/westgard-summary.md`:

| batch | rejected | warned | first signal |
|---|---|---|---|
| 2–4 | 0/16 | 0/16 | in control |
| 5 | 0/16 | 4/16 | 4₁ₛ, acetaldehyde, sensors 1, 2, 9, 10 |
| 6 | 4/16 | 5/16 | 1₃ₛ, toluene, sensors 7, 8, 15, 16 (z +3.2 to +3.9) |
| 7 | 5/16 | 2/16 | sensors 1, 9, 10 cross 3 SD low on toluene |
| 8–10 | 4/16 | 1–4/16 | sensors 1, 2, 9, 10 sustained (2₂ₛ + 4₁ₛ) |

Three properties the PSI design did not have. Batches 2–4 are in control —
the population shifted, but no sensor's response to a given gas moved out
of limits. The first signal is a warning, raised by the trend rule before
any single point is alarming. And the rejects name four specific channels,
consistently, from batch 7 onward: a maintenance action, not a
recalibration of the array.

## Justification of the thresholds

The threshold values are Westgard's, unmodified. What has to be justified
is why a framework with these particular limits is right here, and that
rests on the asymmetry between the two error costs.

**Cost of a false positive** — a batch flagged that was in fact fine. The
consequences are an investigation (re-run of the control material,
consumables, instrument time), the analyst hours to work through it, delay
to any results queued behind the run, and a retraining candidate a reviewer
has to assess and reject. Real, bounded, and paid in hours.

**Cost of a missed detection** — a batch not flagged whose measurements
were out of tolerance. The consequences are not bounded by the incident.
Results have already been reported. Establishing scope means a lookback to
the last known-good control point, which may be several runs earlier;
every result in that window is suspect and may require recall and re-test.
Affected clients must be notified. A nonconformance and CAPA are raised,
with root cause, correction and effectiveness check. The recalibration
interval itself is likely to be shortened afterwards, because the interval
was evidently too long — a permanent increase in running cost. And in an
accredited laboratory the finding is visible at the next assessment, where
the question is not "did you fix it" but "why did your controls not catch
it".

**The asymmetry is at least an order of magnitude, and it is
qualitative rather than merely quantitative.** A false positive costs
time. A missed detection costs reported results, client confidence, and
an accreditation finding. Thresholds should therefore be tight.

**But tight thresholds only help if the alerts are read.** The PSI run is
the evidence: a rule that fires on every batch from the first one produces
exactly the inattention that causes missed detections. Sensitivity that
destroys attention is not sensitivity.

Westgard resolves this tension in the way laboratories resolved it
decades ago — not with one tighter number, but with a graded response.
Rare, high-specificity rules (1₃ₛ, 2₂ₛ) stop the run. Common,
lower-specificity rules (4₁ₛ, 10ₓ) open an investigation without stopping
anything. The expensive error is caught by the rules that stop work; the
cheap-to-investigate early signal is caught by the rules that do not. The
false-positive budget is spent where a false positive costs an
investigation rather than a halted run.

That is the argument for these thresholds, and it is why they are not
tuned. Tuning them to this dataset would optimise for nine batches of a
2013 sensor array and discard the property that makes them defensible:
they are the limits an assessor already recognises, with decades of
operational history, and a deviation from them would itself need
justification.

## Consequences

**Easy:**
- Output is actionable: "sensors 1, 2, 9, 10 rejected on toluene" is a work
  order. "64% of features drifted" is not.
- The Phase 5 Grafana panel is a control chart, which anyone from a
  laboratory reads without training.
- The retraining trigger in Phase 3 has an unambiguous definition: any
  sensor rejected.
- Deviation from the rules is detectable, because the rules are standard.

**Hard / accepted costs:**
- The reference within-gas SDs come from as few as 30 samples
  (acetaldehyde) and 74 (toluene). Those two charts have the least certain
  limits and will be the least reliable. Stated rather than hidden.
- The batch-6 toluene rejects are single-point 1₃ₛ with no trend history,
  because toluene was untested in batches 3–5. They are correct under the
  rules but weaker evidence than the sustained sensor 1/2/9/10 signal.
- Charting `f1` only means a drift that appears solely in the transient
  response shape, with a stable steady-state mean, will not trigger a
  verdict. PSI in the Evidently reports is the partial mitigation; it is
  not a complete one, and that is the main known gap in this design.
- Control charts need history. 4₁ₛ cannot fire before the fourth
  production batch, and 10ₓ cannot fire at all with nine. Early batches are
  judged on single-point rules alone and are therefore less sensitive than
  later ones.
- Using the batch mean assumes samples within a batch are comparable. The
  batches vary in gas concentration as well as in time, so some of the
  measured shift is concentration, not degradation. Separating the two
  would need the concentration metadata, which this dataset does not carry.

## Options considered

- **KS with p < 0.05 (the plan's starting point).** Rejected on evidence:
  126–128 of 128 features on every batch. At this sample size a p-value
  answers a question nobody asked.
- **PSI > 0.25 with a 50% share rule (the plan's starting point).**
  Rejected: every batch breaches from batch 2, and the share rule is a
  credit-risk construct that does not map onto physical sensors. Retained
  as a diagnostic.
- **Tuned PSI — raise the threshold until only later batches breach.**
  Rejected: the threshold would be fitted to nine batches of one array and
  defensible nowhere else. It also cannot distinguish a slow trend from a
  sudden excursion at any threshold, which is the actual requirement.
- **Westgard on all eight features per sensor (768 charts).** Rejected: an
  eightfold alert surface for information that does not change the verdict.
  Revisit if a transient-only drift is ever observed.
- **Westgard with tuned sigma limits.** Rejected: discards the framework's
  main advantage, which is that the limits are recognised and have
  operational history behind them.
- **A single action limit with no warning limit.** Rejected: forces every
  signal to be an alarm or nothing. The acetaldehyde 4₁ₛ at batch 5 — the
  earliest true signal in the data — would have been invisible.

## Related

- ADR-0002 — dataset, reference split and baseline model
- ADR-0004 — gated promotion (the retrain trigger this feeds)
- ADR-0005 — validating a continuously retraining system
- `docs/drift-summary.md` — PSI and KS results per batch
- `docs/westgard-summary.md` — control-chart verdicts per batch
- `src/drift/westgard.py` — rule implementation

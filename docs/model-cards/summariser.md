# Component card — drift summariser

_An LLM component inside a regulated pipeline. Read the advisory statement
before anything else._

## Advisory only — what this component may and may not do

**The summariser writes a note. It does not approve, reject, trigger,
promote or roll back anything.**

- No code path reads its output. The retraining trigger acts on the
  Westgard verdict (`src/drift/retrain.py`); the approval gate acts on a
  human decision (`src/drift/registry.py`). Neither imports this module.
- Its output is not a record of the evaluation. The record is the
  `drift_evaluated` entry in `audit/audit.jsonl` and the JSON verdict under
  `artifacts/`, both written independently of this component.
- Its output is not a reportable result and forms no part of the
  traceability chain in `docs/traceability.md`.

This is a design decision, not a limitation to be lifted later. A
non-deterministic component cannot hold a signature, and under ISO 17025 a
decision about a measurement system needs one.

## Intended use

Turn the structured verdict of a control-chart evaluation into a short
plain-language finding (≤ 120 words) for a laboratory manager who is
experienced with instruments but is not a statistician or a programmer.

## Inputs and outputs

- **Input:** the JSON produced by `to_report_input()` — batch number,
  reference batch, and the rejected and warned sensors with their analyte,
  z-score and rules. Facts only; no prose and no verdict language.
- **Output:** prose. No headings, no bullet points, no recommendations.

## Model and configuration

| | |
|---|---|
| Model | `claude-opus-5` |
| Effort | `low` — a short, constrained transformation of structured input |
| Max tokens | 4000 |
| Prompt | `src/drift/prompts/drift_summary.v1.md`, version 1 |

**The prompt is part of the validated system.** It lives in version
control and changes only through a pull request with a passing eval run.
Treating a prompt as configuration rather than as code is how a change to
system behaviour escapes change control.

## Fallback

If no credentials are configured, or the API errors, or the model refuses
(`stop_reason == "refusal"`), or the response is empty, a deterministic
template renders the same facts. The fallback is not a degraded mode to be
tolerated — **it is the default path in this repository**, since no
credentials are configured here, and it is what the committed eval baseline
scores. The audit trail cannot depend on a third party's uptime.

## Cost

Token spend and an estimated dollar cost are recorded as Prometheus
counters (`src/drift/metrics.py`): `drift_summariser_input_tokens_total`,
`..._output_tokens_total`, `..._calls_total`, `..._fallbacks_total`,
`drift_summariser_cost_usd_total`. Exposed on `/metrics` in Phase 5.

## How it is evaluated

33 golden cases in `tests/eval/cases/` — the nine real production batches
plus 24 systematic edge cases (1 to 16 rejected sensors, each rule alone,
warnings only, one analyte versus six, extreme and marginal z-scores, and a
first run with no history). Cases store expected **properties**, never
expected text.

Seven deterministic scorers, all of which have negative tests proving they
fail on output that violates the property they check:

| Scorer | Checks |
|---|---|
| `is_not_empty` | there is output |
| `names_every_rejected_sensor` | every rejected sensor id appears |
| `names_every_analyte` | every implicated analyte appears |
| `within_word_limit` | ≤ 120 words |
| `no_recommendation_language` | no should/must/recommend/retrain/approve/… |
| `states_in_control_when_clean` | a clean run is said to be clean |
| `distinguishes_warnings` | warnings are mentioned and framed as early signals |

One LLM judge, for the single fuzzy criterion — is this readable to a
non-technical laboratory manager. Run three times with the median taken,
because a single judge run is noisy enough to turn a build red for no
reason. Floor of 4.0 out of 5.

`docs/eval-baseline.json` is committed. CI fails a merge when any
deterministic rate drops or the judge median falls.

## Known limitations

- The committed baseline scores the **template**, not the model, because no
  credentials are configured in this repository. A live baseline requires
  running `--live --judge` once with an API key and re-committing.
- The judge is the same model family as the generator, which is a known
  weakness in LLM-as-judge setups; it is used for one narrow readability
  question only, not for correctness.
- `no_recommendation_language` is a word list. It catches the obvious
  phrasings and will miss an implied recommendation carried by tone.
- The scorers check that required facts are **present**. They do not check
  that everything present is **true** — a hallucinated extra sensor would
  pass every deterministic scorer. Mitigated by the input being small and
  fully structured, not eliminated.

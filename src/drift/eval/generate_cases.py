"""Build the golden eval dataset from real Westgard evaluations.

The cases are not invented: each is a control-chart verdict this system
actually produced, plus hand-built edge cases that the real batches do not
contain. We save the expected *properties* (in the scorers), never expected
output text — LLM text varies and asserting on it would be a flake factory.
"""

import json
from pathlib import Path
from typing import Any, Final

from drift.data import N_BATCHES, load_batch
from drift.summarise import to_report_input
from drift.train import REFERENCE_BATCH
from drift.westgard import (
    ChartEvaluation,
    Rule,
    SensorVerdict,
    Verdict,
    WestgardResult,
    evaluate_batch,
    reference_limits,
)

CASES_DIR: Final = Path(__file__).resolve().parents[3] / "tests" / "eval" / "cases"


def _chart(gas: int, z: float, rule: Rule) -> ChartEvaluation:
    return ChartEvaluation(gas=gas, column="s01_f1", z=z, rules=frozenset({rule}))


def _sensors(
    rejected: list[tuple[str, int, float, Rule]], warned: list[tuple[str, int, float, Rule]]
) -> tuple[SensorVerdict, ...]:
    named = {name for name, *_ in rejected} | {name for name, *_ in warned}
    out = [
        SensorVerdict(name, Verdict.REJECT, (_chart(gas, z, rule),))
        for name, gas, z, rule in rejected
    ]
    out += [
        SensorVerdict(name, Verdict.WARN, (_chart(gas, z, rule),)) for name, gas, z, rule in warned
    ]
    out += [
        SensorVerdict(f"s{i:02d}", Verdict.IN_CONTROL, ())
        for i in range(1, 17)
        if f"s{i:02d}" not in named
    ]
    return tuple(out)


def _synthetic_cases() -> list[tuple[str, WestgardResult]]:
    """Edge cases the ten real batches do not produce.

    Systematic coverage of the properties the deterministic scorers check:
    how many sensors are rejected, which rules fire, whether warnings are
    present, and whether one or many analytes are involved.
    """
    rules = [Rule.R_1_3S, Rule.R_2_2S]
    warn_rules = [Rule.R_4_1S, Rule.R_10X]
    cases: list[tuple[str, WestgardResult]] = [
        ("synthetic-all-in-control", WestgardResult(1, 90, (2, 3), _sensors([], []))),
    ]
    batch = 91

    # Scale: 1, 2, 4, 8 and all 16 sensors rejected on one analyte.
    for count in (1, 2, 4, 8, 16):
        rejected = [(f"s{i:02d}", 6, -3.2 - i / 10, Rule.R_1_3S) for i in range(1, count + 1)]
        result = WestgardResult(1, batch, (2, 3), _sensors(rejected, []))
        cases.append((f"synthetic-reject-{count:02d}", result))
        batch += 1

    # Each rule alone, as a rejection and as a warning.
    for rule in rules:
        cases.append(
            (
                f"synthetic-rule-{rule.value}",
                WestgardResult(1, batch, (2, 3), _sensors([("s05", 3, -3.4, rule)], [])),
            )
        )
        batch += 1
    for rule in warn_rules:
        cases.append(
            (
                f"synthetic-warn-{rule.value}",
                WestgardResult(1, batch, (2, 3), _sensors([], [("s06", 4, -1.6, rule)])),
            )
        )
        batch += 1

    # One analyte vs several, with and without warnings alongside.
    for n_analytes in (1, 3, 6):
        rejected = [
            (f"s{i:02d}", (i % n_analytes) + 1, -3.5, Rule.R_1_3S) for i in range(1, n_analytes + 2)
        ]
        for with_warning in (False, True):
            warned = [("s15", 2, 1.5, Rule.R_4_1S)] if with_warning else []
            suffix = "warn" if with_warning else "only"
            cases.append(
                (
                    f"synthetic-analytes-{n_analytes}-{suffix}",
                    WestgardResult(1, batch, (2, 3), _sensors(rejected, warned)),
                )
            )
            batch += 1

    # Both rules on different sensors in the same run.
    cases.append(
        (
            "synthetic-mixed-rules",
            WestgardResult(
                1,
                batch,
                (2, 3),
                _sensors(
                    [("s01", 6, 4.2, Rule.R_1_3S), ("s02", 2, -2.4, Rule.R_2_2S)],
                    [("s03", 3, 1.4, Rule.R_4_1S), ("s04", 4, 0.3, Rule.R_10X)],
                ),
            ),
        )
    )
    batch += 1

    # Extreme and marginal z-scores.
    for label, z in (("extreme", -18.7), ("marginal", -3.01), ("positive", 3.02)):
        cases.append(
            (
                f"synthetic-z-{label}",
                WestgardResult(1, batch, (2, 3), _sensors([("s13", 5, z, Rule.R_1_3S)], [])),
            )
        )
        batch += 1

    # Warnings only, at several scales.
    for count in (1, 4, 10):
        warned = [(f"s{i:02d}", 4, -1.5, Rule.R_4_1S) for i in range(1, count + 1)]
        result = WestgardResult(1, batch, (2, 3), _sensors([], warned))
        cases.append((f"synthetic-warnonly-{count:02d}", result))
        batch += 1

    # No history: the first production run, single-point rules only.
    first_run = WestgardResult(1, batch, (), _sensors([("s09", 1, -3.3, Rule.R_1_3S)], []))
    cases.append(("synthetic-no-history", first_run))
    return cases


def build_cases() -> list[dict[str, Any]]:
    reference = load_batch(REFERENCE_BATCH)
    limits = reference_limits(reference)
    history: list = []
    cases = []
    for batch in range(REFERENCE_BATCH + 1, N_BATCHES + 1):
        current = load_batch(batch)
        result = evaluate_batch(limits, history, current, reference_batch=REFERENCE_BATCH)
        history = [*history, current]
        cases.append({"id": f"batch{batch:02d}", "input": to_report_input(result)})
    for case_id, result in _synthetic_cases():
        cases.append({"id": case_id, "input": to_report_input(result)})
    return cases


def write_cases(out_dir: Path = CASES_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for case in build_cases():
        path = out_dir / f"{case['id']}.json"
        path.write_text(json.dumps(case, indent=2) + "\n")
        paths.append(path)
    return paths


def load_cases(cases_dir: Path = CASES_DIR) -> list[dict[str, Any]]:
    files = sorted(cases_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no eval cases in {cases_dir} — run generate_cases")
    return [json.loads(p.read_text()) for p in files]


if __name__ == "__main__":
    for path in write_cases():
        print(path)

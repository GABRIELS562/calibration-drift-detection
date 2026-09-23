"""Tests for the eval harness.

The important ones are the negative tests: a scorer suite that passes
everything is not a scorer suite. Each deterministic scorer is shown to
fail on output that violates exactly the property it checks.
"""

import json
from pathlib import Path

import pytest
from conftest import requires_dataset

from drift.eval.generate_cases import build_cases, load_cases
from drift.eval.run_eval import JUDGE_FLOOR, compare, generate, run, summarise_scores
from drift.eval.scorers import (
    JUDGE_RUNS,
    judge_readability,
    score_deterministic,
)

CASE_REJECT = {
    "id": "t",
    "input": {
        "batch": 7,
        "reference_batch": 1,
        "n_sensors": 16,
        "control_feature": "f1",
        "rejected": [{"sensor": "s01", "analyte": "toluene", "z": -3.1, "rules": ["1_3s"]}],
        "warned": [{"sensor": "s02", "analyte": "acetaldehyde", "z": -1.6, "rules": ["4_1s"]}],
    },
}
CASE_CLEAN = {
    "id": "c",
    "input": {
        "batch": 3,
        "reference_batch": 1,
        "n_sensors": 16,
        "control_feature": "f1",
        "rejected": [],
        "warned": [],
    },
}
GOOD = (
    "In batch 7, sensor s01 moved beyond three standard deviations on toluene. "
    "Sensor s02 carried a warning on acetaldehyde, an early signal rather than a failure."
)


def _by_name(text: str, case: dict) -> dict[str, bool]:
    return {s.name: s.passed for s in score_deterministic(text, case)}


def test_good_output_passes_every_scorer() -> None:
    assert all(_by_name(GOOD, CASE_REJECT).values())


def test_scorer_catches_a_missing_sensor_id() -> None:
    text = "A sensor drifted on toluene beyond three standard deviations. One carried a warning."

    assert _by_name(text, CASE_REJECT)["names_every_rejected_sensor"] is False


def test_scorer_catches_a_missing_analyte() -> None:
    text = "Sensor s01 moved beyond three standard deviations. Sensor s02 carried a warning."

    assert _by_name(text, CASE_REJECT)["names_every_analyte"] is False


def test_scorer_catches_an_overlong_summary() -> None:
    text = GOOD + " padding" * 200

    assert _by_name(text, CASE_REJECT)["within_word_limit"] is False


@pytest.mark.parametrize(
    "phrase",
    [
        "The model should be retrained.",
        "We recommend replacing sensor s01.",
        "You must approve the candidate.",
        "Sensor s01 needs to be replaced.",
        "I suggest promoting the new version.",
    ],
)
def test_scorer_catches_recommendation_language(phrase: str) -> None:
    assert _by_name(GOOD + " " + phrase, CASE_REJECT)["no_recommendation_language"] is False


def test_scorer_catches_silence_about_an_in_control_run() -> None:
    text = "Batch 3 was evaluated against the reference distribution."

    assert _by_name(text, CASE_CLEAN)["states_in_control_when_clean"] is False


def test_scorer_catches_an_unmentioned_warning() -> None:
    text = "In batch 7, sensor s01 moved beyond three standard deviations on toluene."

    assert _by_name(text, CASE_REJECT)["distinguishes_warnings"] is False


def test_scorer_catches_empty_output() -> None:
    assert _by_name("   ", CASE_REJECT)["is_not_empty"] is False


# --- judge ---


def test_judge_returns_none_without_a_client() -> None:
    assert judge_readability(GOOD, client=None) is None


def test_judge_takes_the_median_of_three_runs(fake_client_factory) -> None:
    from types import SimpleNamespace

    scores = iter(["2", "4", "5"])

    class Messages:
        calls = 0

        def create(self, **_kwargs):
            Messages.calls += 1
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=next(scores))],
                stop_reason="end_turn",
                model="claude-opus-5",
                usage=SimpleNamespace(input_tokens=10, output_tokens=1),
            )

    client = SimpleNamespace(messages=Messages())

    assert judge_readability(GOOD, client=client) == 4.0
    assert Messages.calls == JUDGE_RUNS


def test_judge_survives_a_failing_run(fake_client_factory) -> None:
    from types import SimpleNamespace

    outcomes = iter([RuntimeError("boom"), "4", "4"])

    class Messages:
        def create(self, **_kwargs):
            nxt = next(outcomes)
            if isinstance(nxt, Exception):
                raise nxt
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=nxt)],
                stop_reason="end_turn",
                model="claude-opus-5",
                usage=SimpleNamespace(input_tokens=10, output_tokens=1),
            )

    assert judge_readability(GOOD, client=SimpleNamespace(messages=Messages())) == 4.0


# --- cases and baseline ---


def test_golden_cases_are_committed_and_cover_the_real_batches() -> None:
    cases = load_cases()
    ids = {c["id"] for c in cases}

    assert len(cases) >= 30
    assert {f"batch{b:02d}" for b in range(2, 11)} <= ids
    assert any(c["input"]["rejected"] == [] for c in cases)
    assert any(len(c["input"]["rejected"]) >= 8 for c in cases)


def test_cases_store_properties_not_expected_text() -> None:
    for case in load_cases():
        assert set(case) == {"id", "input"}
        assert "expected_text" not in case


def test_fallback_generator_passes_every_case() -> None:
    summary = summarise_scores(run(client=None, judge_client=None))

    assert summary["failing_cases"] == []
    assert all(s["rate"] == 1.0 for s in summary["scorers"].values())


def test_compare_flags_a_regression_but_not_an_improvement() -> None:
    baseline = {"scorers": {"a": {"rate": 1.0}}, "judge_median": 4.0}

    worse = compare({"scorers": {"a": {"rate": 0.9}}, "judge_median": 4.0}, baseline)
    better = compare({"scorers": {"a": {"rate": 1.0}}, "judge_median": 5.0}, baseline)

    assert worse and "a" in worse[0]
    assert better == []


def test_compare_flags_a_deleted_scorer() -> None:
    problems = compare({"scorers": {}, "judge_median": None}, {"scorers": {"a": {"rate": 1.0}}})

    assert any("disappeared" in p for p in problems)


def test_compare_enforces_a_judge_floor() -> None:
    problems = compare(
        {"scorers": {}, "judge_median": JUDGE_FLOOR - 1}, {"scorers": {}, "judge_median": None}
    )

    assert any("below floor" in p for p in problems)


def test_committed_baseline_matches_the_current_fallback() -> None:
    from drift.eval.run_eval import BASELINE_PATH

    baseline = json.loads(Path(BASELINE_PATH).read_text())
    current = summarise_scores(run(client=None, judge_client=None))

    assert compare(current, baseline) == []


def test_generate_uses_the_model_when_a_client_is_given(fake_client) -> None:
    text = generate(CASE_REJECT, client=fake_client)

    assert text.startswith("Sensor s01")


@requires_dataset
def test_build_cases_is_deterministic() -> None:
    assert [c["id"] for c in build_cases()] == [c["id"] for c in build_cases()]

"""Tests for the advisory drift summariser and its deterministic fallback."""

import json
from pathlib import Path

import pytest

from drift.metrics import COUNTERS, SUMMARISER_CALLS, SUMMARISER_FALLBACKS
from drift.summarise import (
    MAX_WORDS,
    PROMPT_PATH,
    PROMPT_VERSION,
    Summary,
    render_fallback,
    summarise,
    to_report_input,
)
from drift.westgard import ChartEvaluation, Rule, SensorVerdict, Verdict, WestgardResult


def _result(
    batch: int, rejected: list[tuple[str, int, float, Rule]], warned: list[str]
) -> WestgardResult:
    sensors = []
    for name, gas, z, rule in rejected:
        chart = ChartEvaluation(gas=gas, column=f"{name}_f1", z=z, rules=frozenset({rule}))
        sensors.append(SensorVerdict(name, Verdict.REJECT, (chart,)))
    for name in warned:
        chart = ChartEvaluation(gas=4, column=f"{name}_f1", z=-1.6, rules=frozenset({Rule.R_4_1S}))
        sensors.append(SensorVerdict(name, Verdict.WARN, (chart,)))
    sensors.append(SensorVerdict("s16", Verdict.IN_CONTROL, ()))
    return WestgardResult(1, batch, tuple(range(2, batch)), tuple(sensors))


@pytest.fixture(autouse=True)
def _clean_counters():
    COUNTERS.reset()
    yield
    COUNTERS.reset()


def test_prompt_is_version_controlled_and_versioned() -> None:
    assert PROMPT_PATH.is_file()
    assert PROMPT_VERSION == 1
    assert "advisory" in PROMPT_PATH.read_text().lower()


def test_report_input_is_json_serialisable_and_minimal() -> None:
    result = _result(7, [("s01", 6, -3.1, Rule.R_1_3S)], ["s02"])

    payload = to_report_input(result)
    json.dumps(payload)

    assert payload["batch"] == 7
    assert payload["rejected"][0]["sensor"] == "s01"
    assert payload["rejected"][0]["analyte"] == "toluene"
    assert payload["rejected"][0]["rules"] == ["1_3s"]
    assert payload["rejected"][0]["z"] == -3.1
    assert payload["warned"][0]["sensor"] == "s02"
    assert payload["n_sensors"] == 3


def test_fallback_names_every_rejected_sensor_and_analyte() -> None:
    result = _result(7, [("s01", 6, -3.1, Rule.R_1_3S), ("s09", 6, -2.6, Rule.R_2_2S)], ["s02"])

    text = render_fallback(to_report_input(result))

    assert "s01" in text and "s09" in text
    assert "toluene" in text
    assert "three standard deviations" in text
    assert len(text.split()) <= MAX_WORDS


def test_fallback_states_in_control_plainly() -> None:
    text = render_fallback(to_report_input(_result(3, [], [])))

    assert "no sensor" in text.lower()
    assert "batch 3" in text


def test_fallback_distinguishes_warnings_from_rejections() -> None:
    text = render_fallback(to_report_input(_result(5, [], ["s01", "s02"])))

    assert "warning" in text.lower()
    assert "rejected" not in text.lower() or "no sensor" in text.lower()


def test_fallback_uses_no_recommendation_language() -> None:
    text = render_fallback(to_report_input(_result(7, [("s01", 6, -3.4, Rule.R_1_3S)], [])))

    for word in ("should", "recommend", "must", "retrain", "advise", "suggest"):
        assert word not in text.lower()


def test_summarise_falls_back_when_no_client_available() -> None:
    result = _result(7, [("s01", 6, -3.1, Rule.R_1_3S)], [])

    summary = summarise(result, client=None)

    assert isinstance(summary, Summary)
    assert summary.source == "fallback"
    assert summary.prompt_version == PROMPT_VERSION
    assert "s01" in summary.text
    assert COUNTERS.get(SUMMARISER_FALLBACKS) == 1
    assert COUNTERS.get(SUMMARISER_CALLS) == 0


def test_summarise_falls_back_when_the_api_raises() -> None:
    class Failing:
        class messages:  # noqa: N801
            @staticmethod
            def create(**_kwargs):
                raise RuntimeError("service unavailable")

    summary = summarise(_result(7, [("s01", 6, -3.1, Rule.R_1_3S)], []), client=Failing())

    assert summary.source == "fallback"
    assert "s01" in summary.text
    assert COUNTERS.get(SUMMARISER_FALLBACKS) == 1


def test_summarise_records_tokens_and_cost_on_success(fake_client) -> None:
    summary = summarise(_result(7, [("s01", 6, -3.1, Rule.R_1_3S)], []), client=fake_client)

    assert summary.source == "model"
    assert summary.text.startswith("Sensor s01")
    assert summary.input_tokens == 1200 and summary.output_tokens == 90
    assert COUNTERS.get(SUMMARISER_CALLS) == 1
    assert COUNTERS.get(SUMMARISER_FALLBACKS) == 0
    assert COUNTERS.get("drift_summariser_cost_usd_total") == pytest.approx(
        1200 / 1e6 * 5.0 + 90 / 1e6 * 25.0
    )


def test_summarise_falls_back_when_the_model_refuses(fake_client_factory) -> None:
    client = fake_client_factory(stop_reason="refusal")

    summary = summarise(_result(7, [("s01", 6, -3.1, Rule.R_1_3S)], []), client=client)

    assert summary.source == "fallback"


def test_summarise_never_returns_empty_text(fake_client_factory) -> None:
    client = fake_client_factory(text="   ")

    summary = summarise(_result(7, [("s01", 6, -3.1, Rule.R_1_3S)], []), client=client)

    assert summary.source == "fallback"
    assert summary.text.strip()


def test_summary_to_dict_round_trips(tmp_path: Path, fake_client) -> None:
    summary = summarise(_result(7, [("s01", 6, -3.1, Rule.R_1_3S)], []), client=fake_client)

    d = summary.to_dict()
    (tmp_path / "s.json").write_text(json.dumps(d))

    assert d["prompt_version"] == PROMPT_VERSION
    assert d["source"] == "model"
    assert d["model"]

"""Tests for Westgard multirule control charts on the steady-state feature."""

import numpy as np
import pandas as pd
import pytest

from drift.westgard import (
    ChartEvaluation,
    Rule,
    Verdict,
    control_columns,
    evaluate_batch,
    evaluate_rules,
    reference_limits,
    sensor_verdict,
    z_table,
)

# --- rules on a z-score sequence; the LAST point is the run under evaluation ---


def test_in_control_sequence_fires_nothing() -> None:
    assert evaluate_rules([0.5, -0.8, 1.2, -0.3]) == frozenset()


def test_1_3s_fires_on_current_point_beyond_3_sigma() -> None:
    assert evaluate_rules([0.1, 3.2]) == {Rule.R_1_3S}
    assert evaluate_rules([0.1, -3.01]) == {Rule.R_1_3S}


def test_1_3s_does_not_fire_on_historical_excursion() -> None:
    assert Rule.R_1_3S not in evaluate_rules([3.5, 0.2])


def test_2_2s_needs_two_consecutive_same_side_beyond_2_sigma() -> None:
    assert evaluate_rules([0.0, 2.1, 2.4]) == {Rule.R_2_2S}
    assert evaluate_rules([0.0, -2.1, -2.4]) == {Rule.R_2_2S}
    assert Rule.R_2_2S not in evaluate_rules([0.0, 2.1, -2.4])  # opposite sides
    assert Rule.R_2_2S not in evaluate_rules([0.0, 2.1, 1.9])  # second point inside


def test_4_1s_needs_four_consecutive_same_side_beyond_1_sigma() -> None:
    assert evaluate_rules([0.0, -1.4, -1.6, -1.8, -1.5]) == {Rule.R_4_1S}
    assert Rule.R_4_1S not in evaluate_rules([-1.4, -1.6, -1.8])  # only three
    assert Rule.R_4_1S not in evaluate_rules([-1.4, -1.6, 0.9, -1.5])  # broken run


def test_10x_needs_ten_consecutive_on_one_side_of_mean() -> None:
    assert evaluate_rules([0.2] * 10) == {Rule.R_10X}
    assert Rule.R_10X not in evaluate_rules([0.2] * 9)
    assert Rule.R_10X not in evaluate_rules([0.2] * 5 + [-0.1] + [0.2] * 4)


def test_missing_point_breaks_consecutive_runs_but_not_1_3s() -> None:
    assert Rule.R_2_2S not in evaluate_rules([2.5, None, 2.5])
    assert Rule.R_4_1S not in evaluate_rules([-1.5, -1.5, None, -1.5, -1.5])
    assert evaluate_rules([None, 3.5]) == {Rule.R_1_3S}
    assert evaluate_rules([2.0, None]) == frozenset()  # gas absent this run: nothing to judge


def test_rules_can_fire_together() -> None:
    fired = evaluate_rules([-1.2, -1.3, -2.5, -3.4])
    assert fired == {Rule.R_1_3S, Rule.R_2_2S, Rule.R_4_1S}


# --- verdicts ---


def _chart(gas: int, rules: set[Rule]) -> ChartEvaluation:
    return ChartEvaluation(gas=gas, column="s01_f1", z=0.0, rules=frozenset(rules))


def test_sensor_verdict_reject_beats_warn_beats_in_control() -> None:
    assert sensor_verdict([_chart(1, set()), _chart(2, set())]).status == Verdict.IN_CONTROL
    assert sensor_verdict([_chart(1, {Rule.R_4_1S})]).status == Verdict.WARN
    assert sensor_verdict([_chart(1, {Rule.R_10X})]).status == Verdict.WARN
    assert (
        sensor_verdict([_chart(1, {Rule.R_4_1S}), _chart(2, {Rule.R_2_2S})]).status
        == Verdict.REJECT
    )
    assert sensor_verdict([_chart(1, {Rule.R_1_3S})]).status == Verdict.REJECT


def test_sensor_verdict_lists_only_triggering_charts() -> None:
    v = sensor_verdict([_chart(1, set()), _chart(3, {Rule.R_1_3S}), _chart(5, {Rule.R_4_1S})])

    assert [c.gas for c in v.triggers] == [3, 5]


# --- limits and z-scores from data ---


def test_control_columns_are_steady_state_only() -> None:
    cols = control_columns()

    assert len(cols) == 16
    assert cols[0] == "s01_f1" and cols[-1] == "s16_f1"
    assert all(c.endswith("_f1") for c in cols)


def test_reference_limits_per_gas_and_sensor(synthetic_batch: pd.DataFrame) -> None:
    limits = reference_limits(synthetic_batch)

    assert limits.shape == (6, 16 * 3)  # gas x (control column, statistic)
    assert list(limits.columns.levels[0]) == control_columns()
    assert limits.loc[3, ("s01_f1", "n")] == 20
    assert limits.loc[3, ("s01_f1", "mean")] == pytest.approx(30.0, abs=2.0)


def test_reference_limits_rejects_gas_with_too_few_samples(synthetic_batch: pd.DataFrame) -> None:
    thin = synthetic_batch[~((synthetic_batch["label"] == 6) & (synthetic_batch.index % 20 != 0))]

    with pytest.raises(ValueError, match="gas 6"):
        reference_limits(thin)


def test_z_table_is_nan_for_absent_gas(synthetic_batch: pd.DataFrame) -> None:
    limits = reference_limits(synthetic_batch)
    no_toluene = synthetic_batch[synthetic_batch["label"] != 6].assign(batch=3)

    z = z_table(limits, no_toluene)

    assert z.shape == (6, 16)
    assert np.isnan(z.loc[6, "s01_f1"])
    assert abs(z.loc[1, "s01_f1"]) < 1.0


def test_evaluate_batch_flags_shifted_sensor_only(synthetic_batch: pd.DataFrame) -> None:
    limits = reference_limits(synthetic_batch)
    history = [synthetic_batch.assign(batch=b) for b in (2, 3)]
    current = synthetic_batch.assign(batch=4)
    current["s07_f1"] = current["s07_f1"] + 4 * limits[("s07_f1", "std")].mean()

    result = evaluate_batch(limits, history, current, reference_batch=1)

    assert result.current_batch == 4 and result.history_batches == (2, 3)
    by_sensor = {s.sensor: s for s in result.sensors}
    assert by_sensor["s07"].status == Verdict.REJECT
    assert Rule.R_1_3S in by_sensor["s07"].triggers[0].rules
    assert all(by_sensor[s].status == Verdict.IN_CONTROL for s in by_sensor if s != "s07")
    assert result.rejected_sensors == ("s07",)


def test_evaluate_batch_trend_rule_needs_history(synthetic_batch: pd.DataFrame) -> None:
    limits = reference_limits(synthetic_batch)
    std = limits[("s02_f1", "std")].mean()
    drifted = [
        synthetic_batch.assign(batch=b, s02_f1=synthetic_batch["s02_f1"] + 1.5 * std)
        for b in (2, 3, 4, 5)
    ]

    short = evaluate_batch(limits, drifted[:2], drifted[2], reference_batch=1)
    long = evaluate_batch(limits, drifted[:3], drifted[3], reference_batch=1)

    assert {s.sensor: s.status for s in short.sensors}["s02"] == Verdict.IN_CONTROL
    assert {s.sensor: s.status for s in long.sensors}["s02"] == Verdict.WARN


def test_evaluate_batch_requires_history_in_order(synthetic_batch: pd.DataFrame) -> None:
    limits = reference_limits(synthetic_batch)
    with pytest.raises(ValueError, match="chronological"):
        evaluate_batch(
            limits,
            [synthetic_batch.assign(batch=5)],
            synthetic_batch.assign(batch=4),
            reference_batch=1,
        )


def test_result_to_dict_is_serialisable(synthetic_batch: pd.DataFrame) -> None:
    import json

    limits = reference_limits(synthetic_batch)
    result = evaluate_batch(limits, [], synthetic_batch.assign(batch=2), reference_batch=1)

    d = result.to_dict()
    json.dumps(d)
    assert d["sensors"][0]["status"] == "in_control"
    assert d["control_feature"] == "f1"


# --- runner summary ---


def test_summary_table_names_worst_chart_per_sensor(synthetic_batch: pd.DataFrame) -> None:
    from drift.run_westgard import summary_table

    limits = reference_limits(synthetic_batch)
    current = synthetic_batch.assign(batch=2)
    current["s03_f1"] = current["s03_f1"] + 5 * limits[("s03_f1", "std")].mean()
    result = evaluate_batch(limits, [], current, reference_batch=1)

    table = summary_table([result])

    row = next(line for line in table.splitlines() if line.startswith("| 2 "))
    assert "1/16" in row and "s03" in row and "1_3s" in row

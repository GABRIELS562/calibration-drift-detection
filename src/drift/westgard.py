"""Westgard multirule control charts on each sensor's steady-state response.

The analyte is the gas class; the run is a production batch; the control
statistic is the batch mean of a sensor's ``f1`` feature for that gas, in
units of the reference within-gas standard deviation. Rules are evaluated
for the *current* run using the preceding batches as history — a violation
in the past does not condemn today's run, and a gas absent from a batch
breaks a consecutive sequence rather than counting as in control.

Rules (Westgard, 1981):
    1_3s  one point beyond 3 SD                        -> reject
    2_2s  two consecutive beyond 2 SD, same side       -> reject
    4_1s  four consecutive beyond 1 SD, same side      -> investigate
    10x   ten consecutive on one side of the mean      -> investigate
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import numpy as np
import pandas as pd

from drift.data import GAS_CLASSES, N_SENSORS

CONTROL_FEATURE: Final = "f1"
MIN_REFERENCE_SAMPLES: Final = 5
SIGMA_REJECT: Final = 3.0
SIGMA_WARN: Final = 2.0
SIGMA_TREND: Final = 1.0
RUN_2_2S: Final = 2
RUN_4_1S: Final = 4
RUN_10X: Final = 10


class Rule(StrEnum):
    R_1_3S = "1_3s"
    R_2_2S = "2_2s"
    R_4_1S = "4_1s"
    R_10X = "10x"


class Verdict(StrEnum):
    IN_CONTROL = "in_control"
    WARN = "warn"
    REJECT = "reject"


REJECT_RULES: Final = frozenset({Rule.R_1_3S, Rule.R_2_2S})


@dataclass(frozen=True)
class ChartEvaluation:
    gas: int
    column: str
    z: float | None
    rules: frozenset[Rule]


@dataclass(frozen=True)
class SensorVerdict:
    sensor: str
    status: Verdict
    triggers: tuple[ChartEvaluation, ...]


@dataclass(frozen=True)
class WestgardResult:
    reference_batch: int
    current_batch: int
    history_batches: tuple[int, ...]
    sensors: tuple[SensorVerdict, ...]
    control_feature: str = CONTROL_FEATURE
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    @property
    def rejected_sensors(self) -> tuple[str, ...]:
        return tuple(s.sensor for s in self.sensors if s.status is Verdict.REJECT)

    @property
    def warned_sensors(self) -> tuple[str, ...]:
        return tuple(s.sensor for s in self.sensors if s.status is Verdict.WARN)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for s in d["sensors"]:
            s["status"] = s["status"].value
            for t in s["triggers"]:
                t["rules"] = sorted(r.value for r in t["rules"])
        return {
            **d,
            "rejected_sensors": list(self.rejected_sensors),
            "warned": list(self.warned_sensors),
        }


def control_columns() -> list[str]:
    return [f"s{i:02d}_{CONTROL_FEATURE}" for i in range(1, N_SENSORS + 1)]


# --- rules -------------------------------------------------------------------


def _trailing_run(seq: Sequence[float | None], sigma: float, length: int) -> bool:
    """True when the last ``length`` points are all beyond ``sigma`` on the same side."""
    if len(seq) < length:
        return False
    tail = seq[-length:]
    if any(v is None for v in tail):
        return False
    signs = {np.sign(v) for v in tail}
    return len(signs) == 1 and all(abs(v) > sigma for v in tail)


def evaluate_rules(seq: Sequence[float | None]) -> frozenset[Rule]:
    """Rules violated by the last point of ``seq``. ``None`` = gas absent from that run."""
    if not seq or seq[-1] is None:
        return frozenset()
    fired = set()
    if abs(seq[-1]) > SIGMA_REJECT:
        fired.add(Rule.R_1_3S)
    if _trailing_run(seq, SIGMA_WARN, RUN_2_2S):
        fired.add(Rule.R_2_2S)
    if _trailing_run(seq, SIGMA_TREND, RUN_4_1S):
        fired.add(Rule.R_4_1S)
    if _trailing_run(seq, 0.0, RUN_10X):
        fired.add(Rule.R_10X)
    return frozenset(fired)


def sensor_verdict(charts: Sequence[ChartEvaluation]) -> SensorVerdict:
    triggers = tuple(c for c in charts if c.rules)
    if any(c.rules & REJECT_RULES for c in triggers):
        status = Verdict.REJECT
    elif triggers:
        status = Verdict.WARN
    else:
        status = Verdict.IN_CONTROL
    sensor = charts[0].column.split("_")[0]
    return SensorVerdict(sensor=sensor, status=status, triggers=triggers)


# --- limits and z-scores -----------------------------------------------------


def reference_limits(reference: pd.DataFrame) -> pd.DataFrame:
    """Per (gas, control column): ``mean``, ``std``, ``n`` from the reference batch.

    Returned frame is indexed by gas with a two-level column index
    ``(column, statistic)``.
    """
    grouped = reference.groupby("label")[control_columns()]
    stats = pd.concat({"mean": grouped.mean(), "std": grouped.std(), "n": grouped.count()}, axis=1)
    stats = stats.swaplevel(axis=1).sort_index(axis=1).reindex(sorted(GAS_CLASSES))
    for gas in GAS_CLASSES:
        n = stats.loc[gas].xs("n", level=1).min() if gas in stats.index else 0
        if pd.isna(n) or n < MIN_REFERENCE_SAMPLES:
            raise ValueError(f"reference has too few samples for gas {gas}: {int(n or 0)}")
    return stats


def z_table(limits: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Batch-mean z-score per (gas, control column); NaN where the gas is absent."""
    cols = control_columns()
    batch_mean = current.groupby("label")[cols].mean().reindex(sorted(GAS_CLASSES))
    mean = limits.xs("mean", axis=1, level=1)[cols]
    std = limits.xs("std", axis=1, level=1)[cols]
    return (batch_mean - mean) / std


def _chronological(history: Sequence[pd.DataFrame], current: pd.DataFrame) -> tuple[int, ...]:
    batches = [int(df["batch"].iloc[0]) for df in history] + [int(current["batch"].iloc[0])]
    if batches != sorted(set(batches)):
        raise ValueError(f"history and current must be chronological and distinct, got {batches}")
    return tuple(batches[:-1])


def _sequence(tables: Sequence[pd.DataFrame], gas: int, column: str) -> list[float | None]:
    return [None if np.isnan(t.loc[gas, column]) else float(t.loc[gas, column]) for t in tables]


def evaluate_batch(
    limits: pd.DataFrame,
    history: Sequence[pd.DataFrame],
    current: pd.DataFrame,
    *,
    reference_batch: int,
) -> WestgardResult:
    """Evaluate every sensor's control charts for ``current``, given the preceding batches."""
    history_batches = _chronological(history, current)
    tables = [z_table(limits, df) for df in (*history, current)]
    sensors = []
    for column in control_columns():
        charts = []
        for gas in sorted(GAS_CLASSES):
            seq = _sequence(tables, gas, column)
            charts.append(
                ChartEvaluation(gas=gas, column=column, z=seq[-1], rules=evaluate_rules(seq))
            )
        sensors.append(sensor_verdict(charts))
    return WestgardResult(
        reference_batch=reference_batch,
        current_batch=int(current["batch"].iloc[0]),
        history_batches=history_batches,
        sensors=tuple(sensors),
    )

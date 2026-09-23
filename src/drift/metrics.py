"""Counters exposed on ``/metrics`` in Phase 5.

Deliberately dependency-free: a process-local registry that the FastAPI app
renders in Prometheus text format. Token spend is tracked here because an
LLM call that nobody is counting is an LLM call nobody can budget for.
"""

from dataclasses import dataclass, field
from threading import Lock
from typing import Final

SUMMARISER_INPUT_TOKENS: Final = "drift_summariser_input_tokens_total"
SUMMARISER_OUTPUT_TOKENS: Final = "drift_summariser_output_tokens_total"
SUMMARISER_CALLS: Final = "drift_summariser_calls_total"
SUMMARISER_FALLBACKS: Final = "drift_summariser_fallbacks_total"
SUMMARISER_COST_USD: Final = "drift_summariser_cost_usd_total"


@dataclass
class Counters:
    """Monotonic counters. Reset only in tests."""

    values: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def increment(self, name: str, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError(f"counters only increase, got {amount} for {name!r}")
        with self._lock:
            self.values[name] = self.values.get(name, 0.0) + amount

    def get(self, name: str) -> float:
        return self.values.get(name, 0.0)

    def reset(self) -> None:
        with self._lock:
            self.values.clear()

    def render_prometheus(self) -> str:
        lines = []
        for name in sorted(self.values):
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {self.values[name]}")
        return "\n".join(lines) + ("\n" if lines else "")


COUNTERS: Final = Counters()

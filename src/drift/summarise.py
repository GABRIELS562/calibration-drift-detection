"""Advisory plain-language summary of a control-chart evaluation.

**The summariser is advisory. It does not approve, reject, or trigger
anything.** It turns the structured verdict into a short written finding for
a laboratory manager. Nothing downstream reads its output; the gate
(ADR-0004) acts on the Westgard verdict, never on this text.

The prompt lives in ``prompts/drift_summary.v1.md`` under version control and
changes only through a pull request with a passing eval run: it is part of
the validated system, and changing it changes the output.

If the API is unavailable, or refuses, or returns nothing usable, a
deterministic template renders the same facts. The record cannot depend on
a third party's uptime.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from drift.data import GAS_CLASSES
from drift.metrics import (
    COUNTERS,
    SUMMARISER_CALLS,
    SUMMARISER_COST_USD,
    SUMMARISER_FALLBACKS,
    SUMMARISER_INPUT_TOKENS,
    SUMMARISER_OUTPUT_TOKENS,
)
from drift.westgard import Verdict, WestgardResult

PROMPT_PATH: Final = Path(__file__).parent / "prompts" / "drift_summary.v1.md"
PROMPT_VERSION: Final = 1
MODEL: Final = "claude-opus-5"
MAX_WORDS: Final = 120
# Short, constrained transformation of structured input: low effort is
# sufficient and keeps the per-summary cost predictable.
EFFORT: Final = "low"
MAX_TOKENS: Final = 4000
# claude-opus-5 list price, USD per million tokens.
INPUT_USD_PER_MTOK: Final = 5.0
OUTPUT_USD_PER_MTOK: Final = 25.0

RULE_PHRASES: Final[dict[str, str]] = {
    "1_3s": "beyond three standard deviations",
    "2_2s": "two consecutive runs beyond two standard deviations",
    "4_1s": "four consecutive runs beyond one standard deviation",
    "10x": "ten consecutive runs on one side of the mean",
}


@dataclass(frozen=True)
class Summary:
    text: str
    source: str  # "model" | "fallback"
    prompt_version: int
    model: str
    input_tokens: int
    output_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _charts(sensor: Any) -> list[dict[str, Any]]:
    worst = max(sensor.triggers, key=lambda c: abs(c.z or 0.0))
    return {
        "sensor": sensor.sensor,
        "analyte": GAS_CLASSES[worst.gas],
        "z": round(worst.z, 2) if worst.z is not None else None,
        "rules": sorted(str(r) for r in worst.rules),
    }


def to_report_input(result: WestgardResult) -> dict[str, Any]:
    """The JSON the summariser is given. Facts only — no prose, no verdict."""
    return {
        "batch": result.current_batch,
        "reference_batch": result.reference_batch,
        "n_sensors": len(result.sensors),
        "control_feature": result.control_feature,
        "rejected": [_charts(s) for s in result.sensors if s.status is Verdict.REJECT],
        "warned": [_charts(s) for s in result.sensors if s.status is Verdict.WARN],
    }


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def render_fallback(payload: dict[str, Any]) -> str:
    """Deterministic rendering of the same facts. Always available."""
    batch, rejected, warned = payload["batch"], payload["rejected"], payload["warned"]
    if not rejected and not warned:
        return (
            f"In batch {batch}, no sensor was rejected and none is under warning. "
            f"All {payload['n_sensors']} channels remained within control limits "
            f"against the batch {payload['reference_batch']} reference."
        )

    parts = []
    if rejected:
        by_rule: dict[str, list[str]] = {}
        for entry in rejected:
            phrase = RULE_PHRASES.get(entry["rules"][0], entry["rules"][0])
            by_rule.setdefault(f"{entry['analyte']}, {phrase}", []).append(entry["sensor"])
        clauses = [f"{_join(sensors)} on {desc}" for desc, sensors in by_rule.items()]
        detail = "; ".join(clauses)
        parts.append(f"In batch {batch}, {len(rejected)} sensor(s) were rejected: {detail}.")
    else:
        parts.append(f"In batch {batch}, no sensor was rejected.")
    if warned:
        names = _join([e["sensor"] for e in warned])
        analytes = sorted({e["analyte"] for e in warned})
        parts.append(
            f"{names} carried a warning on {_join(analytes)}, "
            "an early signal rather than a failure."
        )
    return " ".join(parts)


def _extract_text(response: Any) -> str:
    blocks = getattr(response, "content", [])
    return "".join(b.text for b in blocks if getattr(b, "type", "") == "text").strip()


def _record_cost(input_tokens: int, output_tokens: int) -> None:
    COUNTERS.increment(SUMMARISER_INPUT_TOKENS, input_tokens)
    COUNTERS.increment(SUMMARISER_OUTPUT_TOKENS, output_tokens)
    COUNTERS.increment(
        SUMMARISER_COST_USD,
        input_tokens / 1e6 * INPUT_USD_PER_MTOK + output_tokens / 1e6 * OUTPUT_USD_PER_MTOK,
    )


def default_client() -> Any | None:
    """An Anthropic client, or None when no credentials are configured."""
    try:
        import anthropic

        return anthropic.Anthropic()
    except Exception:
        return None


def summarise(result: WestgardResult, *, client: Any | None) -> Summary:
    """Summarise one evaluation. Falls back to the template on any failure."""
    payload = to_report_input(result)
    fallback = Summary(
        text=render_fallback(payload),
        source="fallback",
        prompt_version=PROMPT_VERSION,
        model="none",
        input_tokens=0,
        output_tokens=0,
    )
    if client is None:
        COUNTERS.increment(SUMMARISER_FALLBACKS)
        return fallback

    import json

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": EFFORT},
            system=PROMPT_PATH.read_text(),
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
    except Exception:
        COUNTERS.increment(SUMMARISER_FALLBACKS)
        return fallback

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    _record_cost(input_tokens, output_tokens)

    text = _extract_text(response)
    if getattr(response, "stop_reason", None) == "refusal" or not text:
        COUNTERS.increment(SUMMARISER_FALLBACKS)
        return fallback

    COUNTERS.increment(SUMMARISER_CALLS)
    return Summary(
        text=text,
        source="model",
        prompt_version=PROMPT_VERSION,
        model=getattr(response, "model", MODEL),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))

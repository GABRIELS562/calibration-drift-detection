"""Scorers for the drift summariser.

Deterministic scorers first: they never flake and they carry most of the
value. Exactly one criterion — whether the finding reads to a non-technical
laboratory manager — needs a judge, and a judge is noisy, so it is run
three times and the median is taken.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from statistics import median
from typing import Any, Final

from drift.summarise import MAX_WORDS, word_count

# Words that would turn an advisory note into a recommendation (ADR-0004).
RECOMMENDATION_PATTERN: Final = re.compile(
    r"\b(should|must|need to|needs to|recommend\w*|advise[sd]?|advisable|suggest\w*|"
    r"ought to|require[sd]?\b|retrain\w*|replace the model|approve\w*|"
    r"reject the model|promote\w*)\b",
    re.IGNORECASE,
)
JUDGE_RUNS: Final = 3
JUDGE_MODEL: Final = "claude-opus-5"
JUDGE_PROMPT: Final = """You are grading a written finding prepared for the
manager of a calibration laboratory. The manager is experienced with
instruments and quality control but is not a statistician or a programmer.

Score readability from 1 to 5:
5 - immediately clear; plain language; a manager could act on it unaided
4 - clear, with at most one piece of unexplained jargon
3 - understandable but requires effort or re-reading
2 - heavy jargon, raw identifiers or statistics presented without meaning
1 - incomprehensible to a non-specialist

Reply with the digit only. No explanation."""


@dataclass(frozen=True)
class ScoreResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class CaseScores:
    case_id: str
    deterministic: tuple[ScoreResult, ...]
    judge_score: float | None

    @property
    def all_passed(self) -> bool:
        return all(s.passed for s in self.deterministic)

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.deterministic if not s.passed)


def names_every_rejected_sensor(text: str, case: dict[str, Any]) -> ScoreResult:
    expected = [e["sensor"] for e in case["input"]["rejected"]]
    missing = [s for s in expected if s not in text]
    return ScoreResult(
        "names_every_rejected_sensor",
        not missing,
        f"missing {missing}" if missing else f"all {len(expected)} present",
    )


def names_every_analyte(text: str, case: dict[str, Any]) -> ScoreResult:
    expected = {e["analyte"] for e in case["input"]["rejected"]}
    missing = sorted(a for a in expected if a.lower() not in text.lower())
    return ScoreResult(
        "names_every_analyte", not missing, f"missing {missing}" if missing else "all present"
    )


def within_word_limit(text: str, _case: dict[str, Any]) -> ScoreResult:
    count = word_count(text)
    return ScoreResult("within_word_limit", count <= MAX_WORDS, f"{count} words (max {MAX_WORDS})")


def no_recommendation_language(text: str, _case: dict[str, Any]) -> ScoreResult:
    found = sorted({m.group(0).lower() for m in RECOMMENDATION_PATTERN.finditer(text)})
    return ScoreResult(
        "no_recommendation_language", not found, f"found {found}" if found else "none found"
    )


def states_in_control_when_clean(text: str, case: dict[str, Any]) -> ScoreResult:
    if case["input"]["rejected"]:
        return ScoreResult("states_in_control_when_clean", True, "not applicable")
    clean = re.search(r"\bno sensor\b|\bnone\b|\bin control\b|within control", text, re.IGNORECASE)
    return ScoreResult(
        "states_in_control_when_clean", bool(clean), "says so" if clean else "does not say so"
    )


def distinguishes_warnings(text: str, case: dict[str, Any]) -> ScoreResult:
    if not case["input"]["warned"]:
        return ScoreResult("distinguishes_warnings", True, "not applicable")
    mentioned = re.search(r"warn\w*|early signal", text, re.IGNORECASE)
    return ScoreResult(
        "distinguishes_warnings", bool(mentioned), "mentioned" if mentioned else "not mentioned"
    )


def is_not_empty(text: str, _case: dict[str, Any]) -> ScoreResult:
    return ScoreResult("is_not_empty", bool(text.strip()), f"{len(text)} chars")


SCORERS: Final[tuple[Callable[[str, dict[str, Any]], ScoreResult], ...]] = (
    is_not_empty,
    names_every_rejected_sensor,
    names_every_analyte,
    within_word_limit,
    no_recommendation_language,
    states_in_control_when_clean,
    distinguishes_warnings,
)


def score_deterministic(text: str, case: dict[str, Any]) -> tuple[ScoreResult, ...]:
    return tuple(scorer(text, case) for scorer in SCORERS)


def judge_readability(text: str, *, client: Any | None, runs: int = JUDGE_RUNS) -> float | None:
    """Median of ``runs`` judge scores. ``None`` when no client is available.

    A single judge run is noisy enough to turn a green build red for no
    reason, so the median of three is used.
    """
    if client is None:
        return None
    scores = []
    for _ in range(runs):
        try:
            response = client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=1000,
                output_config={"effort": "low"},
                system=JUDGE_PROMPT,
                messages=[{"role": "user", "content": text}],
            )
        except Exception:
            continue
        blocks = getattr(response, "content", [])
        raw = "".join(b.text for b in blocks if getattr(b, "type", "") == "text")
        match = re.search(r"[1-5]", raw)
        if match:
            scores.append(float(match.group(0)))
    return median(scores) if scores else None

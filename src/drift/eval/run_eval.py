"""Run the eval suite and compare against the committed baseline.

    uv run python -m drift.eval.run_eval              # score the fallback
    uv run python -m drift.eval.run_eval --live       # score the model
    uv run python -m drift.eval.run_eval --update-baseline

The prompt is version-controlled, but version control cannot tell you
whether a change made the output worse. This can. CI fails the merge when
any deterministic check regresses against ``docs/eval-baseline.json``.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

from drift.eval.generate_cases import load_cases
from drift.eval.scorers import CaseScores, judge_readability, score_deterministic
from drift.summarise import PROMPT_VERSION, default_client, render_fallback

BASELINE_PATH: Final = Path(__file__).resolve().parents[3] / "docs" / "eval-baseline.json"
JUDGE_FLOOR: Final = 4.0


def generate(case: dict[str, Any], *, client: Any | None) -> str:
    """The text under test: the model when live, the template otherwise."""
    if client is None:
        return render_fallback(case["input"])
    from drift.summarise import MAX_TOKENS, MODEL, PROMPT_PATH

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        output_config={"effort": "low"},
        system=PROMPT_PATH.read_text(),
        messages=[{"role": "user", "content": json.dumps(case["input"], indent=2)}],
    )
    blocks = getattr(response, "content", [])
    return "".join(b.text for b in blocks if getattr(b, "type", "") == "text").strip()


def run(*, client: Any | None, judge_client: Any | None) -> list[CaseScores]:
    results = []
    for case in load_cases():
        text = generate(case, client=client)
        results.append(
            CaseScores(
                case_id=case["id"],
                deterministic=score_deterministic(text, case),
                judge_score=judge_readability(text, client=judge_client),
            )
        )
    return results


def summarise_scores(results: list[CaseScores]) -> dict[str, Any]:
    per_scorer: dict[str, dict[str, int]] = {}
    for case in results:
        for score in case.deterministic:
            bucket = per_scorer.setdefault(score.name, {"passed": 0, "total": 0})
            bucket["total"] += 1
            bucket["passed"] += int(score.passed)
    judged = [c.judge_score for c in results if c.judge_score is not None]
    return {
        "prompt_version": PROMPT_VERSION,
        "n_cases": len(results),
        "scorers": {
            name: {**counts, "rate": counts["passed"] / counts["total"]}
            for name, counts in sorted(per_scorer.items())
        },
        "judge_median": (sorted(judged)[len(judged) // 2] if judged else None),
        "failing_cases": sorted(c.case_id for c in results if not c.all_passed),
    }


def compare(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Regressions only — an improvement is never a failure."""
    problems = []
    for name, counts in current["scorers"].items():
        before = baseline["scorers"].get(name, {}).get("rate")
        if before is not None and counts["rate"] < before:
            problems.append(f"{name}: {before:.2%} -> {counts['rate']:.2%}")
    for name in baseline["scorers"]:
        if name not in current["scorers"]:
            problems.append(f"{name}: scorer disappeared")
    now, was = current["judge_median"], baseline.get("judge_median")
    if now is not None and was is not None and now < was:
        problems.append(f"judge_median: {was} -> {now}")
    if now is not None and now < JUDGE_FLOOR:
        problems.append(f"judge_median {now} below floor {JUDGE_FLOOR}")
    return problems


def _print(summary: dict[str, Any]) -> None:
    print(f"prompt v{summary['prompt_version']}, {summary['n_cases']} cases")
    for name, counts in summary["scorers"].items():
        mark = "ok  " if counts["rate"] == 1.0 else "FAIL"
        print(f"  {mark} {name}: {counts['passed']}/{counts['total']}")
    print(f"  judge_median: {summary['judge_median']}")
    if summary["failing_cases"]:
        print(f"  failing cases: {', '.join(summary['failing_cases'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--live", action="store_true", help="call the model instead of the template"
    )
    parser.add_argument("--judge", action="store_true", help="also run the readability judge")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    client = default_client() if args.live else None
    if args.live and client is None:
        print("error: --live needs Anthropic credentials, none configured", file=sys.stderr)
        return 1
    judge_client = default_client() if args.judge else None
    if args.judge and judge_client is None:
        print("error: --judge needs Anthropic credentials, none configured", file=sys.stderr)
        return 1

    summary = summarise_scores(run(client=client, judge_client=judge_client))
    summary["generator"] = "model" if args.live else "fallback"
    _print(summary)

    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"baseline written -> {BASELINE_PATH.name}")
        return 0

    if not BASELINE_PATH.is_file():
        print("error: no committed baseline — run with --update-baseline", file=sys.stderr)
        return 1
    problems = compare(summary, json.loads(BASELINE_PATH.read_text()))
    if problems:
        print("\nREGRESSION against committed baseline:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("\nno regression against committed baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())

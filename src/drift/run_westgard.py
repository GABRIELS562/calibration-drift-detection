"""Evaluate Westgard control charts for every production batch in sequence.

    uv run python -m drift.run_westgard

Each batch is judged with all earlier production batches as history, so
the trend rules (4_1s, 10x) see the same sequence a lab would.
"""

import json
import sys
from pathlib import Path
from typing import Final

from drift.data import GAS_CLASSES, N_BATCHES, RAW_DIR, load_batch
from drift.detect import ARTIFACTS_DIR
from drift.reference import sha256_of_file
from drift.train import REFERENCE_BATCH
from drift.westgard import Verdict, WestgardResult, evaluate_batch, reference_limits

SUMMARY_PATH: Final = Path(__file__).resolve().parents[2] / "docs" / "westgard-summary.md"
_HASH_PREFIX: Final = 12


def _triggers(result: WestgardResult, status: Verdict) -> str:
    parts = []
    for s in result.sensors:
        if s.status is not status:
            continue
        worst = max(s.triggers, key=lambda c: abs(c.z or 0.0))
        rules = "+".join(sorted(r.value for r in worst.rules))
        parts.append(f"{s.sensor} ({GAS_CLASSES[worst.gas][:5]} z={worst.z:+.1f} {rules})")
    return ", ".join(parts) if parts else "—"


def summary_table(results: list[WestgardResult]) -> str:
    lines = [
        f"Reference: batch {results[0].reference_batch}. Control statistic: batch mean of each "
        "sensor's steady-state response (`f1`) per gas, in reference within-gas SD. "
        "Reject on 1_3s or 2_2s; warn on 4_1s or 10x. Worst chart shown per sensor.",
        "",
        "| batch | rejected | warned | reject triggers | warn triggers |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.current_batch} | {len(r.rejected_sensors)}/16 | {len(r.warned_sensors)}/16 | "
            f"{_triggers(r, Verdict.REJECT)} | {_triggers(r, Verdict.WARN)} |"
        )
    return "\n".join(lines) + "\n"


def run() -> list[WestgardResult]:
    reference = load_batch(REFERENCE_BATCH)
    limits = reference_limits(reference)
    ref_hash = sha256_of_file(RAW_DIR / f"batch{REFERENCE_BATCH}.dat")[:_HASH_PREFIX]
    out_dir = ARTIFACTS_DIR / ref_hash / "westgard"
    out_dir.mkdir(parents=True, exist_ok=True)

    history: list = []
    results = []
    for batch in range(REFERENCE_BATCH + 1, N_BATCHES + 1):
        current = load_batch(batch)
        result = evaluate_batch(limits, history, current, reference_batch=REFERENCE_BATCH)
        (out_dir / f"batch{batch}.json").write_text(json.dumps(result.to_dict(), indent=2) + "\n")
        results.append(result)
        history = [*history, current]
        print(
            f"batch {batch:2d}: reject {len(result.rejected_sensors):2d}/16  "
            f"warn {len(result.warned_sensors):2d}/16  -> {_triggers(result, Verdict.REJECT)[:80]}"
        )
    SUMMARY_PATH.write_text(f"# Westgard summary\n\n{summary_table(results)}")
    print(f"summary -> {SUMMARY_PATH.relative_to(SUMMARY_PATH.parents[1])}")
    return results


def main() -> int:
    try:
        run()
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

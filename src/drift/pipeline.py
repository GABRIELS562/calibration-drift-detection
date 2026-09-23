"""The drift-to-candidate pipeline for one production batch.

    uv run python -m drift.pipeline --batch 7

Evaluates the Westgard charts for the batch, and if any sensor is rejected,
trains a candidate and registers it as pending-approval. Exit code 0 means
no action needed; 10 means a candidate is waiting for a human.
"""

import argparse
import os
import sys
from typing import Final

import mlflow

from drift.audit import AUDIT_LOG_PATH, append_event
from drift.data import N_BATCHES, RAW_DIR, load_batch
from drift.reference import sha256_of_file
from drift.retrain import should_retrain, train_candidate_for_batch
from drift.train import DEFAULT_TRACKING_URI, REFERENCE_BATCH
from drift.westgard import evaluate_batch, reference_limits

EXIT_CANDIDATE_PENDING: Final = 10


def run(batch: int) -> int:
    reference = load_batch(REFERENCE_BATCH)
    limits = reference_limits(reference)
    history = [load_batch(b) for b in range(REFERENCE_BATCH + 1, batch)]
    current = load_batch(batch)

    result = evaluate_batch(limits, history, current, reference_batch=REFERENCE_BATCH)
    decision = should_retrain(result)
    append_event(
        AUDIT_LOG_PATH,
        action="drift_evaluated",
        actor="pipeline",
        details={
            "batch": batch,
            "rejected_sensors": list(result.rejected_sensors),
            "warned_sensors": list(result.warned_sensors),
            "triggered": decision.triggered,
            "reason": decision.reason,
        },
    )
    print(decision.reason)
    if not decision.triggered:
        return 0

    dataset_sha256 = sha256_of_file(RAW_DIR / f"batch{batch}.dat")
    version = train_candidate_for_batch(
        decision,
        reference=reference,
        history=history,
        current=current,
        dataset_sha256=dataset_sha256,
    )
    print(f"candidate registered: version {version} (pending-approval)")
    print("promotion requires an approval — nothing has been deployed")
    return EXIT_CANDIDATE_PENDING


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--batch", type=int, required=True, help=f"production batch 2-{N_BATCHES}")
    args = parser.parse_args(argv)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    try:
        return run(args.batch)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

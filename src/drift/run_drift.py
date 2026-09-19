"""Run the drift check for one or more production batches against Batch 1.

    uv run python -m drift.run_drift --batches all
    uv run python -m drift.run_drift --batches 2-4 --num-method ks

Reports go to ``artifacts/drift/<reference-hash>/`` so a change to the
reference produces a new directory rather than overwriting the old one.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

from drift.data import N_BATCHES, RAW_DIR, load_batch
from drift.detect import ARTIFACTS_DIR, DriftConfig, DriftResult, run_drift_check, save_reports
from drift.reference import sha256_of_file
from drift.train import REFERENCE_BATCH

SUMMARY_PATH: Final = Path(__file__).resolve().parents[2] / "docs" / "drift-summary.md"
_HASH_PREFIX: Final = 12


def parse_batches(spec: str) -> list[int]:
    """``all`` | ``2-5`` | ``2,7,10`` -> sorted batch numbers, never the reference."""
    production = range(REFERENCE_BATCH + 1, N_BATCHES + 1)
    if spec == "all":
        return list(production)
    try:
        if "-" in spec:
            lo, hi = (int(p) for p in spec.split("-", 1))
            batches = list(range(lo, hi + 1))
        else:
            batches = [int(p) for p in spec.split(",")]
    except ValueError as exc:
        raise ValueError(f"cannot parse batch spec {spec!r}") from exc
    bad = [b for b in batches if b not in production]
    if bad:
        raise ValueError(f"batches must be {production.start}-{production.stop - 1}, got {bad}")
    return sorted(set(batches))


def _top_feature(result: DriftResult) -> str:
    worst = max(result.features, key=lambda c: c.score)
    return f"{worst.column} ({worst.score:.2f})"


def summary_table(results: list[DriftResult]) -> str:
    cfg = results[0].config
    lines = [
        f"Reference: batch {results[0].reference_batch} ({results[0].n_reference} rows). "
        f"Features: {cfg.num_method} > {cfg.num_threshold}. "
        f"Label: {cfg.cat_method} p < {cfg.cat_threshold}. "
        f"Breach when drifted share >= {cfg.drift_share}.",
        "",
        "| batch | rows | drifted features | share | breached | label drifted | worst feature |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.current_batch} | {r.n_current} | {r.n_drifted}/{len(r.features)} | "
            f"{r.share_drifted:.2f} | {'yes' if r.breached else 'no'} | "
            f"{'yes' if r.label.drifted else 'no'} | {_top_feature(r)} |"
        )
    return "\n".join(lines) + "\n"


def run(batches: list[int], config: DriftConfig, *, write_summary: bool) -> list[DriftResult]:
    reference = load_batch(REFERENCE_BATCH)
    ref_hash = sha256_of_file(RAW_DIR / f"batch{REFERENCE_BATCH}.dat")[:_HASH_PREFIX]
    out_dir = ARTIFACTS_DIR / ref_hash / config.num_method
    results = []
    for batch in batches:
        result, snapshot = run_drift_check(reference, load_batch(batch), config=config)
        html, _ = save_reports(result, snapshot, out_dir=out_dir)
        results.append(result)
        print(
            f"batch {batch:2d}: {result.n_drifted:3d}/{len(result.features)} drifted "
            f"(share {result.share_drifted:.2f}, breached={result.breached}, "
            f"label={result.label.drifted}) -> {html.relative_to(ARTIFACTS_DIR.parent)}"
        )
    if write_summary:
        SUMMARY_PATH.write_text(f"# Drift summary\n\n{summary_table(results)}")
        print(f"summary -> {SUMMARY_PATH.relative_to(SUMMARY_PATH.parents[1])}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--batches", default="all", help="all | 2-5 | 2,7,10")
    parser.add_argument("--num-method", default=DriftConfig.num_method)
    parser.add_argument("--num-threshold", type=float, default=DriftConfig.num_threshold)
    parser.add_argument(
        "--no-summary", action="store_true", help="don't rewrite docs/drift-summary.md"
    )
    args = parser.parse_args(argv)
    try:
        batches = parse_batches(args.batches)
        config = DriftConfig(num_method=args.num_method, num_threshold=args.num_threshold)
        run(batches, config, write_summary=not args.no_summary)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

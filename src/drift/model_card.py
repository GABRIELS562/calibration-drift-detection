"""Model cards generated from the registry, not written by hand.

A card restates what the registry already holds — provenance, metrics,
approval state — in the form an assessor or a reviewer reads. Generating
it means it cannot drift away from the model it describes.
"""

from pathlib import Path
from typing import Any, Final

import mlflow

from drift.constants import MODEL_NAME
from drift.data import GAS_CLASSES, N_FEATURES, N_SENSORS

CARDS_DIR: Final = Path(__file__).resolve().parents[2] / "docs" / "model-cards"

_INTENDED_USE: Final = f"""Classify which of {len(GAS_CLASSES)} gases
({", ".join(GAS_CLASSES.values())}) is present from {N_FEATURES} features
produced by a {N_SENSORS}-sensor metal-oxide array.

The model supports an instrument-drift monitoring exercise. It is **not**
a released measurement method and its outputs are not reportable results.
Predictions are valid only for the sensor array and acquisition conditions
represented in the training batches listed below."""

_LIMITATIONS: Final = """- The model is an **untuned** random forest chosen for the clarity of the
  governance story, not for accuracy (ADR-0002). No hyperparameter search
  has been performed.
- Performance is reported on data held out from the training batches. It
  says nothing about batches collected later, which is the whole subject of
  the drift monitoring.
- The reference distribution is a single batch of 445 samples, with as few
  as 30 samples for acetaldehyde. Control limits for the sparser gases are
  the least certain (ADR-0003).
- Gas concentration is not available in the dataset, so a change in
  concentration and a change in sensor response cannot be separated.
- The model has no abstain option: it always returns one of six classes,
  including for a gas it was never trained on."""


def _version_tags(version: str) -> dict[str, Any]:
    client = mlflow.MlflowClient()
    try:
        mv = client.get_model_version(MODEL_NAME, version)
    except Exception as exc:
        raise ValueError(f"no registered version {version!r} of {MODEL_NAME}") from exc
    return {"version": str(mv.version), "created": mv.creation_timestamp, **mv.tags}


def _run_params(tags: dict[str, Any]) -> dict[str, str]:
    """Training parameters live on the run; approval state lives on the version tags."""
    run_id = tags.get("run_id")
    if not run_id:
        return {}
    return dict(mlflow.get_run(run_id).data.params)


def _metrics(tags: dict[str, Any]) -> str:
    run_id = tags.get("run_id")
    if not run_id:
        return "_not recorded_"
    data = mlflow.get_run(run_id).data.metrics
    own = {k: v for k, v in data.items() if not k.startswith("incumbent_")}
    rows = ["| metric | this version | incumbent at registration |", "|---|---|---|"]
    for key in sorted(own):
        incumbent = data.get(f"incumbent_{key}")
        against = f"{incumbent:.4f}" if incumbent is not None else "—"
        rows.append(f"| {key} | {own[key]:.4f} | {against} |")
    return "\n".join(rows)


def _approval_section(tags: dict[str, Any]) -> str:
    status = tags.get("approval_status", "unknown")
    lines = [f"- **Status:** `{status}`"]
    for label, actor_key, reason_key, at_key in (
        ("Approved", "approved_by", "approval_reason", "approved_at"),
        ("Rejected", "rejected_by", "rejection_reason", "rejected_at"),
        ("Rolled back", "rolled_back_by", "rollback_reason", "rolled_back_at"),
    ):
        if tags.get(actor_key):
            lines.append(f"- **{label} by:** {tags[actor_key]} at {tags.get(at_key, '?')}")
            lines.append(f"- **{label} because:** {tags.get(reason_key, '—')}")
    if status == "pending-approval":
        lines.append("- **Not deployed.** Promotion requires a human approval (ADR-0004).")
    return "\n".join(lines)


def render_card(version: str) -> str:
    tags = _version_tags(version)
    params = _run_params(tags)
    batches = params.get("training_batches", "batch 1 (initial baseline)")
    provenance_keys = {"dataset_sha256", "source", "trigger", "training_batches"}
    param_summary = ", ".join(
        f"`{k}={v}`" for k, v in sorted(params.items()) if k not in provenance_keys
    )
    return f"""# Model card — `{MODEL_NAME}` version {version}

_Generated from the model registry. Do not edit by hand._

## Intended use

{_INTENDED_USE}

## Training data

- **Batches:** {batches}
- **Dataset SHA-256:** `{tags.get("dataset_sha256", "—")}`
- **Reference distribution:** batch 1, `data/reference/baseline_stats.json`

## Why this version exists

{tags.get("trigger", "—")}

## Performance

{_metrics(tags)}

Model parameters: {param_summary}

Comparison recorded at registration: {tags.get("comparison", "—")}
Regression against incumbent: `{tags.get("regression", "—")}`

## Validation status

{_approval_section(tags)}

## Known limitations

{_LIMITATIONS}

## Traceability

This version → its MLflow run (`{tags.get("run_id", "—")}`) → the dataset
hash above → `data/reference/baseline_stats.json` carrying the same hash for
the baseline → the approval record in `audit/audit.jsonl`. See
`docs/traceability.md`.
"""


def write_card(version: str, *, out_dir: Path = CARDS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"v{version}.md"
    path.write_text(render_card(version))
    return path

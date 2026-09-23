"""The approval gate: candidates register themselves, humans promote them.

A candidate is registered with ``approval_status=pending-approval`` and no
alias. Nothing in this module promotes a model as a side effect of training
it; ``approve`` is the only function that moves the ``production`` alias,
and it requires a named actor and a reason. Every transition is written to
the model version's tags, which is the audit trail (ADR-0004).
"""

from datetime import UTC, datetime
from typing import Any, Final

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from drift.constants import (
    APPROVED,
    MODEL_NAME,
    PENDING,
    PRODUCTION_ALIAS,
    REJECTED,
    ROLLED_BACK,
)
from drift.train import EXPERIMENT_NAME, SKOPS_TRUSTED_TYPES

CANDIDATE_EXPERIMENT: Final = "candidates"
_COMPARISON_METRIC: Final = "f1_macro"


class ApprovalError(RuntimeError):
    """Raised when a promotion, rejection or rollback is not permitted."""


def _client() -> mlflow.MlflowClient:
    return mlflow.MlflowClient()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


NO_INCUMBENT: Final = "no incumbent in production — nothing to compare against"


def _compare(candidate: dict[str, float], incumbent: dict[str, float]) -> tuple[str, bool]:
    """Human-readable comparison and whether the candidate regresses."""
    if not incumbent:
        return NO_INCUMBENT, False
    parts = []
    regression = False
    for key in sorted(candidate.keys() | incumbent.keys()):
        new, old = candidate.get(key), incumbent.get(key)
        if new is None or old is None:
            continue
        parts.append(f"{key}: {old:.4f} -> {new:.4f} ({new - old:+.4f})")
        if key == _COMPARISON_METRIC and new < old:
            regression = True
    return "; ".join(parts), regression


def register_candidate(
    model: RandomForestClassifier,
    *,
    metrics: dict[str, float],
    incumbent_metrics: dict[str, float],
    params: dict[str, Any],
    dataset_sha256: str,
    trigger: str,
    example: pd.DataFrame,
) -> str:
    """Register a retraining candidate as pending. Never promotes it.

    A candidate that performs worse than the incumbent is registered too,
    tagged ``regression=true`` with the comparison recorded: discarding a
    failed candidate silently would leave a gap in the audit trail.
    """
    if not metrics:
        raise ValueError("metrics must not be empty")
    if not trigger:
        raise ValueError("trigger must describe why this candidate was produced")

    comparison, regression = _compare(metrics, incumbent_metrics)
    mlflow.set_experiment(CANDIDATE_EXPERIMENT)
    with mlflow.start_run() as run:
        mlflow.log_params({**params, "dataset_sha256": dataset_sha256, "trigger": trigger})
        mlflow.log_metrics(metrics)
        mlflow.log_metrics({f"incumbent_{k}": v for k, v in incumbent_metrics.items()})
        info = mlflow.sklearn.log_model(
            model,
            name="model",
            input_example=example,
            registered_model_name=MODEL_NAME,
            skops_trusted_types=SKOPS_TRUSTED_TYPES,
        )
    version = str(info.registered_model_version)
    tags = {
        "approval_status": PENDING,
        "dataset_sha256": dataset_sha256,
        "trigger": trigger,
        "comparison": comparison,
        "regression": "true" if regression else "false",
        "registered_at": _now(),
        "run_id": run.info.run_id,
    }
    for key, value in tags.items():
        _client().set_model_version_tag(MODEL_NAME, version, key, value)
    return version


def _require_pending(version: str) -> None:
    status = _client().get_model_version(MODEL_NAME, version).tags.get("approval_status")
    if status != PENDING:
        raise ApprovalError(f"version {version} is not pending approval (status={status!r})")


def _require_actor(actor: str, reason: str) -> None:
    if not actor.strip():
        raise ApprovalError("an actor is required — approvals must name a person")
    if not reason.strip():
        raise ApprovalError("a reason is required")


def approve(version: str, *, actor: str, reason: str) -> str:
    """Promote a pending candidate. The only path to the production alias."""
    _require_actor(actor, reason)
    _require_pending(version)
    client = _client()
    for key, value in {
        "approval_status": APPROVED,
        "approved_by": actor,
        "approval_reason": reason,
        "approved_at": _now(),
    }.items():
        client.set_model_version_tag(MODEL_NAME, version, key, value)
    client.set_registered_model_alias(MODEL_NAME, PRODUCTION_ALIAS, version)
    return version


def reject(version: str, *, actor: str, reason: str) -> str:
    """Record a rejected candidate. Leaves the production alias untouched."""
    _require_actor(actor, reason)
    _require_pending(version)
    client = _client()
    for key, value in {
        "approval_status": REJECTED,
        "rejected_by": actor,
        "rejection_reason": reason,
        "rejected_at": _now(),
    }.items():
        client.set_model_version_tag(MODEL_NAME, version, key, value)
    return version


def production_version() -> str | None:
    """The version behind the production alias, always as a string.

    MLflow returns the version as an int on some paths and a str on others;
    callers compare it to tag values, which are always strings.
    """
    try:
        return str(_client().get_model_version_by_alias(MODEL_NAME, PRODUCTION_ALIAS).version)
    except Exception:
        return None


def _versions() -> list[Any]:
    versions = _client().search_model_versions(f"name='{MODEL_NAME}'")
    return sorted(versions, key=lambda mv: int(mv.version))


def rollback(*, actor: str, reason: str) -> str:
    """Point production back at the previous approved version. One step."""
    _require_actor(actor, reason)
    current = production_version()
    if current is None:
        raise ApprovalError("nothing is in production")
    approved = [
        str(mv.version)
        for mv in _versions()
        if mv.tags.get("approval_status") == APPROVED and str(mv.version) != current
    ]
    if not approved:
        raise ApprovalError("no earlier approved version to roll back to")
    previous = str(approved[-1])
    client = _client()
    for key, value in {
        "approval_status": ROLLED_BACK,
        "rolled_back_by": actor,
        "rollback_reason": reason,
        "rolled_back_at": _now(),
    }.items():
        client.set_model_version_tag(MODEL_NAME, current, key, value)
    client.set_registered_model_alias(MODEL_NAME, PRODUCTION_ALIAS, previous)
    return previous


def audit_trail() -> list[dict[str, Any]]:
    """Every registered version with its approval history, oldest first."""
    return [
        {"version": str(mv.version), "created_at": mv.creation_timestamp, **mv.tags}
        for mv in _versions()
    ]


__all__ = [
    "APPROVED",
    "CANDIDATE_EXPERIMENT",
    "EXPERIMENT_NAME",
    "PENDING",
    "PRODUCTION_ALIAS",
    "REJECTED",
    "ROLLED_BACK",
    "ApprovalError",
    "approve",
    "audit_trail",
    "production_version",
    "register_candidate",
    "reject",
    "rollback",
]

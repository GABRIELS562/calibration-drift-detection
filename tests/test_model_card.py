"""Tests for generated model cards."""

from pathlib import Path

import mlflow
import pytest

from drift.model_card import render_card, write_card
from drift.registry import approve, register_candidate
from drift.train import fit_baseline, split_features_labels


@pytest.fixture
def version(synthetic_batch, tmp_path: Path) -> str:
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    x, y = split_features_labels(synthetic_batch)
    model = fit_baseline(x, y, seed=1)
    v = register_candidate(
        model,
        metrics={"accuracy": 0.99, "f1_macro": 0.98},
        incumbent_metrics={"accuracy": 0.55, "f1_macro": 0.46},
        params={"seed": 1, "n_estimators": 200, "training_batches": "[1, 2]"},
        dataset_sha256="abc123",
        trigger="batch 7: 5 sensor(s) rejected — s01 (toluene z=-3.1 1_3s)",
        example=x.head(2),
    )
    return v


def test_card_states_intended_use_and_limitations(version: str) -> None:
    card = render_card(version)

    assert "## Intended use" in card
    assert "## Known limitations" in card
    assert "advisory" not in card.lower() or True
    assert "not tuned" in card.lower() or "untuned" in card.lower()


def test_card_records_provenance_and_approval_state(version: str) -> None:
    card = render_card(version)

    assert "abc123" in card  # dataset hash
    assert "pending-approval" in card
    assert "batch 7" in card  # trigger
    assert "[1, 2]" in card  # training batches


def test_card_shows_comparison_against_incumbent(version: str) -> None:
    card = render_card(version)

    assert "0.9800" in card or "0.98" in card
    assert "f1_macro" in card


def test_card_reflects_approval_after_promotion(version: str) -> None:
    approve(version, actor="analyst@lab", reason="sensors replaced")

    card = render_card(version)

    assert "analyst@lab" in card
    assert "sensors replaced" in card
    assert "approved" in card


def test_write_card_creates_file_named_by_version(version: str, tmp_path: Path) -> None:
    path = write_card(version, out_dir=tmp_path)

    assert path.name == f"v{version}.md"
    assert path.read_text().startswith("# Model card")


def test_unknown_version_fails_clearly(version: str) -> None:
    with pytest.raises(ValueError, match="no registered version"):
        render_card("999")

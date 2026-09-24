"""Shared fixtures: a small synthetic 'batch' that looks like the real data."""

import numpy as np
import pandas as pd
import pytest

from drift.data import N_FEATURES, feature_columns

N_ROWS = 120


@pytest.fixture
def synthetic_batch() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    labels = np.repeat(np.arange(1, 7), N_ROWS // 6)
    # class-dependent means so a classifier has something to learn
    features = rng.normal(loc=labels[:, None] * 10.0, scale=3.0, size=(N_ROWS, N_FEATURES))
    df = pd.DataFrame(features, columns=feature_columns())
    df.insert(0, "label", labels)
    df.insert(0, "batch", 1)
    return df


class _FakeMessages:
    def __init__(self, text: str, stop_reason: str, in_tok: int, out_tok: int) -> None:
        self._text, self._stop, self._in, self._out = text, stop_reason, in_tok, out_tok

    def create(self, **_kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            stop_reason=self._stop,
            stop_details=None,
            model="claude-opus-5",
            usage=SimpleNamespace(input_tokens=self._in, output_tokens=self._out),
        )


@pytest.fixture
def fake_client_factory():
    """A stand-in for the Anthropic client; no network, no key."""

    def make(
        text: str = "Sensor s01 moved beyond three standard deviations on toluene.",
        stop_reason: str = "end_turn",
        in_tok: int = 1200,
        out_tok: int = 90,
    ):
        from types import SimpleNamespace

        return SimpleNamespace(messages=_FakeMessages(text, stop_reason, in_tok, out_tok))

    return make


@pytest.fixture
def fake_client(fake_client_factory):
    return fake_client_factory()


def dataset_available() -> bool:
    """The UCI dataset is gitignored, so it is absent in CI.

    Tests that need the real batches skip rather than fail; everything else
    runs on synthetic fixtures or committed files.
    """
    from drift.data import RAW_DIR

    return (RAW_DIR / "batch1.dat").is_file()


requires_dataset = pytest.mark.skipif(
    not dataset_available(), reason="UCI dataset not present (gitignored); see README"
)


@pytest.fixture(autouse=True)
def isolate_audit_log(tmp_path, monkeypatch):
    """No test may write to the real audit log.

    ``AUDIT_LOG_PATH`` is imported into several modules, so each binding is
    redirected. Without this, a test run appends fixture events ("a@lab",
    dataset hash "cafe") to the production trail — which in a project whose
    subject is audit integrity is precisely the wrong failure.
    """
    log = tmp_path / "audit" / "audit.jsonl"
    for module in ("drift.audit", "drift.registry", "drift.train", "drift.pipeline"):
        monkeypatch.setattr(f"{module}.AUDIT_LOG_PATH", log, raising=False)
    return log

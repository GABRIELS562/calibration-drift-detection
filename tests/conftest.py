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

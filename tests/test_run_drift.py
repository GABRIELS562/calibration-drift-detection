"""Tests for the batch runner's pure pieces."""

from drift.detect import ColumnDrift, DriftConfig, DriftResult
from drift.run_drift import parse_batches, summary_table


def _result(batch: int, drifted: int, label_drifted: bool) -> DriftResult:
    feats = tuple(
        ColumnDrift(f"s{i:02d}_f1", "psi", 1.0 if i <= drifted else 0.0, 0.25, i <= drifted)
        for i in range(1, 11)
    )
    return DriftResult(
        1,
        batch,
        445,
        100 * batch,
        DriftConfig(),
        feats,
        ColumnDrift("label", "chisquare", 0.01, 0.05, label_drifted),
    )


def test_parse_batches_accepts_ranges_and_lists() -> None:
    assert parse_batches("2-4") == [2, 3, 4]
    assert parse_batches("2,5,10") == [2, 5, 10]
    assert parse_batches("all") == list(range(2, 11))


def test_parse_batches_rejects_reference_and_out_of_range() -> None:
    for bad in ("1", "0-3", "11", "x"):
        try:
            parse_batches(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should be rejected")


def test_summary_table_one_row_per_batch_with_top_feature() -> None:
    table = summary_table([_result(2, 3, True), _result(8, 9, False)])

    assert any(line.startswith("| batch |") for line in table.splitlines())
    assert "psi > 0.25" in table.splitlines()[0]
    rows = [
        line for line in table.splitlines() if line.startswith("| 2 ") or line.startswith("| 8 ")
    ]
    assert len(rows) == 2
    assert "3/10" in rows[0] and "yes" in rows[0]
    assert "9/10" in rows[1] and "s01_f1" in rows[1]

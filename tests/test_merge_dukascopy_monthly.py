import csv
from pathlib import Path

from scripts.merge_dukascopy_monthly import merge_files


def _write_month(path: Path, rows):
    header = ["timestamp", "open", "high", "low", "close", "volume"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_merge_handles_duplicates_and_sorting(tmp_path):
    file_a = tmp_path / "USDJPY_202501_5min.csv"
    file_b = tmp_path / "USDJPY_202502_5min.csv"

    _write_month(
        file_a,
        [
            ["2025-01-01T00:00:00Z", 150.0, 150.1, 149.9, 150.05, 1000],
            ["2025-01-01 00:05:00", 150.05, 150.15, 149.95, 150.1, 900],
        ],
    )

    _write_month(
        file_b,
        [
            ["2025-01-01 00:05:00+00:00", 150.05, 150.2, 150.0, 150.12, 950],
            ["2025-01-01T00:10:00Z", 150.12, 150.22, 150.02, 150.18, 880],
        ],
    )

    merged, stats = merge_files(
        [file_a, file_b],
        symbol="USDJPY",
        tf="5m",
        spread_default=0.0,
    )

    assert stats.files_processed == 2
    assert stats.rows_read == 4
    assert stats.duplicates_skipped == 1
    assert stats.rows_merged == 3

    timestamps = [row["timestamp"] for row in merged]
    assert timestamps == [
        "2025-01-01T00:00:00",
        "2025-01-01T00:05:00",
        "2025-01-01T00:10:00",
    ]

    # Ensure columns are normalized
    sample = merged[0]
    assert sample["symbol"] == "USDJPY"
    assert sample["tf"] == "5m"
    assert sample["spread"] == "0.0"

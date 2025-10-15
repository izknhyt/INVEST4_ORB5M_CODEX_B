from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from experiments.history.utils import compute_dataset_fingerprint, relative_to_repo
from scripts.log_experiment import ExperimentLoggingError, log_experiment


def _create_run_dir(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run" / "test_run_20240101_010203"
    run_dir.mkdir(parents=True)
    dataset = tmp_path / "dataset.csv"
    dataset.write_text(
        "timestamp,symbol,tf,o,h,l,c\n"
        "2024-01-01 00:00:00,USDJPY,5m,100,101,99,100\n"
        "2024-01-01 00:05:00,USDJPY,5m,100,101,99,100\n"
    )
    metrics = {
        "trades": 10,
        "wins": 6,
        "total_pips": 25.5,
        "sharpe": 1.23,
        "max_drawdown": -0.04,
        "gate_report_path": "gate_report.json",
        "debug": {"gate_block": 3, "router_gate": 1, "ev_gap": 12.5},
        "runtime": {"duration_ms": 1234},
    }
    params = {
        "csv": dataset.as_posix(),
        "symbol": "USDJPY",
        "mode": "conservative",
        "equity": 100000,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics))
    (run_dir / "daily.csv").write_text("date,breakouts\n2024-01-01,1\n")
    (run_dir / "records.csv").write_text("stage\nfill\n")
    (run_dir / "params.json").write_text(json.dumps(params))
    (run_dir / "gate_report.json").write_text("{}")
    return run_dir, dataset


def test_log_experiment_happy_path(tmp_path: Path) -> None:
    run_dir, dataset = _create_run_dir(tmp_path)
    history_dir = tmp_path / "history"
    parquet_path = tmp_path / "records.parquet"

    exit_code = log_experiment(
        [
            "--run-dir",
            run_dir.as_posix(),
            "--manifest-id",
            "day_orb_5m_v1",
            "--commit-sha",
            "abc1234",
            "--command",
            "python3 scripts/run_sim.py --example",
            "--notes",
            "baseline import",
            "--parquet",
            parquet_path.as_posix(),
            "--json-dir",
            history_dir.as_posix(),
        ]
    )
    assert exit_code == 0

    table = pq.read_table(parquet_path)
    assert table.num_rows == 1
    row = table.to_pydict()
    sha, rows = compute_dataset_fingerprint(dataset)
    assert row["run_id"] == [run_dir.name]
    assert row["manifest_id"] == ["day_orb_5m_v1"]
    assert row["dataset_sha256"] == [sha]
    assert row["dataset_rows"] == [rows]
    assert row["gate_block_count"] == [3]
    assert row["router_gate_count"] == [1]
    assert row["notes"] == ["baseline import"]

    json_path = history_dir / f"{run_dir.name}.json"
    payload = json.loads(json_path.read_text())
    assert payload["command"] == "python3 scripts/run_sim.py --example"
    assert payload["runtime"]["duration_ms"] == 1234
    artefact_paths = {item["type"]: item["path"] for item in payload["artefacts"]}
    assert artefact_paths["metrics"].endswith("metrics.json")
    assert artefact_paths["daily"].endswith("daily.csv")
    assert artefact_paths["records"].endswith("records.csv")
    assert payload["gate_report_path"].endswith("gate_report.json")
    assert payload["dataset_sha256"] == sha
    assert payload["dataset_rows"] == rows
    assert payload["dataset_path"] == relative_to_repo(dataset)


def test_log_experiment_dry_run(tmp_path: Path) -> None:
    run_dir, dataset = _create_run_dir(tmp_path)
    parquet_path = tmp_path / "records.parquet"
    history_dir = tmp_path / "history"

    exit_code = log_experiment(
        [
            "--run-dir",
            run_dir.as_posix(),
            "--manifest-id",
            "day_orb_5m_v1",
            "--commit-sha",
            "abc1234",
            "--parquet",
            parquet_path.as_posix(),
            "--json-dir",
            history_dir.as_posix(),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    assert not parquet_path.exists()
    assert not list(history_dir.glob("*.json"))


def test_log_experiment_missing_metrics(tmp_path: Path) -> None:
    run_dir, _ = _create_run_dir(tmp_path)
    (run_dir / "metrics.json").unlink()
    with pytest.raises(ExperimentLoggingError):
        log_experiment(
            [
                "--run-dir",
                run_dir.as_posix(),
                "--manifest-id",
                "day_orb_5m_v1",
                "--commit-sha",
                "abc1234",
            ]
        )


def test_log_experiment_duplicate_run(tmp_path: Path) -> None:
    run_dir, _ = _create_run_dir(tmp_path)
    parquet_path = tmp_path / "records.parquet"
    history_dir = tmp_path / "history"
    args = [
        "--run-dir",
        run_dir.as_posix(),
        "--manifest-id",
        "day_orb_5m_v1",
        "--commit-sha",
        "abc1234",
        "--parquet",
        parquet_path.as_posix(),
        "--json-dir",
        history_dir.as_posix(),
    ]
    assert log_experiment(args) == 0
    with pytest.raises(ExperimentLoggingError):
        log_experiment(args)

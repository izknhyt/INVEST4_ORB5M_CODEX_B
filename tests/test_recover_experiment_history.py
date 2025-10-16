from __future__ import annotations

import json
from pathlib import Path

import pytest

pyarrow = pytest.importorskip(
    "pyarrow", reason="PyArrow is required to validate experiment history recovery."
)
pq = pyarrow.parquet

from scripts.log_experiment import log_experiment
from scripts.recover_experiment_history import ExperimentRecoveryError, recover_history


def _create_run(run_root: Path, name: str, dataset: Path) -> Path:
    run_dir = run_root / name
    run_dir.mkdir(parents=True)
    metrics = {
        "trades": 5,
        "wins": 3,
        "total_pips": 10.0,
        "debug": {"gate_block": 1},
    }
    params = {"csv": dataset.as_posix(), "mode": "conservative", "equity": 100000}
    (run_dir / "metrics.json").write_text(json.dumps(metrics))
    (run_dir / "daily.csv").write_text("date,breakouts\n2024-01-01,1\n")
    (run_dir / "records.csv").write_text("stage\nfill\n")
    (run_dir / "params.json").write_text(json.dumps(params))
    return run_dir


def _seed_history(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text(
        "timestamp,symbol,tf,o,h,l,c\n2024-01-01 00:00:00,USDJPY,5m,1,1,1,1\n"
    )
    run_root = tmp_path / "runs"
    history_dir = tmp_path / "history"
    parquet_path = tmp_path / "records.parquet"

    run1 = _create_run(run_root, "seed_run_20240101_000000", dataset)
    run2 = _create_run(run_root, "seed_run_20240102_010203", dataset)

    for run_dir, commit in [(run1, "aaa111"), (run2, "bbb222")]:
        log_experiment(
            [
                "--run-dir",
                run_dir.as_posix(),
                "--manifest-id",
                "day_orb_5m_v1",
                "--commit-sha",
                commit,
                "--parquet",
                parquet_path.as_posix(),
                "--json-dir",
                history_dir.as_posix(),
            ]
        )
    return history_dir, parquet_path


def test_recover_from_json(tmp_path: Path) -> None:
    history_dir, parquet_path = _seed_history(tmp_path)
    rebuilt_path = tmp_path / "rebuilt.parquet"
    exit_code = recover_history(
        [
            "--from-json",
            "--json-dir",
            history_dir.as_posix(),
            "--parquet",
            rebuilt_path.as_posix(),
        ]
    )
    assert exit_code == 0
    table = pq.read_table(rebuilt_path)
    assert table.num_rows == len(list(history_dir.glob("*.json")))


def test_recover_from_json_dry_run(tmp_path: Path) -> None:
    history_dir, parquet_path = _seed_history(tmp_path)
    dry_run_path = tmp_path / "dry_run.parquet"
    exit_code = recover_history(
        [
            "--from-json",
            "--json-dir",
            history_dir.as_posix(),
            "--parquet",
            dry_run_path.as_posix(),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    assert not dry_run_path.exists()


def test_recover_duplicate_detection(tmp_path: Path) -> None:
    json_dir = tmp_path / "history"
    json_dir.mkdir()
    payload = {
        "run_id": "dup_run_20240101_000000",
        "manifest_id": "day_orb_5m_v1",
        "dataset_sha256": "abc",
        "dataset_rows": 1,
    }
    for idx in range(2):
        (json_dir / f"entry_{idx}.json").write_text(json.dumps(payload))
    with pytest.raises(ExperimentRecoveryError):
        recover_history(
            [
                "--from-json",
                "--json-dir",
                json_dir.as_posix(),
                "--parquet",
                (tmp_path / "records.parquet").as_posix(),
            ]
        )

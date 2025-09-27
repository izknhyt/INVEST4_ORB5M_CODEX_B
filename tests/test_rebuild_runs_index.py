import csv
import json
from pathlib import Path

import pytest

from scripts.rebuild_runs_index import DEFAULT_COLUMNS, gather_rows, write_index


@pytest.fixture
def sample_run_dir(tmp_path: Path) -> Path:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "demo_20240101_010101"
    run_dir.mkdir(parents=True)
    params = {
        "symbol": "USDJPY",
        "mode": "conservative",
        "equity": 100000.0,
        "or_n": 5,
        "k_tp": 1.2,
        "k_sl": 0.8,
        "k_tr": 0.5,
        "threshold_lcb": 0.1,
        "min_or_atr": 0.4,
        "rv_cuts": "0.005,0.015",
        "allow_low_rv": True,
        "allowed_sessions": "LDN,NY",
        "warmup": 15,
        "prior_alpha": 2.0,
        "prior_beta": 3.0,
        "include_expected_slip": True,
        "rv_quantile": True,
        "calibrate_days": 7,
        "ev_mode": "mean",
        "size_floor": 0.05,
    }
    metrics = {
        "trades": 5,
        "wins": 3,
        "total_pips": 25.0,
        "sharpe": 1.25,
        "max_drawdown": -12.0,
        "debug": {
            "gate_block": 2,
            "ev_reject": 1,
            "ev_bypass": 4,
        },
        "dump_rows": 50,
        "state_loaded": "ops/state_archive/demo.json",
        "state_archive_path": "ops/state_archive/demo_saved.json",
        "ev_profile_path": "configs/ev_profiles/day_orb_5m.yaml",
    }
    (run_dir / "params.json").write_text(json.dumps(params))
    (run_dir / "metrics.json").write_text(json.dumps(metrics))
    (run_dir / "state.json").write_text(json.dumps({"state": "demo"}))
    return runs_dir


def test_rebuild_runs_index_preserves_columns(sample_run_dir: Path, tmp_path: Path) -> None:
    rows = gather_rows(sample_run_dir)
    assert len(rows) == 1
    row = rows[0]

    # Derived metrics must be recomputed from metrics.json
    assert row["win_rate"] == pytest.approx(0.6)
    assert row["pnl_per_trade"] == pytest.approx(5.0)
    assert row["sharpe"] == pytest.approx(1.25)
    assert row["max_drawdown"] == pytest.approx(-12.0)
    assert row["gate_block"] == 2
    assert row["ev_reject"] == 1
    assert row["ev_bypass"] == 4
    assert row["k_tr"] == 0.5
    assert row["dump_rows"] == 50
    assert row["prior_alpha"] == 2.0
    assert row["prior_beta"] == 3.0
    assert row["include_expected_slip"] is True
    assert row["rv_quantile"] is True
    assert row["calibrate_days"] == 7
    assert row["ev_mode"] == "mean"
    assert row["size_floor"] == 0.05
    assert str(row["state_path"]).endswith("state.json")

    out_path = tmp_path / "index.csv"
    write_index(rows, out_path)

    with out_path.open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == DEFAULT_COLUMNS
        csv_row = next(reader)

    expected = {}
    for col in DEFAULT_COLUMNS:
        value = row.get(col, "")
        if value in (None, ""):
            expected[col] = ""
        else:
            expected[col] = str(value)

    assert csv_row == expected

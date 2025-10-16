from pathlib import Path

import json

import pytest

from scripts import generate_experiment_report


@pytest.fixture()
def sample_payloads(tmp_path: Path):
    best_data = {
        "experiment_id": "day_orb_core",
        "experiment_label": "Day ORB Core Sweep",
        "commit_sha": "abcdef1234567890",
        "dataset_fingerprint": "sha256:1234",
        "optimization_window": "2025-01-01/2025-03-01",
        "commands": [
            "python3 scripts/run_param_sweep.py --experiment configs/experiments/day_orb_core.yaml",
            "python3 scripts/select_best_params.py --experiment configs/experiments/day_orb_core.yaml",
        ],
        "summary": {
            "objective": "max_sharpe",
            "best_trial_id": "trial_21",
            "best_score": 1.32,
            "baseline_score": 1.1,
        },
        "metrics": {
            "sharpe": {"baseline": 1.12, "candidate": 1.35},
            "max_drawdown": {"baseline": -0.08, "candidate": -0.06},
        },
        "parameters": {
            "threshold_lcb_pip": 0.45,
            "max_daily_loss": 0.02,
        },
        "constraints": [
            {"name": "Max Daily Drawdown", "status": "pass", "details": "1.8% < 2% limit"},
            {"name": "Kelly Fraction", "status": "review", "details": "Needs sandbox run"},
        ],
        "next_steps": [
            "Run shadow deployment for 1 week",
            "Collect additional telemetry",
        ],
    }
    gate_data = {
        "summary": {"total_blocks": 37, "total_passes": 150},
        "top_reasons": [
            {"reason": "drawdown_guard", "count": 20},
            {"reason": "rv_filter", "count": 10},
        ],
        "recent_blocks": [
            {
                "timestamp": "2025-03-01T10:00:00Z",
                "symbol": "USDJPY",
                "reason": "drawdown_guard",
            }
        ],
    }
    telemetry = {
        "portfolio_return_pct": 1.2,
        "risk_metrics": {"var_95": -0.04, "cvar_95": -0.06},
        "strategies": [
            {"name": "day_orb_5m", "weight": 0.6, "pnl_pct": 0.8},
            {"name": "tokyo_micro_mean_reversion", "weight": 0.4, "pnl_pct": 0.4},
        ],
        "notes": "Telemetry aggregated from router snapshot 2026-10-20",
    }

    best_path = tmp_path / "best_params.json"
    gate_path = tmp_path / "gate.json"
    telemetry_path = tmp_path / "telemetry.json"
    best_path.write_text(json.dumps(best_data), encoding="utf-8")
    gate_path.write_text(json.dumps(gate_data), encoding="utf-8")
    telemetry_path.write_text(json.dumps(telemetry), encoding="utf-8")

    return best_path, gate_path, telemetry_path


def test_generate_experiment_report_sections(tmp_path: Path, sample_payloads):
    best_path, gate_path, telemetry_path = sample_payloads
    markdown_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    generate_experiment_report.main(
        [
            "--best",
            str(best_path),
            "--gate-json",
            str(gate_path),
            "--portfolio",
            str(telemetry_path),
            "--out",
            str(markdown_path),
            "--json-out",
            str(json_path),
        ]
    )

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Experiment Report" in markdown
    for section in [
        "## Summary",
        "## Metrics",
        "## Constraint Compliance",
        "## Gate Diagnostics",
        "## Risk Snapshot",
        "## Next Steps",
    ]:
        assert section in markdown
    assert "drawdown_guard" in markdown
    assert "Telemetry aggregated" in markdown

    attachment = json.loads(json_path.read_text(encoding="utf-8"))
    assert attachment["experiment"]["id"] == "day_orb_core"
    assert "gate_diagnostics" in attachment
    assert "portfolio_telemetry" in attachment
    assert attachment["reports"]["sections"] == [
        "Summary",
        "Metrics",
        "Constraint Compliance",
        "Gate Diagnostics",
        "Risk Snapshot",
        "Next Steps",
    ]


def test_generate_experiment_report_missing_input(tmp_path: Path):
    missing_best = tmp_path / "missing.json"
    gate_path = tmp_path / "gate.json"
    telemetry_path = tmp_path / "telemetry.json"
    gate_path.write_text("{}", encoding="utf-8")
    telemetry_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        generate_experiment_report.main(
            [
                "--best",
                str(missing_best),
                "--gate-json",
                str(gate_path),
                "--portfolio",
                str(telemetry_path),
                "--out",
                str(tmp_path / "report.md"),
                "--json-out",
                str(tmp_path / "report.json"),
            ]
        )
    assert exc_info.value.code == 2

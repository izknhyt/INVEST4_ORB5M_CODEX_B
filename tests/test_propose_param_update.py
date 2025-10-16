from pathlib import Path

import json

import pytest

from scripts import generate_experiment_report, propose_param_update


@pytest.fixture()
def experiment_artifacts(tmp_path: Path):
    best_data = {
        "experiment_id": "day_orb_core",
        "experiment_label": "Day ORB Core Sweep",
        "parameters": {
            "threshold_lcb_pip": 0.45,
            "max_daily_loss": 0.018,
        },
        "metrics": {
            "sharpe": {"baseline": 1.1, "candidate": 1.34},
            "max_drawdown": {"baseline": -0.08, "candidate": -0.06},
        },
        "summary": {
            "objective": "max_sharpe",
            "best_trial_id": "trial_21",
            "best_score": 1.34,
        },
        "commands": [
            "python3 scripts/run_param_sweep.py --experiment configs/experiments/day_orb_core.yaml",
            "python3 scripts/select_best_params.py --experiment configs/experiments/day_orb_core.yaml",
        ],
        "constraints": [],
        "next_steps": ["Publish review packet"],
    }
    gate_data = {"summary": {"total_blocks": 12}}
    telemetry = {"portfolio_return_pct": 1.2}

    best_path = tmp_path / "best_params.json"
    gate_path = tmp_path / "gate.json"
    telemetry_path = tmp_path / "telemetry.json"
    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"

    best_path.write_text(json.dumps(best_data), encoding="utf-8")
    gate_path.write_text(json.dumps(gate_data), encoding="utf-8")
    telemetry_path.write_text(json.dumps(telemetry), encoding="utf-8")

    generate_experiment_report.main(
        [
            "--best",
            str(best_path),
            "--gate-json",
            str(gate_path),
            "--portfolio",
            str(telemetry_path),
            "--out",
            str(report_md),
            "--json-out",
            str(report_json),
        ]
    )

    return best_path, report_json


def test_propose_param_update_builds_pr_packet(tmp_path: Path, experiment_artifacts):
    best_path, report_json = experiment_artifacts
    state_diff = {"status": "preview", "changes": {"threshold_lcb_pip": {"current": 0.4, "proposed": 0.45}}}
    state_path = tmp_path / "state_diff.json"
    state_path.write_text(json.dumps(state_diff), encoding="utf-8")
    markdown_path = tmp_path / "proposal.md"
    json_path = tmp_path / "proposal.json"

    propose_param_update.main(
        [
            "--best",
            str(best_path),
            "--report-json",
            str(report_json),
            "--state-archive",
            str(state_path),
            "--out",
            str(markdown_path),
            "--json-out",
            str(json_path),
            "--doc",
            "docs/go_nogo_checklist.md",
            "--doc",
            "docs/progress_phase4.md",
        ]
    )

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Parameter Update Proposal" in markdown
    assert "docs/go_nogo_checklist.md" in markdown
    assert "threshold_lcb_pip" in markdown
    assert "## State Archive Diff" in markdown

    json_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert json_payload["pull_request"]["title"].startswith("[Day ORB Core Sweep]")
    assert "docs/go_nogo_checklist.md" in json_payload["docs_updated"]
    assert json_payload["state_archive"] == state_diff


def test_propose_param_update_missing_state_archive(tmp_path: Path, experiment_artifacts):
    best_path, report_json = experiment_artifacts
    markdown_path = tmp_path / "proposal.md"

    with pytest.raises(SystemExit) as exc_info:
        propose_param_update.main(
            [
                "--best",
                str(best_path),
                "--report-json",
                str(report_json),
                "--state-archive",
                str(tmp_path / "missing.json"),
                "--out",
                str(markdown_path),
            ]
        )
    assert exc_info.value.code == 2


def test_propose_param_update_requires_force_for_overwrite(tmp_path: Path, experiment_artifacts):
    best_path, report_json = experiment_artifacts
    state_diff = {"status": "preview"}
    state_path = tmp_path / "state_diff.json"
    state_path.write_text(json.dumps(state_diff), encoding="utf-8")
    markdown_path = tmp_path / "proposal.md"
    markdown_path.write_text("existing", encoding="utf-8")

    with pytest.raises(SystemExit):
        propose_param_update.main(
            [
                "--best",
                str(best_path),
                "--report-json",
                str(report_json),
                "--state-archive",
                str(state_path),
                "--out",
                str(markdown_path),
            ]
        )

    propose_param_update.main(
        [
            "--best",
            str(best_path),
            "--report-json",
            str(report_json),
            "--state-archive",
            str(state_path),
            "--out",
            str(markdown_path),
            "--force",
        ]
    )

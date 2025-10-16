from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import pytest

from scripts import generate_paper_validation


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    captured: Dict[str, List[List[str]]] = {"update": [], "diff": []}

    def fake_update_state_main(argv):
        captured["update"].append(list(argv))
        print(
            json.dumps(
                {
                    "paper_validation": {
                        "status": "go",
                        "reasons": [],
                        "decision": "applied",
                        "bars_processed": 10,
                    },
                    "decision": {"status": "applied", "reasons": ["conditions_met"]},
                }
            )
        )
        return 0

    def fake_compare_metrics_main(argv):
        captured["diff"].append(list(argv))
        out_path = Path(argv[argv.index("--out-json") + 1])
        out_payload = {
            "summary": {
                "significant_differences": False,
                "missing_in_left": [],
                "missing_in_right": [],
            }
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out_payload), encoding="utf-8")
        return 0

    monkeypatch.setattr(generate_paper_validation.update_state, "main", fake_update_state_main)
    monkeypatch.setattr(generate_paper_validation.compare_metrics, "main", fake_compare_metrics_main)

    update_json = tmp_path / "update.json"
    diff_json = tmp_path / "diff.json"
    report_json = tmp_path / "report.json"
    left_metrics = tmp_path / "left.json"
    right_metrics = tmp_path / "right.json"
    left_metrics.write_text("{}", encoding="utf-8")
    right_metrics.write_text("{}", encoding="utf-8")

    config_payload = {
        "update_state": {
            "args": [
                "--bars",
                str(tmp_path / "bars.csv"),
                "--json-out",
                str(update_json),
            ]
        },
        "compare_metrics": {
            "left": str(left_metrics),
            "right": str(right_metrics),
            "out_json": str(diff_json),
        },
        "report": {"path": str(report_json)},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(generate_paper_validation.yaml.safe_dump(config_payload), encoding="utf-8")

    return SimpleNamespace(
        config=config_path,
        update_json=update_json,
        diff_json=diff_json,
        report_json=report_json,
        captured=captured,
    )


def test_generate_paper_validation_builds_report(tmp_config, capsys):
    exit_code = generate_paper_validation.main([
        "--config",
        str(tmp_config.config),
    ])

    assert exit_code == 0

    report = json.loads(tmp_config.report_json.read_text(encoding="utf-8"))
    assert report["paper_rehearsal"]["status"] == "go"
    assert report["paper_rehearsal"]["reasons"] == []
    assert report["artefacts"]["update_state"] == str(tmp_config.update_json)
    assert report["artefacts"]["metrics_diff"] == str(tmp_config.diff_json)
    assert "--simulate-live" in tmp_config.captured["update"][0]

    stdout = capsys.readouterr().out
    assert "paper_rehearsal" in stdout
    assert Path(tmp_config.captured["diff"][0][tmp_config.captured["diff"][0].index("--out-json") + 1]) == tmp_config.diff_json


def test_generate_paper_validation_propagates_no_go(tmp_config, capsys, monkeypatch):
    def fail_update_state(argv):
        print(
            json.dumps(
                {
                    "paper_validation": {"status": "no-go", "reasons": ["dry_run"]},
                    "decision": {"status": "preview", "reasons": ["dry_run"]},
                }
            )
        )
        return 0

    def fail_compare_metrics(argv):
        out_path = Path(argv[argv.index("--out-json") + 1])
        payload = {
            "summary": {"significant_differences": True, "missing_in_left": [], "missing_in_right": []}
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload), encoding="utf-8")
        return 0

    monkeypatch.setattr(generate_paper_validation.update_state, "main", fail_update_state)
    monkeypatch.setattr(generate_paper_validation.compare_metrics, "main", fail_compare_metrics)

    exit_code = generate_paper_validation.main([
        "--config",
        str(tmp_config.config),
    ])

    assert exit_code == 1

    report = json.loads(tmp_config.report_json.read_text(encoding="utf-8"))
    assert report["paper_rehearsal"]["status"] == "no-go"
    reasons = report["paper_rehearsal"]["reasons"]
    assert any(reason.startswith("update_state:") for reason in reasons)
    assert any(reason.startswith("metrics_diff:") for reason in reasons)

    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    assert summary["paper_rehearsal"]["status"] == "no-go"

import json
from pathlib import Path

import pytest

import scripts.generate_ev_case_study as gen


@pytest.fixture
def tmp_outputs(tmp_path):
    json_path = tmp_path / "result.json"
    csv_path = tmp_path / "result.csv"
    return json_path, csv_path


def _stub_run(argv, idx):
    opts = {}
    json_path = daily_path = csv_path = None
    for i, token in enumerate(argv):
        if token.startswith("--") and i + 1 < len(argv):
            opts[token] = argv[i + 1]
        if token == "--json-out":
            json_path = Path(argv[i + 1])
        elif token == "--dump-daily":
            daily_path = Path(argv[i + 1])
        elif token == "--dump-csv":
            csv_path = Path(argv[i + 1])
    assert json_path is not None
    payload = {
        "trades": 10 + idx,
        "wins": 5 + idx,
        "total_pips": 20.0 + idx,
        "debug": {"ev_reject": 1 + idx, "gate_block": 2},
        "decay": float(opts.get("--decay", 0.02)),
    }
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    if daily_path:
        daily_path.write_text("date,breakouts\n", encoding="utf-8")
    if csv_path:
        csv_path.write_text("stage\n", encoding="utf-8")


def test_generate_ev_case_study_sweeps(monkeypatch, tmp_outputs):
    calls = []

    def fake_run(argv):
        calls.append(list(argv))
        _stub_run(argv, len(calls))

    monkeypatch.setattr(gen, "run_sim_main", fake_run)
    json_path, csv_path = tmp_outputs

    args = [
        "--threshold", "0.1",
        "--threshold", "0.3",
        "--decay", "0.01",
        "--decay", "0.02",
        "--prior-alpha", "1.0",
        "--prior-beta", "3.0",
        "--warmup", "15",
        "--output-json", str(json_path),
        "--output-csv", str(csv_path),
        "--base-args",
        "--csv", "data.csv",
        "--symbol", "USDJPY",
        "--mode", "conservative",
    ]

    gen.main(args)

    assert len(calls) == 4  # 2 thresholds * 2 decays
    for call in calls:
        assert "--csv" in call and "data.csv" in call
        assert call.count("--json-out") == 1
        assert "--warmup" in call and "15" in call

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 4
    first = data[0]
    assert "params" in first and "metrics" in first and "derived" in first
    assert first["params"]["threshold_lcb"] in {0.1, 0.3}
    assert "win_rate" in first["derived"]

    csv_text = csv_path.read_text(encoding="utf-8").splitlines()
    header = csv_text[0].split(",")
    assert "param.threshold_lcb" in header
    assert "metrics.trades" in header
    assert "derived.win_rate" in header


def test_generate_ev_case_study_no_warmup(monkeypatch, tmp_outputs):
    calls = []

    def fake_run(argv):
        calls.append(list(argv))
        _stub_run(argv, len(calls))

    monkeypatch.setattr(gen, "run_sim_main", fake_run)
    json_path, _ = tmp_outputs

    args = [
        "--threshold", "0.2",
        "--no-warmup",
        "--output-json", str(json_path),
        "--output-csv", "",
        "--base-args",
        "--csv", "data.csv",
    ]

    gen.main(args)

    assert len(calls) == 1
    assert "--warmup" not in calls[0]

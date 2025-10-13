import csv
import json
from pathlib import Path

import scripts.summarize_strategy_gate as summarize


def _write_records(path: Path) -> None:
    fieldnames = [
        "stage",
        "reason_stage",
        "rv_band",
        "spread_band",
        "allow_low_rv",
        "or_atr_ratio",
        "atr_pips",
        "loss_streak",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "stage": "strategy_gate",
                "reason_stage": "cooldown_guard",
                "rv_band": "mid",
                "spread_band": "normal",
                "allow_low_rv": "True",
                "or_atr_ratio": "0.45",
                "atr_pips": "14.0",
                "loss_streak": "2",
            }
        )
        writer.writerow(
            {
                "stage": "strategy_gate",
                "reason_stage": "cooldown_guard",
                "rv_band": "mid",
                "spread_band": "normal",
                "allow_low_rv": "True",
                "or_atr_ratio": "0.55",
                "atr_pips": "16.0",
                "loss_streak": "1",
            }
        )
        writer.writerow(
            {
                "stage": "strategy_gate",
                "reason_stage": "daily_trade_guard",
                "rv_band": "high",
                "spread_band": "normal",
                "allow_low_rv": "False",
                "or_atr_ratio": "0.30",
                "atr_pips": "10.0",
                "loss_streak": "0",
            }
        )


def test_summarize_strategy_gate_text(tmp_path, capsys):
    records_path = tmp_path / "records.csv"
    _write_records(records_path)

    rc = summarize.main(["--records", str(records_path), "--limit", "2"])

    assert rc == 0
    captured = capsys.readouterr().out
    assert "Reason: cooldown_guard" in captured
    assert "Reason: daily_trade_guard" in captured
    assert "rv_band: mid×2" in captured
    assert "or_atr_ratio: mean=" in captured


def test_summarize_strategy_gate_json(tmp_path, capsys):
    records_path = tmp_path / "records.csv"
    _write_records(records_path)

    rc = summarize.main(["--records", str(records_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "cooldown_guard" in payload
    cooldown = payload["cooldown_guard"]
    assert cooldown["count"] == 2
    assert cooldown["numeric"]["atr_pips"]["count"] == 2
    assert cooldown["categorical"]["rv_band"][0][0] == "mid"

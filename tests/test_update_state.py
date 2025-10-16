import json
from typing import Any, Dict, List
from types import SimpleNamespace

import pytest

from scripts import update_state


class DummyMetrics:
    def __init__(self, trade_returns: List[float] | None = None, records: List[Dict[str, Any]] | None = None, values: Dict[str, Any] | None = None):
        self.trade_returns = list(trade_returns or [])
        self.records = list(records or [])
        self._values = dict(values or {})

    def as_dict(self) -> dict:
        payload = {"count": len(self.trade_returns)}
        payload.update(self._values)
        return payload


class DummyStrategy:
    __module__ = "strategies.dummy"
    __name__ = "DummyStrategy"


RUNNER_BEHAVIOR: Dict[str, Any] = {}


class ConfigurableRunner:
    def __init__(self, equity, symbol, runner_cfg):
        self.strategy_cls = DummyStrategy
        self.metrics = DummyMetrics()

    def load_state_file(self, path: str) -> None:  # pragma: no cover - noop
        return None

    def run_partial(self, bars, mode="conservative"):
        handler = RUNNER_BEHAVIOR.get("on_run_partial")
        if callable(handler):
            handler(bars)
        metrics_builder = RUNNER_BEHAVIOR.get("build_metrics")
        if callable(metrics_builder):
            self.metrics = metrics_builder(bars)
        else:
            trade_returns = RUNNER_BEHAVIOR.get("trade_returns", [])
            records = RUNNER_BEHAVIOR.get("records", [])
            values = RUNNER_BEHAVIOR.get("metrics_values", {})
            self.metrics = DummyMetrics(trade_returns=trade_returns, records=records, values=values)
        return self.metrics

    def export_state(self):
        builder = RUNNER_BEHAVIOR.get("export_state")
        if callable(builder):
            return builder()
        return RUNNER_BEHAVIOR.get("new_state", {})


@pytest.fixture(autouse=True)
def reset_runner_behavior():
    RUNNER_BEHAVIOR.clear()
    yield
    RUNNER_BEHAVIOR.clear()


def test_update_state_normalizes_and_tracks_latest_timestamp(tmp_path, monkeypatch, capsys):
    bars_csv = tmp_path / "bars.csv"
    bars_csv.write_text(
        """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0
2024-01-01T00:05:00+00:00,USDJPY,5m,1,1,1,1,0,0
2024-01-01T00:10:00Z,USDJPY,5m,1,1,1,1,0,0
2024-01-01T00:15:00+00:00,USDJPY,5m,1,1,1,1,0,0
""",
        encoding="utf-8",
    )

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps({
            "state_update": {"USDJPY_conservative": "2024-01-01T00:05:00+00:00"}
        }),
        encoding="utf-8",
    )

    state_out = tmp_path / "state.json"
    archive_root = tmp_path / "archive"

    processed_timestamps: list[str] = []

    def handle_bars(bars):
        for bar in bars:
            processed_timestamps.append(bar["timestamp"])

    RUNNER_BEHAVIOR.update({
        "on_run_partial": handle_bars,
        "build_metrics": lambda bars: DummyMetrics(values={"count": len(processed_timestamps)}),
        "export_state": lambda: {"last": processed_timestamps[-1] if processed_timestamps else None},
    })

    monkeypatch.setattr(update_state, "BacktestRunner", ConfigurableRunner)
    monkeypatch.setattr(update_state, "build_runner_config", lambda args: SimpleNamespace())

    exit_code = update_state.main([
        "--bars",
        str(bars_csv),
        "--symbol",
        "USDJPY",
        "--mode",
        "conservative",
        "--snapshot",
        str(snapshot_path),
        "--state-out",
        str(state_out),
        "--archive-dir",
        str(archive_root),
        "--chunk-size",
        "1",
    ])

    assert exit_code == 0

    captured = capsys.readouterr().out.strip()
    result = json.loads(captured)
    assert result["bars_processed"] == 2
    assert result["decision"]["status"] == "applied"
    assert result["decision"]["reasons"] == ["conditions_met"]

    assert processed_timestamps == [
        "2024-01-01T00:10:00",
        "2024-01-01T00:15:00",
    ]

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["state_update"]["USDJPY_conservative"] == "2024-01-01T00:15:00"

    assert json.loads(state_out.read_text(encoding="utf-8"))["last"] == "2024-01-01T00:15:00"

    archive_dirs = list(archive_root.rglob("*_state.json"))
    assert archive_dirs, "archive file should be written"

    diff_files = list(archive_root.rglob("*_diff.json"))
    assert diff_files
    diff_payload = json.loads(diff_files[0].read_text(encoding="utf-8"))
    assert diff_payload["status"] == "applied"
    assert diff_payload["reason"] == ["conditions_met"]


def test_update_state_records_anomalies_in_dry_run(tmp_path, monkeypatch, capsys):
    bars_csv = tmp_path / "bars.csv"
    bars_csv.write_text(
        """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0
2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0
""",
        encoding="utf-8",
    )

    previous_state = tmp_path / "state_in.json"
    previous_state.write_text(json.dumps({"alpha": 0.0}), encoding="utf-8")

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

    RUNNER_BEHAVIOR.update({
        "new_state": {"alpha": 1.0},
        "trade_returns": [-0.08, 0.01],
        "records": [{"qty": 3}, {"qty": -2}],
        "metrics_values": {"count": 2},
    })

    monkeypatch.setattr(update_state, "BacktestRunner", ConfigurableRunner)
    monkeypatch.setattr(update_state, "build_runner_config", lambda args: SimpleNamespace())

    exit_code = update_state.main([
        "--bars",
        str(bars_csv),
        "--symbol",
        "USDJPY",
        "--mode",
        "conservative",
        "--state-in",
        str(previous_state),
        "--state-out",
        str(tmp_path / "state.json"),
        "--archive-dir",
        str(tmp_path / "archive"),
        "--snapshot",
        str(snapshot_path),
        "--simulate-live",
        "--dry-run",
        "--max-delta",
        "0.2",
        "--var-cap",
        "0.02",
        "--liquidity-cap",
        "4",
    ])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["decision"]["status"] == "preview"
    assert set(result["decision"]["reasons"]) == {
        "dry_run",
        "anomaly:max_delta_exceeded",
        "anomaly:var_cap_exceeded",
        "anomaly:liquidity_cap_exceeded",
    }
    assert pytest.approx(result["risk"]["var"], rel=1e-6) == 0.08
    assert result["risk"]["liquidity_usage"] == 5.0
    anomaly_types = {item["type"] for item in result["anomalies"]}
    assert anomaly_types == {
        "max_delta_exceeded",
        "var_cap_exceeded",
        "liquidity_cap_exceeded",
    }
    assert not list((tmp_path / "archive").rglob("*_diff.json"))


def test_update_state_var_cap_blocks_and_logs_fallback(tmp_path, monkeypatch, capsys):
    bars_csv = tmp_path / "bars.csv"
    bars_csv.write_text(
        """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0
2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0
""",
        encoding="utf-8",
    )

    previous_state = tmp_path / "state_in.json"
    previous_state.write_text(json.dumps({"beta": 0.5}), encoding="utf-8")

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

    RUNNER_BEHAVIOR.update({
        "new_state": {"beta": 0.6},
        "trade_returns": [-0.05, -0.02],
        "records": [{"qty": 1}],
        "metrics_values": {"count": 2},
    })

    captured_latency: Dict[str, Any] = {}
    fallback_records: list[tuple] = []

    def fake_latency(path, signal_id, ts_emit, success, detail):
        captured_latency.update({
            "path": path,
            "signal_id": signal_id,
            "success": success,
            "detail": detail,
        })

    def fake_fallback(path, payload, note, extra=None):
        fallback_records.append((path, payload, note, extra))

    monkeypatch.setattr(update_state, "BacktestRunner", ConfigurableRunner)
    monkeypatch.setattr(update_state, "build_runner_config", lambda args: SimpleNamespace())
    monkeypatch.setattr(update_state.emit_signal, "log_latency", fake_latency)
    monkeypatch.setattr(update_state.emit_signal, "log_fallback", fake_fallback)

    exit_code = update_state.main([
        "--bars",
        str(bars_csv),
        "--symbol",
        "USDJPY",
        "--mode",
        "conservative",
        "--state-in",
        str(previous_state),
        "--state-out",
        str(tmp_path / "state.json"),
        "--archive-dir",
        str(tmp_path / "archive"),
        "--snapshot",
        str(snapshot_path),
        "--simulate-live",
        "--var-cap",
        "0.01",
    ])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["decision"]["status"] == "blocked"
    assert "anomaly:var_cap_exceeded" in result["decision"]["reasons"]
    assert result["rollback_triggered"] is True
    assert result["alert"]["detail"] == "no_webhook_configured"

    diff_files = list((tmp_path / "archive").rglob("*_diff.json"))
    assert diff_files
    diff_payload = json.loads(diff_files[0].read_text(encoding="utf-8"))
    assert diff_payload["status"] == "blocked"
    assert "anomaly:var_cap_exceeded" in diff_payload["reason"]

    assert captured_latency["signal_id"] == "state_update_rollback"
    assert captured_latency["success"] is False
    assert captured_latency["detail"] == "no_webhook_configured"

    assert fallback_records
    _, payload, note, extra = fallback_records[0]
    assert note == "no_webhook_configured"
    assert payload.signal_id == "state_update_rollback"
    assert extra["env_var"] == "SIGNAL_WEBHOOK_URLS"


def test_update_state_blocks_when_override_disabled(tmp_path, monkeypatch, capsys):
    bars_csv = tmp_path / "bars.csv"
    bars_csv.write_text(
        """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0
2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0
""",
        encoding="utf-8",
    )

    override = tmp_path / "override.json"
    override.write_text(
        json.dumps({"status": "disabled", "reason": "maintenance"}),
        encoding="utf-8",
    )

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

    RUNNER_BEHAVIOR.update({
        "new_state": {"gamma": 1.0},
        "trade_returns": [0.01, 0.02],
        "records": [{"qty": 0.5}],
    })

    monkeypatch.setattr(update_state, "BacktestRunner", ConfigurableRunner)
    monkeypatch.setattr(update_state, "build_runner_config", lambda args: SimpleNamespace())

    exit_code = update_state.main([
        "--bars",
        str(bars_csv),
        "--symbol",
        "USDJPY",
        "--mode",
        "conservative",
        "--override-path",
        str(override),
        "--state-out",
        str(tmp_path / "state.json"),
        "--archive-dir",
        str(tmp_path / "archive"),
        "--snapshot",
        str(snapshot_path),
        "--simulate-live",
    ])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["decision"]["status"] == "blocked"
    assert result["decision"]["reasons"] == ["override_disabled"]
    assert result["rollback_triggered"] is False

    diff_files = list((tmp_path / "archive").rglob("*_diff.json"))
    assert diff_files
    diff_payload = json.loads(diff_files[0].read_text(encoding="utf-8"))
    assert diff_payload["status"] == "blocked"
    assert diff_payload["reason"] == ["override_disabled"]

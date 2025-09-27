import json
from types import SimpleNamespace

from scripts import update_state


class DummyMetrics:
    def __init__(self, count: int):
        self.count = count

    def as_dict(self) -> dict:
        return {"count": self.count}


class DummyStrategy:
    __module__ = "strategies.dummy"
    __name__ = "DummyStrategy"


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

    class DummyRunner:
        def __init__(self, equity, symbol, runner_cfg):
            self.strategy_cls = DummyStrategy
            self.metrics = DummyMetrics(0)

        def load_state_file(self, path: str) -> None:  # pragma: no cover - noop
            return None

        def run_partial(self, bars, mode="conservative"):
            for bar in bars:
                processed_timestamps.append(bar["timestamp"])
            self.metrics = DummyMetrics(len(processed_timestamps))
            return self.metrics

        def export_state(self):
            return {"last": processed_timestamps[-1] if processed_timestamps else None}

    monkeypatch.setattr(update_state, "BacktestRunner", DummyRunner)
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

    assert processed_timestamps == [
        "2024-01-01T00:10:00",
        "2024-01-01T00:15:00",
    ]

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["state_update"]["USDJPY_conservative"] == "2024-01-01T00:15:00"

    assert json.loads(state_out.read_text(encoding="utf-8"))["last"] == "2024-01-01T00:15:00"

    archive_dirs = list(archive_root.rglob("*_state.json"))
    assert archive_dirs, "archive file should be written"

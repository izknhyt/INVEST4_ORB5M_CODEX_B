import pytest

from scripts import analyze_signal_latency


def test_load_latencies_handles_z_suffix(tmp_path):
    csv_path = tmp_path / "latency.csv"
    csv_path.write_text(
        "signal_id,status,ts_emit,ts_ack,detail\n"
        "abc123,success,2024-05-01T00:00:00Z,2024-05-01T00:00:01Z,ok\n",
        encoding="utf-8",
    )

    records = analyze_signal_latency.load_latencies(csv_path)

    assert len(records) == 1
    record = records[0]
    assert record["signal_id"] == "abc123"
    assert record["status"] == "success"
    assert record["detail"] == "ok"
    assert record["latency"] == pytest.approx(1.0)

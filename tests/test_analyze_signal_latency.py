import csv
import json

import scripts.analyze_signal_latency as analyze_module


def test_analyze_flags_latency_breach():
    records = [
        {"latency": 2.0, "status": "success"},
        {"latency": 8.0, "status": "success"},
        {"latency": 9.0, "status": "success"},
    ]

    summary = analyze_module.analyze(records, latency_threshold=5.0, failure_threshold=0.5)

    assert summary["thresholds"]["p95_latency"]["breach"] is True
    assert summary["thresholds"]["failure_rate"]["breach"] is False
    assert summary["slo_breach_ratio"] == 2 / summary["latency_samples"]


def test_main_writes_structured_outputs(tmp_path):
    csv_path = tmp_path / "latency.csv"
    csv_path.write_text(
        "signal_id,ts_emit,ts_ack,status,detail\n"
        "id1,2025-01-01T00:00:00+00:00,2025-01-01T00:00:01+00:00,success,ok\n"
        "id2,2025-01-01T00:00:01+00:00,2025-01-01T00:00:02+00:00,success,ok\n",
        encoding="utf-8",
    )
    out_json = tmp_path / "summary.json"
    out_csv = tmp_path / "summary.csv"

    exit_code = analyze_module.main(
        [
            "--input",
            str(csv_path),
            "--slo-threshold",
            "5",
            "--failure-threshold",
            "0.25",
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
        ]
    )

    assert exit_code == 0

    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["latency_samples"] == 2
    assert summary["thresholds"]["p95_latency"]["breach"] is False
    assert summary["thresholds"]["failure_rate"]["breach"] is False

    with out_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["metric"] == "total"
    assert rows[5]["metric"] == "p95_latency"
    assert rows[5]["breach"] in {"False", ""}

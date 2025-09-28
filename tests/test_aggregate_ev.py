import csv
import json
import sys
from pathlib import Path

from scripts import aggregate_ev


def _write_state(path: Path, *, alpha: float, beta: float) -> None:
    payload = {
        "ev_buckets": {
            "asia:low:quiet": {
                "alpha": alpha,
                "beta": beta,
            }
        },
        "ev_global": {
            "alpha": alpha + 1.0,
            "beta": beta + 2.0,
        },
    }
    with path.open("w") as f:
        json.dump(payload, f)


def test_main_generates_profile_and_csv(tmp_path, monkeypatch):
    strategy = "day_orb_5m.DayORB5m"
    symbol = "USDJPY"
    mode = "conservative"

    archive_root = tmp_path / "ops" / "state_archive"
    target_dir = archive_root / strategy / symbol / mode
    target_dir.mkdir(parents=True)

    _write_state(target_dir / "20240101_010101_state.json", alpha=1.0, beta=2.0)
    _write_state(target_dir / "20240102_020202_state.json", alpha=3.0, beta=4.0)

    out_yaml = tmp_path / "ev_profile.yaml"
    out_csv = tmp_path / "ev_summary.csv"

    argv = [
        "aggregate_ev",
        "--archive",
        str(archive_root),
        "--strategy",
        strategy,
        "--symbol",
        symbol,
        "--mode",
        mode,
        "--out-yaml",
        str(out_yaml),
        "--out-csv",
        str(out_csv),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    returncode = aggregate_ev.main()

    assert returncode == 0
    assert out_yaml.exists()
    assert out_csv.exists()

    with out_yaml.open() as f:
        profile = json.load(f)

    assert profile["meta"]["files_total"] == 2
    assert profile["meta"]["recent_count"] == 2
    assert profile["global"]["long_term"]["observations"] == 2
    assert profile["global"]["recent"]["observations"] == 2

    bucket_entries = profile["buckets"]
    assert len(bucket_entries) == 1
    bucket = bucket_entries[0]
    assert bucket["bucket"] == {
        "session": "asia",
        "spread_band": "low",
        "rv_band": "quiet",
    }
    assert bucket["recent"]["observations"] == 2

    with out_csv.open() as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert {row["window"] for row in rows} == {"long_term", "recent"}
    assert {row["bucket"] for row in rows} == {"asia:low:quiet"}

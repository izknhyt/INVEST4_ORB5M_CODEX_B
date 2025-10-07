"""Regression tests for scripts/aggregate_ev.py CLI behavior."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import scripts.aggregate_ev as aggregate_ev
from scripts.aggregate_ev import REPO_ROOT


def write_state(path: Path, alpha: float, beta: float, *, global_alpha: float, global_beta: float) -> None:
    state = {
        "ev_buckets": {
            "asia:low:stable": {
                "alpha": alpha,
                "beta": beta,
            }
        },
        "ev_global": {
            "alpha": global_alpha,
            "beta": global_beta,
        },
    }
    with path.open("w") as f:
        json.dump(state, f)


def test_aggregate_ev_generates_outputs(tmp_path: Path) -> None:
    strategy_key = "day_orb_5m.DayORB5m"
    symbol = "USDJPY"
    mode = "conservative"

    archive_dir = tmp_path / "ops" / "state_archive" / strategy_key / symbol / mode
    archive_dir.mkdir(parents=True)

    write_state(
        archive_dir / "20240101_000000.json",
        alpha=2.0,
        beta=3.0,
        global_alpha=4.0,
        global_beta=6.0,
    )
    write_state(
        archive_dir / "20240102_000000.json",
        alpha=4.0,
        beta=5.0,
        global_alpha=4.0,
        global_beta=6.0,
    )

    out_yaml = tmp_path / "profile.yaml"
    out_csv = tmp_path / "profile.csv"

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "aggregate_ev.py"),
            "--archive",
            str(tmp_path / "ops" / "state_archive"),
            "--strategy",
            strategy_key,
            "--symbol",
            symbol,
            "--mode",
            mode,
            "--out-yaml",
            str(out_yaml),
            "--out-csv",
            str(out_csv),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Wrote YAML profile" in result.stdout

    assert out_yaml.exists()
    with out_yaml.open() as f:
        profile = json.load(f)

    assert profile["meta"]["files_total"] == 2
    assert profile["global"]["long_term"]["alpha_avg"] == 4.0
    assert profile["global"]["long_term"]["beta_avg"] == 6.0

    buckets = {entry["bucket"]["session"]: entry for entry in profile["buckets"]}
    assert "asia" in buckets
    bucket_stats = buckets["asia"]
    assert bucket_stats["long_term"]["alpha_avg"] == 3.0
    assert bucket_stats["long_term"]["beta_avg"] == 4.0
    assert bucket_stats["long_term"]["observations"] == 2
    assert bucket_stats["recent"]["observations"] == 2

    assert out_csv.exists()
    with out_csv.open() as f:
        rows = list(csv.DictReader(f))

    assert rows
    long_term_rows = [row for row in rows if row["window"] == "long_term"]
    assert long_term_rows and long_term_rows[0]["bucket"] == "asia:low:stable"


def test_aggregate_ev_supports_archive_namespace(tmp_path: Path) -> None:
    strategy_key = "strategies.mean_reversion.MeanReversionStrategy"
    symbol = "USDJPY"
    mode = "conservative"

    archive_base = tmp_path / "state_archive"
    namespace = Path("strategies.mean_reversion.MeanReversionStrategy") / symbol / mode
    archive_dir = archive_base / namespace
    archive_dir.mkdir(parents=True)

    write_state(
        archive_dir / "20240101_000000.json",
        alpha=1.0,
        beta=2.0,
        global_alpha=3.0,
        global_beta=4.0,
    )

    out_yaml = tmp_path / "manifest_profile.yaml"

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "aggregate_ev.py"),
            "--archive",
            str(archive_base),
            "--archive-namespace",
            str(namespace),
            "--strategy",
            strategy_key,
            "--symbol",
            symbol,
            "--mode",
            mode,
            "--out-yaml",
            str(out_yaml),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Wrote YAML profile" in result.stdout
    assert out_yaml.exists()


def test_default_output_uses_module_tail(tmp_path: Path, monkeypatch, capsys) -> None:
    archive_base = tmp_path / "ops" / "state_archive"
    strategy = "strategies.mean_reversion.MeanReversionStrategy"
    symbol = "USDJPY"
    mode = "conservative"

    archive_dir = archive_base / strategy / symbol / mode
    archive_dir.mkdir(parents=True)
    write_state(
        archive_dir / "20240101_000000.json",
        alpha=1.0,
        beta=1.0,
        global_alpha=2.0,
        global_beta=2.0,
    )

    monkeypatch.setattr(aggregate_ev, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "aggregate_ev.py",
            "--archive",
            str(archive_base),
            "--strategy",
            strategy,
            "--symbol",
            symbol,
            "--mode",
            mode,
        ],
    )

    assert aggregate_ev.main() == 0
    captured = capsys.readouterr()
    default_profile = tmp_path / "configs" / "ev_profiles" / "mean_reversion.yaml"
    assert default_profile.exists()
    assert "mean_reversion.yaml" in captured.out

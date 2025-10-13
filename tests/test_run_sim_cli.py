import csv
import json
import shutil
import textwrap
import uuid
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

import pytest

import scripts.run_sim as run_sim

from scripts.run_sim import (
    CSVFormatError,
    CSVLoaderStats,
    ROOT_PATH,
    load_bars_csv,
    main as run_sim_main,
    _write_daily_csv,
)


CSV_CONTENT = """timestamp,symbol,tf,o,h,l,c,v,spread,zscore
2024-01-01T08:00:00Z,USDJPY,5m,150.00,150.10,149.90,150.02,0,0.02,0.0
2024-01-01T08:05:00Z,USDJPY,5m,150.01,150.11,149.91,150.03,0,0.02,0.3
2024-01-01T08:10:00Z,USDJPY,5m,150.02,150.12,149.92,150.04,0,0.02,0.8
2024-01-01T08:15:00Z,USDJPY,5m,150.03,150.13,149.93,150.05,0,0.02,-0.7
2024-01-01T08:20:00Z,USDJPY,5m,150.04,150.14,149.94,150.06,0,0.02,0.6
"""


CSV_MULTI_SYMBOL = """timestamp,symbol,tf,o,h,l,c,v,spread,zscore
2024-01-01T08:00:00Z,USDJPY,5m,150.00,150.10,149.90,150.02,0,0.02,0.0
2024-01-01T08:05:00Z,USDJPY,5m,150.01,150.11,149.91,150.03,0,0.02,0.3
2024-01-01T09:00:00Z,EURUSD,15m,1.1000,1.1010,1.0990,1.1005,0,0.02,0.1
2024-01-01T09:15:00Z,EURUSD,15m,1.1006,1.1016,1.0996,1.1008,0,0.02,0.2
"""


CSV_OHLC_ONLY = textwrap.dedent(
    """\
    timestamp,open,high,low,close
    2024-01-01T10:00:00Z,150.10,150.20,150.00,150.12
    2024-01-01T10:05:00Z,150.11,150.21,150.01,150.13
    2024-01-01T10:10:00Z,150.12,150.22,150.02,150.14
    """
)


MANIFEST_TEMPLATE = textwrap.dedent(
    """\
    meta:
      id: test_mean_reversion
      name: Test Mean Reversion
      version: "1.0"
      category: day
    strategy:
      class_path: strategies.mean_reversion.MeanReversionStrategy
      instruments:
        - symbol: USDJPY
          timeframe: 5m
          mode: conservative
      parameters:
        or_n: 2
        cooldown_bars: 1
        zscore_threshold: 1.0
        tp_atr_mult: 0.8
        sl_atr_mult: 1.0
        trail_atr_mult: 0.0
        min_tp_pips: 4.0
        min_sl_pips: 8.0
        sl_over_tp: 1.1
        allow_high_rv: true
        allow_mid_rv: true
        allow_low_rv: true
        max_adx: 28.0
        zscore_relief_scale: 1.2
        zscore_penalty_scale: 1.0
        ev_profile_obs_norm: 25.0
    router:
      allowed_sessions: [LDN, NY]
    risk:
      risk_per_trade_pct: 0.1
      max_daily_dd_pct: 8.0
      notional_cap: 500000
      max_concurrent_positions: 1
      warmup_trades: 0
    features:
      required: [zscore, rv_band]
      optional: [atr14, adx14]
    runner:
      runner_config:
        threshold_lcb_pip: 0.0
        min_or_atr_ratio: 0.0
        allowed_sessions: [LDN, NY]
        allow_low_rv: true
        spread_bands:
          narrow: 3.0
          normal: 5.0
          wide: 99.0
        warmup_trades: 0
      cli_args:
        equity: 100000
        auto_state: false
        aggregate_ev: false
    state: {}
    """
)


def _write_manifest(
    tmpdir: Path,
    *,
    auto_state: bool = False,
    aggregate_ev: bool = False,
    mode: str = "conservative",
) -> Path:
    manifest = MANIFEST_TEMPLATE
    manifest = manifest.replace("mode: conservative", f"mode: {mode}")
    manifest = manifest.replace(
        "auto_state: false", f"auto_state: {'true' if auto_state else 'false'}"
    )
    manifest = manifest.replace(
        "aggregate_ev: false", f"aggregate_ev: {'true' if aggregate_ev else 'false'}"
    )
    path = tmpdir / "manifest.yaml"
    path.write_text(manifest, encoding="utf-8")
    return path


def _write_multi_instrument_manifest(tmpdir: Path) -> Path:
    manifest = MANIFEST_TEMPLATE.replace(
        "  instruments:\n    - symbol: USDJPY\n      timeframe: 5m\n      mode: conservative",
        "  instruments:\n"
        "    - symbol: USDJPY\n"
        "      timeframe: 5m\n"
        "      mode: conservative\n"
        "    - symbol: EURUSD\n"
        "      timeframe: 15m\n"
        "      mode: bridge",
    )
    path = tmpdir / "manifest_multi.yaml"
    path.write_text(manifest, encoding="utf-8")
    return path


def test_load_bars_csv_tolerates_blank_volume_and_spread(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2024-01-01T09:00:00Z,USDJPY,5m,150.10,150.20,150.00,150.12,,\n"
        "2024-01-01T09:05:00Z,USDJPY,5m,150.11,150.21,150.01,150.13,0.0,0.01\n",
        encoding="utf-8",
    )

    bars = list(
        load_bars_csv(
            str(csv_path),
            symbol="USDJPY",
            default_symbol="USDJPY",
            default_tf="5m",
        )
    )

    assert len(bars) == 2
    assert bars[0]["v"] == 0.0
    assert bars[0]["spread"] == 0.0
    assert bars[1]["spread"] == 0.01


def test_load_bars_csv_normalizes_timeframe(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2024-01-01T09:00:00Z,USDJPY,5M,150.10,150.20,150.00,150.12,0,0.01\n"
        "2024-01-01T09:05:00Z,USDJPY,,150.11,150.21,150.01,150.13,0,0.02\n",
        encoding="utf-8",
    )

    bars = list(
        load_bars_csv(
            str(csv_path),
            symbol="USDJPY",
            default_symbol="USDJPY",
            default_tf="5M",
        )
    )

    assert [bar["tf"] for bar in bars] == ["5m", "5m"]


def test_load_bars_csv_collects_skip_stats(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2024-01-01T09:00:00Z,USDJPY,5m,150.10,150.20,150.00,bad,0,0.01\n"
        "2024-01-01T09:05:00Z,USDJPY,5m,150.11,150.21,150.01,150.13,0,0.02\n",
        encoding="utf-8",
    )

    stats = CSVLoaderStats()
    iterator = load_bars_csv(
        str(csv_path),
        symbol="USDJPY",
        default_symbol="USDJPY",
        default_tf="5m",
        stats=stats,
    )
    bars = list(iterator)

    assert len(bars) == 1
    assert stats.skipped_rows == 1
    assert stats.last_error_code == "price_parse_error"
    assert stats.reason_counts["price_parse_error"] == 1
    assert stats.last_row is not None
    assert stats.last_row["line"] == 2
    assert stats.last_row["row"]["c"] == "bad"
    assert iterator.stats.skipped_rows == 1


def test_load_bars_csv_strict_raises_on_skip(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2024-01-01T09:00:00Z,USDJPY,5m,150.10,150.20,150.00,bad,0,0.01\n"
        "2024-01-01T09:05:00Z,USDJPY,5m,150.11,150.21,150.01,150.13,0,0.02\n",
        encoding="utf-8",
    )

    iterator = load_bars_csv(
        str(csv_path),
        symbol="USDJPY",
        default_symbol="USDJPY",
        default_tf="5m",
        strict=True,
    )

    with pytest.raises(CSVFormatError) as exc:
        list(iterator)

    assert exc.value.code == "rows_skipped"
    assert exc.value.details is not None
    assert "last_error=price_parse_error" in exc.value.details
    assert iterator.stats.skipped_rows == 1


def test_load_bars_csv_requires_symbol_when_missing(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_OHLC_ONLY, encoding="utf-8")

    iterator = load_bars_csv(str(csv_path))

    with pytest.raises(CSVFormatError) as exc:
        next(iterator)

    assert exc.value.code == "symbol_required"


def test_load_bars_csv_supports_headerless_validated_snapshot(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "2024-01-01T09:00:00Z,USDJPY,5m,150.10,150.20,150.00,150.12,0,0.01\n"
        "2024-01-01T09:05:00Z,USDJPY,5m,150.11,150.21,150.01,150.13,0,0.02\n",
        encoding="utf-8",
    )

    iterator = load_bars_csv(
        str(csv_path),
        symbol="USDJPY",
        default_symbol="USDJPY",
        default_tf="5m",
    )
    bars = list(iterator)

    assert [bar["timestamp"] for bar in bars] == [
        "2024-01-01T09:00:00Z",
        "2024-01-01T09:05:00Z",
    ]
    assert bars[0]["o"] == 150.10
    assert bars[1]["c"] == 150.13
    assert iterator.stats.skipped_rows == 0


def test_run_sim_with_manifest(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    json_out = tmp_path / "metrics.json"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--json-out",
            str(json_out),
        ]
    )

    assert rc == 0
    assert json_out.exists()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert "trades" in data
    assert data["symbol"] == "USDJPY"
    assert data["mode"] == "conservative"
    assert data["debug"]["csv_loader"]["skipped_rows"] == 0


def test_run_sim_accepts_out_json_alias(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    json_out = tmp_path / "alias_metrics.json"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-json",
            str(json_out),
        ]
    )

    assert rc == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["symbol"] == "USDJPY"
    assert payload["mode"] == "conservative"


def test_run_sim_manifest_uppercase_mode(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, mode="ConSeRvAtIvE")
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    json_out = tmp_path / "uppercase_metrics.json"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--json-out",
            str(json_out),
        ]
    )

    assert rc == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["mode"] == "conservative"


def test_run_sim_writes_daily_csv(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    json_out = tmp_path / "metrics.json"
    daily_out = tmp_path / "daily.csv"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--json-out",
            str(json_out),
            "--out-daily-csv",
            str(daily_out),
        ]
    )

    assert rc == 0
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data.get("dump_daily") == str(daily_out)
    with daily_out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows
    first_row = rows[0]
    assert first_row["date"] == "2024-01-01"
    assert "pnl_pips" in first_row


def test_write_daily_csv_preserves_fractional_wins(tmp_path: Path) -> None:
    daily = {
        "2024-01-02": {
            "breakouts": 1,
            "gate_pass": 1,
            "gate_block": 0,
            "ev_pass": 0,
            "ev_reject": 0,
            "fills": 1,
            "wins": 0.625,
            "pnl_pips": 1.5,
        }
    }
    daily_path = tmp_path / "daily.csv"
    _write_daily_csv(daily_path, daily)

    with daily_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows
    row = rows[0]
    assert row["date"] == "2024-01-02"
    assert pytest.approx(float(row["wins"]), rel=0, abs=1e-9) == 0.625


def test_run_sim_respects_time_window(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    json_out = tmp_path / "metrics.json"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--json-out",
            str(json_out),
            "--start-ts",
            "2024-01-01T08:05:00Z",
            "--end-ts",
            "2024-01-01T08:15:00Z",
        ]
    )

    assert rc == 0
    data = json.loads(json_out.read_text(encoding="utf-8"))
    # Expect a subset of bars was processed, so runtime metadata exists
    assert data["symbol"] == "USDJPY"
    assert data.get("manifest_id") == "test_mean_reversion"
    assert data["debug"]["csv_loader"]["skipped_rows"] == 0


def test_run_sim_can_select_non_default_instrument(tmp_path: Path) -> None:
    manifest_path = _write_multi_instrument_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_MULTI_SYMBOL, encoding="utf-8")
    json_out = tmp_path / "metrics.json"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--json-out",
            str(json_out),
            "--symbol",
            "EURUSD",
            "--mode",
            "bridge",
        ]
    )

    assert rc == 0
    assert json_out.exists()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["symbol"] == "EURUSD"
    assert data["mode"] == "bridge"
    assert data["debug"]["csv_loader"]["skipped_rows"] == 0


def test_run_sim_warns_when_rows_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2024-01-01T08:00:00Z,USDJPY,5m,150.00,150.10,149.90,not_a_number,0,0.02\n"
        "2024-01-01T08:05:00Z,USDJPY,5m,150.01,150.11,149.91,150.03,0,0.02\n",
        encoding="utf-8",
    )
    json_out = tmp_path / "metrics.json"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--json-out",
            str(json_out),
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "Skipped 1 CSV row" in captured.err
    data = json.loads(json_out.read_text(encoding="utf-8"))
    loader_debug = data["debug"]["csv_loader"]
    assert loader_debug["skipped_rows"] == 1
    assert loader_debug["last_error_code"] == "price_parse_error"


def test_run_sim_strict_raises_on_skips(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2024-01-01T08:00:00Z,USDJPY,5m,150.00,150.10,149.90,not_a_number,0,0.02\n"
        "2024-01-01T08:05:00Z,USDJPY,5m,150.01,150.11,149.91,150.03,0,0.02\n",
        encoding="utf-8",
    )

    with pytest.raises(CSVFormatError) as excinfo:
        run_sim_main(
            [
                "--manifest",
                str(manifest_path),
                "--csv",
                str(csv_path),
                "--strict",
            ]
        )

    assert excinfo.value.code == "rows_skipped"
    assert excinfo.value.details is not None
    assert "skipped=1" in excinfo.value.details


def test_run_sim_creates_run_directory(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    run_dirs = list(out_dir.iterdir())
    assert len(run_dirs) == 1
    run_path = run_dirs[0]
    metrics_path = run_path / "metrics.json"
    params_path = run_path / "params.json"
    assert metrics_path.exists()
    assert params_path.exists()
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics.get("run_dir") == str(run_path)
    assert metrics.get("dump_daily") == str(run_path / "daily.csv")
    assert metrics.get("session_log") == str(run_path / "session.log")
    assert (run_path / "daily.csv").exists()
    session_log_path = run_path / "session.log"
    assert session_log_path.exists()
    session_log = json.loads(session_log_path.read_text(encoding="utf-8"))
    assert session_log["exit_code"] == 0
    assert session_log["paths"]["run_dir"] == str(run_path)
    assert session_log["warnings"] == []
    assert session_log["stdout"] is not None
    assert session_log["command"] == [
        "scripts/run_sim.py",
        "--manifest",
        str(manifest_path),
        "--csv",
        str(csv_path),
        "--out-dir",
        str(out_dir),
    ]


def test_run_sim_cli_can_disable_auto_state(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, auto_state=True)
    state_dir = tmp_path / "state_archive"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_text = manifest_text.replace(
        "        aggregate_ev: false",
        f"        aggregate_ev: false\n        state_archive: {state_dir}",
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    run_dirs = sorted(out_dir.iterdir())
    assert run_dirs
    run_path = run_dirs[0]
    assert (run_path / "state.json").exists()

    shutil.rmtree(out_dir)
    if state_dir.exists():
        shutil.rmtree(state_dir)

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
            "--no-auto-state",
        ]
    )

    assert rc == 0
    run_dirs = sorted(out_dir.iterdir())
    assert run_dirs
    run_path = run_dirs[0]
    assert not (run_path / "state.json").exists()
    metrics = json.loads((run_path / "metrics.json").read_text(encoding="utf-8"))
    assert "loaded_state" not in metrics


def test_run_sim_cli_handles_string_bool_flags(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, auto_state=True, aggregate_ev=True)
    state_dir = tmp_path / "state_archive"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_text = manifest_text.replace(
        "    auto_state: true",
        '    auto_state: "false"',
    )
    manifest_text = manifest_text.replace(
        "    aggregate_ev: true",
        f'    aggregate_ev: "false"\n    state_archive: {state_dir}',
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    run_dirs = sorted(out_dir.iterdir())
    assert run_dirs
    run_path = run_dirs[0]
    assert not (run_path / "state.json").exists()
    assert not state_dir.exists()
    metrics = json.loads((run_path / "metrics.json").read_text(encoding="utf-8"))
    assert "loaded_state" not in metrics
    params = json.loads((run_path / "params.json").read_text(encoding="utf-8"))
    assert params.get("auto_state") is False
    assert params.get("aggregate_ev") is False


def test_run_sim_cli_omits_loaded_state_on_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest(tmp_path, auto_state=True)
    state_dir = tmp_path / "state_archive"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_text = manifest_text.replace(
        "        aggregate_ev: false",
        f"        aggregate_ev: false\n        state_archive: {state_dir}",
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")

    state_dir.mkdir(parents=True, exist_ok=True)
    mismatched_state = state_dir / "20250101_000000.json"
    mismatched_state.write_text(
        json.dumps(
            {
                "meta": {
                    "config_fingerprint": "legacy-fingerprint",
                    "last_timestamp": "2024-01-01T07:55:00Z",
                },
                "metrics": {"trades": 10, "wins": 5, "total_pips": 12.3},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.run_sim._resolve_state_archive", lambda config: state_dir)
    monkeypatch.setattr(
        "scripts.run_sim._latest_state_file", lambda path: mismatched_state
    )

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    run_dirs = sorted(out_dir.iterdir())
    assert run_dirs
    run_path = run_dirs[0]
    metrics = json.loads((run_path / "metrics.json").read_text(encoding="utf-8"))
    assert "loaded_state" not in metrics
    warnings = metrics.get("debug", {}).get("warnings", [])
    assert any("config_fingerprint mismatch" in msg for msg in warnings)


def test_run_sim_timestamps_use_aware_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest(tmp_path, auto_state=True)
    state_dir = tmp_path / "state_archive"

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    frozen_now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    call_count = 0

    def _fake_utcnow_aware(*, dt_cls=None):  # type: ignore[override]
        nonlocal call_count
        call_count += 1
        return frozen_now

    monkeypatch.setattr("scripts.run_sim.utcnow_aware", _fake_utcnow_aware)
    monkeypatch.setattr("scripts.run_sim._resolve_state_archive", lambda config: state_dir)
    monkeypatch.setattr("scripts.run_sim._latest_state_file", lambda path: None)

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    # `_write_run_outputs` and the auto-state block should both rely on the helper.
    assert call_count >= 2

    run_dirs = sorted(out_dir.iterdir())
    assert run_dirs
    run_path = run_dirs[0]
    expected_suffix = frozen_now.strftime("%Y%m%d_%H%M%S")
    assert run_path.name.endswith(expected_suffix)

    state_files = sorted(state_dir.glob("*.json"))
    assert state_files
    for state_file in state_files:
        assert state_file.stem == expected_suffix


def test_run_sim_uses_custom_archive_namespace_with_custom_root(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, auto_state=True)
    custom_root = tmp_path / "custom_state_archive"
    namespace = "custom/strategy/ns"

    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_text = manifest_text.replace(
        "    aggregate_ev: false",
        f"    aggregate_ev: false\n    state_archive: {custom_root}",
    )
    manifest_text = manifest_text.replace(
        "state: {}",
        f"state:\n  archive_namespace: {namespace}",
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    archive_dir = custom_root / Path(namespace)
    assert archive_dir.exists() and archive_dir.is_dir()
    state_files = sorted(archive_dir.glob("*.json"))
    assert state_files, "expected state file in custom archive namespace"

    run_dirs = sorted(out_dir.iterdir())
    assert run_dirs
    run_path = run_dirs[0]
    assert (run_path / "state.json").exists()


def test_run_sim_relative_out_dir_resolves_to_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    relative_base = Path("tmp_run_sim") / f"cli_{uuid.uuid4().hex}"
    resolved_base = (ROOT_PATH / relative_base).resolve()

    if resolved_base.exists():
        shutil.rmtree(resolved_base)

    monkeypatch.chdir(tmp_path)

    try:
        rc = run_sim_main(
            [
                "--manifest",
                str(manifest_path),
                "--csv",
                str(csv_path),
                "--out-dir",
                str(relative_base),
            ]
        )

        assert rc == 0
        run_dirs = list(resolved_base.iterdir())
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]
        run_dir_resolved = run_dir.resolve()
        root_resolved = ROOT_PATH.resolve()
        assert run_dir_resolved.is_dir()
        assert run_dir.parent == resolved_base
        assert run_dir_resolved == root_resolved or root_resolved in run_dir_resolved.parents
    finally:
        shutil.rmtree(resolved_base, ignore_errors=True)


def test_run_sim_relative_json_out_resolves_to_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest(tmp_path)
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    json_relative = Path("runs") / f"cli_{uuid.uuid4().hex}.json"
    json_expected = ROOT_PATH / json_relative

    if json_expected.exists():
        json_expected.unlink()

    monkeypatch.chdir(tmp_path)

    try:
        rc = run_sim_main(
            [
                "--manifest",
                str(manifest_path),
                "--csv",
                str(csv_path),
                "--json-out",
                str(json_relative),
            ]
        )

        assert rc == 0
        assert json_expected.exists()
        assert json_expected.parent == ROOT_PATH / "runs"
        data = json.loads(json_expected.read_text(encoding="utf-8"))
        assert data.get("symbol") == "USDJPY"
    finally:
        if json_expected.exists():
            json_expected.unlink()


def test_run_sim_reports_aggregate_ev_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _write_manifest(
        tmp_path, auto_state=True, aggregate_ev=True
    )
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    json_out = tmp_path / "metrics.json"

    captured_kwargs: dict[str, Any] = {}

    class DummyResult:
        def __init__(self) -> None:
            self.returncode = 2
            self.stdout = "aggregate stdout\n"
            self.stderr = "aggregate stderr\n"

    def fake_run(cmd: list[str], **kwargs: Any) -> DummyResult:
        captured_kwargs["cmd"] = cmd
        captured_kwargs["kwargs"] = kwargs
        return DummyResult()

    monkeypatch.setattr("scripts.run_sim.subprocess.run", fake_run)

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--json-out",
            str(json_out),
        ]
    )

    assert rc == 1
    assert json_out.exists()

    captured = capsys.readouterr()
    assert "aggregate_ev stdout" in captured.err
    assert "aggregate stdout" in captured.err
    assert "aggregate_ev stderr" in captured.err
    assert "aggregate stderr" in captured.err
    assert "Failed to aggregate EV" in captured.err

    assert captured_kwargs["kwargs"]["capture_output"] is True
    assert captured_kwargs["kwargs"]["text"] is True
    cmd = captured_kwargs["cmd"]
    assert "--archive" in cmd
    archive_index = cmd.index("--archive")
    assert cmd[archive_index + 1] == str(ROOT_PATH / "ops" / "state_archive")
    assert "--archive-namespace" not in cmd
    assert "--strategy" in cmd
    strategy_index = cmd.index("--strategy")
    assert (
        cmd[strategy_index + 1] == "mean_reversion.MeanReversionStrategy"
    )


def test_run_sim_session_log_records_aggregate_ev_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest(tmp_path, auto_state=True, aggregate_ev=True)
    state_dir = tmp_path / "state_archive"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_text = manifest_text.replace(
        "        aggregate_ev: true",
        f"        aggregate_ev: true\n        state_archive: {state_dir}",
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    def _failing_aggregate_ev(_namespace_path: Path, _config: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(run_sim, "_aggregate_ev", _failing_aggregate_ev)

    rc = run_sim_main(
        [
            "--manifest",
            str(manifest_path),
            "--csv",
            str(csv_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    run_dirs = sorted(out_dir.iterdir())
    assert run_dirs
    run_path = run_dirs[0]
    session_log_path = run_path / "session.log"
    assert session_log_path.exists()
    session_log = json.loads(session_log_path.read_text(encoding="utf-8"))
    assert session_log["exit_code"] == 1
    assert any("Failed to aggregate EV: boom" in entry for entry in session_log["warnings"])
    assert session_log["paths"]["state_saved"] is not None

#!/usr/bin/env python3
"""Minimal simulation CLI (manifest-first).

The tool now keeps the command-line surface tiny on purpose:

```
python3 scripts/run_sim.py \
    --manifest configs/strategies/day_orb_5m.yaml \
    --csv validated/USDJPY/5m.csv \
    --json-out runs/latest_metrics.json \
    --start-ts 2025-01-01T00:00:00Z --end-ts 2025-01-31T23:55:00Z
```

All other behaviour (state load/save, EV profile, fill/EV overrides) is driven
via the manifest `runner.cli_args` block so that we no longer need dozens of
flags. See the docs for the expected keys.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence

import os
import sys

# Ensure project root is on sys.path when running as a script
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_PATH = Path(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from configs.strategies.loader import StrategyManifest, load_manifest
from core.fill_engine import SameBarPolicy
from core.runner import BacktestRunner, RunnerConfig
from core.runner_execution import RunnerExecutionManager
from core.runner_lifecycle import RunnerLifecycleManager
from core.router_pipeline import PortfolioTelemetry, build_portfolio_state
from core.utils import yaml_compat as yaml
from router.router_v1 import select_candidates


class CSVFormatError(Exception):
    """Raised when the input CSV lacks required fields or context."""

    def __init__(self, code: str, *, details: Optional[str] = None) -> None:
        self.code = code
        self.details = details
        message = code if details is None else f"{code}: {details}"
        super().__init__(message)


@dataclass
class CSVLoaderStats:
    """Lightweight diagnostics collected while ingesting CSV rows."""

    skipped_rows: int = 0
    last_error_code: Optional[str] = None
    last_row: Optional[Dict[str, Any]] = None
    reason_counts: Dict[str, int] = field(default_factory=dict)

    def record_skip(self, code: str, row: Optional[Dict[str, Any]] = None) -> None:
        self.skipped_rows += 1
        self.last_error_code = code
        if row is not None:
            try:
                self.last_row = dict(row)
            except Exception:
                self.last_row = {"__repr__": repr(row)}
        self.reason_counts[code] = self.reason_counts.get(code, 0) + 1

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"skipped_rows": self.skipped_rows}
        if self.last_error_code is not None:
            data["last_error_code"] = self.last_error_code
        if self.last_row is not None:
            data["last_row"] = self.last_row
        if self.reason_counts:
            data["reason_counts"] = dict(self.reason_counts)
        return data


CSV_COLUMN_ALIASES: Dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "datetime", "date"),
    "symbol": ("symbol", "sym", "ticker", "instrument"),
    "tf": ("tf", "timeframe", "interval", "period"),
    "o": ("o", "open", "open_price"),
    "h": ("h", "high", "high_price"),
    "l": ("l", "low", "low_price"),
    "c": ("c", "close", "close_price"),
    "v": ("v", "volume", "vol", "qty"),
    "spread": ("spread", "spr", "spread_pips"),
}

_HEADERLESS_FALLBACK_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "tf",
    "o",
    "h",
    "l",
    "c",
    "v",
    "spread",
)
_HEADERLESS_RESTKEY = "__headerless_extra__"
_REQUIRED_CANONICAL_COLUMNS: tuple[str, ...] = ("timestamp", "o", "h", "l", "c")
_KNOWN_HEADER_TOKENS: set[str] = {
    alias
    for canonical, aliases in CSV_COLUMN_ALIASES.items()
    for alias in (canonical, *aliases)
}


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return ROOT_PATH / path


def _strategy_state_key(strategy_cls: type) -> str:
    module = getattr(strategy_cls, "__module__", "strategy") or "strategy"
    if module.startswith("strategies."):
        module = module.split(".", 1)[1]
    name = getattr(strategy_cls, "__name__", "Strategy")
    return f"{module}.{name}"


def _latest_state_file(path: Path) -> Optional[Path]:
    if not path.exists() or not path.is_dir():
        return None
    candidates = sorted(p for p in path.glob("*.json") if p.is_file())
    return candidates[-1] if candidates else None


def _parse_iso8601(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _iso8601_arg(value: str) -> datetime:
    try:
        return _normalize_datetime(_parse_iso8601(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO8601 timestamp: {value}") from exc


def _float_or_zero(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        if not value.strip():
            return 0.0
        value = value.strip()
    return float(value)


def load_bars_csv(
    path: str,
    *,
    symbol: Optional[str] = None,
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
    default_symbol: Optional[str] = None,
    default_tf: str = "5m",
    strict: bool = False,
    stats: Optional[CSVLoaderStats] = None,
) -> Iterator[Dict[str, Any]]:
    import csv  # Local import to avoid polluting module namespace unnecessarily

    loader_stats = stats or CSVLoaderStats()

    def _format_strict_details(
        reason: str, context: Optional[Dict[str, Any]]
    ) -> str:
        parts = [f"skipped={loader_stats.skipped_rows}", f"last_error={reason}"]
        if isinstance(context, dict):
            line = context.get("line")
            if line is not None:
                parts.append(f"line={line}")
        return ", ".join(parts)

    def _record_skip(reason: str, context: Optional[Dict[str, Any]] = None) -> None:
        loader_stats.record_skip(reason, context)
        if strict:
            raise CSVFormatError(
                "rows_skipped",
                details=_format_strict_details(reason, context),
            )

    def _normalize_header_token(value: Optional[str]) -> str:
        return str(value or "").strip().lower()

    def _looks_like_headerless(fieldnames: Optional[Sequence[str]]) -> bool:
        if not fieldnames:
            return False
        normalized = [_normalize_header_token(name) for name in fieldnames]
        recognized = sum(1 for token in normalized if token in _KNOWN_HEADER_TOKENS)
        if recognized >= len(_REQUIRED_CANONICAL_COLUMNS):
            return False
        data_like = any(
            any(ch.isdigit() for ch in token)
            or ("t" in token and "-" in token)
            or "." in token
            for token in normalized
        )
        return data_like

    def _row_matches_header_tokens(row: Dict[str, Any]) -> bool:
        for column in _HEADERLESS_FALLBACK_COLUMNS:
            value = row.get(column)
            if value is None:
                return False
            if _normalize_header_token(value) != column:
                return False
        return True

    def _iter() -> Iterator[Dict[str, Any]]:
        default_tf_normalized = (
            str(default_tf).strip().lower() if default_tf is not None else ""
        )
        if not default_tf_normalized:
            default_tf_normalized = "5m"
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise CSVFormatError("header_missing")

            header_lookup = {
                _normalize_header_token(name): name
                for name in reader.fieldnames
                if name is not None
            }
            alias_map: Dict[str, str] = {}
            for canonical, aliases in CSV_COLUMN_ALIASES.items():
                for alias in aliases:
                    actual = header_lookup.get(alias)
                    if actual:
                        alias_map[canonical] = actual
                        break

            missing_required = [
                key for key in _REQUIRED_CANONICAL_COLUMNS if key not in alias_map
            ]
            headerless_mode = False
            if missing_required:
                if _looks_like_headerless(reader.fieldnames or []):
                    headerless_mode = True
                    f.seek(0)
                    reader = csv.DictReader(
                        f,
                        fieldnames=list(_HEADERLESS_FALLBACK_COLUMNS),
                        restkey=_HEADERLESS_RESTKEY,
                    )
                    alias_map = {
                        column: column for column in _HEADERLESS_FALLBACK_COLUMNS
                    }
                    missing_required = [
                        key
                        for key in _REQUIRED_CANONICAL_COLUMNS
                        if key not in alias_map
                    ]
                if missing_required:
                    raise CSVFormatError(
                        "missing_required_columns",
                        details=",".join(missing_required),
                    )

            used_columns = set(alias_map.values())
            symbol_key = alias_map.get("symbol")
            tf_key = alias_map.get("tf")
            volume_key = alias_map.get("v")
            spread_key = alias_map.get("spread")

            for row in reader:
                row_copy = dict(row)
                extra_values = None
                if headerless_mode:
                    extra_values = row_copy.pop(_HEADERLESS_RESTKEY, None)
                context = {"line": reader.line_num, "row": dict(row_copy)}

                if headerless_mode and reader.line_num == 1 and _row_matches_header_tokens(row_copy):
                    continue

                ts_raw = row_copy.get(alias_map["timestamp"])
                if ts_raw in (None, ""):
                    _record_skip("timestamp_missing", context)
                    continue

                try:
                    open_px = float(row_copy[alias_map["o"]])
                    high_px = float(row_copy[alias_map["h"]])
                    low_px = float(row_copy[alias_map["l"]])
                    close_px = float(row_copy[alias_map["c"]])
                except (TypeError, ValueError):
                    _record_skip("price_parse_error", context)
                    continue

                row_symbol: Optional[str]
                if symbol_key:
                    raw_symbol = row_copy.get(symbol_key)
                    row_symbol = str(raw_symbol).strip() if raw_symbol is not None else None
                else:
                    row_symbol = default_symbol.strip() if isinstance(default_symbol, str) else default_symbol
                if not row_symbol:
                    raise CSVFormatError(
                        "symbol_required",
                        details="Provide --csv together with --manifest that supplies symbol info.",
                    )

                row_tf: str
                if tf_key and row_copy.get(tf_key):
                    raw_tf = str(row_copy[tf_key]).strip()
                    row_tf = raw_tf.lower() if raw_tf else default_tf_normalized
                else:
                    row_tf = default_tf_normalized
                if symbol and row_symbol != symbol:
                    continue

                ts_filter_required = start_ts is not None or end_ts is not None
                if ts_filter_required:
                    try:
                        bar_dt = _normalize_datetime(_parse_iso8601(str(ts_raw)))
                    except ValueError:
                        _record_skip("timestamp_parse_error", context)
                        continue
                    if start_ts and bar_dt < start_ts:
                        continue
                    if end_ts and bar_dt > end_ts:
                        continue

                bar: Dict[str, Any] = {
                    "timestamp": ts_raw,
                    "symbol": row_symbol,
                    "tf": row_tf,
                    "o": open_px,
                    "h": high_px,
                    "l": low_px,
                    "c": close_px,
                    "v": _float_or_zero(row_copy.get(volume_key, 0.0) if volume_key else 0.0),
                    "spread": _float_or_zero(row_copy.get(spread_key, 0.0) if spread_key else 0.0),
                }

                for key, value in row_copy.items():
                    if key in used_columns:
                        continue
                    if value in (None, ""):
                        continue
                    try:
                        bar[key] = float(value)
                    except ValueError:
                        bar[key] = value

                if extra_values:
                    for index, value in enumerate(extra_values):
                        if value in (None, ""):
                            continue
                        key = f"extra_{index}"
                        try:
                            bar[key] = float(value)
                        except ValueError:
                            bar[key] = value

                yield bar

    class _CSVBarIterator(Iterator[Dict[str, Any]]):
        def __init__(self, generator: Iterator[Dict[str, Any]], stats_obj: CSVLoaderStats) -> None:
            self._generator = generator
            self.stats = stats_obj

        def __iter__(self) -> "_CSVBarIterator":
            return self

        def __next__(self) -> Dict[str, Any]:
            return next(self._generator)

    return _CSVBarIterator(_iter(), loader_stats)

@dataclass
class RuntimeConfig:
    manifest: StrategyManifest
    manifest_path: Path
    csv_path: Path
    json_out: Optional[Path]
    daily_csv_out: Optional[Path]
    equity: float
    start_ts: Optional[datetime]
    end_ts: Optional[datetime]
    out_dir: Optional[Path]
    auto_state: bool
    aggregate_ev: bool
    strict: bool
    state_archive_root: Path
    ev_profile_path: Optional[Path]
    use_ev_profile: bool
    symbol: str
    timeframe: str
    mode: str
    runner_config: RunnerConfig
    strategy_cls: type
    run_base_dir: Optional[Path]


def _load_strategy_class(class_path: str) -> type:
    module_name, _, cls_name = class_path.rpartition(".")
    if not module_name:
        raise ValueError(f"Invalid strategy class path: {class_path}")
    module = __import__(module_name, fromlist=[cls_name])
    return getattr(module, cls_name)


def _runner_config_from_manifest(manifest: StrategyManifest) -> RunnerConfig:
    rcfg = RunnerConfig()
    rcfg.merge_strategy_params(manifest.strategy.parameters, replace=True)
    overrides = manifest.runner.runner_config
    for key, value in overrides.items():
        try:
            setattr(rcfg, key, value)
        except AttributeError:
            continue
    tf_values: list[str] = []
    for instrument in manifest.strategy.instruments:
        tf_value = str(getattr(instrument, "timeframe", "")).strip().lower()
        if tf_value and tf_value not in tf_values:
            tf_values.append(tf_value)
    if tf_values:
        rcfg.allowed_timeframes = tuple(tf_values)
    router_sessions = tuple(
        str(s).strip().upper()
        for s in manifest.router.allowed_sessions
        if str(s).strip()
    )
    if router_sessions:
        rcfg.allowed_sessions = router_sessions
    rcfg.warmup_trades = int(manifest.risk.warmup_trades)
    rcfg.risk_per_trade_pct = float(manifest.risk.risk_per_trade_pct)
    rcfg.max_daily_dd_pct = manifest.risk.max_daily_dd_pct
    rcfg.notional_cap = manifest.risk.notional_cap
    rcfg.max_concurrent_positions = int(manifest.risk.max_concurrent_positions)
    return rcfg


def _describe_instrument(instrument) -> str:
    mode = getattr(instrument, "mode", None) or "conservative"
    mode_str = str(mode).strip() or "conservative"
    return f"{instrument.symbol}/{instrument.timeframe}/{mode_str}"


def _select_instrument(
    manifest: StrategyManifest,
    *,
    symbol: Optional[str] = None,
    mode: Optional[str] = None,
) -> Any:
    instruments = list(manifest.strategy.instruments)
    if not instruments:
        raise SystemExit(json.dumps({"error": "instrument_missing"}))

    symbol_filter = symbol.upper().strip() if symbol else None
    mode_filter = mode.strip().lower() if mode else None

    def _instrument_mode(value: Any) -> str:
        inst_mode = getattr(value, "mode", None)
        normalized = str(inst_mode).strip().lower() if inst_mode is not None else "conservative"
        return normalized if normalized else "conservative"

    matches = []
    for inst in instruments:
        inst_symbol = inst.symbol.upper().strip()
        inst_mode = _instrument_mode(inst)
        if symbol_filter and inst_symbol != symbol_filter:
            continue
        if mode_filter and inst_mode != mode_filter:
            continue
        matches.append(inst)

    if symbol_filter or mode_filter:
        if not matches:
            raise SystemExit(
                json.dumps(
                    {
                        "error": "instrument_not_found",
                        "symbol": symbol_filter,
                        "mode": mode_filter,
                        "choices": [_describe_instrument(inst) for inst in instruments],
                    }
                )
            )
        if len(matches) > 1:
            raise SystemExit(
                json.dumps(
                    {
                        "error": "instrument_ambiguous",
                        "symbol": symbol_filter,
                        "mode": mode_filter,
                        "choices": [_describe_instrument(inst) for inst in matches],
                        "hint": "Specify both --symbol and --mode to disambiguate",
                    }
                )
            )
        return matches[0]

    return instruments[0]


def _prepare_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    manifest_path = _resolve_repo_path(Path(args.manifest))
    manifest = load_manifest(manifest_path)
    instrument = _select_instrument(
        manifest,
        symbol=args.symbol,
        mode=args.mode,
    )
    symbol = instrument.symbol
    timeframe = instrument.timeframe
    mode = instrument.mode or "conservative"

    manifest_cli = dict(manifest.runner.cli_args or {})

    csv_path_value = args.csv or manifest_cli.get("csv") or manifest_cli.get("default_csv")
    if not csv_path_value:
        raise SystemExit(json.dumps({"error": "csv_required"}))
    csv_path = _resolve_repo_path(Path(csv_path_value))

    json_out_value: Optional[Path]
    if args.json_out:
        json_out_value = Path(args.json_out)
    elif manifest_cli.get("json_out"):
        json_out_value = Path(manifest_cli["json_out"])
    elif manifest_cli.get("out_json"):
        json_out_value = Path(manifest_cli["out_json"])
    else:
        json_out_value = None

    json_out: Optional[Path]
    if json_out_value is not None:
        json_out = (
            json_out_value
            if json_out_value.is_absolute()
            else _resolve_repo_path(json_out_value)
        )
    else:
        json_out = None

    if getattr(args, "out_daily_csv", None):
        daily_csv_value: Optional[Path] = Path(args.out_daily_csv)
    elif manifest_cli.get("out_daily_csv"):
        daily_csv_value = Path(manifest_cli["out_daily_csv"])
    elif manifest_cli.get("dump_daily"):
        daily_csv_value = Path(manifest_cli["dump_daily"])
    else:
        daily_csv_value = None

    if daily_csv_value is not None:
        daily_csv_out = (
            daily_csv_value
            if daily_csv_value.is_absolute()
            else _resolve_repo_path(daily_csv_value)
        )
    else:
        daily_csv_out = None

    if args.equity is not None:
        equity = float(args.equity)
    else:
        equity = float(manifest_cli.get("equity", 100000.0))

    out_dir_value: Optional[Path]
    if args.out_dir:
        out_dir_value = Path(args.out_dir)
    elif manifest_cli.get("out_dir"):
        out_dir_value = Path(manifest_cli["out_dir"])
    else:
        out_dir_value = None

    resolved_out_dir: Optional[Path] = None
    if out_dir_value is not None:
        resolved_out_dir = (
            out_dir_value
            if out_dir_value.is_absolute()
            else _resolve_repo_path(out_dir_value)
        )

    auto_state = bool(manifest_cli.get("auto_state", True))
    if args.auto_state is not None:
        auto_state = bool(args.auto_state)
    aggregate_ev = bool(manifest_cli.get("aggregate_ev", True))
    strict = bool(args.strict)

    state_archive_root = Path(manifest_cli.get("state_archive", "ops/state_archive"))
    state_archive_root = _resolve_repo_path(state_archive_root)

    use_ev_profile = bool(manifest_cli.get("use_ev_profile", True))
    ev_profile_path = manifest_cli.get("ev_profile") or manifest.state.ev_profile
    if ev_profile_path and use_ev_profile:
        ev_profile_path = _resolve_repo_path(Path(ev_profile_path))
    else:
        ev_profile_path = None

    strategy_cls = _load_strategy_class(manifest.strategy.class_path)
    runner_cfg = _runner_config_from_manifest(manifest)

    run_base_dir = resolved_out_dir

    return RuntimeConfig(
        manifest=manifest,
        manifest_path=manifest_path,
        csv_path=csv_path,
        json_out=json_out,
        equity=equity,
        start_ts=args.start_ts,
        end_ts=args.end_ts,
        out_dir=resolved_out_dir,
        auto_state=auto_state,
        aggregate_ev=aggregate_ev,
        strict=strict,
        state_archive_root=state_archive_root,
        ev_profile_path=Path(ev_profile_path) if ev_profile_path else None,
        use_ev_profile=use_ev_profile,
        symbol=symbol,
        timeframe=timeframe,
        mode=mode,
        runner_config=runner_cfg,
        strategy_cls=strategy_cls,
        run_base_dir=run_base_dir,
        daily_csv_out=daily_csv_out,
    )


def _load_ev_profile(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data else None


def _resolve_archive_namespace(
    config: RuntimeConfig,
) -> tuple[Optional[Path], Optional[str]]:
    namespace_raw = getattr(config.manifest.state, "archive_namespace", None)
    if not namespace_raw:
        return None, None

    namespace_str = str(namespace_raw).strip()
    if not namespace_str:
        return None, None

    namespace_path = Path(namespace_str)
    if namespace_path.is_absolute():
        return namespace_path, namespace_str

    resolved_path = config.state_archive_root / namespace_path
    # Use POSIX-style separators so CLI consumers receive a stable string.
    return resolved_path, namespace_path.as_posix()


def _resolve_state_archive(config: RuntimeConfig) -> Path:
    namespace_path, _ = _resolve_archive_namespace(config)
    if namespace_path is not None:
        return namespace_path
    state_key = _strategy_state_key(config.strategy_cls)
    return config.state_archive_root / state_key / config.symbol / config.mode


def _aggregate_ev(_namespace_path: Path, config: RuntimeConfig) -> None:
    _, namespace_str = _resolve_archive_namespace(config)
    cmd = [
        sys.executable,
        str(ROOT_PATH / "scripts" / "aggregate_ev.py"),
        "--archive",
        str(config.state_archive_root),
        "--strategy",
        config.manifest.strategy.class_path,
        "--symbol",
        config.symbol,
        "--mode",
        config.mode,
        "--recent",
        "5",
    ]
    if namespace_str:
        cmd.extend(["--archive-namespace", namespace_str])
    if config.ev_profile_path:
        cmd.extend(["--out-yaml", str(config.ev_profile_path)])
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        if result.stdout:
            print("[run_sim] aggregate_ev stdout:", file=sys.stderr)
            print(result.stdout.rstrip("\n"), file=sys.stderr)
        if result.stderr:
            print("[run_sim] aggregate_ev stderr:", file=sys.stderr)
            print(result.stderr.rstrip("\n"), file=sys.stderr)
        raise RuntimeError(f"aggregate_ev failed with exit code {result.returncode}")


def _store_run_summary(run_dir: Path, config: RuntimeConfig) -> None:
    try:
        from scripts.ev_vs_actual_pnl import store_run_summary  # optional pandas dep
    except ModuleNotFoundError as exc:
        if getattr(exc, "name", "") == "pandas":
            return
        raise
    run_base = config.run_base_dir
    if not run_base:
        return
    if not (run_dir / "records.csv").exists():
        return
    try:
        store_run_summary(
            runs_dir=run_base,
            run_id=run_dir.name,
            store_dir=run_base,
            store_daily=False,
            top_n=5,
        )
    except Exception:
        # Optional convenience; ignore failures so the main run still succeeds.
        return


def _format_ts(dt_value: Optional[datetime]) -> Optional[str]:
    if dt_value is None:
        return None
    dt_utc = dt_value.replace(tzinfo=timezone.utc)
    return dt_utc.isoformat().replace("+00:00", "Z")


def _write_daily_csv(path: Path, daily: Mapping[str, Mapping[str, Any]]) -> None:
    import csv as _csv

    cols = [
        "date",
        "breakouts",
        "gate_pass",
        "gate_block",
        "ev_pass",
        "ev_reject",
        "fills",
        "wins",
        "pnl_pips",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = _csv.writer(f)
        writer.writerow(cols)
        for day in sorted(daily.keys()):
            entry = daily.get(day, {}) or {}
            writer.writerow(
                [
                    day,
                    int(entry.get("breakouts", 0)),
                    int(entry.get("gate_pass", 0)),
                    int(entry.get("gate_block", 0)),
                    int(entry.get("ev_pass", 0)),
                    int(entry.get("ev_reject", 0)),
                    int(entry.get("fills", 0)),
                    int(entry.get("wins", 0)),
                    float(entry.get("pnl_pips", 0.0)),
                ]
            )


def _write_run_outputs(
    config: RuntimeConfig,
    out: Dict[str, Any],
    metrics,
) -> Optional[Path]:
    if not config.run_base_dir:
        return None

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = config.run_base_dir / f"{config.symbol}_{config.mode}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    out["run_dir"] = str(run_dir)

    params = {
        "manifest": str(config.manifest_path),
        "csv": str(config.csv_path),
        "symbol": config.symbol,
        "timeframe": config.timeframe,
        "mode": config.mode,
        "equity": config.equity,
        "start_ts": _format_ts(config.start_ts),
        "end_ts": _format_ts(config.end_ts),
        "auto_state": config.auto_state,
        "aggregate_ev": config.aggregate_ev,
        "ev_profile": str(config.ev_profile_path) if config.ev_profile_path else None,
    }

    daily = getattr(metrics, "daily", None)
    if daily:
        daily_path = run_dir / "daily.csv"
        _write_daily_csv(daily_path, daily)
        out.setdefault("dump_daily", str(daily_path))

    with (run_dir / "params.json").open("w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)

    with (run_dir / "metrics.json").open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    records = getattr(metrics, "records", None)
    if records:
        import csv as _csv

        header = sorted({key for record in records for key in record.keys()})
        with (run_dir / "records.csv").open("w", newline="", encoding="utf-8") as f:
            writer = _csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for record in records:
                writer.writerow(record)

    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run minimal ORB simulation from a manifest")
    parser.add_argument("--manifest", required=True, help="Path to strategy manifest YAML")
    parser.add_argument("--csv", help="Override CSV input path (manifest defaults otherwise)")
    parser.add_argument(
        "--json-out",
        "--out-json",
        dest="json_out",
        help="Write metrics JSON to the specified path",
    )
    parser.add_argument(
        "--out-daily-csv",
        "--dump-daily",
        dest="out_daily_csv",
        help="Write daily roll-up CSV to the specified path",
    )
    parser.add_argument(
        "--symbol",
        help="Select manifest instrument by symbol when multiple entries exist",
    )
    parser.add_argument(
        "--mode",
        help="Select manifest instrument by execution mode when multiple entries share the symbol",
    )
    parser.add_argument("--equity", type=float, help="Override equity (default from manifest or 100000)")
    parser.add_argument("--start-ts", type=_iso8601_arg, help="Start timestamp (ISO8601)")
    parser.add_argument("--end-ts", type=_iso8601_arg, help="End timestamp (ISO8601)")
    parser.add_argument("--out-dir", help="Directory to store run artefacts (params/state/metrics)")
    parser.add_argument(
        "--auto-state",
        dest="auto_state",
        action="store_true",
        help="Force automatic state load/save even if the manifest disables it",
    )
    parser.add_argument(
        "--no-auto-state",
        dest="auto_state",
        action="store_false",
        help="Disable automatic state load/save even if the manifest enables it",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Raise CSVFormatError if the loader skips any rows due to parse errors",
    )
    parser.set_defaults(auto_state=None)
    return parser


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = _prepare_runtime_config(args)

    csv_path = str(config.csv_path)
    loader_stats = CSVLoaderStats()
    bars_iter = load_bars_csv(
        csv_path,
        symbol=config.symbol,
        start_ts=config.start_ts,
        end_ts=config.end_ts,
        default_symbol=config.symbol,
        default_tf=config.timeframe,
        strict=config.strict,
        stats=loader_stats,
    )
    try:
        first_bar = next(bars_iter)
    except StopIteration:
        print(json.dumps({"error": "no_bars"}))
        return 1

    bars_for_runner = chain(
        [first_bar] if first_bar.get("symbol") == config.symbol else [],
        (bar for bar in bars_iter if bar.get("symbol") == config.symbol),
    )

    runner = BacktestRunner(
        equity=config.equity,
        symbol=config.symbol,
        runner_cfg=config.runner_config,
        debug=False,
        strategy_cls=config.strategy_cls,
    )

    if config.use_ev_profile and config.ev_profile_path:
        profile = _load_ev_profile(config.ev_profile_path)
        if profile:
            runner.ev_profile = profile
            runner._apply_ev_profile()

    archive_dir: Optional[Path] = None
    loaded_state_path: Optional[str] = None
    if config.auto_state:
        archive_dir = _resolve_state_archive(config)
        latest_state = _latest_state_file(archive_dir)
        if latest_state is not None:
            try:
                runner.load_state_file(str(latest_state))
                loaded_state_path = str(latest_state)
            except Exception:
                loaded_state_path = None

    metrics = runner.run(bars_for_runner, mode=config.mode)
    metrics.debug["csv_loader"] = loader_stats.as_dict()
    if loader_stats.skipped_rows:
        last_error = loader_stats.last_error_code or "unknown"
        print(
            f"[run_sim] Skipped {loader_stats.skipped_rows} CSV row(s); last_error={last_error}",
            file=sys.stderr,
        )
        if config.strict:
            raise CSVFormatError(
                "rows_skipped",
                details=f"skipped={loader_stats.skipped_rows}, last_error={last_error}",
            )

    runtime_mapping: Dict[str, Dict[str, Any]] = {}
    runtime_snapshot = getattr(metrics, "runtime", {}) or {}
    if runtime_snapshot:
        runtime_mapping[config.manifest.id] = dict(runtime_snapshot)
    telemetry_snapshot = PortfolioTelemetry(active_positions={config.manifest.id: 0})
    portfolio_state = build_portfolio_state(
        [config.manifest], telemetry=telemetry_snapshot, runtime_metrics=runtime_mapping or None
    )
    router_results = select_candidates(
        {"session": None, "spread_band": None, "rv_band": None},
        [config.manifest],
        portfolio=portfolio_state,
    )

    out = metrics.as_dict()
    if metrics.debug:
        out["debug"] = metrics.debug
    out["decay"] = runner.ev_global.decay
    out["manifest_id"] = config.manifest.id
    out["symbol"] = config.symbol
    out["mode"] = config.mode
    out["equity"] = config.equity
    if router_results:
        out["router"] = [result.as_dict() for result in router_results]
    if loaded_state_path:
        out["loaded_state"] = loaded_state_path

    run_dir = _write_run_outputs(config, out, metrics)
    if run_dir is not None:
        _store_run_summary(run_dir, config)

    if config.daily_csv_out:
        _write_daily_csv(config.daily_csv_out, getattr(metrics, "daily", {}) or {})
        out["dump_daily"] = str(config.daily_csv_out)

    if config.json_out:
        config.json_out.parent.mkdir(parents=True, exist_ok=True)
        with config.json_out.open("w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))

    archive_save_path: Optional[str] = None
    if config.auto_state:
        archive_dir = archive_dir or _resolve_state_archive(config)
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        archive_path = archive_dir / f"{timestamp}.json"
        state_payload = runner.export_state()
        with archive_path.open("w", encoding="utf-8") as f:
            json.dump(state_payload, f, ensure_ascii=False, indent=2)
        archive_save_path = str(archive_path)
        if run_dir is not None:
            with (run_dir / "state.json").open("w", encoding="utf-8") as f:
                json.dump(state_payload, f, ensure_ascii=False, indent=2)

    if config.aggregate_ev and archive_save_path:
        try:
            _aggregate_ev(archive_dir or _resolve_state_archive(config), config)
        except Exception as exc:
            print(f"[run_sim] Failed to aggregate EV: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

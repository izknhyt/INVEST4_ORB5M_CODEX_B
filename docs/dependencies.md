# Dependency Overview

This repository primarily targets a pure-Python runtime and keeps external packages optional. The table below lists the third-party libraries that unlock specific workflows together with installation guidance.

## Runtime Extensions

| Package | Purpose | Used by | Installation Notes |
| --- | --- | --- | --- |
| `dukascopy-python` | Fetch live 5m bars directly from Dukascopy. | `scripts/run_daily_workflow.py --ingest --use-dukascopy`, `scripts/live_ingest_worker.py` | Install with `pip install dukascopy-python`. The workflow falls back to Yahoo Finance automatically even if this package is missing. |
| _なし_（HTTP 経由） | Yahoo Finance フォールバック。`requests` 標準依存のみで稼働。 | `scripts/run_daily_workflow.py --ingest --use-yfinance`, `scripts/live_ingest_worker.py`, `scripts/yfinance_fetch.py` | 最新実装では `yfinance` パッケージ不要。プロキシ環境でも追加ホイールなしで稼働する。 |
| `pandas` | Tabular post-processing for benchmark summaries, EV analysis scripts, and ad-hoc notebooks. | `scripts/report_benchmark_summary.py`, `scripts/compute_metrics.py`, `scripts/ev_optimize_from_records.py`, `scripts/summarize_runs.py`, `scripts/ev_vs_actual_pnl.py`, notebooks under `analysis/` | 必要に応じて `pip install pandas matplotlib`。`scripts/run_benchmark_pipeline.py --disable-plot` を指定すれば PNG 生成をスキップし、依存を持ち込まずにサマリーを更新できる。 |
| `pyarrow` | Required to manage the experiment history Parquet store (logging, recovery, analytics). | `scripts/log_experiment.py`, `scripts/recover_experiment_history.py`, utilities under `experiments/history/` | Install with `pip install pyarrow` before appending or rebuilding experiment history. Pytest will skip the related suites when the dependency is absent. |
| `matplotlib` | Optional summary chart rendering. Falls back gracefully when absent. | `scripts/report_benchmark_summary.py --plot-out`（`scripts/run_benchmark_pipeline.py --summary-plot` から引き継がれる）, notebooks under `analysis/` | Install with `pip install pandas matplotlib` when PNG export is needed. |

## Development Tooling

| Package | Purpose | Used by | Installation Notes |
| --- | --- | --- | --- |
| `pytest` | Runs the unit/integration suite described in the README and runbooks. | `python3 -m pytest` across `tests/` | Install locally with `pip install pytest` before executing the regression suite. |

## Offline / Proxy-Constrained Environments

Corporate proxy policies in the sandbox currently block direct PyPI downloads. Prepare offline wheels for ingestion dependencies when running inside that environment:

```bash
pip install dukascopy_python-*.whl
```

Keep the wheels in a shared artifact store so that future ingest runs and freshness checks can be retried without reopening proxy exemptions.

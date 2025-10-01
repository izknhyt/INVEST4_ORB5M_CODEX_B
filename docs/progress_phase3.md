# フェーズ3 進捗レポート（運用準備）

## 通知SLO運用
- `scripts/analyze_signal_latency.py` を導入済。サンプルcron設定 (`scripts/cron_schedule_example.json`) に日次チェックを追記。
- フォールバックログ（`ops/signal_notifications.log`）と連携し、異常時に手動通知できるよう整備済み。

## state アーカイブ
- `scripts/archive_state.py` を追加。`python3 scripts/archive_state.py --runs-dir runs --output ops/state_archive` で各ランの `state.json` を日次バージョンとして保存。
- `ops/state_archive/` に初期アーカイブ（168件）を作成。`docs/state_runbook.md` と併せて運用手順を明文化。

## スケジューラ統合
- `scripts/run_daily_workflow.py` を追加。最適化 (`--optimize`)、レイテンシ分析 (`--analyze-latency`)、stateアーカイブ (`--archive-state`) をまとめて実行可能。
- Cron 例 (`scripts/cron_schedule_example.json`) を用意。実際の自動化は CI/cron 環境に合わせて設定。

## Dukascopy Auto Ingestion
- Introduced `scripts/dukascopy_fetch.py` and refactored `scripts/pull_prices.py` so the same ingestion pipeline accepts in-memory bar records.
- `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy` now re-fetches the latest USDJPY 5m bars directly from Dukascopy and appends them to `raw/`, `validated/`, and `features/` idempotently.
- Added regression coverage for the new `ingest_records` helper to guarantee duplicate-safe runs when the workflow is triggered multiple times per day.
- Added `scripts/merge_dukascopy_monthly.py` to combine monthly exports like `USDJPY_202501_5min.csv` into a single `data/usdjpy_5m_2025.csv`, then ingested the merged file to backfill `raw/`→`features/` ahead of live refresh。
- Implemented `scripts/fetch_prices_api.py` with Alpha Vantage defaults, credential loading via `scripts/_secrets.py`, and retry/ratelimit controls. `python3 scripts/run_daily_workflow.py --ingest --use-api` now streams REST responses into `pull_prices.ingest_records`, with pytest covering success and HTTP failure logging。
- 2025-10-24: Alpha Vantage FX_INTRADAY がプレミアム専用であることを確認し、REST ルートは保留ステータスへ移行。運用は `--use-dukascopy` を主経路とし、障害時は yfinance 由来バーを正規化して `ingest_records` へ流せるよう要件整理を進める。

## TODO
- `analysis/broker_fills.ipynb` による Fill 差分可視化と、ブローカー仕様に合わせたモデル調整。
- `run_daily_workflow.py` のログ出力・通知内容を強化し、本番運用フローへ組み込む。
- state アーカイブの保存期間やクリーンアップ方針を `docs/state_runbook.md` に追記。

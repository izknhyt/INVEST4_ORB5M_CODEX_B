# API-Based Price Ingestion Plan

## 1. Scope
- Target: USDJPY 5m bars (extensible interface for additional symbols/timeframes).
- Usage context: personal workflow prioritizing free-tier APIs (e.g., Alpha Vantage, Twelve Data) with rate limits around 5 req/min・500 req/day; design should conserve quota and clarify upgrade paths if limits are exceeded.
- 2025-10 Update: Alpha Vantage FX_INTRADAY がプレミアム専用のため REST/API 連携は保留。運用は Dukascopy → `ingest_records` のルートを標準とし、無料APIはフォールバック候補として仕様を維持する。2025-11 時点では Dukascopy 失敗/鮮度低下検知時に yfinance (`period="7d"`) へ自動切替するフェイルオーバーを `run_daily_workflow.py` 内へ組み込む。
- Goals:
  - Acquire recent bars from external REST (phase 1) and prepare for Streaming integration.
  - Feed the results into the existing `pull_prices.py` pipeline without manual CSV steps.
  - Ensure `run_daily_workflow.py --ingest` keeps `raw/`, `validated/`, `features/` and `ops/runtime_snapshot.json.ingest` up to date so freshness checks stay within 6h.

## 2. Data Flow
Dukascopy feed（正式運用） → 正常時は `scripts/dukascopy_fetch.py` → normalized bar iterator → `pull_prices.ingest_records` → CSV append (`raw`/`validated`/`features`) → snapshot/anomaly logging。フェイルオーバー条件（例: 90 分超の鮮度遅延/取得失敗）に該当した場合は自動で `scripts/yfinance_fetch.py` (`period="7d"`, シンボル正規化付き) を呼び出し同フローに合流する。REST API provider（保留中）も同じインターフェースに揃える。

## 3. Modules & Interfaces
- `scripts/fetch_prices_api.py`
  - CLI: `python3 scripts/fetch_prices_api.py --symbol USDJPY --tf 5m --start-ts ... --end-ts ... [--out csv|stream] [--dry-run]`.
  - Library: `fetch_prices(symbol: str, tf: str, start: datetime, end: datetime) -> Iterator[Dict[str, Any]]`.
  - Responsibilities: pagination, query parameter construction, retries/backoff, rate-limit handling, basic schema validation（現状は保留ステータス。契約/無料API確保後に即再開できる実装基盤として保持）。
- `scripts/dukascopy_fetch.py`
  - Lightweight wrapper around `dukascopy_python.live_fetch`, normalizing rows to the ingestion schema (timestamp/symbol/tf/o/h/l/c/v/spread).
  - Provides CLI for ad-hoc exports and is invoked by `run_daily_workflow.py --ingest --use-dukascopy` to refresh recent 5m bars.
- `scripts/merge_dukascopy_monthly.py`
  - Globs monthly CSV dumps (e.g., `USDJPY_202501_5min.csv`) and produces a single normalized file for bulk backfill prior to live refresh.
  - Ensures duplicates are de-duplicated and timestamps are sorted so `pull_prices.ingest_records` can append cleanly.
- `scripts/_secrets.py` (new helper)
  - `load_api_credentials(service: str)` reads from `configs/api_keys.yml` or environment variables (fallback) and centralizes error messages.
- `scripts/pull_prices.py`
  - Exposes `ingest_records(rows: Iterable[Dict[str, Any]], ...)` so CSV path ingestion and API/Dukascopy providers share the same idempotent pipeline.
- `scripts/run_daily_workflow.py`
  - `--ingest` gains provider flags (`--use-api`, `--use-dukascopy`) so we can switch between REST exports and the Dukascopy bridge。2025-10 現在は `--use-dukascopy` を標準運用とし、`--use-api` はオプション保留。2025-11 以降は `--dukascopy-freshness-threshold-minutes`（既定 90 分）で鮮度を監視し、閾値超過時に yfinance への自動フェイルオーバーが発火する。
  - Exit non-zero on hard failures so Webhook/alert integrations continue to work。

## 4. Configuration
- `configs/api_ingest.yml` (new):
  - `base_url`, endpoint paths, required query params。
  - `rate_limit` (requests/min), `batch_size`, `lookback_minutes` (buffer before `last_ts`)。Free-tier defaults should reflect conservative quotas (≤5 req/min, ≤500 req/day) and allow optional overrides。Alpha Vantage 設定は保留ステータスとし、再開時に差し替えやすい YAML を維持。
  - `activation_criteria` プレースホルダを明示し、REST ルートを有効化する判断指標を管理する: `target_cost_ceiling_usd`（例: 月額 40 USD 以内）、`minimum_free_quota_per_day`（例: 500 リクエスト以上）、`retry_budget_per_run`（例: 15 リトライ以内）。閾値は `docs/state_runbook.md` での運用手順に沿ってレビューし、逸脱時は `--use-api` を停止する。2025-11 時点では `configs/api_ingest.yml` に同値を反映し、候補プロバイダの実測レートを付記した。
    - Alpha Vantage Premium: 49.99 USD/月、75 req/min、1,500 req/日。`target_cost_ceiling_usd=40` を超過し、FX_INTRADAY がプレミアム専用となったため保留。
    - Alpha Vantage Free: 0 USD、5 req/min、≈500 req/日。ただし FX_INTRADAY は Premium 限定で実運用不可。
    - Twelve Data Free: 0 USD、8 req/min、800 req/日、30 日分の 5m 履歴（同時シンボル 2 本）。コスト/レート要件は満たすが、履歴長とシンボル上限を考慮したフォールバック運用が必要。
    - yfinance: 0 USD、7 日バッチ取得（`period="7d"`）で 1 リクエストあたり 5m バーを 60 日分まで取得。既存フェイルオーバー経路として継続運用。
  - `credential_rotation` セクションで `cadence_days`（例: 30 日）、`next_rotation_at`、`owner` を記載するプレースホルダを追加し、CI/ローカル双方で参照する。更新後は `docs/checklists/p1-04_api_ingest.md` のローテーション記録項目をチェックする。
- `configs/api_keys.yml` (new or repurposed): store API key/secret with rotation notes.
- Local `.env` pattern: for personal use, load keys from environment variables (not committed) and document manual rotation steps.
- Safety margin: default 60 minutes so gaps around clock shifts or downtime are re-requested。Dukascopy 経路では別途 `--dukascopy-freshness-threshold-minutes`（既定 90 分）を確認し、超過時は自動で yfinance (`pip install dukascopy-python yfinance`) へ切替わる。

## 5. Error Handling & Observability
- Retries: exponential backoff (2s, 4s, 8s, 16s, 32s) with jitter; cap attempts to 5.
- HTTP 4xx/5xx: classify vs. retryable; log to `ops/logs/ingest_anomalies.jsonl` with `source="api"` and reason codes.
- Data validation: reject rows missing timestamp/symbol/price; record anomaly entries and continue.
- Metrics (future): capture fetch duration, rows ingested, retry counts in structured log for potential Grafana ingestion.

## 6. Testing Strategy
- Unit tests:
  - Mock API responses (success, pagination, 4xx, 429, 500) to assert retry/backoff logic.
  - `pull_prices.ingest_rows` idempotency: duplicates, gaps, malformed rows.
- Integration tests:
  - Fixture mini-API (Flask/pytest-httpserver) serving deterministic bars; run `run_daily_workflow.py --ingest --use-api --dry-run` and compare resulting CSV snapshots in temp dir（API再開時に有効化）。
  - Freshness script invocation with patched `datetime.now()` to simulate timely updates.
- Regression:
  - Ensure `python3 scripts/pull_prices.py --source ...` legacy path remains functional (CSV ingestion still supported).

## 7. Documentation Updates
- `README.md`: extend On-demand Ingest CLI section with API mode usage and credential setup.
- `docs/state_runbook.md`: add API ingest routine, key rotation procedure, failure recovery steps.
- `docs/checklists/p1-04_api_ingest.md`: capture DoD checklist (credentials, config, workflow run, tests passing, freshness verified).

## 8. Open Questions
- API provider choice (OANDA REST? Alpha Vantage? in-house feed) and associated rate limits/SLA。Alpha Vantage はプレミアム専用となったため、無料枠で使える代替 API or 有償契約を再検討する必要あり。2025-11 時点では Twelve Data Free をフォールバック候補として比較し、保留解除の前提条件（履歴 30 日制限の扱い / シンボル追加時のコスト試算）を洗い出す。
- Credential storage: local `.env` vs. secrets manager; rotation cadence。`configs/api_ingest.yml` の `credential_rotation` テンプレに日付・担当・保管場所を反映し、30 日ごとの見直しを既定にするか要検討。`docs/state_runbook.md` とチェックリストでの記録サイクルをどう同期するかも整理する。
- Streaming/WebSocket rollout timing and relation to current REST-first scope.
- yfinance フォールバックは `scripts/yfinance_fetch.py` と `--use-yfinance` 経路で実装済み。依存パッケージの導入手順、取得遅延の許容範囲、Dukascopy からの切替判断基準を runbook/チェックリストへ追記する必要がある。Yahoo Finance の intraday 保持期間（≒60 日）に合わせて `period="7d"` で一括取得し、シンボルマッピング（例: USDJPY → JPY=X）や未来日クランプを組み込んだ運用整理も必要。

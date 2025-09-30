# API-Based Price Ingestion Plan

## 1. Scope
- Target: USDJPY 5m bars (extensible interface for additional symbols/timeframes).
- Usage context: personal workflow prioritizing free-tier APIs (e.g., Alpha Vantage, Twelve Data) with rate limits around 5 req/min・500 req/day; design should conserve quota and clarify upgrade paths if limits are exceeded.
- Goals:
  - Acquire recent bars from external REST (phase 1) and prepare for Streaming integration.
  - Feed the results into the existing `pull_prices.py` pipeline without manual CSV steps.
  - Ensure `run_daily_workflow.py --ingest` keeps `raw/`, `validated/`, `features/` and `ops/runtime_snapshot.json.ingest` up to date so freshness checks stay within 6h.

## 2. Data Flow
API provider (JSON/CSV) or Dukascopy feed → `scripts/fetch_prices_api.py` / `scripts/dukascopy_fetch.py` → normalized bar iterator → `pull_prices.ingest_records` → CSV append (`raw`/`validated`/`features`) → snapshot/anomaly logging.

## 3. Modules & Interfaces
- `scripts/fetch_prices_api.py`
  - CLI: `python3 scripts/fetch_prices_api.py --symbol USDJPY --tf 5m --start-ts ... --end-ts ... [--out csv|stream] [--dry-run]`.
  - Library: `fetch_prices(symbol: str, tf: str, start: datetime, end: datetime) -> Iterator[Dict[str, Any]]`.
  - Responsibilities: pagination, query parameter construction, retries/backoff, rate-limit handling, basic schema validation.
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
  - `--ingest` gains provider flags (`--use-api`, `--use-dukascopy`) so we can switch between REST exports and the Dukascopy bridge. When enabled, compute `(last_ts - buffer, now)` and call the relevant fetcher → `pull_prices.ingest_records`.
  - Exit non-zero on hard failures so Webhook/alert integrations continue to work.

## 4. Configuration
- `configs/api_ingest.yml` (new):
  - `base_url`, endpoint paths, required query params.
  - `rate_limit` (requests/min), `batch_size`, `lookback_minutes` (buffer before `last_ts`). Free-tier defaults should reflect conservative quotas (≤5 req/min, ≤500 req/day) and allow optional overrides.
- `configs/api_keys.yml` (new or repurposed): store API key/secret with rotation notes.
- Local `.env` pattern: for personal use, load keys from environment variables (not committed) and document manual rotation steps.
- Safety margin: default 60 minutes so gaps around clock shifts or downtime are re-requested.

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
  - Fixture mini-API (Flask/pytest-httpserver) serving deterministic bars; run `run_daily_workflow.py --ingest --use-api --dry-run` and compare resulting CSV snapshots in temp dir.
  - Freshness script invocation with patched `datetime.now()` to simulate timely updates.
- Regression:
  - Ensure `python3 scripts/pull_prices.py --source ...` legacy path remains functional (CSV ingestion still supported).

## 7. Documentation Updates
- `README.md`: extend On-demand Ingest CLI section with API mode usage and credential setup.
- `docs/state_runbook.md`: add API ingest routine, key rotation procedure, failure recovery steps.
- `docs/checklists/p1-04_api_ingest.md`: capture DoD checklist (credentials, config, workflow run, tests passing, freshness verified).

## 8. Open Questions
- API provider choice (OANDA REST? Alpha Vantage? in-house feed) and associated rate limits/SLA.
- Credential storage: local `.env` vs. secrets manager; rotation cadence.
- Streaming/WebSocket rollout timing and relation to current REST-first scope.

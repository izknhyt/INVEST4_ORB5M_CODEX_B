# Phase 3 Observability Automation Blueprint

> Cross-reference: [docs/task_backlog.md#p3-観測性・レポート自動化](../task_backlog.md#p3-観測性・レポート自動化)

## Context Inventory
- **Existing deliverables**
  - `scripts/analyze_signal_latency.py` captures point-in-time latency measurements with cron-ready defaults referenced in `docs/progress_phase3.md`.
  - `scripts/archive_state.py` and `scripts/run_daily_workflow.py` are wired for state retention and orchestration, with dashboard refresh guidance in `docs/observability_dashboard.md` and high-level roadmap anchors in `docs/observability_plan.md`.
  - Dashboard review flows already enumerate CLI commands, telemetry checkpoints, and dataset mappings for EV, slippage, win-rate LCB, and turnover exports.
- **Open risks** (from plan and dashboard notes)
  - Dashboard refresh cadence must balance ingestion latency tolerances and versioned artefact retention for auditability.
  - Shared responsibilities between data engineering and trading operations are not yet codified, risking alert ownership gaps.
  - Notebook/BI parity depends on consistent loaders and access controls that are not fully documented.
- **Desired automation goals**
  - Convert signal latency sampling into a governed cadence with automated SLO breach alerts.
  - Automate weekly summary webhook payloads that consolidate run, utilisation, and health metrics.
  - Standardise dashboard export datasets for downstream notebooks/BI, ensuring reproducibility and escalation readiness.

## Scope
- **In scope**: Scheduling, interfaces, and validation checkpoints required to automate Phase 3 telemetry sampling, weekly reporting, and dashboard dataset exports.
- **Out of scope**: Implementation of new CLI features, UI visualisations, or third-party integrations beyond the documented interfaces; production credential management and infrastructure-as-code provisioning.

## Assumptions
1. Existing scripts (`analyze_signal_latency`, `summarize_runs`, `export_dashboard_data`) remain the primary automation entrypoints and can be extended without major refactors.
2. Operations teams can consume webhook payloads in JSON via Slack or internal incident tooling, and 5xx responses must be retried by the scheduler.
3. Portfolio telemetry samples mirror the router demo dataset described in `docs/observability_dashboard.md`, and new datasets must not break downstream notebook expectations.
4. Cron or CI orchestrators are available to trigger daily/weekly jobs with environment variables for secrets (webhook URLs, storage paths).

## System Boundaries
- **Inputs**: `runs/` artefacts, `reports/portfolio_summary.json`, `ops/state_archive/**`, and `reports/portfolio_samples/router_demo/**` as catalogued in dashboard guidance.
- **Processing surfaces**: Python CLIs under `scripts/` executed by `run_daily_workflow.py` or standalone schedules; automation must operate within repository tooling.
- **Outputs**: `ops/signal_latency.csv` (rotated), webhook POST payloads, `out/dashboard_snapshot.json` and derived weekly snapshots stored under `reports/` or shared storage.
- **Interfaces with external systems**: Webhook endpoints (HTTP POST), Slack/email notifications, optional artefact uploads to shared storage (outside repo scope).

## Interface Requirements

### Signal Latency Sampling Cadence
- **Cadence**: Sample latency every 15 minutes during trading sessions (00:00–24:00 UTC) with aggregated hourly rollups; retain raw samples for 14 days and rollups for 90 days.
- **Sampling windows**: Each `analyze_signal_latency` run must emit `timestamp_utc`, `source`, `latency_ms`, `p95_latency_ms`, and `status` per data feed. Scheduler should trigger at `*/15 * * * *` (cron) with environment variable `LATENCY_SLO_MS` (default 120000).
- **Storage**: Append measurements to `ops/signal_latency.csv` with rotation when file exceeds 10 MB; archive rotated files under `ops/signal_latency_archive/%Y/%m/`.
- **Alerting**: When `p95_latency_ms` exceeds `LATENCY_SLO_MS` for two consecutive samples, emit a webhook alert using the weekly report schema’s `alerts` block (see below) with `severity=warning`; escalate to `severity=critical` if three consecutive breaches occur or `status` equals `error`.
- **Observability contract**: Automation must expose a health endpoint/log summary (stdout JSON) including `samples_written`, `rollups_written`, `breach_count`, and `next_rotation_bytes` for ingestion by higher-level orchestrators.

### Weekly Report Webhook Payload Schema
- **Endpoint**: Configurable via `OBS_WEEKLY_WEBHOOK_URL` secret; POST JSON with `Content-Type: application/json`.
- **Payload structure**:
  ```json
  {
    "generated_at": "<ISO8601 UTC>",
    "week_start": "<ISO8601 UTC>",
    "week_end": "<ISO8601 UTC>",
    "runs": {
      "baseline": [{"run_id": "...", "ev": {"latest": float, "trend_7d": float}, "win_rate_lcb": float}],
      "rolling": [{"run_id": "...", "ev": {"latest": float, "trend_7d": float}, "turnover": {"avg_trades_per_day": float}}]
    },
    "utilisation": {
      "categories": [{"name": "day_orb", "budget_pct": float, "headroom_pct": float, "status": "ok|warning|breach"}]
    },
    "execution_health": {
      "slippage_bps": {"day_orb_5m": float, "tokyo_micro": float},
      "reject_rate": {"day_orb_5m": float, "tokyo_micro": float}
    },
    "latency": {
      "p95_ms": float,
      "breaches": [{"timestamp": "<ISO8601 UTC>", "source": "dukascopy", "p95_ms": float, "status": "warning|critical"}]
    },
    "alerts": [{
      "id": "latency-breach-20260627",
      "severity": "info|warning|critical",
      "message": "<human readable summary>",
      "owner": "observability-oncall",
      "next_action": "<playbook reference>"
    }],
    "attachments": [{"name": "dashboard_snapshot", "uri": "s3://.../dashboard_snapshot_2026-06-27.json"}]
  }
  ```
- **Validation**: Payload must conform to JSON Schema draft 2020-12; missing `alerts` or `attachments` arrays should be serialised as empty lists. Retries: exponential backoff starting at 1 minute, max 5 attempts; log failure with `retry_attempt`, `status_code`, `response_body`.
- **Security**: Support HMAC-SHA256 signature header `X-OBS-Signature` using shared secret `OBS_WEBHOOK_SECRET`.

### Dashboard Export Datasets
- **Required exports**:
  1. **EV history** — Source: `ops/state_archive/<strategy>/<symbol>/<mode>/*`. Fields: `generated_at`, `strategy`, `symbol`, `mode`, `ev_alpha`, `ev_beta`, `ev_decay`, `win_rate_lcb`. Refresh daily at 00:30 UTC.
  2. **Slippage telemetry** — Source: `reports/portfolio_samples/router_demo/telemetry.json`. Fields: `generated_at`, `strategy`, `slippage_bps`, `reject_rate`, `fill_count`, `window_days`. Refresh daily post-latency job (01:00 UTC) to capture latest execution metrics.
  3. **Turnover summary** — Source: `runs/index.csv` + `runs/<id>/daily.csv`. Fields: `run_id`, `start_ts`, `end_ts`, `avg_trades_per_day`, `avg_trades_active_day`, `win_rate`, `drawdown_pct`. Refresh weekly before webhook dispatch (Sundays 23:30 UTC).
  4. **Latency rollups** — Source: aggregated samples appended to `ops/signal_latency_rollup.csv`. Fields: `hour_utc`, `source`, `p50_ms`, `p95_ms`, `breach_flag`. Refresh hourly via same cadence job.
- **Export contract**: `analysis/export_dashboard_data.py` must accept `--dataset <name>` to emit each dataset individually to `out/dashboard/<dataset>.json` and support a `--manifest out/dashboard/manifest.json` listing dataset versions with `checksum_sha256` and `generated_at`.
- **Distribution**: Weekly automation copies latest dataset bundle to shared storage with retention of 8 weeks; include metadata file `out/dashboard/README.json` describing refresh timestamps and upstream commands.

### Ownership & Escalation Flows
- **Signal latency pipeline** — Primary owner: Observability Oncall (trading ops). Secondary: Data Engineering. Escalation: warning alerts notify oncall Slack channel; critical alerts trigger PagerDuty within 5 minutes. Runbook: `docs/state_runbook.md#signal-latency` (to be added).
- **Weekly report webhook** — Primary owner: Research Operations. Secondary: Observability Oncall. Failed deliveries after max retries escalate via email to `ops-alerts@` and auto-create ticket in `OPS-JIRA` with payload log attached.
- **Dashboard exports** — Primary owner: Analytics Engineering. Secondary: Research Ops for validation. Refresh failures log to `ops/dashboard_export.log`; if two consecutive refresh windows miss, escalate to Observability Oncall with summary of missing datasets.
- **Cross-team communication**: Quarterly review meeting to reconcile KPIs and thresholds; automation must post success/failure summaries to `#observability-updates` channel with references to latest artefacts.

### Validation Checkpoints
- **Pre-deployment**: Extend pytest coverage for `analyze_signal_latency` sampling cadence (mock scheduler) and schema validation for webhook payload generator. Add integration test to ensure `export_dashboard_data.py --dataset ev_history` outputs expected fields.
- **Runtime health**: Nightly job executes `python3 -m pytest tests/test_observability_automation.py` (to be created) covering payload schema, latency breach logic, and export manifests.
- **Manual verification**: Weekly checklist ensures webhook payload matches schema (validate via `jsonschema`), dataset checksums align with manifest, and latency rollups show no missing hours. Document results in `docs/checklists/p3_observability_automation.md` (follow-up).
- **Audit trail**: Automation must log execution metadata (`job_id`, `started_at`, `completed_at`, `status`, `artefacts`) to `ops/automation_runs.log`; a monthly review verifies log retention and SLO compliance.

## Follow-up Actions
1. Draft detailed CLI design updates for cadence controls (`--rollup-retention-days`, webhook retries, dataset manifests).
2. Create regression checklist at `docs/checklists/p3_observability_automation.md` aligning with validation checkpoints.
3. Update `docs/state_runbook.md` with new runbook anchors for latency sampling and webhook escalation.
4. Coordinate with analytics engineering to provision shared storage paths and retention policy documentation.

## References
- [docs/observability_plan.md](../observability_plan.md)
- [docs/observability_dashboard.md](../observability_dashboard.md)
- [docs/progress_phase3.md](../progress_phase3.md)

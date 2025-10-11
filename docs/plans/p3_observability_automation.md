# Phase 3 Observability Automation Blueprint

> Cross-reference: [docs/task_backlog.md#p3-観測性・レポート自動化](../task_backlog.md#p3-観測性・レポート自動化)

## Executive Summary

- **Objective**: Convert the manually reviewed Phase 2 telemetry flows into repeatable automation that samples signal latency, publishes weekly health payloads, and refreshes dashboard datasets without human intervention.
- **Definition of Done (DoD)**: Schedulers call into hardened CLIs with schema validation, automated alerting, retention/rotation policies, and documented runbook hooks for every dataset or webhook referenced here. Observability oncall can recover from failures using only the automation logs and referenced checklists.
- **Key Dependencies**: Stable router demo datasets, access to webhook secrets, storage locations for dataset bundles, and pytest coverage for cadence logic/schema validation.
- **Primary Deliverables**: CLI extensions (cadence flags, manifest outputs), automation run logs, JSON schemas, updated runbooks/checklists, and coordination artifacts with analytics engineering.
- **Success Metrics**: (1) No missed cron executions over a four-week pilot; (2) latency breach alerts acknowledged within 10 minutes of emission; (3) dashboard bundle checksum drift resolved within a single automation retry cycle; (4) zero manual steps required in the weekly checklist once cutover completes.

## Implementation Status (2026-07-06)
- `scripts/analyze_signal_latency.py`, `scripts/summarize_runs.py`, `analysis/export_dashboard_data.py`, `scripts/verify_observability_job.py`, `scripts/verify_dashboard_bundle.py`, and `scripts/run_daily_workflow.py --observability` now implement the detailed design requirements（ロック・ローテーション・Webhook 署名・manifest 連番・ドライランガード等）。
- 主要 CLI は `schemas/automation_run.schema.json`／`schemas/observability_weekly_report.schema.json`／`schemas/dashboard_manifest.schema.json` に従って検証され、`tests/test_analyze_signal_latency.py` / `tests/test_weekly_payload.py` / `tests/test_dashboard_datasets.py` / `tests/test_verify_observability_job.py` / `tests/test_verify_dashboard_bundle.py` / `tests/test_run_daily_workflow.py` が回帰を保証する。
- 運用手順は `docs/state_runbook.md#観測性オートメーション` と `docs/observability_dashboard.md` の自動化クイックスタートにまとめ、DoD チェックリスト `docs/checklists/p3_observability_automation.md` も更新して完了条件とログレビュー手順を反映した。
- 今後のフォローアップはスケジューラ本番切り替えと Secrets ローテーション演習（`state.md` / `docs/todo_next.md` の Next Task 参照）に集約済み。

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

### Preconditions & Dependencies

| Area | Requirement | Validation Hook |
| --- | --- | --- |
| Data inputs | `runs/index.csv`, router demo telemetry, and state archives are refreshed at least daily and remain backward compatible. | Nightly `scripts/build_router_snapshot.py` / `scripts/report_portfolio_summary.py` dry-run log archived in `runs/router_pipeline/latest/README.md` (to be created). |
| Secrets | `OBS_WEEKLY_WEBHOOK_URL` and `OBS_WEBHOOK_SECRET` stored in scheduler secrets store with rotation owner documented in `ops/credentials.md`. | Manual smoke test before go-live, recorded in `docs/checklists/p3_observability_automation.md`. |
| Storage | Shared storage path for dashboard bundle has write permission for automation account and 60-day retention guard. | Storage acceptance note attached to backlog entry with link to infrastructure ticket. |
| Test coverage | New pytest modules for cadence logic and schema validation land alongside CLI changes. | CI badge remains green; failures block deployment. |

## Assumptions
1. Existing scripts (`analyze_signal_latency`, `summarize_runs`, `export_dashboard_data`) remain the primary automation entrypoints and can be extended without major refactors.
2. Operations teams can consume webhook payloads in JSON via Slack or internal incident tooling, and 5xx responses must be retried by the scheduler.
3. Portfolio telemetry samples mirror the router demo dataset described in `docs/observability_dashboard.md`, and new datasets must not break downstream notebook expectations.
4. Cron or CI orchestrators are available to trigger daily/weekly jobs with environment variables for secrets (webhook URLs, storage paths).

## Non-Functional Requirements

- **Reliability**: Automation must tolerate transient network and filesystem faults via retry/backoff strategies and surface final status via structured logs; recovery from a failed run must require at most one rerun with no manual cleanup.
- **Auditability**: All generated artefacts (payloads, CSVs, manifests) include provenance metadata (`generated_at`, `source_command`, `commit_sha`) so oncall can trace issues without shelling into the scheduler host.
- **Security**: Secrets are read only at runtime, never logged, and in-memory buffers containing credentials are cleared after use; webhook payload signing failures must be logged with redacted diagnostics.
- **Performance**: End-to-end daily workflow (ingest + latency rollups + exports) should complete within 20 minutes under nominal dataset volumes to stay under the orchestration SLA.

## System Boundaries
- **Inputs**: `runs/` artefacts, `reports/portfolio_summary.json`, `ops/state_archive/**`, and `reports/portfolio_samples/router_demo/**` as catalogued in dashboard guidance.
- **Processing surfaces**: Python CLIs under `scripts/` executed by `run_daily_workflow.py` or standalone schedules; automation must operate within repository tooling.
- **Outputs**: `ops/signal_latency.csv` (rotated), webhook POST payloads, `out/dashboard_snapshot.json` and derived weekly snapshots stored under `reports/` or shared storage.
- **Interfaces with external systems**: Webhook endpoints (HTTP POST), Slack/email notifications, optional artefact uploads to shared storage (outside repo scope).

### Architecture Overview & Data Flow

1. **Ingestion window** — `run_daily_workflow.py --ingest` acquires validated bars and updates `runs/` artefacts. Success triggers the state archive refresh hook.
2. **State archival** — `archive_state.py` snapshots strategy states and appends provenance metadata for downstream EV history exports.
3. **Latency sampling** — `analyze_signal_latency.py` collects raw samples every 15 minutes, hands them to the rollup helper, and rotates archives once retention thresholds are breached.
4. **Dataset exports** — `export_dashboard_data.py` reads refreshed runs/state artefacts, emits JSON bundles, and updates the dataset manifest.
5. **Weekly payload** — A dedicated workflow aggregates run/latency/utilisation signals and posts the webhook payload, persisting the generated JSON alongside the manifest entry.
6. **Observability logging** — Each step appends a structured record to `ops/automation_runs.log` keyed by `job_id`, linking logs to artefacts and scheduler identifiers.

## Interface Requirements

### Signal Latency Sampling Cadence
- **Cadence**: Sample latency every 15 minutes during trading sessions (00:00–24:00 UTC) with aggregated hourly rollups; retain raw samples for 14 days and rollups for 90 days.
- **Sampling windows**: Each `analyze_signal_latency` run must emit `timestamp_utc`, `source`, `latency_ms`, `p95_latency_ms`, and `status` per data feed. Scheduler should trigger at `*/15 * * * *` (cron) with environment variable `LATENCY_SLO_MS` (default 120000).
- **Storage**: Append measurements to `ops/signal_latency.csv` with rotation when file exceeds 10 MB; archive rotated files under `ops/signal_latency_archive/%Y/%m/`.
- **Alerting**: When `p95_latency_ms` exceeds `LATENCY_SLO_MS` for two consecutive samples, emit a webhook alert using the weekly report schema’s `alerts` block (see below) with `severity=warning`; escalate to `severity=critical` if three consecutive breaches occur or `status` equals `error`.
- **Observability contract**: Automation must expose a health endpoint/log summary (stdout JSON) including `samples_written`, `rollups_written`, `breach_count`, and `next_rotation_bytes` for ingestion by higher-level orchestrators.

**Implementation notes**

- Extend `scripts/analyze_signal_latency.py` with `--rollup-retention-days` (default `90`) and `--raw-retention-days` (default `14`) flags so schedulers can tune retention without code edits.
- Add helper `analysis/latency_rollup.py` (follow-up) or equivalent module to consolidate aggregation logic shared by CLI and pytest fixtures.
- Emit structured logs with `job_id` and `schedule_trigger` to support traceability across overlapping cron runs.
- Guard concurrent executions with a file lock (`ops/signal_latency.lock`) and emit a skipped-run log entry when the lock cannot be acquired within 30 seconds.
- Capture per-source breach streak counters so alert escalations can include the exact number of consecutive breaches and last breaching timestamp.

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

**Implementation notes**

- Publish JSON Schema at `schemas/observability_weekly_report.schema.json`; treat the schema version as part of the payload (`schema_version` field) and bump when structure changes.
- Capture webhook delivery attempts in `ops/automation_runs.log` with entries: `job_id`, `attempt`, `status`, `response_ms`, `status_code`, `error`, `payload_checksum_sha256`.
- Provide a dry-run mode (`--dry-run-webhook`) that prints payload to stdout and writes to `out/weekly_report/<timestamp>.json` for manual inspection.
- Persist the last successful payload (and signature) under `ops/weekly_report_history/<week_start>.json` for audit recovery and to support replay without regenerating metrics.
- Implement deterministic payload ordering (sort runs/utilisation arrays) so checksum diffs only occur when field values change.
- Add a schema conformance unit test that loads the generated payload and validates it against the committed JSON Schema to prevent silent drift.

### Dashboard Export Datasets
- **Required exports**:
  1. **EV history** — Source: `ops/state_archive/<strategy>/<symbol>/<mode>/*`. Fields: `generated_at`, `strategy`, `symbol`, `mode`, `ev_alpha`, `ev_beta`, `ev_decay`, `win_rate_lcb`. Refresh daily at 00:30 UTC.
  2. **Slippage telemetry** — Source: `reports/portfolio_samples/router_demo/telemetry.json`. Fields: `generated_at`, `strategy`, `slippage_bps`, `reject_rate`, `fill_count`, `window_days`. Refresh daily post-latency job (01:00 UTC) to capture latest execution metrics.
  3. **Turnover summary** — Source: `runs/index.csv` + `runs/<id>/daily.csv`. Fields: `run_id`, `start_ts`, `end_ts`, `avg_trades_per_day`, `avg_trades_active_day`, `win_rate`, `drawdown_pct`. Refresh weekly before webhook dispatch (Sundays 23:30 UTC).
  4. **Latency rollups** — Source: aggregated samples appended to `ops/signal_latency_rollup.csv`. Fields: `hour_utc`, `source`, `p50_ms`, `p95_ms`, `breach_flag`. Refresh hourly via same cadence job.
- **Export contract**: `analysis/export_dashboard_data.py` must accept `--dataset <name>` to emit each dataset individually to `out/dashboard/<dataset>.json` and support a `--manifest out/dashboard/manifest.json` listing dataset versions with `checksum_sha256` and `generated_at`.
- **Distribution**: Weekly automation copies latest dataset bundle to shared storage with retention of 8 weeks; include metadata file `out/dashboard/README.json` describing refresh timestamps and upstream commands.

**Implementation notes**

- Add dataset-specific validation scripts under `tests/test_dashboard_datasets.py` to assert field presence and value ranges (e.g., turnover `avg_trades_per_day` > 0 when run active days > 0).
- Version manifest entries with monotonically increasing `sequence` numbers to simplify diffing when checksums differ.
- Include provenance metadata per dataset (source command, commit hash, upstream artefact path) so downstream analysts can reconstruct context without consulting scheduler logs.
- Introduce a post-export verification script (`scripts/verify_dashboard_bundle.py`, follow-up) that checks manifest completeness, dataset checksums, and retention policy compliance before uploads.
- Snapshot dataset manifests to `ops/dashboard_export_history/<timestamp>.json` to enable rollback without re-running exports.
- Require export jobs to write a heartbeat file (`ops/dashboard_export_heartbeat.json`) with `job_id`, `generated_at`, and dataset statuses so monitoring can detect stalled runs.

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
- **Disaster recovery drill**: Quarterly exercise restores the latest dataset bundle and weekly payload solely from `ops/*_history` artefacts to confirm recovery documentation remains accurate.
- **Security review**: Annual review validates webhook signature code paths, secret rotation notes, and log redaction, with findings recorded alongside the checklist.

### Implementation Milestones

| Milestone | Description | Exit Criteria | Owner |
| --- | --- | --- | --- |
| M1 – CLI Hardening | Land retention flags, schema emission, and structured logging changes. | PR merged with passing pytest + schema artefacts committed. | Research Ops |
| M2 – Scheduler Dry Runs | Configure cron/CI jobs in dry-run mode, verifying secrets, storage permissions, and artefact generation. | Dry-run payload + dataset bundle stored under `out/` with checklist sign-off. | Observability Oncall |
| M3 – Production Cutover | Enable live webhook + storage replication, rotate initial logs into `ops/automation_runs.log`. | First week of automation completes without manual intervention; weekly checklist archived. | Observability Oncall & Analytics Eng. |
| M4 – Post-launch Review | Assess SLO adherence, update dashboard/runbook anchors, file follow-up issues. | Retrospective doc added to `docs/progress_phase3.md`, backlog updated with residual tasks. | Cross-functional (Ops + Analytics) |

### Risk Register

| Risk | Impact | Mitigation | Contingency |
| --- | --- | --- | --- |
| Latency job overlap causing duplicate writes | Elevated false breach counts, CSV corruption | Use file lock + `job_id` guard; cron spacing with 1-minute buffer | Auto-prune duplicate rows in nightly maintenance script, alert via checklist |
| Webhook secret rotation unsynchronised | Failed weekly payload delivery | Document rotation window + oncall notification in `docs/state_runbook.md` | Fallback to email summary using dry-run payload until secret restored |
| Dashboard dataset schema drift | Downstream notebooks fail | Versioned manifest + pytest contract tests | Rollback to last successful bundle stored under retention policy |
| Shared storage outage during export | Weekly dataset bundle missing | Write exports locally first, queue upload retries with exponential backoff | Provide manual upload runbook leveraging retained local artefacts |

## Follow-up Actions
1. Draft detailed CLI design updates for cadence controls (`--rollup-retention-days`, webhook retries, dataset manifests).
2. Create regression checklist at `docs/checklists/p3_observability_automation.md` aligning with validation checkpoints.
3. Update `docs/state_runbook.md` with new runbook anchors for latency sampling and webhook escalation.
4. Coordinate with analytics engineering to provision shared storage paths and retention policy documentation.

## Operational Readiness Checklist (Snapshot)

| Area | Validation Owner | Exit Criteria |
| --- | --- | --- |
| Scheduler configuration | Observability Oncall | Cron specs committed, dry-run logs linked in `docs/progress_phase3.md`. |
| Secrets management | Research Ops | Rotation calendar documented, last smoke test timestamp recorded. |
| Artefact retention | Analytics Engineering | `ops/*_history` directories populated with at least two retained rotations. |
| Monitoring hooks | Observability Oncall | Heartbeat files ingested by monitoring, alerts verified in staging. |

## Outstanding Questions & Decisions Log

| Topic | Status | Owner | Next Step |
| --- | --- | --- | --- |
| Shared storage namespace | Open | Analytics Engineering | Confirm final path and ACLs before M2. |
| PagerDuty escalation mapping | Open | Observability Oncall | Map automation alerts to existing PD services and document in runbook. |
| JSON Schema versioning cadence | Proposed | Research Ops | Establish version bump policy tied to release tags. |

## References
- [docs/observability_plan.md](../observability_plan.md)
- [docs/observability_dashboard.md](../observability_dashboard.md)
- [docs/progress_phase3.md](../progress_phase3.md)

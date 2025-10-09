# Data Quality Alert Operations Runbook

This runbook defines how operators should respond when the
`scripts/check_data_quality.py` workflow emits a
`data_quality_failure` webhook. Follow these steps to keep the daily
ingestion pipeline accountable and to document recoveries in a
consistent location.

## Alert Overview

- **Trigger sources**
  - `python3 scripts/check_data_quality.py --webhook ...` when run
    manually or through
    `python3 scripts/run_daily_workflow.py --check-data-quality`.
  - Failures fire when either `--fail-under-coverage` is breached or
    when `--fail-on-calendar-day-warnings` is combined with
    `--calendar-day-summary`. Duplicate saturation also raises a
    failure once the CLI sees at least the configured number of
    duplicate timestamp groups (`--fail-on-duplicate-groups`). The
    daily workflow enables this guard by default with a threshold of 5.
- **Payload fields**
  - `event`: Always `data_quality_failure`.
  - `csv_path`, `symbol`, `timeframe`: Identify the audited data set.
  - `coverage_ratio`, `missing_rows_estimate`, `gap_count`,
    `duplicate_groups`: Primary metrics that justify the alert.
  - `calendar_day_warnings`: List of UTC days with coverage below the
    configured threshold.
  - `generated_at`: UTC timestamp recorded by the CLI.
- **Artifacts to inspect**
  - `reports/data_quality/<symbol>_<tf>_summary.json`
  - `reports/data_quality/<symbol>_<tf>_gap_inventory.csv|json`
  - Optional duplicate exports if the CLI was invoked with
    `--out-duplicates-*` flags.

## Immediate Triage Checklist

1. **Confirm alert scope** — Extract `symbol`, `timeframe`, and
   `csv_path` from the webhook payload. If the alert came from the
   daily workflow, cross-check the run invocation in the workflow log
   or `state.md` entry for that day.
2. **Open the summary JSON** — Review
   `reports/data_quality/<symbol>_<tf>_summary.json` and verify the
   reported `coverage_ratio`, `gap_count`, and
   `calendar_day_summary.warnings` match the alert payload.
3. **Inspect gap/duplicate inventories** — Use the exported CSV/JSON
   inventories to identify which UTC ranges require backfills or
   deduplication. If the daily workflow was invoked with the default
   manifest, the inventories reside under `reports/data_quality/`.
4. **Reproduce locally if needed** — Run the CLI with the flags that
   triggered the alert to confirm whether the issue persists or has
   been resolved by a manual retry. Example reproduction:

   ```bash
   python3 scripts/check_data_quality.py \
     --csv validated/USDJPY/5m.csv \
     --symbol USDJPY \
     --out-json reports/data_quality/usdjpy_5m_summary.json \
     --out-gap-csv reports/data_quality/usdjpy_5m_gap_inventory.csv \
     --calendar-day-summary \
     --fail-under-coverage 0.995 \
     --fail-on-calendar-day-warnings
   ```

5. **Schedule remediation** — Decide whether the resolution requires a
   data backfill (`scripts/pull_prices.py`), manual CSV patching, or an
   ingest fallback change. Capture the action plan in the acknowledgement
   log described below.

## Acknowledgement Tracking

Log every alert and follow-up inside
[`ops/health/data_quality_alerts.md`](../ops/health/data_quality_alerts.md)
so reviewers can verify that each notification received an owner and
resolution. Append a row to the Markdown table with the following
fields:

| Column | Description |
| --- | --- |
| `alert_timestamp` | `generated_at` value from the webhook payload |
| `symbol` / `tf` | Symbol and timeframe reported by the alert |
| `coverage_ratio` | Coverage value captured in the alert payload |
| `ack_by` | Initial responder (name or handle) |
| `ack_timestamp` | When acknowledgement was recorded |
| `status` | `investigating`, `backfill-running`, `resolved`, or `escalated` |
| `remediation` | Command references or notes describing the fix |
| `follow_up` | Tickets/tasks created for long-term mitigation |

Keep the log sorted with newest entries at the top and include command
snippets (for example `python3 scripts/pull_prices.py --symbol USDJPY`
or reruns of the audit CLI) inside the `remediation` column for quick
replay.

## Escalation Triggers

Escalate the alert to the broader operations channel and capture the
handoff in `state.md` when any of the following conditions occur:

- **No acknowledgement within 30 minutes** of the webhook firing.
- **Repeated failures** — The same symbol/timeframe triggers alerts in
  two consecutive workflow runs.
- **Severe coverage drop** — `coverage_ratio < 0.98` or more than two
  consecutive `calendar_day_warnings` entries.
- **Duplicate saturation** — `duplicate_groups >= 5` after applying the
  production filters. The daily workflow already fails the audit when
  this guard triggers, so you should see an alert as soon as the
  threshold is breached.

When escalating, include links to the summary JSON, gap inventories, and
the acknowledgement table entry. Create or update the relevant backlog
or `docs/todo_next.md` items if the remediation requires multiple work
sessions.

## Wrap-up

1. Re-run the audit CLI to confirm the failure no longer reproduces.
2. Update the acknowledgement table row to `resolved` (or `escalated` if
   the issue persists) with the verification timestamp.
3. Append a short note to `state.md` summarising the resolution steps so
   the session log remains authoritative.

Maintaining this loop keeps coverage anomalies visible, auditable, and
triaged without drifting from the Definition of Done for the data
quality backlog.

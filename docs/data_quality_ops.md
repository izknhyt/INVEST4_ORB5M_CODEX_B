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
    duplicate timestamp groups (`--fail-on-duplicate-groups`) or a
    single timestamp expands beyond the maximum allowed occurrences
    (`--fail-on-duplicate-occurrences`). The daily workflow enables
    these guards by default with thresholds of 5 groups and 3
    occurrences.
- **Payload fields**
  - `event`: Always `data_quality_failure`.
  - `csv_path`, `symbol`, `timeframe`: Identify the audited data set.
  - `coverage_ratio`, `missing_rows_estimate`, `gap_count`,
    `duplicate_groups`: Primary metrics that justify the alert.
  - `calendar_day_warnings`: List of UTC days with coverage below the
    configured threshold.
  - `generated_at`: UTC timestamp recorded by the CLI.
- **Artifacts to inspect**
  - `reports/data_quality/<symbol_lower>_<tf_token>_summary.json` — structured audit summary covering coverage ratios, gap metrics, and calendar-day details.
  - `reports/data_quality/<symbol_lower>_<tf_token>_gap_inventory.csv` / `.json` — full gap inventory exported when `--out-gap-csv` / `--out-gap-json` are provided (the daily workflow enables both). The CSV is emitted with headers even when no gaps are present, making downstream parsing deterministic.
  - Optional duplicate exports in the same directory if the CLI was invoked with `--out-duplicates-*` flags.

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
   inventories in `reports/data_quality/` to identify which UTC ranges
   require backfills or deduplication. Gap filenames follow the
   `<symbol_lower>_<tf_token>_gap_inventory.csv|json` pattern; open the
   CSV (for example with `python3 - <<'PY'` previews) to confirm the
   `start_timestamp` and `missing_rows_estimate` columns before drafting
   a remediation plan.
4. **Reproduce locally if needed** — Run the CLI with the flags that
   triggered the alert to confirm whether the issue persists or has
   been resolved by a manual retry. Example reproduction:

   ```bash
   python3 scripts/check_data_quality.py \
     --csv validated/USDJPY/5m_with_header.csv \
     --symbol USDJPY \
     --out-json reports/data_quality/usdjpy_5m_summary.json \
     --out-gap-csv reports/data_quality/usdjpy_5m_gap_inventory.csv \
     --out-gap-json reports/data_quality/usdjpy_5m_gap_inventory.json \
     --calendar-day-summary \
     --fail-under-coverage 0.995 \
     --fail-on-calendar-day-warnings
   ```

   The CLI prefers the headered snapshot. Running against
   `validated/<SYMBOL>/5m.csv` (legacy headerless format) increments the
   `missing_cols` counter and suppresses coverage ratio checks, so verify
   `5m_with_header.csv` exists before attempting a reproduction. Capture
   the reported `coverage_ratio` and `calendar_day_summary.warnings`
   values from stdout — they feed directly into the acknowledgement log.

5. **Schedule remediation** — Decide whether the resolution requires a
   data backfill (`scripts/pull_prices.py`), manual CSV patching, or an
   ingest fallback change. Capture the action plan in the acknowledgement
   log described below.

## Acknowledgement Tracking

Log every alert and follow-up inside
[`ops/health/data_quality_alerts.md`](../ops/health/data_quality_alerts.md)
so reviewers can verify that each notification received an owner and
resolution. Prefer the helper CLI to avoid manual Markdown edits:

```bash
python3 scripts/record_data_quality_alert.py \
  --alert-timestamp 2026-06-12T09:41:00Z \
  --symbol USDJPY \
  --coverage-ratio 0.2018 \
  --status investigating \
  --ack-by codex \
  --remediation "Reviewing reports/data_quality/usdjpy_5m_summary.json" \
  --follow-up "docs/task_backlog.md#p0-15-data-quality-alert-ops"
```

Append new rows to the top of the table so the latest alerts stay
visible. Add `--dry-run` to preview the Markdown row or `--ack-timestamp`
when recording historical acknowledgements. Keep the following column
definitions handy while confirming the payload:

- The helper refuses coverage ratios outside the inclusive `[0, 1]` range
  and rejects timestamps missing an explicit offset or `Z` suffix. This
  prevents malformed input from corrupting the shared log.
- Offset timestamps are normalised to UTC with a `Z` suffix so later
  automation can diff acknowledgement rows without handling per-entry
  timezone math.

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

To sanity-check the payload before writing, run the helper with
`--dry-run` — the Markdown row prints to stdout without modifying the log.
Once the contents look correct, rerun the command without `--dry-run` to
append the entry. The tool automatically inserts the row beneath the table
header and normalises multi-line remediation notes by replacing newlines
with `<br>` tags.

## Escalation Triggers

Escalate the alert to the broader operations channel and capture the
handoff in `state.md` when any of the following conditions occur:

- **No acknowledgement within 30 minutes** of the webhook firing.
- **Repeated failures** — The same symbol/timeframe triggers alerts in
  two consecutive workflow runs.
- **Severe coverage drop** — `coverage_ratio < 0.98` or more than two
  consecutive `calendar_day_warnings` entries.
- **Duplicate saturation** — `duplicate_groups >= 5` or
  `duplicate_max_occurrences >= 3` after applying the production
  filters. The daily workflow already fails the audit when either guard
  triggers, so you should see an alert as soon as the threshold is
  breached.

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

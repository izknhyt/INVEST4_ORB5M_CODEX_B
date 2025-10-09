# Data Quality Alert Acknowledgements

Log every `data_quality_failure` webhook received from
`scripts/check_data_quality.py` or the daily workflow. Append new
records to the top of the table so the most recent alerts are easiest to
find.

> Tip: use `python3 scripts/record_data_quality_alert.py` to append a row
> without editing this table manually. The script normalises coverage
> ratios and converts multi-line remediation notes to `<br>` tags.

| alert_timestamp (UTC) | symbol | tf | coverage_ratio | ack_by | ack_timestamp (UTC) | status | remediation | follow_up |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-10-09T14:41:49Z | USDJPY | 5m | 0.2018 | codex | 2025-10-09T14:41:58Z | resolved | Re-ran python3 scripts/check_data_quality.py --csv validated/USDJPY/5m_with_header.csv --symbol USDJPY --out-json reports/data_quality/usdjpy_5m_summary.json --out-gap-csv reports/data_quality/usdjpy_5m_gap_inventory.csv --out-gap-json reports/data_quality/usdjpy_5m_gap_inventory.json --calendar-day-summary --calendar-day-coverage-threshold 0.98 --fail-under-coverage 0.995 --fail-on-calendar-day-warnings --fail-on-duplicate-groups 5 --fail-on-duplicate-occurrences 3 to confirm recovery. | docs/task_backlog.md#p0-15-data-quality-alert-ops |
| 2026-06-02T08:15:00Z | USDJPY | 5m | 0.9920 | codex | 2026-06-02T08:15:00Z | investigating | Investigating Dukascopy fallback | docs/task_backlog.md#p0-15-data-quality-alert-ops |
| 2025-10-09T12:13:30Z (dry-run) | USDJPY | 5m | 0.1423 | codex (dry-run) | 2025-10-09T12:13:30Z | resolved | Dry-run validation forcing 1m expectation: `python3 scripts/check_data_quality.py --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --expected-interval-minutes 1 --calendar-day-summary --fail-under-coverage 0.995 --fail-on-calendar-day-warnings --calendar-day-coverage-threshold 0.995 --out-json /tmp/dq_summary_dry_run.json`<br>Reviewed calendar-day warnings and coverage outputs to confirm escalation fields. | Documented pilot outcome in docs/task_backlog.md#p0-15-data-quality-alert-ops |

> Status values: `investigating`, `backfill-running`, `resolved`,
> `escalated`.

Link remediation commands (e.g. rerunning `scripts/check_data_quality.py`
or invoking ingest fallbacks) directly in the table so reviewers can
trace the action history.

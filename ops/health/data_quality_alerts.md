# Data Quality Alert Acknowledgements

Log every `data_quality_failure` webhook received from
`scripts/check_data_quality.py` or the daily workflow. Append new
records to the top of the table so the most recent alerts are easiest to
find.

| alert_timestamp (UTC) | symbol | tf | coverage_ratio | ack_by | ack_timestamp (UTC) | status | remediation | follow_up |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

> Status values: `investigating`, `backfill-running`, `resolved`,
> `escalated`.

Link remediation commands (e.g. rerunning `scripts/check_data_quality.py`
or invoking ingest fallbacks) directly in the table so reviewers can
trace the action history.

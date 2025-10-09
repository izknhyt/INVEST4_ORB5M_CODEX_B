# P0-17 Data quality acknowledgement duplicate guard — DoD checklist

- [x] Review `ops/health/data_quality_alerts.md` to confirm existing rows follow the single-entry-per-alert convention.
- [x] Update `scripts/record_data_quality_alert.py` so duplicate alert timestamp + symbol + timeframe entries fail with a clear error unless an explicit override flag is provided.
- [x] Add regression tests covering both the duplicate failure and the override path.
- [x] Refresh `docs/data_quality_ops.md` and the acknowledgement log guidance (`ops/health/data_quality_alerts.md`) with the new guardrail and override instructions.
- [x] Run `python3 -m pytest` and ensure the suite passes.

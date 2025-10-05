# Portfolio Router Sample Inputs

This directory contains synthetic telemetry and strategy metrics used by the
portfolio monitoring tests.  The files in `router_demo/` simulate a live router
snapshot with two strategies:

- `day_orb_5m_v1` (Day breakout) with modest utilisation.
- `tokyo_micro_mean_reversion_v0` (Scalping) providing decorrelated flow.

The metrics files expose minimal equity curves so the monitoring script can
compute aggregate drawdowns without depending on larger artifacts.  The
telemetry snapshot mirrors the `PortfolioTelemetry` schema consumed by
`core.router_pipeline.build_portfolio_state`.

Use these fixtures as a contract reference for `scripts/report_portfolio_summary.py`.

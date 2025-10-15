# Day ORB Optimization & Adaptive Deployment Plan

## 0. Executive Summary
- Objective: build a repeatable loop that learns from historical Day ORB 5m simulations, surfaces the highest-return parameter sets under risk constraints, and readies them for live deployment with auditable artefacts.
- Outcome: any operator can run one command bundle to ingest new data, re-optimise parameters, review auto-generated reports, and push/rollback state with full traceability.
- Deliverables: experiment history repository, parameter sweep + Bayesian optimisation tooling, gate diagnostics with EV attribution, pseudo-live adaptive updates, risk/portfolio integration, and Go/No-Go automation with documentation updates.

## 0.1 Scope & Guardrails
- **In scope**: USDJPY Day ORB 5m Conservative/Bridge modes, `scripts/run_sim.py` CLI + supporting analysers, experiment storage, router/risk surface hooks, docs & runbooks.
- **Out of scope**: new strategy logic unrelated to parameter tuning, multi-symbol expansion, production data ingest overhauls, UI dashboards beyond Markdown/JSON outputs.
- **Constraints**: keep Python ≥3.10 compatibility, no schema changes without migration notes, prefer append-only artefacts (Parquet + JSON) for review, honour existing CI/pytest command bundle (`python3 -m pytest`).

## 1. Architecture Overview
1. **Data & Experiment Layer** – normalise every backtest result into Parquet (`experiments/history/records.parquet`, regenerated locally) plus per-run JSON (`experiments/history/runs/<run_id>.json`), storing metrics, risk stats, gate counts, parameters, data fingerprints.
2. **Optimisation Layer** – run grid/random/Bayesian sweeps via `scripts/run_param_sweep.py`, enforce hard risk constraints, compute Pareto fronts, and emit best candidates.
3. **Diagnostics Layer** – quantify gate-block EV loss with `scripts/summarize_strategy_gate.py` extensions and publish Markdown diagnostics.
4. **Adaptive Layer** – pseudo-live updater (`scripts/update_state.py --simulate-live`) adjusts thresholds within bounded deltas, integrates risk limits, and supports auto rollback.
5. **Governance Layer** – `scripts/generate_experiment_report.py` & `scripts/propose_param_update.py` create approval packets, update docs, and gate state changes behind human review.

## 2. Component Design
### 2.1 Experiment Repository
- `scripts/log_experiment.py` appends entries to Parquet + JSON, recording SHA256/row-count for datasets, run command strings, git commit, runtime environment.
- Integrity checks via `scripts/recover_experiment_history.py` rebuild the Parquet from JSON when hashes mismatch.

### 2.2 Parameter Optimisation Engine
- `configs/experiments/<name>.yaml` defines search space, seasonal slices, hard constraints (e.g., `max_drawdown <= 0.05`, `trades_per_month >= 20`).
- `python3 scripts/run_param_sweep.py --experiment day_orb_core --workers 4 --max-trials 200` supports:
  - `--search grid|random|bayes`
  - `--score sharpe:max --constraint dd:0.05 --constraint trades_per_month:20`
  - seasonal scoring (`--subperiod 2022Q1` etc.) to guard against regime bias.
- `python3 scripts/select_best_params.py --experiment day_orb_core --out reports/simulations/day_orb_core/best_params.json` filters to feasible Pareto front and writes ranked candidates.

### 2.3 Gate Diagnostics
- Extend `scripts/summarize_strategy_gate.py` to compute per-reason EV loss & volume gap; store JSON at `reports/day_orb/gate_breakdown_<run_id>.json` and Markdown at `reports/day_orb/gate_diagnostics_<date>.md`.
- Provide quick command: `python3 scripts/summarize_strategy_gate.py --run-dir <run> --stage gate_block --ev-report --top 15`.

### 2.4 Adaptive Update & Rollback
- `python3 scripts/update_state.py --simulate-live --dry-run --max-delta 0.2 --var-cap 0.04` ingests the latest data slice, adjusts thresholds (bounded per parameter), and outputs proposed diff (`ops/state_archive/<ts>/state.json`).
- Abnormal conditions (BOCPD regime change, drawdown spike, data anomaly) trigger automatic rollback to prior archive and send alerts via `notifications/emit_signal.py --channel risk-alerts`.
- Manual override: `python3 scripts/disable_auto_adjust.py --reason <text>` logs the pause in `state.md` and halts adjustments until re-enabled.

### 2.5 Risk & Portfolio Integration
- `python3 scripts/run_param_sweep.py --portfolio-config configs/portfolio/day_orb_suite.yaml` evaluates correlated strategies, estimating VAR and liquidity usage.
- Verify allocations by building the router snapshot and portfolio summary already in the repo:
  - `python3 scripts/build_router_snapshot.py --output runs/router_pipeline/day_orb --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml --manifest-run day_orb_5m_v1=reports/portfolio_samples/router_demo/metrics/day_orb_5m_v1.json --manifest-run tokyo_micro_mean_reversion_v0=reports/portfolio_samples/router_demo/metrics/tokyo_micro_mean_reversion_v0.json --positions day_orb_5m_v1=1 --positions tokyo_micro_mean_reversion_v0=1 --correlation-window-minutes 240 --indent 2`
  - `python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/day_orb --output reports/portfolio_summary_day_orb.json --indent 2`
  These commands provide the Go/No-Go sanity check without requiring new tooling.

### 2.6 Reporting & Approvals
- `python3 scripts/generate_experiment_report.py --experiment day_orb_core --out reports/experiments/day_orb_core_2026w32.md`
  - includes metrics table, seasonal breakdown, gate EV chart, risk comparison, pseudo-live drift vs backtest, recommendations.
- `python3 scripts/propose_param_update.py --experiment day_orb_core --best reports/simulations/day_orb_core/best_params.json` produces PR template, updates `docs/go_nogo_checklist.md`, `docs/progress_phase4.md`, and opens backlog links.

## 3. Workflow
### 3.1 Daily
1. `python3 scripts/check_data_quality.py --csv validated/USDJPY/5m.csv --symbol USDJPY --out-json reports/data_quality/usdjpy_5m_daily.json --fail-under-coverage 0.995`.
2. `python3 scripts/update_state.py --simulate-live --dry-run --max-delta 0.2 --var-cap 0.04` and review warnings.
3. Append notes to `state.md`, ship alerts if thresholds breached.

### 3.2 Weekly
1. `python3 scripts/run_param_sweep.py --experiment day_orb_core --search bayes --max-trials 300 --workers 4`.
2. `python3 scripts/select_best_params.py --experiment day_orb_core --out reports/simulations/day_orb_core/best_params.json`.
3. `python3 scripts/generate_experiment_report.py --experiment day_orb_core`.
4. `python3 scripts/propose_param_update.py --experiment day_orb_core --best reports/simulations/day_orb_core/best_params.json` to start approval.

### 3.3 Go/No-Go
- Review Markdown packet + artefacts.
- Run `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --load-best day_orb_core --mode conservative --out-dir runs/review/day_orb_core_latest` for confirmation.
- Approvers sign off via PR workflow; on success run live/paper switch.

## 4. Implementation Roadmap (6 Weeks)
1. **W1** – Stand up experiment repository, migrate historical runs, document in `docs/progress_phase4.md`.
2. **W2** – Deliver grid/random sweeps, best-param emitter, initial Markdown reports.
3. **W3** – Add Bayesian optimiser, seasonal guards, gate EV attribution, Parquet recovery tooling.
4. **W4** – Pseudo-live updater with rollback + alerting, integrate risk caps, update runbooks.
5. **W5** – Portfolio-aware sweeps, router validation, Go/No-Go PR automation.
6. **W6** – CI/cron wiring, paper-trade validation, drift monitoring dashboards, close-out review.

## 5. Test & Validation Strategy
- Core regression: `python3 -m pytest` + targeted suites (`tests/test_run_param_sweep.py`, `tests/test_update_state.py`) to be added.
- Scenario bundles: until the dedicated stress harness lands (tracked via backlog follow-up), create shock windows by slicing the validated feed — for example `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --start-ts 2020-03-01T00:00:00Z --end-ts 2020-04-30T23:55:00Z --out-dir runs/scenarios/day_orb_panic_202003`. Once `scripts/build_stress_dataset.py` (planned) is available, swap to its generated CSV/JSON outputs for repeatability.
- Consistency check: `python3 scripts/run_sim.py ... --load-best day_orb_core` should match metrics stored in the selected baseline run (`runs/sweeps/day_orb_core/<best_run>/metrics.json`) within tolerances (Sharpe ±0.05, maxDD ±0.2%).
- Drift monitor: compare pseudo-live performance vs backtest via `python3 scripts/compare_metrics.py --left runs/sweeps/day_orb_core/<best_run>/metrics.json --right runs/pseudo_live/latest/metrics.json --tolerance 0.05`.

## 6. Risks & Mitigations
| Risk | Mitigation |
| --- | --- |
| Data anomalies corrupt optimisation | Enforce daily data audit; stop sweeps when `status=invalid_data`; maintain recovery log. |
| Bayesian optimiser overfits low sample regimes | Require seasonal minima, fallback to random search, log warning when trials < threshold. |
| Auto adjustments degrade live performance | Limit per-day deltas, require manual approval for large shifts, implement automatic rollback triggers. |
| Portfolio VAR overshoot | Integrate VAR/liq caps into sweep scoring; fail candidate selection when exceeded. |
| Operational overload | Auto-generate reports/PR templates; synchronise `state.md`/docs via scripts; send digest notifications. |

## 7. Definition of Done
- Experiment history populated, validated against legacy runs, and recoverable from JSON.
- Parameter sweep CLI + Bayesian optimiser + best-params emitter operational with tests.
- Gate diagnostics output EV-aware reports saved under `reports/day_orb/`.
- Pseudo-live updater adjusts parameters within caps, logs to `ops/state_archive/`, and supports rollback/alerts.
- Go/No-Go workflow auto-produces Markdown + PR artefacts, references updated docs (`docs/go_nogo_checklist.md`, `docs/progress_phase4.md`).
- Regression commands executed (`python3 -m pytest`, weekly sweep dry-run, pseudo-live dry-run) and recorded in progress docs.

## 8. References & Follow-up
- Aligns with backlog initiative P0-09 "On-demand Day ORB Simulation Check" and new tasks enumerated in `docs/task_backlog.md` (see latest update).
- Detailed implementation notes live in `docs/day_orb_optimization_detailed_design.md`.
- See also: `docs/simulation_plan.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md`, `docs/observability_dashboard.md` for operational context.

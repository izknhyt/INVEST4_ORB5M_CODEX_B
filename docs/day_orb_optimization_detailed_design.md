# Day ORB Optimisation & Adaptive Deployment — Detailed Design v0.1

> Primary references: [docs/plans/day_orb_optimization.md](plans/day_orb_optimization.md), [docs/task_backlog.md](task_backlog.md#p0-20-day-orb-experiment-history-bootstrap-open), [docs/progress_phase4.md](progress_phase4.md), [docs/state_runbook.md](state_runbook.md), [docs/go_nogo_checklist.md](go_nogo_checklist.md).

## 0. Executive Summary (Lead Engineer POV)
- This document decomposes the high-level plan into implementable modules with explicit data contracts, failure handling, and test strategy so P0-20〜P0-22 can proceed without rediscovery.
- Focus areas: experiment history bootstrap, parameter optimisation engine, gate diagnostics, pseudo-live adaptation, risk/portfolio validation, reporting & approvals, and supporting automation hooks.
- Each module lists DoD checkpoints, CLI/API signatures, data schemas, and observability hooks required for regression-proof delivery.

## 1. Goals & Non-Goals
- **Goals**
  - Provide reproducible storage for every Day ORB backtest run (metadata + artefacts) and guarantee recovery paths.
  - Automate parameter exploration (grid/random/BO) with constraint enforcement, output ranking, and artefact logging.
  - Quantify gate blockage impact and surface actionable diagnostics automatically.
  - Enable pseudo-live adaptive adjustments with hard safety rails, alerting, and rollback operations.
  - Integrate Day ORB outputs into the router/portfolio pipeline and produce operator-ready Go/No-Go packets.
- **Non-Goals**
  - Introducing new trading strategies or router scoring algorithms beyond configuration of existing modules.
  - Building UI dashboards; Markdown/JSON artefacts remain the delivery format.
  - Live trading automation; scope ends at paper-ready operational readiness.

## 2. Assumptions & Prerequisites
- Python 3.10+ environment with existing dependencies listed in [docs/dependencies.md](dependencies.md). Additional packages (e.g., `optuna` for BO) must be pinned in `runtime.yml` when introduced.
- Validated USDJPY 5m data (`validated/USDJPY/5m.csv`) covers the backtest window, and `scripts/check_data_quality.py` passes with production flags before optimisation tasks start.
- `runs/index.csv` is up-to-date via `scripts/rebuild_runs_index.py` so legacy runs can be migrated automatically.
- Codex sessions adhere to [docs/codex_workflow.md](codex_workflow.md) for state/doc synchronisation, and approvals remain on-request.
- No network egress; all tooling must operate offline.

## 3. System Overview
```
┌────────────────────┐
│scripts/run_sim.py  │
└───────┬────────────┘
        │ metrics.json / daily.csv / records.csv
┌───────▼────────────┐       ┌────────────────────────┐
│scripts/log_        │       │experiments/history/     │
│experiment.py       │──────▶│records.parquet + runs/* │
└───────┬────────────┘       └─────────┬──────────────┘
        │                               │
        │                               ▼
        │                 ┌────────────────────────┐
        │                 │scripts/run_param_sweep │
        │                 │+ select_best_params    │
        │                 └─────────┬──────────────┘
        │                           │best_params.json / reports
        ▼                           ▼
┌────────────────────┐   ┌────────────────────────┐
│scripts/summarize_  │   │scripts/update_state.py │
│strategy_gate.py    │   │--simulate-live         │
└────────┬───────────┘   └────────┬──────────────┘
         │ diagnostics             │ state diffs / alerts
         ▼                        ▼
┌────────────────────┐   ┌────────────────────────┐
│scripts/generate_   │   │scripts/build_router_   │
│experiment_report.py│   │snapshot.py + report…   │
└────────┬───────────┘   └────────┬──────────────┘
         ▼                        ▼
   Markdown packet          Portfolio summary
         │                        │
         └────────────┬───────────┘
                      ▼
            Go/No-Go decision
```

## 4. Module Specifications

### 4.1 Experiment History Repository (`experiments/history/*`)
- **DoD link**: [P0-20](task_backlog.md#p0-20-day-orb-experiment-history-bootstrap-open).
- **Responsibilities**
  - Persist every run with metadata + checksums (Parquet generated locally + tracked JSON).
  - Allow reconstruction of Parquet from JSON when corruption is detected.
  - Provide query helpers for sweeps, diagnostics, and reporting.
- **Files & Structures**
- `experiments/history/records.parquet`
    - Columns: `run_id`, `manifest_id`, `mode`, `timestamp_utc`, `commit_sha`, `dataset_sha256`, `dataset_rows`, `command`, `metrics_path`, `gate_report_path`, `equity`, `sharpe`, `max_drawdown`, `trades`, `win_rate`, `ev_gap`, `gate_block_count`, `router_gate_count`, `notes`.
    - Partition: none initially; future extension may use `manifest_id`.
    - Git tracking: excluded from commits; recreate via `scripts/recover_experiment_history.py --from-json` when needed.
  - `experiments/history/runs/<run_id>.json`
    - Schema mirrors Parquet + `artefacts` array (relative paths) + `runtime` block (duration_ms, debug flags).
- **CLI**
  - `python3 scripts/log_experiment.py --run-dir runs/tmp/day_orb5m_conservative_20251015_203034 --manifest-id day_orb_5m_v1 --mode conservative --commit-sha $(git rev-parse HEAD)`
    - Options: `--equity`, `--notes`, `--dataset-sha256`, `--dataset-rows`, `--dry-run`.
    - Behaviour: read metrics/daily/records, auto-detect dataset fingerprint from CSV path (fallback to manifest default). Append to Parquet + JSON; verify Parquet write success.
  - `python3 scripts/recover_experiment_history.py --from-json` rebuilds Parquet from JSON set, verifying row counts.
- **Error Handling**
  - If metrics missing → abort with `exit 2`, log to stderr, no partial writes.
  - If Parquet write fails → temporary file removed; JSON still written; `stdout` provides manual recovery command.
  - Detect duplicate `run_id` collisions and compare content hash; mismatch → abort.
- **Testing**
  - `tests/test_log_experiment.py` covering happy path, missing artefacts, duplicate detection, dry-run.
  - `tests/test_recover_experiment_history.py` verifying rebuild + checksum matching.

### 4.2 Parameter Optimisation Engine (`scripts/run_param_sweep.py`, `scripts/select_best_params.py`)
- **DoD link**: [P0-21](task_backlog.md#p0-21-day-orb-optimisation-engine-bring-up-open).
- **Responsibilities**
  - Execute sweeps using grid/random/Bayesian search.
  - Enforce hard constraints before scoring.
  - Emit ranked candidates and update experiment history.
- **CLI Contracts**
  - `python3 scripts/run_param_sweep.py --experiment configs/experiments/day_orb_core.yaml --search bayes --max-trials 300 --workers 4 --out runs/sweeps/day_orb_core --log-history`
    - YAML schema sections:
      - `manifest_path`, `search_space`, `constraints`, `seasonal_slices`, `scoring`, `bayes` (kernel, priors), `runner` (equity, debug flags), `data_filters`.
    - Output: per-trial directory `runs/sweeps/day_orb_core/<timestamp>_<seed>/metrics.json`, `params.json`, `log.json` (status, constraint results).
  - `python3 scripts/select_best_params.py --experiment day_orb_core --runs-dir runs/sweeps/day_orb_core --top-k 5 --out reports/simulations/day_orb_core/best_params.json`
    - Output JSON structure: `{

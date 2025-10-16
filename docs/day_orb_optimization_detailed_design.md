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
    - Output JSON structure:
      - Top-level keys
        - `experiment`: experiment identifier resolved from the YAML (`<namespace>/<name>` when declared, file stem otherwise).
        - `config_path`: repository-relative path to the resolved experiment configuration.
        - `generated_at`: ISO-8601 UTC timestamp emitted by `utcnow_iso()`.
        - `runs_dir`: repository-relative path to the sweep directory that was scanned.
        - `top_k`: integer cap applied to the ranking list.
        - `trials`: aggregate counters with four integers — `total` (all discovered `result.json` files), `completed` (status=`completed`), `feasible` (completed and all constraints passed), `pareto` (completed+feasible that survived Pareto filtering for the configured objectives).
        - `ranking`: ordered array (length ≤ `top_k`) of dictionaries. Each entry contains:
          - `rank`: 1-based position after scoring.
          - `trial_id`, optional `seed`, and `status` from the trial payload.
          - `feasible` boolean (status=`completed` and constraints all pass).
          - `score` (float) and `score_breakdown` (per-objective contributions) returned by `config.scoring.compute`.
          - `tie_breaker_key` array and `tie_breakers` list mirroring the configured tie-break metrics.
          - `constraints`: map from constraint id → `{status, metric, op, threshold, observed}`.
          - `constraints_summary`: `{passed: <count>, failed: [<ids>...]}` for quick inspection.
          - `pareto_optimal`: boolean flag indicating whether the candidate sits on the Pareto frontier for all objectives.
          - `params`, `metrics`, and `seasonal` payloads exactly as recorded in `result.json` (all JSON-serialisable dictionaries).
          - Provenance fields — `run_dir`, `result_path`, and (when available) `metrics_path` are normalised to repo-relative POSIX strings. `command`, `history`, and dataset fingerprint (`dataset_fingerprint` with `path`/`sha256`/`rows`) propagate unchanged.
        - Optional `infeasible`: present when `--include-infeasible` is passed and lists non-feasible completed trials with the same schema as `ranking` (minus `rank`).
        - Optional `notes`: experiment-level annotations pulled from the YAML (`history_notes`).
      - CLI stdout always emits a compact JSON line `{ "output": <path>, "feasible": <int> }` so batch runners can pick up the artefact path without parsing the full report.
      - Per-trial artefacts generated by `scripts/run_param_sweep.py`:
        - `trial_dir/result.json`: canonical payload with `trial_id`, `status`, `params`, `metrics`, `seasonal`, optional `score`, `constraints`, `history`, dataset fingerprint, `command_str`, and `run_dir` when the trial executed the backtester.
        - `trial_dir/manifest.yaml`: runner manifest snapshot to keep the evaluation reproducible.
        - When `--log-history` is set, completed runs are also registered through `experiments/history` via `log_experiment`.
      - Sweep-level JSON contracts:
        - `sweep_summary.json`: `{ experiment, config_path, timestamp, search, total_trials, completed, failures, dry_run }` with exit code `1` when any trial fails (non-completed status not equal to `dry_run`).
        - `log.json`: `{ experiment, config_path, generated_at, entries: [...], summary: { total, completed, success, violations, dry_run } }`, where each entry summarises a trial’s feasibility, failed constraints, dataset fingerprint, and canonical `result_path`.
  - **Error Handling**
    - `run_param_sweep.py`
      - Raises exit code `2` when a requested search strategy is unavailable (`NotImplementedError`), printing the message to stderr.
      - Propagates `RuntimeError` if `pandas` is absent when metrics post-processing is required (guarded by `_require_pandas`).
      - Each trial directory contains a `result.json` regardless of success; failed or interrupted trials record `status` ≠ `completed` and are still written so diagnostics aren’t lost.
    - `select_best_params.py`
      - Exit code `2` when the `runs_dir` is missing; stderr includes `Runs directory not found`.
      - Exit code `1` with `No trial results found` when no `result.json` files are present.
      - All other validation errors (invalid JSON, missing constraint metrics) propagate as stack traces so CI can fail loudly.
  - **Testing Strategy**
    - `tests/test_param_sweep_cli.py::test_run_param_sweep_dry_run` verifies dry-run planning, per-trial manifest snapshots, and the `sweep_summary.json` counters for deterministic grids.
    - `tests/test_param_sweep_cli.py::test_select_best_params_ranks_feasible` ensures ranking prefers feasible completions, ignores failed trials, and persists CLI artefacts.
    - `tests/test_select_best_params.py::test_select_best_params_pareto_filter` covers Pareto-front extraction, dataset fingerprints, constraint summaries, and ranking metadata.
    - Regression coverage relies on `python3 -m pytest tests/test_param_sweep_cli.py tests/test_select_best_params.py` before promoting any schema changes.

### 4.3 Gate Diagnostics (`scripts/summarize_strategy_gate.py`)
- **DoD link**: [Plan §2.3](plans/day_orb_optimization.md#23-gate-diagnostics) / [P4-04 backlog](task_backlog.md#p4-04-day-orb-シンプル化リブート2025-10-13追加) observability readiness.
- **Responsibilities**
  - Consume `records.csv` emitted by `scripts/run_sim.py --debug` and quantify why orders were gated (`strategy_gate`, `gate_block`, `router_gate`, etc.).
  - Provide both human-readable summaries and machine-parsable JSON for EV attribution dashboards and diff comparisons.
  - Support stage filtering so operators can contrast guardrails (cooldown, ATR floor, session filter) independently.
- **CLI**
  - `python3 scripts/summarize_strategy_gate.py --run-dir runs/tmp/day_orb5m_debug/USDJPY_conservative_20251013_232321 --stage gate_block --limit 15`
    - `--records`: explicit `records.csv` path; when omitted `--run-dir`/`records.csv` is used.
    - `--stage`: stage column to match (defaults to `strategy_gate`).
    - `--limit`/`--top`: maximum reasons displayed in text mode (default 10).
    - `--json`: switch stdout to JSON mode.
- **Output Schema**
  - Text mode prints a descending frequency list per reason with categorical histograms (`rv_band`, `spread_band`, `allow_low_rv`) and numeric aggregates (mean/min/max for fields like `or_atr_ratio`, `loss_streak`, `daily_loss_pips`).
  - JSON mode returns an object `{ <reason>: { "count": <int>, "numeric": { <field>: { count, mean, min, max } }, "categorical": { <field>: [[value, count], ...] } } }` sorted by `count`.
  - Numeric fields tracked: `or_atr_ratio`, `min_or_atr_ratio`, `atr_pips`, `loss_streak`, `daily_trade_count`, `qty`, `p_lcb`, etc. Categorical fields: `rv_band`, `spread_band`, `allow_low_rv` (extensible via constants in the module).
- **Error Handling**
  - Missing file → process aborts with `SystemExit` and message `records.csv not found at <path>` (non-zero exit for automation awareness).
  - CSV missing the `stage` column raises `SystemExit("records.csv is missing the 'stage' column")` to catch ingest regressions early.
  - When no rows match the requested stage, stdout receives `No records found for stage '<stage>' ...` and exit code `0` so cron tasks do not fail unnecessarily.
  - Non-numeric values in numeric fields are ignored (graceful coercion via `_coerce_float`).
- **Testing Strategy**
  - `tests/test_summarize_strategy_gate.py::test_summarize_strategy_gate_text` exercises the text renderer, categorical aggregation, and numeric statistics ordering.
  - `tests/test_summarize_strategy_gate.py::test_summarize_strategy_gate_json` locks the JSON schema including nested counts.
  - `tests/test_run_sim_cli.py::test_run_sim_debug_records_written` guarantees `run_sim.py --debug` populates the columns consumed here.
  - Operational validation pairs the CLI with real runs while diffing against prior JSON outputs (`reports/diffs/*.json`).

### 4.4 Adaptive Update Engine (`scripts/update_state.py --simulate-live`)
- **DoD link**: [Plan §2.4](plans/day_orb_optimization.md#24-adaptive-update--rollback).
- **Responsibilities**
  - Replay newly ingested bars into the Day ORB runner, update persistent `state.json`, and maintain `ops/state_archive/<strategy>/<symbol>/<mode>` snapshots with diffs.
  - Enforce pseudo-live guardrails (`--max-delta`, `--var-cap`, `--liquidity-cap`) and trigger rollbacks/alerts when anomalies occur.
  - Provide automation-friendly JSON so downstream schedulers, alerting hooks, and approval workflows can reason about state transitions.
- **CLI**
  - Core invocation: `python3 scripts/update_state.py --simulate-live --symbol USDJPY --mode conservative --max-delta 0.2 --var-cap 0.04 --liquidity-cap 1.5 --alert-mode auto --alert-webhook risk-alerts.json`
    - Data sources: `--bars` (defaults to `validated/<symbol>/5m.csv`), `--snapshot` for incremental replay metadata, `--state-in`/`--state-out` for manual override.
    - Runner overrides mirror `scripts/run_sim.py` (`--threshold-lcb`, `--min-or-atr`, `--or-n`, `--allowed-sessions`, etc.) so tuning changes can be staged without editing manifests.
    - Guardrail flags: `--simulate-live` toggles anomaly detection; `--max-delta`, `--var-cap`, `--liquidity-cap` bound parameter drift, VAR, and gross notional usage respectively.
    - Override management: `--override-action {status,disable,enable}` and `--override-path` to gate auto-application, with `--override-reason` required when disabling.
    - Alert routing: `--alert-mode {auto,disable,force}`, `--alert-webhook` override, latency/fallback logs default to `ops/state_alert_latency.csv` and `ops/state_alerts.log`.
    - Execution controls: `--dry-run` (preview only), `--chunk-size` for replay batching, `--json-out` to persist the final JSON payload.
- **Output JSON structure**
  - Success path prints a JSON object to stdout with:
    - `bars_processed`: integer count of new bars consumed; zero triggers the early-return payload `{ "message": "no_new_bars", "symbol": ..., "mode": ..., "last_ts": ... }`.
    - Backtest metrics flattened from `BacktestRunner.metrics.as_dict()` (trades, wins, sharpe, etc.).
    - `state_out`: final path written (even in dry-run, points to intended location), `simulate_live`, `dry_run`, and `override` status (`{status, reason, updated_at, path, enabled}`) for auditability.
    - `risk`: `{ "var": <float>, "liquidity_usage": <float> }` summarising risk metrics from the replay.
    - `anomalies`: array of violation dictionaries (`max_delta_exceeded`, `var_cap_exceeded`, `liquidity_cap_exceeded`) including offending fields and caps.
    - `diff`: truncated change set with `updated`/`added`/`removed` entries (`field`, `previous`, `current`, `abs_delta`).
    - `decision`: `{ "status": "applied"|"blocked"|"preview", "reasons": [ ... ] }` derived from override state, dry-run flag, and anomalies.
    - Archive metadata when applied: `strategy_key`, `archive_dir`, `ev_archive_latest`, `ev_archives_pruned`, `aggregate_ev_rc`, `diff_path`, `diff_status`, `diff_reason`.
    - When rollbacks fire, `rollback_triggered` is `true` and `alert` documents the webhook dispatch attempt (`mode`, `urls`, `timestamp`, `status`, fallback info when applicable).
  - Override management commands (`--override-action status|disable|enable`) also emit JSON payloads (`{override_path,status,reason,updated_at}`) for chatops consumption and exit without touching state.
- **Error Handling**
  - Missing bars file prints `{ "error": "bars_not_found", "path": ... }` with exit code `1`.
  - Override disable without `--override-reason` returns exit code `2` with JSON error.
  - When pandas/backtest errors bubble up during replay the script propagates exceptions (non-zero exit) so operators can inspect logs; partial archive writes are avoided unless the run is marked `applied`.
  - Guardrail violations under `--simulate-live` switch the decision to `blocked` yet still emit the diff and anomalies for review; archive snapshots are skipped unless `--dry-run` is false and guardrails pass.
- **Testing Strategy**
  - `tests/test_update_state.py` covers timestamp normalisation, dry-run anomaly logging, VAR/liquidity cap enforcement (including alert logging), and override-disabled behaviour.
  - `tests/test_run_daily_workflow.py::test_update_state_resolves_bars_override` ensures orchestration flows hand correct paths to the CLI.
  - `tests/test_live_ingest_worker.py::_run_update_state` verifies worker wrappers propagate lowercase modes and the CLI contract.
  - Regression guard: `python3 -m pytest tests/test_update_state.py tests/test_run_daily_workflow.py tests/test_live_ingest_worker.py` whenever modifying the pseudo-live pipeline.

### 4.5 Risk & Portfolio Integration (`scripts/build_router_snapshot.py`, `scripts/report_portfolio_summary.py`)
- **DoD link**: [Plan §2.5](plans/day_orb_optimization.md#25-risk--portfolio-integration).
- **Responsibilities**
  - Collate Day ORB (and partner) run metrics into router-ready telemetry, preserving manifest metadata and equity curves.
  - Compute pairwise correlations / correlation tag summaries, merge active positions, and surface portfolio budget headroom for Go/No-Go decisions.
  - Provide downstream reporting via `report_portfolio_summary.py` to validate risk exposure against governance caps.
- **CLI Workflows**
  - Snapshot build: `python3 scripts/build_router_snapshot.py --manifest configs/strategies/day_orb_5m.yaml --manifest tokyo_micro_mean_reversion.yaml --manifest-run day_orb_5m_v1=runs/sweeps/.../metrics.json --positions day_orb_5m_v1=1 --correlation-window-minutes 240 --output runs/router_pipeline/day_orb --indent 2`
    - Supports globbing directories (`--manifest` multiple times), explicit run overrides (`--manifest-run id=path` for `metrics.json` or run directories), and fallback to `runs/index.csv` (`--runs-index`).
    - Risk inputs: `--positions id=count`, `--category-budget category=pct`, `--category-budget-csv` (columns `category,budget_pct`), plus global `--correlation-window-minutes` for telemetry metadata.
    - Output directory defaults to `runs/router_pipeline/latest`; JSON indentation is adjustable via `--indent` (0 for compact).
  - Portfolio summary: `python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/day_orb --output reports/portfolio_summary_day_orb.json --indent 2`
    - Consumes the telemetry bundle and emits consolidated metrics (budget utilisation, breaches, correlation commentary) for review packets.
- **Output Schema**
  - Snapshot `telemetry.json` holds:
    - `active_positions`: map manifest id → quantity after applying overrides/defaults.
    - `category_utilisation_pct`, `category_caps_pct`, `category_budget_pct`, `category_budget_headroom_pct`: floats keyed by risk category.
    - `gross_exposure_pct` and `gross_exposure_cap_pct` (global leverage usage).
    - `strategy_correlations`: symmetric map of correlations per manifest pair and `correlation_meta` for tag-level maxima.
    - `execution_health`: aggregator output from `build_portfolio_state` (missing metrics, stale data, etc.).
    - `correlation_window_minutes`: echo of CLI flag for context.
  - Per-strategy metrics under `metrics/<manifest_id>.json` include manifest path, source run directory, `source_metrics`, preserved `equity_curve`, and optional runtime snapshot (drawdown, sharpe, trade counts) derived via `_build_runtime_metrics`.
  - `report_portfolio_summary.py` emits `{ "telemetry_path": ..., "generated_at": ..., "budget_status": ..., "breaches": [...], "warnings": [...], "positions": {...}, "correlation_summary": {...} }` — matching the schemas enforced in `tests/test_report_portfolio_summary.py` / `tests/test_portfolio_monitor.py`.
- **Error Handling**
  - Missing manifests or metrics raise `FileNotFoundError`/`ValueError` with explicit context (invalid equity curves, inconsistent lengths, absent budgets) to abort early.
  - Category budgets require either CLI flags or CSV; misformatted budgets throw `ValueError` with the problematic category value.
  - When correlations cannot be computed (insufficient points) the matrix falls back to zeros but remains present in the payload so diffing works.
- **Testing Strategy**
  - `tests/test_report_portfolio_summary.py` covers end-to-end CLI execution, zero-equity handling, manifest normalisation, correlation outputs, and ensures help text exposes new flags.
  - `tests/test_router_pipeline.py` validates helper utilities (runs index loading, correlation calculation) that back the CLI.
  - Continuous validation via `python3 -m pytest tests/test_report_portfolio_summary.py tests/test_portfolio_monitor.py tests/test_router_pipeline.py` prior to altering schema or CLI defaults.

### 4.6 Reporting & Approvals (`scripts/generate_experiment_report.py`, `scripts/propose_param_update.py`)
- **DoD link**: [Plan §2.6](plans/day_orb_optimization.md#26-reporting--approvals).
- **Responsibilities**
  - Transform optimisation outputs (`best_params.json`, gate diagnostics, portfolio telemetry) into operator-friendly Markdown packets with embedded tables, charts references, and follow-up checklists.
  - Automate PR preparation (`scripts/propose_param_update.py`) to sync docs (`docs/go_nogo_checklist.md`, `docs/progress_phase4.md`), populate reviewer tasks, and stage state archive diffs.
  - Capture reproducibility breadcrumbs (commands executed, artefact paths, commit SHA) inline so approvals can be replayed without reverse engineering.
- **CLI Contracts**
  - `python3 scripts/generate_experiment_report.py --experiment day_orb_core --best reports/simulations/day_orb_core/best_params.json --gate-json reports/day_orb/gate_breakdown_latest.json --portfolio runs/router_pipeline/day_orb/telemetry.json --out reports/experiments/day_orb_core_2026w32.md`
    - Inputs: best-params payload, gate diagnostics JSON, telemetry bundle, optional comparison metrics (baseline vs proposal) to chart improvements or regressions.
    - Outputs: Markdown with sections `Summary`, `Metrics`, `Constraint Compliance`, `Gate Diagnostics`, `Risk Snapshot`, `Next Steps`, plus embedded JSON references for auditors.
  - `python3 scripts/propose_param_update.py --experiment day_orb_core --best reports/simulations/day_orb_core/best_params.json --state-archive ops/state_archive/... --out docs/proposals/day_orb_core_2026w32.md`
    - Generates PR-ready Markdown, updates backlog/status documents, and can emit a machine-readable changelog (`--json-out`) for automation.
- **Schemas & Artefacts**
  - Markdown front matter includes experiment id, commit SHA, dataset fingerprint, optimisation window, and command bundle.
  - Embedded JSON attachments (written alongside Markdown) summarise reviewer checklist status: `{ "experiment": ..., "reports": [...], "approvals": { ... } }`.
  - Proposal generator exports `{ "pull_request": { "title": ..., "body": ... }, "docs_updated": [...], "state_archive": ... }` when `--json-out` is requested to integrate with bots.
- **Error Handling Expectations**
  - Missing prerequisite artefacts (best params, gate JSON, telemetry) must abort with exit code `2` and actionable stderr (e.g., `best_params not found`), never emitting partial Markdown.
  - Validation should ensure ranked candidates align with the report payload (trial ids present, metrics consistent) before rendering tables; discrepancies yield non-zero exit and mention offending trial ids.
  - Proposal automation should refuse to overwrite docs unless `--force` is passed, prompting operators when existing drafts are detected.
- **Testing Strategy**
  - Unit tests will fixture representative JSON inputs to verify Markdown sections, checklist propagation, and PR body templates.
  - Integration tests should cover failure handling (missing artefacts, mismatched ids) and end-to-end generation feeding into `scripts/propose_param_update.py`.
  - Regression guardrails integrate with the main suite via `python3 -m pytest tests/test_generate_experiment_report.py tests/test_propose_param_update.py`; reviewers run this bundle before approving parameter updates.

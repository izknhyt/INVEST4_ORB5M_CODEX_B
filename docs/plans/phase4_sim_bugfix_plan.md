# Phase 4 Simulation Bugfix & Refactor Plan

## 0. Executive Summary
- Focus: harden the Day ORB simulation pipeline before Phase 4 validation by removing deterministic and sporadic defects, then refactor the CLI and runner for maintainability without regressing financial outputs.
- Success hinges on shipping a reproducible baseline, codifying every bug into tests, and instrumenting the workflow so Codex Cloud and local operators can re-run the suite without guesswork.
- Deliverables: patched `scripts/run_sim.py` + runner modules, expanded pytest coverage, refreshed long-run artefacts under `runs/phase4/backtests/` and `reports/`, and updated operational documentation (`docs/progress_phase4.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md`).

## 1. Objectives & Success Criteria
- **Stability**: Conservative and Bridge 2018–2025 runs complete without crashes, non-deterministic fills, or missing artefacts.
- **Accuracy**: Metrics (`Sharpe`, `max_drawdown`, `annual_win_rate`, EV buckets) match archived baselines or expected improvements after parameter updates.
- **Regression Safety**: Every defect encountered during triage is converted into an automated test covering logic, CLI, and data quality. CI (`python3 -m pytest`) and long-run simulations must pass post-refactor.
- **Operational Readiness**: Documentation and `state.md` logs contain reproducible commands, artefact paths, and sign-offs for Phase 4 DoD (aligned with P4-01/P4-02/P4-03 backlog entries).

## 2. Context & Pain Points
- Reference run (`runs/phase4/backtests/USDJPY_conservative_20251012_140919`) exposed: inconsistent Brownian Bridge fill ordering, EV gate miscounts, stale CLI flags, and gaps when validated data snapshots changed.
- Manifest (`configs/strategies/day_orb_5m.yaml`) and dataset (`validated/USDJPY/5m.csv`) evolved during Phase 3 → 4 transition; regression coverage lagged behind the new defaults.
- Codex Cloud automation requires deterministic artefact layout (`reports/long_{mode}.json`, `*_daily.csv`) and verbose logging to unblock headless troubleshooting.

## 3. Workstreams Overview
| ID | Theme | Primary Outcomes | Key Artefacts |
| --- | --- | --- | --- |
| W1 | Baseline Reproducibility | Deterministic long-run outputs, diffable metrics, reproducible commands | `runs/phase4/backtests/*`, `reports/long_{mode}*.json/csv` |
| W2 | Defect Remediation & Guard Rails | Bug backlog flushed, targeted regression tests, CLI flag parity | `scripts/run_sim.py`, `tests/test_run_sim_cli.py`, `tests/test_runner*.py` |
| W3 | Structural Refactor | Modular CLI pipeline, shared I/O utilities, clearer logging | `scripts/run_sim.py`, `scripts/lib/run_sim_io.py` (new), logging configs |
| W4 | Observability & Ops Sync | Enhanced instrumentation, docs and state alignment, nightly automation spec | `docs/progress_phase4.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md` |

## 4. Detailed Playbook
### W1 — Baseline Reproducibility
1. Validate input data before any code change:
   - `python3 scripts/check_data_quality.py --csv validated/USDJPY/5m.csv --calendar-day-summary`
   - Document coverage in `docs/progress_phase4.md` and attach representative JSON snippets if anomalies exist.
2. Establish gold runs for both modes:
   - `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --start-ts 2018-01-01T00:00:00Z --end-ts 2025-12-31T23:55:00Z --out-json reports/long_conservative.json --out-daily-csv reports/long_conservative_daily.csv --out-dir runs/phase4/backtests --no-auto-state`
   - `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode bridge --start-ts 2018-01-01T00:00:00Z --end-ts 2025-12-31T23:55:00Z --out-json reports/long_bridge.json --out-daily-csv reports/long_bridge_daily.csv --out-dir runs/phase4/backtests --no-auto-state`
3. Diff `metrics.json` and `daily.csv` against archived runs; record deltas (expected vs unexpected) in `docs/progress_phase4.md` with direct file links.
4. Snapshot CLI stdout/stderr and key log excerpts into `runs/phase4/backtests/<timestamp>/session.log` for reproducibility.

### W2 — Defect Remediation & Guard Rails
1. Build a structured bug notebook (table or tracked issue list) capturing for each defect: reproduction command, observed vs expected, root cause hypothesis, priority (Blocker / High / Medium / Low).
2. Convert high-priority findings into failing tests before patching:
   - CLI/argument regressions → `tests/test_run_sim_cli.py`
   - Runner logic (fill sequencing, EV gate thresholds, trailing stops, state archival) → `tests/test_runner.py`, `tests/test_runner_features.py`
   - Data ingestion/validation gaps → `tests/test_data_robustness.py` with fixtures under `tests/fixtures/run_sim/`
3. Apply minimal hotfixes (Phase A) guided by tests, keeping public interfaces stable. Collect commit-level notes on impacted modules.
4. Maintain focused pytest loops during remediation:
   - `python3 -m pytest tests/test_run_sim_cli.py`
   - `python3 -m pytest tests/test_runner.py tests/test_runner_features.py`
   - `python3 -m pytest -k robustness --maxfail=1`
5. After each fix, rerun the relevant long-run command(s) to ensure financial outputs remain sane; log results in `docs/progress_phase4.md` alongside bug IDs.

### W3 — Structural Refactor
1. Once W2 test suite is green, extract the CLI into discrete helpers:
   - Argument parsing
   - Manifest + dataset resolution
   - Runner orchestration
   - Artefact writers / state integration
2. Move shared I/O helpers into `scripts/lib/run_sim_io.py` (new) or equivalent, ensuring unit tests cover JSON/CSV writes and directory handling.
3. Expand logging to emit structured events (EV gate decisions, Brownian Bridge probabilities, trailing stop adjustments) with unique context IDs for later correlation.
4. Enforce module boundaries with additional tests (e.g., `tests/test_run_sim_io.py`) and update imports to avoid circular dependencies.
5. Execute `python3 -m pytest` plus the long-run commands to certify parity before merging.

### W4 — Observability & Operational Sync
1. Surface new logging fields or behavioural toggles in `docs/state_runbook.md` (incident response) and `docs/go_nogo_checklist.md` (release sign-off).
2. Record every significant run and fix in `state.md` (timestamp, command, outcome, follow-up) to feed Codex Cloud automation.
3. Update `docs/progress_phase4.md` with:
   - Bug summary table (ID, fix status, regression test reference, artefact link)
   - Long-run metric snapshots after each major parameter or code change
   - Checklist of nightly/weekly automation commands (e.g., `python3 scripts/run_sim.py ... --no-auto-state`)
4. Define the nightly smoke test bundle for Codex Cloud (`python3 -m pytest tests/test_run_sim_cli.py tests/test_runner.py`, plus a shortened simulation if runtime permits) and link it in `docs/state_runbook.md`.

## 5. Test & Tooling Strategy
- Pytest guard rails:
  - Core regression: `python3 -m pytest tests/test_run_sim_cli.py tests/test_runner.py tests/test_runner_features.py`
  - Robustness sweep: `python3 -m pytest -k robustness --maxfail=1`
  - Optional focussed suites (`tests/test_run_sim_io.py`, `tests/test_data_robustness.py::test_missing_calendar_blocks` once added).
- Simulation spot checks: run shortened windows (e.g., 2024 Q1) during development to validate performance quickly before launching the full 2018–2025 backtest.
- Artefact diffing: adopt `python3 scripts/compare_metrics.py --left runs/phase4/backtests/<prev>/metrics.json --right runs/phase4/backtests/<curr>/metrics.json` (script to add if missing) to automate numerical comparisons.
- Continuous integration: gate merges on pytest success; optionally integrate the conservative long-run command as a nightly job in Codex Cloud.

## 6. Data Integrity Gates
- Always run the coverage audit before and after large refactors: `python3 scripts/check_data_quality.py --csv validated/USDJPY/5m.csv --calendar-day-summary`.
- Document any preprocessing (`data/usdjpy_5m_2018-2024_utc.csv` merges, header injections) in `docs/progress_phase4.md` and keep CSV hashes in `state.md`.
- Record expected schema versions in the manifest (`archive_namespace`, feature toggles) so refactors do not silently diverge from the dataset contract.

## 7. Documentation & Communication
- `docs/progress_phase4.md`: add a dedicated "Simulation Bugfix & Refactor" subsection with timeline, bug table, and metrics snapshots.
- `docs/task_backlog.md`: log progress under P4-01 (long-run improvements) with date-stamped notes referencing this plan.
- `docs/go_nogo_checklist.md`: ensure the simulation validation row points to the refreshed regression test suite and most recent long-run artefacts.
- `state.md`: maintain chronological logs (start/finish timestamps, commands executed, artefact locations, blockers).
- Commit/PR hygiene: include the exact commands executed in the PR description and summarise the outcomes (tests, long-run metrics). Summaries remain in Japanese per collaboration norms.

## 8. Timeline & Milestones
| Week | Focus | Exit Signals |
| --- | --- | --- |
| Week 0 (current) | Plan approval, baseline reruns, bug notebook populated | Deterministic baseline artefacts, doc updates committed |
| Week 1 | Hotfix high-priority defects, expand regression suite | All known blockers resolved, pytest suite green |
| Week 2 | Structural refactor, logging upgrades | Modular `scripts/run_sim.py`, new helper modules tested |
| Week 3 | Operational polish, automation rehearsal | Nightly smoke plan documented, Go/No-Go checklist aligned |

## 9. Exit Criteria (Phase 4 Readiness)
- Conservative and Bridge 2018–2025 runs meet Phase 4 DoD metrics and updated artefacts are stored under `reports/` with reproducible commands.
- Bug backlog is empty or reclassified with mitigation, and each entry references a regression test.
- Refactored code passes full pytest suite and long-run replays without behavioural drift.
- Documentation (`docs/progress_phase4.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md`, `state.md`) reflects the new workflow and has cross-links to artefacts.

## 10. Open Questions
1. Should we introduce additional manifests (e.g., alternative symbols or shorter look-back windows) to verify generalisation before Phase 4 sign-off?
2. Where should exploratory parameter sweeps live (`runs/phase4/experiments/` vs dedicated archive) to preserve auditability without cluttering the baseline directory?
3. Which subset of the long-run commands can run nightly within Codex Cloud resource constraints? Do we need a shortened scenario for daily health checks?

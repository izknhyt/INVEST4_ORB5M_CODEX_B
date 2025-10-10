# P2 Completion Task Plan

## Context
The P2 portfolio initiative already has core plumbing in place (strategy manifests, router expansion, and a refreshed
portfolio evaluation CLI walkthrough). Remaining work needs to lock regression coverage, ensure reproducible artefacts,
and document the final review workflow so the phase can be signed off confidently.

## Task Breakdown

### P2-03 Portfolio evaluation regression automation
- **Goal**: Freeze the router snapshot + portfolio summary workflows into deterministic fixtures so regressions surface
  budget headroom, correlation windows, and drawdown changes.
- **Definition of Done**:
  - Add pytest coverage that exercises `scripts/build_router_snapshot.py` and `scripts/report_portfolio_summary.py`
    against the curated router demo metrics, asserting budget warning/breach paths.
  - Capture the refresh commands in documentation (logic overview + observability dashboard) with links to the
    generated artefacts.
  - Ensure the regression runs as part of `python3 -m pytest` and document troubleshooting steps in the checklist.
- **Dependencies**: Verified router demo metrics under `reports/portfolio_samples/router_demo/metrics/` and up-to-date
  manifests for Day ORB / Tokyo Micro mean reversion.
- **Deliverables**: Test updates, refreshed docs, and a note in `docs/checklists/p2_portfolio_evaluation.md` pointing to
  the regression suite.

### P2-04 Portfolio dataset maintenance & rotation
- **Goal**: Maintain long-lived sample metrics and telemetry snapshots so reviewers can diff portfolio behaviour without
  re-running expensive backtests.
- **Definition of Done**:
  - Establish a rotation procedure for `reports/portfolio_samples/router_demo/` with retention rules and last-refresh
    metadata recorded in the backlog.
  - Document how to replace aged metrics while keeping router snapshot CLI arguments in sync.
  - Provide a lightweight validation script (or CLI flag) that checks sample metrics still match manifest expectations
    before publishing.
- **Dependencies**: Completion of P2-03 so regression guards exist; access to baseline runs listed in `runs/index.csv`.
- **Deliverables**: Maintenance procedure notes (docs + backlog) and a helper script or documented command that
  validates sample metrics.
- **Status 2026-06-20**: Router demo rotation log, retention guidance, and refresh steps captured in
  `docs/checklists/p2_portfolio_evaluation.md`. Introduced `scripts/validate_portfolio_samples.py` plus
  `tests/test_validate_portfolio_samples.py` so `python3 scripts/validate_portfolio_samples.py --samples-dir
  reports/portfolio_samples/router_demo --manifest configs/strategies/day_orb_5m.yaml --manifest
  configs/strategies/tokyo_micro_mean_reversion.yaml` can gate sample refreshes before publishing updates.

### P2-05 Portfolio review hand-off package
- **Goal**: Compile the final artefact bundle and reviewer guide needed to close P2 and transition toward P3 automation.
- **Definition of Done**:
  - Produce a reviewer-facing summary (docs/progress_phase2.md or a dedicated hand-off note) that links the regression
    suite, sample artefacts, and operational checklist.
  - Update `docs/task_backlog.md` with completion evidence and archive the corresponding `docs/todo_next.md` entry.
  - Record reproducibility commands (pytest + CLI refresh) and expected outputs in `state.md` for audit trail.
- **Dependencies**: Successful completion of P2-03 and P2-04 so artefacts and maintenance procedures are locked.
- **Deliverables**: Updated documentation, backlog/todo/state sync, and a reference bundle ready for reviewer sign-off.

## Execution Order
1. Implement P2-03 to secure automated regression coverage and documentation anchors.
2. Proceed to P2-04 so curated datasets remain trustworthy between reviews.
3. Close with P2-05 to deliver the hand-off package and formally mark the P2 initiative complete.

## Closure Status (2026-06-26)
- ✅ **P2-03 regression automation** — Warning/breach fixtures are locked in `tests/test_report_portfolio_summary.py` and
  `tests/test_portfolio_monitor.py`, with reviewer guidance captured in `docs/checklists/p2_portfolio_evaluation.md` and
  `docs/observability_dashboard.md`.
- ✅ **P2-04 dataset maintenance** — Rotation workflow, retention rules, and the
  `scripts/validate_portfolio_samples.py` guard are live with logs anchored in `docs/todo_next_archive.md` and
  `state.md`.
- ✅ **P2-05 reviewer hand-off** — The reviewer bundle in `docs/progress_phase2.md` links fixed artefacts, commands,
  and Japanese PR summary guidance, keeping backlog/todo/state entries in sync.

### Readiness for P3 Observability automation
- Preconditions for P3 have been met: curated artefacts, regression coverage, and review documentation all reference the
  same router demo snapshot and validation commands.
- Scope refinement now shifts to detailing the automation milestones for signal latency monitoring, weekly report
  generation, and dashboard data exports. These work items remain tracked under
  [docs/task_backlog.md#p3-観測性・レポート自動化](../task_backlog.md#p3-観測性・レポート自動化).
- Next actions: capture latency sampling cadence options, outline webhook payload fields, and identify required
  telemetry tables so implementation can start without blocking on design clarifications.

## Testing Expectations
- Each task must keep `python3 -m pytest` green and include any targeted CLI runs.
- Artefact refresh commands should be runnable from repo root without additional environment variables.

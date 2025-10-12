# Phase 4 Simulation Bugfix & Refactor Plan

## 0. Executive Summary
- Focus: harden the Day ORB simulation pipeline before Phase 4 validation by removing deterministic and sporadic defects, then refactor the CLI and runner for maintainability without regressing financial outputs.
- Success hinges on shipping a reproducible baseline, codifying every bug into tests, and instrumenting the workflow so Codex Cloud and local operators can re-run the suite without guesswork.
- Deliverables: patched `scripts/run_sim.py` + runner modules, expanded pytest coverage, refreshed long-run artefacts under `runs/phase4/backtests/` and `reports/`, and updated operational documentation (`docs/progress_phase4.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md`).
- Backlog alignment: maps to P4-01 (long-run parity), P4-02 (runner hardening), and P4-03 (operational readiness) with explicit doc/state updates for each exit.

## 0.1 Scope & Guardrails
- **In scope**: Day ORB 5m strategy (Conservative / Bridge), Python runner + CLI stack, validated USDJPY 5m data pipeline, Codex Cloud automation glue.
- **Out of scope**: New strategy features, multi-symbol manifest expansion, non-USDJPY data remediation beyond coverage/duplicate audits, portfolio router changes.
- **Constraints**: Must keep manifests/backtests reproducible under Python 3.10, no dependency upgrades beyond pinned requirements, and no schema changes that would invalidate existing artefact archives without migration notes.

## 0.2 Dependencies & Interfaces
- **Dataset readiness**: `validated/USDJPY/5m.csv` backfill and header alignment (per `state.md` Next Task) must land before W1 begins. Capture SHA256 + row count in `docs/progress_phase4.md` and mirror the numbers in `state.md` for reproducibility.
- **Manifest contract**: `configs/strategies/day_orb_5m.yaml` is the single source of truth for feature toggles. Any refactor that mutates schema must also update `configs/strategies/README.md` (if added) and the manifest changelog.
- **Runner state compatibility**: Persisted snapshots in `runs/**/state.json` include a `runner_config_fingerprint`. Before altering runner defaults, record the pre-change fingerprint in `docs/progress_phase4.md` and confirm resumption parity when the fingerprint changes.
- **Automation hooks**: Codex Cloud nightly workflows consume `runs/phase4/backtests/index.csv` and `reports/long_*.json`. Refactors must keep filenames stable or provide a compatibility shim plus migration notice.
- **Downstream integrations**: Router/portfolio analytics ingest EV bucket summaries. Coordinate format changes with the owners listed in `docs/router_architecture.md` before merging.
- **Ops tooling**: `scripts/manage_task_cycle.py` remains the gatekeeper for doc/state synchronisation. W0 must validate the dry-run flows so later stages do not drift from operational guardrails.

## 0.3 Review Follow-ups
- [ ] **Bug notebook template landed** — Publish the table skeleton described in W0.6 directly inside `docs/progress_phase4.md#bug-tracking` and link to the owning backlog ticket before declaring W0 complete. Owner: Tech Lead (Due: W0 end-of-week).
- [ ] **Baseline evidence cross-links** — Once dataset hashes and baseline commands are logged, ensure `docs/progress_phase4.md` and `state.md` share the same SHA256 / row-count tuples and include a permalink to `runs/phase4/backtests/index.csv`. Owner: Ops (Due: first W1 sync).
- [ ] **Compare-metrics automation** — If `scripts/compare_metrics.py` does not yet exist, open backlog item `P4-04` during W1 kickoff to track delivery and reference it from Section 5.5 so diff automation is not forgotten. Owner: Backtest WG (Due: W1 day 2).

## 1. Objectives & Success Criteria
- **Stability**: Conservative and Bridge 2018–2025 runs complete without crashes, non-deterministic fills, or missing artefacts. Runs seeded from clean state must match reruns that resume from persisted state snapshots. _Updated 2026-07-25: the validated snapshot presently spans 2018-01-01T00:00:00Z–2025-10-02T22:15:00Z; see [state.md#next-task](../../state.md#next-task) for the restoration backlog tracking the remaining 2025 extension work._
- **Accuracy**: Metrics (`Sharpe`, `max_drawdown`, `annual_win_rate`, EV buckets) match archived baselines or expected improvements after parameter updates. Numerical tolerance: ±0.5 bp on win-rate/Sharpe, ±0.1% on drawdown, 0 tolerance for trade-count drift unless documented.
- **Regression Safety**: Every defect encountered during triage is converted into an automated test covering logic, CLI, and data quality. CI (`python3 -m pytest`) and long-run simulations must pass post-refactor. Git history must link test IDs to backlog bug IDs.
- **Operational Readiness**: Documentation and `state.md` logs contain reproducible commands, artefact paths, dataset hash evidence, and sign-offs for Phase 4 DoD (aligned with P4-01/P4-02/P4-03 backlog entries).
- **Automation Readiness**: Nightly smoke bundle executes within ≤90 minutes on Codex Cloud standard nodes and produces artefacts under a deterministic directory layout.

## 2. Context & Pain Points
- Reference run (`runs/phase4/backtests/USDJPY_conservative_20251012_140919`) exposed: inconsistent Brownian Bridge fill ordering, EV gate miscounts, stale CLI flags, and gaps when validated data snapshots changed.
- Manifest (`configs/strategies/day_orb_5m.yaml`) and dataset (`validated/USDJPY/5m.csv`) evolved during Phase 3 → 4 transition; regression coverage lagged behind the new defaults.
- Codex Cloud automation requires deterministic artefact layout (`reports/long_{mode}.json`, `*_daily.csv`) and verbose logging to unblock headless troubleshooting.

## 3. Workstreams Overview
| ID | Theme | Primary Outcomes | Key Artefacts | Exit Signals | Owners |
| --- | --- | --- | --- | --- | --- |
| W0 | Preflight & Alignment | Scope signed-off, dataset fingerprints captured, backlog/task anchors synced | `docs/task_backlog.md`, `docs/progress_phase4.md`, `state.md` | SHA & backlog anchors recorded, comms cadence logged in `docs/progress_phase4.md` | Tech Lead + Ops |
| W1 | Baseline Reproducibility | Deterministic long-run outputs, diffable metrics, reproducible commands | `runs/phase4/backtests/*`, `reports/long_{mode}*.json/csv` | Conservative/Bridge gold runs stored with hashes + diff reports, rerun commands documented | Backtest WG |
| W2 | Defect Remediation & Guard Rails | Bug backlog flushed, targeted regression tests, CLI flag parity | `scripts/run_sim.py`, `tests/test_run_sim_cli.py`, `tests/test_runner*.py` | Bug notebook entries resolved or deferred with tests, pytest green, long-run sanity reruns logged | Backtest WG + QA |
| W3 | Structural Refactor | Modular CLI pipeline, shared I/O utilities, clearer logging | `scripts/run_sim.py`, `scripts/lib/run_sim_io.py` (new), logging configs | New module boundaries enforced by tests, performance deltas ≤±10%, migration note merged | Platform |
| W4 | Observability & Ops Sync | Enhanced instrumentation, docs and state alignment, nightly automation spec | `docs/progress_phase4.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md` | Nightly smoke doc approved, operator appendix published, automation dry-run recorded | Ops + DevRel |

Workstreams overlap by at most two days—changes only graduate downstream once upstream exit signals are documented in `docs/progress_phase4.md`.

## 3.1 Milestone Handshake Checklist
- Confirm backlog anchors (`P4-01`–`P4-03`) marked “In Progress” with the latest date and link to this plan.
- Record SHA256 of `validated/USDJPY/5m.csv` and manifest version in `state.md` before code changes.
- Baseline reruns must occur before any remediation/refactor commit merges; store diff reports in `reports/diffs/`.

## 4. Detailed Playbook
### W0 — Preflight & Alignment
1. Sync `state.md` Next Task block with Phase 4 bugfix scope and log current dataset/manifest fingerprints.
2. Reconcile backlog/task trackers: ensure `docs/task_backlog.md` and `docs/todo_next.md` reference this plan and enumerate planned deliverables.
3. Establish communication cadence (daily async update in `docs/progress_phase4.md`, weekly review meeting notes).
4. Capture hardware/runtime baselines (CPU type, RAM, average wall-clock for conservative run) to detect performance regressions later.
5. Validate `scripts/manage_task_cycle.py --dry-run start-task --anchor P4-01` and `--dry-run finish-task` outputs so doc/state commits remain reproducible when workstreams close.
6. Stage a shared bug notebook skeleton at `docs/progress_phase4.md#bug-tracking` (table placeholder) before remediation starts.
   | Bug ID | Date Logged | Symptom Summary | Impact | Status | Regression Test | Artefact Link | Owner |
   | --- | --- | --- | --- | --- | --- | --- | --- |
   | TBD-001 | 2026-07-XX | Example: Resume run drifts daily wins | High | Open | tests/test_runner.py::test_resume_parity | runs/phase4/backtests/resume_check/metrics.json | Backtest WG |
   Capture at least the columns above when seeding the table so subsequent updates stay consistent.

### W1 — Baseline Reproducibility
1. Validate input data before any code change:
   - `python3 scripts/check_data_quality.py --csv validated/USDJPY/5m.csv --calendar-day-summary`
   - Document coverage in `docs/progress_phase4.md` and attach representative JSON snippets if anomalies exist.
2. Establish gold runs for both modes (the validated snapshot currently ends at **2025-10-02T22:15:00Z**, reflecting the latest ingest noted in [state.md#next-task](../../state.md#next-task); record the commands below verbatim while this remains the terminal bar):
   - `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --start-ts 2018-01-01T00:00:00Z --end-ts 2025-10-02T22:15:00Z --out-json reports/long_conservative.json --out-daily-csv reports/long_conservative_daily.csv --out-dir runs/phase4/backtests --no-auto-state`
   - `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode bridge --start-ts 2018-01-01T00:00:00Z --end-ts 2025-10-02T22:15:00Z --out-json reports/long_bridge.json --out-daily-csv reports/long_bridge_daily.csv --out-dir runs/phase4/backtests --no-auto-state`
   _Updated 2026-07-25: this horizon reflects the validated coverage derived from the latest USDJPY 5 m snapshot; document any subsequent ingest date changes alongside the command updates._
   - When the dataset is extended again (e.g., restored to a 2025-12-31T23:55:00Z horizon), follow this update path: rerun the data quality audit, adjust both `--end-ts` arguments and any narrative references to the new terminal bar, refresh `docs/progress_phase4.md`/`state.md` with the updated hashes plus artefact links, and note in `docs/task_backlog.md` that the 2025 horizon has been reinstated for W1 reproducibility.
3. Validate resume parity using the same artefact directory:
   - First pass (state creation): `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/phase4/backtests/resume_check --auto-state`
   - Second pass (state reuse): re-run the command above and diff `metrics.json`/`records.csv`; log the fingerprint + diff outcome in `docs/progress_phase4.md`.
4. Diff `metrics.json` and `daily.csv` against archived runs; record deltas (expected vs unexpected) in `docs/progress_phase4.md` with direct file links.
   - Use `python3 scripts/compare_metrics.py --left <gold>/metrics.json --right <candidate>/metrics.json` (once implemented) and note the diff artefact path. If the script is still pending, log the backlog ticket opened in Section 0.3 inside the doc entry so reviewers can trace accountability.
5. Snapshot CLI stdout/stderr and key log excerpts into `runs/phase4/backtests/<timestamp>/session.log` for reproducibility.
6. Store SHA256 hashes for each artefact (`metrics.json`, `daily.csv`, `records.csv`) and reference them in `docs/progress_phase4.md`.
7. Set up `reports/diffs/README.md` summarising how to interpret diff outputs to avoid misclassification of expected vs unexpected deltas.
8. Record runtime envelope (start/end timestamps, CPU utilisation snapshot) alongside metrics so later optimisations can be validated without rerunning full histories.

### W2 — Defect Remediation & Guard Rails
1. Build a structured bug notebook at `docs/progress_phase4.md#bug-tracking` capturing for each defect: reproduction command, observed vs expected, root cause hypothesis, owner, priority (Blocker / High / Medium / Low), and intended fix release.
2. Convert high-priority findings into failing tests before patching:
   - CLI/argument regressions → `tests/test_run_sim_cli.py`
   - Runner logic (fill sequencing, EV gate thresholds, trailing stops, state archival) → `tests/test_runner.py`, `tests/test_runner_features.py`
   - Data ingestion/validation gaps → `tests/test_data_robustness.py` with fixtures under `tests/fixtures/run_sim/`
   - Resume parity / state persistence regressions → add parametrised cases to `tests/test_runner.py::test_load_state_round_trip` (or new dedicated test) covering conservative and bridge modes.
3. Apply minimal hotfixes (Phase A) guided by tests, keeping public interfaces stable. Collect commit-level notes on impacted modules and link each change back to a bug notebook ID in commit messages.
4. Maintain focused pytest loops during remediation:
   - `python3 -m pytest tests/test_run_sim_cli.py`
   - `python3 -m pytest tests/test_runner.py tests/test_runner_features.py`
   - `python3 -m pytest -k robustness --maxfail=1`
5. After each fix, rerun the relevant long-run command(s) to ensure financial outputs remain sane; log results in `docs/progress_phase4.md` alongside bug IDs and include metric deltas vs the gold run.
6. Document new config toggles or environment assumptions immediately in `docs/state_runbook.md` to reduce drift.
7. Keep a running change log for telemetry fields (new columns/JSON keys) so downstream consumers can adjust parsers before release.
8. Gate merges on bug notebook sign-off: each resolved item must reference the regression test that now covers it and the artefact path used for verification.

### W3 — Structural Refactor
1. Once W2 test suite is green, extract the CLI into discrete helpers:
   - Argument parsing
   - Manifest + dataset resolution
   - Runner orchestration
   - Artefact writers / state integration
2. Move shared I/O helpers into `scripts/lib/run_sim_io.py` (new) or equivalent, ensuring unit tests cover JSON/CSV writes and directory handling.
3. Expand logging to emit structured events (EV gate decisions, Brownian Bridge probabilities, trailing stop adjustments) with unique context IDs for later correlation and document the schema in `docs/backtest_runner_logging.md`.
4. Enforce module boundaries with additional tests (e.g., `tests/test_run_sim_io.py`) and update imports to avoid circular dependencies.
5. Execute `python3 -m pytest` plus the long-run commands to certify parity before merging.
6. Run performance smoke tests (e.g., 2024 Q1 window) before and after refactor to ensure runtime overhead stays within ±10%.
7. Prepare migration guidance for any internal API adjustments (call sites, manifests) and cross-link it from `docs/progress_phase4.md`.
8. Engage router integration reviewers if EV bucket formats shift; capture sign-off names in `docs/progress_phase4.md` to unblock downstream deployment.

### W4 — Observability & Operational Sync
1. Surface new logging fields or behavioural toggles in `docs/state_runbook.md` (incident response) and `docs/go_nogo_checklist.md` (release sign-off).
2. Record every significant run and fix in `state.md` (timestamp, command, outcome, follow-up) to feed Codex Cloud automation.
3. Update `docs/progress_phase4.md` with:
   - Bug summary table (ID, fix status, regression test reference, artefact link)
   - Long-run metric snapshots after each major parameter or code change
   - Checklist of nightly/weekly automation commands (e.g., `python3 scripts/run_sim.py ... --no-auto-state`)
4. Define the nightly smoke test bundle for Codex Cloud (`python3 -m pytest tests/test_run_sim_cli.py tests/test_runner.py`, plus a shortened simulation if runtime permits) and link it in `docs/state_runbook.md` along with escalation contacts.
5. Publish an “operator quick reference” appendix summarising daily/weekly/monthly tasks and expected artefact locations.
6. Dry-run the smoke bundle on Codex Cloud staging once and record wall-clock/runtime stats plus any deviations from local execution.

## 5. Test & Tooling Strategy

### 5.1 Test Ownership Matrix
| Suite / Tool | Purpose | Trigger | Owner | Exit Criteria |
| --- | --- | --- | --- | --- |
| `python3 -m pytest tests/test_run_sim_cli.py` | Guard CLI contract & flag parity | On every CLI touch + nightly smoke | Backtest WG | Green on latest commit with bug notebook reference updated |
| `python3 -m pytest tests/test_runner.py tests/test_runner_features.py` | Validate fill logic, EV gates, trailing stops | Any runner logic change, weekly cadence otherwise | Backtest WG + QA | No flakiness for 3 consecutive runs, metrics parity vs gold run |
| `python3 -m pytest -k robustness --maxfail=1` | Stress edge cases (missing data, partial windows) | Prior to merging remediation/refactor commits | QA | Zero unexpected failures; new fixtures documented in `tests/fixtures/run_sim/README.md` |
| Long-run conservative/bridge backtests | Financial regression coverage | After W1 baseline + post-defect batches | Backtest WG | Metrics within tolerance, hashes logged in `state.md` |
| Codex Cloud smoke bundle | Automation health | Weekly + before release candidate | Ops | Report attached to `docs/progress_phase4.md` with runtime + artefact links |

### 5.2 Pytest Guard Rails
- Core regression: `python3 -m pytest tests/test_run_sim_cli.py tests/test_runner.py tests/test_runner_features.py`
- Robustness sweep: `python3 -m pytest -k robustness --maxfail=1`
- Optional focussed suites (`tests/test_run_sim_io.py`, `tests/test_data_robustness.py::test_missing_calendar_blocks` once added).

### 5.3 State Persistence Smoke
Run a shortened resume scenario (`python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --mode conservative --start-ts 2024-01-01T00:00:00Z --end-ts 2024-03-31T23:55:00Z --out-dir runs/phase4/backtests/resume_q1 --auto-state`) twice and diff outputs to ensure deterministic reloads.

### 5.4 Simulation Spot Checks
Run shortened windows (e.g., 2024 Q1) during development to validate performance quickly before launching the full 2018–2025 backtest.

### 5.5 Compare-metrics Automation
Adopt `python3 scripts/compare_metrics.py --left runs/phase4/backtests/<prev>/metrics.json --right runs/phase4/backtests/<curr>/metrics.json` (script to add if missing) to automate numerical comparisons.
- If the helper script has not landed yet, reference backlog `P4-04` in the run log and capture a manual diff workflow (e.g., `jq` + spreadsheet steps) so auditors understand the temporary process.

### 5.6 Continuous Integration
Gate merges on pytest success; optionally integrate the conservative long-run command as a nightly job in Codex Cloud.

### 5.7 Test Debt Tracker
Maintain a checklist of unconverted manual repro steps; escalate any open items at the weekly review.

## 6. Data Integrity Gates
- Always run the coverage audit before and after large refactors: `python3 scripts/check_data_quality.py --csv validated/USDJPY/5m.csv --calendar-day-summary`.
- Document any preprocessing (`data/usdjpy_5m_2018-2024_utc.csv` merges, header injections) in `docs/progress_phase4.md` and keep CSV hashes in `state.md`.
- Record expected schema versions in the manifest (`archive_namespace`, feature toggles) so refactors do not silently diverge from the dataset contract.
- Introduce a data freshness checkpoint (`python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6`) before long-run backtests to guard against stale baselines.
- Capture validation evidence (row counts, duplicate stats) in `reports/data_quality/phase4/` with timestamps for audit.

## 6.1 Risk Register & Mitigations
| Risk | Impact | Likelihood | Mitigation / Contingency | Owner |
| --- | --- | --- | --- | --- |
| Validated dataset backfill slips or diverges from plan | Blocks W1 gold runs, invalidates hashes, and stalls baseline parity | Medium | Lock the CSV snapshot in git-lfs or the artefact store, record checksum early, keep a fallback headerless snapshot for smoke tests, and block merges until hashes are recorded in `state.md` | Ops + Backtest WG |
| Runner refactor breaks persisted states | Nightly jobs fail or diverge silently | Medium | Add resume regression tests during W2, enforce the manual resume smoke run in W1, and have QA monitor runner fingerprint deltas | Backtest WG + QA |
| Refactor introduces runtime regression >10% | Extends automation window beyond 90 minutes | Medium | Capture baseline runtimes in W0, add `analysis/perf_baseline.md` quick-check commands if needed, and revert to the previous module boundary when regressions persist beyond a day | Platform |
| Codex Cloud automation resource limits | Nightly smoke bundle flakes or times out | Medium | Capture runtime telemetry in W1, profile hotspots during the W3 refactor, dry-run in W4.6, adjust concurrency or dataset slices, and document manual rerun steps in `docs/state_runbook.md` while escalating when runtime exceeds 80 minutes | Ops |
| Bug notebook entries left untested | Latent regressions reappear post-release | Low-Medium | Enforce the W2.8 test reference requirement, hold weekly notebook status reviews, and block merges lacking linked test IDs | Tech Lead |
| Logging schema drift without documentation updates | Downstream dashboards fail to ingest updates and incident playbooks become outdated | Low | Require a `docs/state_runbook.md` diff on every logging PR, coordinate the W3.8 sign-off, add an integration test stub that loads the latest JSON into router pipeline fixtures, and schedule weekly audits | Ops + DevRel + Platform + Router |
| Diff tooling backlog (compare_metrics script) not delivered | Manual metric checks become error-prone | Medium | Assign a Backtest WG owner during W2, open backlog item P4-04 if the helper is missing, document the interim manual diff workflow, and fail release review if the script remains absent | Backtest WG |

## 7. Documentation & Communication
- `docs/progress_phase4.md`: add a dedicated "Simulation Bugfix & Refactor" subsection with timeline, bug table, and metrics snapshots.
- `docs/task_backlog.md`: log progress under P4-01 (long-run improvements) with date-stamped notes referencing this plan.
- `docs/go_nogo_checklist.md`: ensure the simulation validation row points to the refreshed regression test suite and most recent long-run artefacts.
- `state.md`: maintain chronological logs (start/finish timestamps, commands executed, artefact locations, blockers).
- Commit/PR hygiene: include the exact commands executed in the PR description and summarise the outcomes (tests, long-run metrics). Summaries remain in Japanese per collaboration norms.
- Weekly sync notes: append a dated “Phase 4 Bugfix Stand-up” bullet list to `docs/progress_phase4.md` capturing decisions, outstanding risks, and owners.
- Notify downstream consumers (router/portfolio teams) via `docs/notifications/phase4_sim_release.md` (new) once regression parity is confirmed.

### 7.1 Change Management Checklist
- Every code merge must link to a doc PR (or doc commit) updating `docs/progress_phase4.md` and, when relevant, `docs/state_runbook.md`.
- Add a short-term rollback plan for each risky change (feature flag, manifest revert, or dataset pin) inside the bug notebook entry.
- Archive obsolete artefacts (`runs/phase3/legacy_*`) only after two successful smoke bundles reference the new outputs.
- Maintain a single source-of-truth calendar in `docs/progress_phase4.md` for review meetings, test rehearsal dates, and release cutoffs.

## 8. Timeline & Milestones
| Week | Focus | Exit Signals |
| --- | --- | --- |
| Week 0 (current) | Plan approval, baseline reruns, bug notebook populated | Deterministic baseline artefacts, doc updates committed, dataset hashes logged |
| Week 1 | Hotfix high-priority defects, expand regression suite | All known blockers resolved, pytest suite green, bug notebook only contains deferred/low-priority issues |
| Week 2 | Structural refactor, logging upgrades | Modular `scripts/run_sim.py`, new helper modules tested, performance deltas within tolerance |
| Week 3 | Operational polish, automation rehearsal | Nightly smoke plan documented, Go/No-Go checklist aligned, operator appendix published |
| Week 4 | Observability & Operational Sync | Nightly smoke documentation approved, operator appendix live, Codex Cloud smoke dry-run recorded |

## 9. Exit Criteria (Phase 4 Readiness)
- Conservative and Bridge 2018–2025 runs meet Phase 4 DoD metrics and updated artefacts are stored under `reports/` with reproducible commands.
- Bug backlog is empty or reclassified with mitigation, and each entry references a regression test.
- Refactored code passes full pytest suite and long-run replays without behavioural drift.
- Documentation (`docs/progress_phase4.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md`, `state.md`) reflects the new workflow and has cross-links to artefacts.
- Codex Cloud nightly pipeline executes the smoke bundle without manual intervention and uploads artefacts/logs to the agreed locations.

## 10. Open Questions
1. Should we introduce additional manifests (e.g., alternative symbols or shorter look-back windows) to verify generalisation before Phase 4 sign-off? → Proposal: pilot with a 2022-focused USDJPY slice under `runs/phase4/validation/` and record outcomes before expanding scope. **Owner**: Backtest WG (Due: end of Week 1).
2. Where should exploratory parameter sweeps live (`runs/phase4/experiments/` vs dedicated archive) to preserve auditability without cluttering the baseline directory? → Recommend `runs/phase4/experiments/<ticket-id>/` with an index CSV and README linking to the bug notebook. **Owner**: Tech Lead to ratify naming convention during Week 0 retro.
3. Which subset of the long-run commands can run nightly within Codex Cloud resource constraints? Do we need a shortened scenario for daily health checks? → Action: benchmark a 2019–2020 conservative slice (<30 min target) and document results to decide if nightly cadence is feasible. **Owner**: Ops, coordinate with Backtest WG before Week 2.
4. Do we need an automated alert when baseline metrics drift beyond tolerance? → Consider extending `scripts/compare_metrics.py` to emit Slack/webhook notifications for off-nominal diffs. **Owner**: Platform to spike during W3, with go/no-go at the Week 3 review.


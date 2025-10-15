# 作業タスク一覧（バックログ）

このバックログは「最新値動きを取り込みながら継続学習し、複数戦略ポートフォリオでシグナルを出す」ツールを実現するための優先順位付きタスク群です。各タスク完了時は成果物（コード/ドキュメント/レポート）へのリンクを追記してください。

## ワークフロー統合

各タスクに着手する前に、該当するバックログ項目を `state.md` の `Next Task` ブロックへ明示的に引き込み、進行中であることを記録してください。作業完了後は、成果ノートや反省点を `docs/todo_next.md` に反映し、`state.md` の完了ログと整合するよう同期します。

- 例: [P1-02] 2024-06-18 state.md ログ / [`docs/progress_phase1.md`](./progress_phase1.md)

### Codex Session Operations Guide
Document the repeatable workflow that lets Codex keep `state.md`, `docs/todo_next.md`, and `docs/task_backlog.md` synchronized across sessions, including how to use the supporting scripts and templates.

**DoD**
- `docs/codex_workflow.md` explains pre-session checks, the execution loop, wrap-up steps, and how to apply the shared templates.
- The guide covers dry-run and live usage of `scripts/manage_task_cycle.py` for keeping state/doc updates in lockstep.
- Links to related runbooks and templates are included so future sessions can reproduce the same procedure.

**Progress Notes**
- 2026-06-18: Removed the duplicated "値動きの読み取り" section from `readme/設計方針（投資_3_）v_1.md` so the design reference lists each feature guideline once.
- 2025-09-29: Added `docs/codex_workflow.md` to consolidate operational guidance for Codex agents and clarified the relationship with `docs/state_runbook.md` and the template directory.
- 2025-10-16: Supplemented cloud-run guardrails in `docs/codex_cloud_notes.md` and linked them from the workflow guide to improve sandbox handoffs.
- 2026-02-13: Refreshed `docs/codex_workflow.md` with sandbox/approval guidance (workspace-write + on-request approvals), highlighted `--doc-section` usage for aligning `docs/todo_next.md`, and reiterated `scripts/manage_task_cycle.py` dry-run examples. Synced references with `docs/state_runbook.md` and template links.
- 2026-04-17: Implemented the observability dashboard pipeline (`analysis/export_dashboard_data.py`, `analysis/dashboard/*`, `analysis/portfolio_monitor.ipynb`) and documented refresh/reporting expectations in `docs/observability_dashboard.md`.

## P0: 即着手（オンデマンドインジェスト + 基盤整備）

**Status Update (2026-06-15)**: Live `data_quality_failure` alert validation remains on hold until production emits the first alert. Operational bandwidth is redirected toward P2 portfolio reporting deliverables and P3 observability automation planning.
- 2026-08-04: Hardened the Phase 4 auto-state resume flow so fingerprint mismatches no longer report `loaded_state` in metrics JSON, updated runner lifecycle APIs to surface load success, and captured regression coverage (`tests/test_run_sim_cli.py::test_run_sim_cli_omits_loaded_state_on_mismatch`).
- 2026-08-03: Landed `scripts/compare_metrics.py` for Phase 4 diff automation, added pytest coverage, and logged the USDJPY validated dataset fingerprint + bug notebook template in `docs/progress_phase4.md` / `state.md` per W0 guardrails.
- 2026-08-06: Extended `scripts/summarize_runs.py` with manifest-first `latest_runs` summaries and a `--latest-only` shortcut so ops can confirm the newest `run_id` per manifest from JSON; refreshed `docs/logic_overview.md`, `docs/benchmark_runbook.md`, and `docs/state_runbook.md` accordingly.
- 2026-07-05: Added `--no-auto-state` / `--auto-state` toggles to `scripts/run_sim.py`, expanded `configs/strategies/day_orb_5m.yaml` to include Bridge mode, and seeded `runs/phase4/backtests/` with baseline runs while logging the validated dataset coverage gap in `docs/progress_phase4.md`.
- 2026-07-03: Restored `scripts/run_sim.py` CLI compatibility by adding the `--out-json` alias and `--out-daily-csv` export path so Phase 4 long-run commands execute without argument errors, and refreshed the logging reference accordingly.
- 2026-06-26: Phase 3 observability automation detailed design reviewed (`docs/phase3_detailed_design.md`), clarifying retention/manifest sequencing so the DoD checklist drafting can proceed without blockers.
- 2026-06-27: Restored `scripts/check_data_quality.py` coverage checks for legacy headerless validated CSVs by auto-detecting missing headers, refreshed README / `docs/data_quality_ops.md` guidance, and added regression coverage for the fallback path so P0 data-quality guards stay reliable.
- 2026-06-28: Enabled `scripts/run_sim.py` to auto-detect headerless validated CSV snapshots so manifest-driven backtests can load the shared datasets without manual header injection, extending pytest coverage for the loader fallback.
- 2026-07-16: Patched the BacktestRunner trailing-stop accounting bug so profitable trail exits contribute to EV buckets / win率, documented the remediation in `docs/backtest_runner_logging.md`, and added regression coverage (`python3 -m pytest tests/test_runner.py`).
<a id="p0-12-codex-first-documentation-cleanup"></a>
### ~~P0-12 Codex-first documentation cleanup~~ ✅ (2026-05-17 クローズ)

- **DoD**: Codex operator workflow has a one-page quickstart (`docs/codex_quickstart.md`), the detailed checklist (`docs/state_runbook.md`) is trimmed to actionable bullet lists, README points to both, and `docs/development_roadmap.md` captures immediate→mid-term improvements with backlog links. Backlogとテンプレートは新フローに沿って更新済みであること。
- **Notes**: Focus on reducing duplication between `docs/codex_quickstart.md`, `docs/codex_workflow.md`, README, and `docs/state_runbook.md`; ensure sandbox/approval rules stay explicit.
- **DoD チェックリスト**: [docs/checklists/p0-12_doc_cleanup.md](checklists/p0-12_doc_cleanup.md)
- 2026-04-24: Normalised internal documentation links to use relative paths so Markdown previews and GitHub navigation stay consistent. Synced quickstart/workflow docs with the updated guideline and logged the change in `state.md`.
- 2026-04-25: Re-audited `docs/` Markdown to ensure no `] (docs/...)` style links slipped back in, expanded the workflow guideline with the failure mode, and recorded the hygiene check in `state.md`.
- 2026-05-05: Restructured Codex quickstart/workflow/state runbook into aligned 3-step guides, refreshed README / `docs/todo_next.md` / roadmap anchors, and added deliverable tracking to `state.md`.
- 2026-05-06: Added [docs/documentation_portal.md](documentation_portal.md) as the navigation hub, reorganised README for new-contributor onboarding, and synced quickstart/workflow links.
- 2026-05-07: Introduced the documentation portal orientation cheat sheet and aligned README / quickstart / workflow / state runbook messaging so first-time contributors can map next steps without re-reading every doc.
- 2026-05-08: Synced README doc hub language with the portal, added a documentation hygiene checklist, and refreshed quickstart / workflow / state runbook cross-references so newcomers have a single orientation path.
- 2026-05-11: Re-reviewed README / documentation portal / quickstart / workflow text for P0-12, confirmed anchors stay aligned as of 2025-10-09, and noted no blocking documentation gaps for Codex operators while flagging that any documentation updates after 2025-10-09 require a fresh audit.
- 2026-05-12: Added a dedicated DoD checklist ([docs/checklists/p0-12_doc_cleanup.md](checklists/p0-12_doc_cleanup.md)) to keep documentation alignment checks reusable across sessions.
- 2026-05-13: Revalidated README / documentation portal / quickstart / workflow alignment, synced `docs/todo_next.md` Pending Review entry with `state.md`, and confirmed DoD checklist coverage ahead of close-out.
- 2026-05-17: Archived the Pending Review entry after ticking the final DoD checklist item, synced `state.md` and docs/todo_next archive notes, and re-ran `python3 -m pytest` to keep regressions green.
- ~~**P0-13 run_daily_workflow local CSV override fix**~~ (2026-04-07 完了): `scripts/run_daily_workflow.py` がデフォルト ingest で `pull_prices.py` を呼び出す際に `--local-backup-csv` のパスを尊重する。
  - 2026-04-07: CLI オプションを `pull_prices` コマンドへ伝播し、回帰テスト `tests/test_run_daily_workflow.py::test_ingest_pull_prices_respects_local_backup_override` を追加。`python3 -m pytest` を実行して確認。
- 2026-04-05: `scripts/run_sim.py` を manifest-first CLI へ再設計し、OutDir 実行時にランフォルダ (`params.json` / `metrics.json` / `records.csv` / `daily.csv`) が生成されるよう統合。`tests/test_run_sim_cli.py` / README / `docs/checklists/multi_strategy_validation.md` を更新。
- 2026-02-28: Ensured `BacktestRunner` treats `ev_mode="off"` as a full EV-gate bypass by forcing
  the threshold LCB to negative infinity and preserving the disabled state in context/debug logs.
  Added regression `tests/test_runner.py::test_ev_gate_off_mode_bypasses_threshold_checks` and ran
  `python3 -m pytest tests/test_runner.py` to confirm no breakouts are rejected under the override.
- 2026-03-03: Introduced `FeaturePipeline` to centralise bar ingestion, realised volatility history,
  and context sanitisation, returning the new `RunnerContext` wrapper so `BacktestRunner._compute_features`
  delegates to the shared flow. Added `tests/test_runner_features.py` for direct pipeline coverage and
  refreshed `tests/test_runner.py` to execute via the pipeline path, with `python3 -m pytest`
  verifying regression parity.
- 2026-03-23: `scripts/run_sim.py` で manifest の `archive_namespace` を利用する際に `aggregate_ev.py` が
  誤ったディレクトリを参照して失敗していた問題を修正。`--archive-namespace` フラグを追加して CLI 間で
  namespace を共有し、`tests/test_run_sim_cli.py` / `tests/test_aggregate_ev_script.py` で回帰確認後に
  `python3 -m pytest tests/test_aggregate_ev_script.py tests/test_run_sim_cli.py` を実行。
- 2026-03-31: `scripts/run_sim.py` の manifest ロード時に `--no-ev-profile` 指定を尊重し、`aggregate_ev.py`
  へのコマンド組み立てから `--out-yaml` を除外するガードを追加。`tests/test_run_sim_cli.py` に回帰テストを
  追加し、`python3 -m pytest tests/test_run_sim_cli.py` を実行。
- 2026-04-01: `--no-ev-profile` ガードをユーティリティ化し、CLI からの `--ev-profile` 指定と併用した場合でも
  `aggregate_ev.py` が `--out-yaml` を受け取らないことを回帰テストで確認。`python3 -m pytest tests/test_run_sim_cli.py`
  を実行。
- ~~**state 更新ワーカー**~~ (完了): `scripts/update_state.py` に部分実行ワークフローを実装し、`BacktestRunner.run_partial` と状態スナップショット/EVアーカイブ連携を整備。`ops/state_archive/<strategy>/<symbol>/<mode>/` へ最新5件を保持し、更新後は `scripts/aggregate_ev.py` を自動起動するようにした。

<a id="p0-13-data-quality-audit"></a>
### ~~P0-13 Data quality audit enhancements~~ ✅ (2026-06-12 クローズ)

- **DoD**: `scripts/check_data_quality.py` reports coverage metrics (row counts, start/end timestamps, gap totals), supports JSON exports for automation, and adds regression tests that validate the computed statistics and CLI behaviour.
- **Notes**: Keep compatibility with existing CLI usage while expanding summary fidelity so cron jobs can persist machine-readable outputs. Document new expectations in backlog notes and ensure pytest coverage stays green.
- **DoD チェックリスト**: [docs/checklists/p0-13_data_quality_audit.md](checklists/p0-13_data_quality_audit.md)
- 2026-05-14: Added coverage/monotonic metrics and JSON export support to the audit CLI, introduced pytest coverage for summary stats and CLI output, and verified `python3 -m pytest tests/test_check_data_quality.py` passes alongside the full suite.
- 2026-05-18: Normalised timestamp parsing in `scripts/check_data_quality.py` to accept `Z` suffixes and timezone offsets, updating the pytest fixture to cover UTC/offset inputs so audits don't drop valid rows.
- 2026-05-19: Auto-detected bar intervals and added an `--expected-interval-minutes` override to `scripts/check_data_quality.py`, refreshed pytest coverage, and documented the new CLI flag in the README.
- 2026-05-20: Closed out the reviewer hold by archiving the Pending Review entry, syncing `state.md` / `docs/todo_next*.md`, and confirming the audit CLI documentation and tests remain current.
- 2026-05-23: Captured duplicate timestamp inventories via `--out-duplicates-csv` / `--out-duplicates-json`, added summary truncation controls (`--max-duplicate-report`), refreshed README guidance, and extended pytest coverage so reviewers can locate problematic rows directly from the audit output.
- 2026-05-24: Prioritised duplicate groups by occurrence count in the audit summary, surfaced `duplicate_max_occurrences` / `duplicate_first_timestamp` / `duplicate_last_timestamp` / `duplicate_timestamp_span_minutes`, updated README guidance, and expanded pytest coverage to lock the new metrics.
- 2026-05-25: Added `--min-duplicate-occurrences` filtering to focus audits on severe timestamp collisions, exposed `ignored_duplicate_groups` / `ignored_duplicate_rows` counters in summaries, refreshed README guidance, and extended pytest coverage for the filtered exports.
- 2026-05-26: Added calendar-day coverage segmentation to `scripts/check_data_quality.py` (`--calendar-day-summary`) so reviewers can flag low-coverage UTC days via JSON payloads, updated README usage guidance, and extended pytest coverage for the new CLI flow.
- 2026-05-27: Introduced failure guards to `scripts/check_data_quality.py` so audits can exit non-zero when overall coverage dips below a configurable floor or when calendar-day warnings persist, updated README guidance, and expanded pytest coverage to lock the new CLI switches.
- 2026-05-28: Wired `scripts/run_daily_workflow.py --check-data-quality` to enforce the new coverage thresholds, updated README / `docs/state_runbook.md` with escalation guidance, and expanded pytest coverage to validate the orchestration command.
- 2026-05-29: Enabled `scripts/check_data_quality.py --webhook` to deliver `data_quality_failure` alerts with coverage context, propagated webhook and timeout overrides from `run_daily_workflow.py --check-data-quality`, refreshed README/state runbook guidance, and extended pytest coverage for the new alert flow.
- 2026-05-31: Added duplicate saturation guards to `scripts/check_data_quality.py` via `--fail-on-duplicate-groups`, wired the daily workflow default to fail when five or more duplicate timestamp groups remain after filtering, refreshed README / docs/data_quality_ops.md guidance, and expanded pytest coverage to exercise the new failure paths.
- 2026-06-01: Added `--fail-on-duplicate-occurrences` to `scripts/check_data_quality.py` so audits can fail when a single timestamp grows beyond the allowed repetition count, propagated the threshold through `scripts/run_daily_workflow.py`, refreshed README / docs/data_quality_ops.md guidance, and extended pytest coverage for the new guard.
- 2026-06-02: Updated `scripts/run_daily_workflow.py` to prefer headered validated CSVs (`5m_with_header.csv`) when building downstream commands, falling back to legacy `5m.csv` only when required. Adjusted `tests/test_run_daily_workflow.py` to cover the new default and legacy fallback so data-quality checks no longer fail on headerless historical snapshots.
- 2026-06-02: Revalidated data-quality thresholds (coverage 0.995 / calendar-day 0.98 / duplicate groups 5 / duplicate occurrences 3) across README、docs/data_quality_ops.md、`scripts/run_daily_workflow.py` defaults、および CLI ドキュメントを照合し、運用手順との整合を確認した。

<a id="p0-14-data-quality-gap-report"></a>
### ~~P0-14 Data quality gap reporting~~ ✅ (2026-06-12 クローズ)

- **DoD**: `scripts/check_data_quality.py` can surface full gap inventories with missing-row estimates, export the gap table for downstream tooling, and documents the workflow alongside regression coverage for the new CLI options.
- **Notes**: Preserve backward compatibility for existing summary keys while extending the payload with richer metrics (`missing_rows_estimate`, aggregate gap stats). Ensure optional outputs are guarded behind CLI flags so existing automation keeps running unchanged.
- **DoD チェックリスト**: [docs/checklists/p0-14_data_quality_gap_report.md](checklists/p0-14_data_quality_gap_report.md)
- _New_: Establish the end-to-end workflow (CLI → JSON/CSV export → README usage notes) and keep pytest passing.
- 2026-05-15: Added missing-row estimates, aggregate gap metrics, configurable reporting limits, and gap CSV export to `scripts/check_data_quality.py`; refreshed README usage and extended pytest coverage (`python3 -m pytest`).
- 2026-05-16: Documented artefact destinations and review hand-off details, archived the todo entry, and marked the DoD checklist complete for reviewer pickup.
- 2026-05-21: Added ISO-8601 `--start-timestamp` / `--end-timestamp` filters to `scripts/check_data_quality.py` so partial range audits surface precise gap counts. Updated README guidance, extended pytest coverage, and ensured the summary payload records applied window bounds.
- 2026-05-22: Added `--min-gap-minutes` filtering and `--out-gap-json` export to `scripts/check_data_quality.py` so reviewers can ignore sub-threshold gaps while still tracking the skipped totals. Synced README usage notes and expanded pytest coverage for the new CLI paths.
- 2026-06-12: Revalidated `--out-gap-*` exports against `validated/USDJPY/5m_with_header.csv`, documented default artefact locations and review steps in `docs/data_quality_ops.md`, and refreshed README samples to point at the headered snapshot used by the daily workflow.
<a id="p0-15-data-quality-alert-ops"></a>
### ~~P0-15 Data quality alert operations loop~~ ✅ (2026-06-12 クローズ)

- **DoD**: Operators can acknowledge and escalate `data_quality_failure` webhook alerts using a documented runbook and shared log, and cross-document references point to the workflow from the README and portal.
- **Notes**: Ensure remediation commands are captured so reviewers can replay the fix. Keep escalation criteria aligned with the production thresholds defined in `scripts/check_data_quality.py`.
- **DoD チェックリスト**:
  - `docs/data_quality_ops.md` explains triage, acknowledgement logging, escalation triggers, and wrap-up verification.
  - `ops/health/data_quality_alerts.md` hosts the acknowledgement table template kept in reverse chronological order.
  - README / documentation portal reference the new runbook so operators can discover it without digging through history.
- 2026-05-30: Documented the review loop, created the acknowledgement log template, and linked the runbook from the README and documentation portal.
- 2025-10-09: Piloted the acknowledgement workflow with a dry-run failure by forcing a 1m expected interval, logged the entry in [ops/health/data_quality_alerts.md](../ops/health/data_quality_alerts.md), and confirmed the runbook/backlog cross-references capture escalation hand-offs.
- 2026-06-02: Added `scripts/record_data_quality_alert.py` to capture acknowledgement rows programmatically, documented usage in `docs/data_quality_ops.md`, and created pytest coverage so operators can log alerts without hand-editing Markdown.
- 2026-06-12: Simulated a coverage failure via `--expected-interval-minutes 1`, verified the CLI exports and acknowledged the alert with `scripts/record_data_quality_alert.py`, then re-ran the audit with production flags to confirm a clean pass. Logged the workflow update in `docs/data_quality_ops.md` and refreshed the acknowledgement table.

<a id="p0-16-data-quality-ack-validation"></a>
### ~~P0-16 Data quality acknowledgement input validation~~ ✅ (2026-06-13 クローズ)

- **DoD**: `scripts/record_data_quality_alert.py` rejects invalid coverage ratios, normalises alert/ack timestamps to UTC, and the regression suite asserts both behaviours.
- **Notes**: Guard against malformed webhook payloads or manual data entry errors so the shared acknowledgement log stays machine-parseable for audits.
- 2026-06-13: Added argparse validators for coverage ratios and ISO8601 timestamps, ensured offset inputs convert to `Z`-suffix form, documented the workflow in `docs/data_quality_ops.md`, and extended `tests/test_record_data_quality_alert.py` with conversion/error-path coverage.

<a id="p0-17-data-quality-acknowledgement-duplicate-guard"></a>
### ~~P0-17 Data quality acknowledgement duplicate guard~~ ✅ (2026-06-14 クローズ)

- **DoD**:
  - `scripts/record_data_quality_alert.py` detects acknowledgement rows that already reference the same alert timestamp, symbol, and timeframe and fails loudly instead of appending duplicates (with an override flag when duplicate entries are intentional).
  - Regression tests cover both the failure path and the override behaviour.
  - `docs/data_quality_ops.md` and `ops/health/data_quality_alerts.md` explain the duplicate guard so operators understand how to recover when the CLI refuses to append a row.
- **Notes**: Keep the shared log free from repeated entries for the same alert so auditors can reconcile acknowledgements without guessing which row is authoritative. Provide a clear override for historical imports or intentionally duplicated records.
- 2026-06-14: Added duplicate-detection to `scripts/record_data_quality_alert.py`, introduced a `--allow-duplicate` override, documented the guard in `docs/data_quality_ops.md` / `ops/health/data_quality_alerts.md`, updated the DoD checklist, and extended regression tests to cover the new behaviours.

<a id="p0-18-simulation-daily-wins-precision"></a>
### ~~P0-18 Simulation daily wins precision fix~~ ✅ (2026-07-20 クローズ)

- **DoD**:
  - `scripts/run_sim.py` daily CSV export preserves probability-weighted `wins` values without truncating fractional results.
  - Regression coverage exercises `_write_daily_csv` so fractional wins remain intact after future refactors.
  - Backlog/state/todo docs capture the fix and note the verification command used to validate the behaviour.
- **Deliverables**: Code patch in `scripts/run_sim.py`, updated pytest coverage.
- 2026-07-20: Updated `_write_daily_csv` to keep fractional wins, added pytest coverage (`tests/test_run_sim_cli.py::test_write_daily_csv_preserves_fractional_wins`), ran `python3 -m pytest`, and synced `state.md` / `docs/todo_next.md` with the closure note.

<a id="p0-19-phase4-sim-bugfix-plan"></a>
### ~~P0-19 Phase 4 simulation bugfix & refactor plan refresh~~ ✅ (2026-07-21 クローズ)

- **DoD**:
  - `docs/plans/phase4_sim_bugfix_plan.md` captures W1–W4 workstreams with explicit commands, success metrics, and links to Phase 4 artefacts.
  - The plan specifies regression expectations (`python3 -m pytest` bundles, long-run commands) and references documentation touchpoints (`docs/progress_phase4.md`, `docs/state_runbook.md`, `docs/go_nogo_checklist.md`).
  - Backlog and progress docs log the update so future sessions can follow the remediation playbook without rediscovery.
- 2026-07-21: Reauthored the plan with an executive summary, objectives, workstreams, test/tooling strategy, timeline, and open questions to guide Phase 4 simulation bugfix and refactor execution; aligned references for Codex Cloud hand-offs.

### P0-20 Day ORB experiment history bootstrap (Open)
- **DoD**:
  - Stand up `experiments/history/records.parquet` and per-run JSON under `experiments/history/runs/`, seeded with legacy Day ORB runs and annotated with dataset SHA256/row count, CLI command, and git commit.
  - Deliver `scripts/log_experiment.py` + `scripts/recover_experiment_history.py` with pytest coverage ensuring dual-write integrity and recovery from JSON.
  - Record migration notes and verification commands in `docs/progress_phase4.md` and link the design doc (`docs/plans/day_orb_optimization.md`).
- **Notes**: Blockers must stop downstream automation; capture any missing artefacts in `docs/todo_next.md` before closing.

### P0-21 Day ORB optimisation engine bring-up (Open)
- **DoD**:
  - Add `configs/experiments/day_orb_core.yaml` and implement `scripts/run_param_sweep.py` with grid/random search + hard constraints (drawdown, trades/month).
  - Ship `scripts/select_best_params.py` that emits ranked candidates to `reports/simulations/day_orb_core/best_params.json` and logs provenance to the experiment history.
  - Update `docs/progress_phase4.md` with executed commands (sweep, selection) and refresh backlog anchors (`state.md`, `docs/todo_next.md`).
- **Notes**: Initial delivery may skip Bayesian optimisation; flag the follow-up in P1 if deferred.

### P0-22 Pseudo-live adaptive guardrails (Open)
- **DoD**:
  - Extend `scripts/update_state.py --simulate-live` with bounded parameter deltas (`--max-delta`), VAR/liquidity caps, and archival diffs in `ops/state_archive/`.
  - Implement automatic rollback + alert hooks via `notifications/emit_signal.py` when drift or anomaly thresholds trigger.
  - Document operations + disable/enable procedures in `docs/state_runbook.md` and cross-link from `docs/progress_phase4.md` with dry-run logs.
- **Notes**: Coordinate with risk_manager owners; include reproduction commands (`python3 scripts/update_state.py --simulate-live --dry-run --max-delta 0.2 --var-cap 0.04`).



<a id="p0-07"></a>
### P0-07 runs/index 再構築スクリプト整備 (完了)

- ~~`scripts/rebuild_runs_index.py` が `scripts/run_sim.py` の出力列 (k_tr, gate/EV debug など) と派生指標 (win_rate, pnl_per_trade) を欠損なく復元し、`tests/test_rebuild_runs_index.py` で fixtures 検証を追加。~~
- ~~**ベースライン/ローリング run 起動ジョブ**~~ (2024-06-12 完了): `scripts/run_benchmark_pipeline.py` でベースライン/ローリング run → サマリー → スナップショット更新を一括化し、`run_daily_workflow.py --benchmarks` から呼び出せるようにした。`tests/test_run_benchmark_pipeline.py` で順序・引数伝播・失敗処理を回帰テスト化。
  - 2024-06-05: `tests/test_run_benchmark_runs.py` を追加し、`--dry-run`/通常実行の双方で JSON 出力・アラート生成・スナップショット更新が期待通りであることを検証。
- ~~**P0-09 オンデマンド Day ORB シミュレーション確認**~~ (2026-02-13 完了): `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --mode conservative --equity 100000` を実行し、最新の Day ORB 状態で 50 件トレード・総損益 -132.09 pips を確認。`ops/state_archive/day_orb_5m.DayORB5m/USDJPY/conservative/20251005_132055.json` を生成し、EV プロファイルを再集計した。

## P1: ローリング検証 + 健全性モニタリング（Archive）

フェーズ1タスクの詳細な進捗記録は [docs/task_backlog_p1_archive.md](./task_backlog_p1_archive.md) に保管されています。歴史的な参照が必要な場合は同アーカイブを参照してください。

## P2: マルチ戦略ポートフォリオ化

### ~~P2-01 戦略マニフェスト整備~~ ✅ (2026-01-08 クローズ)
- スキャル/デイ/スイングの候補戦略ごとに、依存特徴量・セッション・リスク上限を YAML で定義し、ルーターが参照できるようにする (`configs/strategies/*.yaml`)。
  - 2025-10-09: `configs/strategies/templates/base_strategy.yaml` に共通テンプレートと記述ガイドを追加し、新規戦略のマニフェスト整備を着手しやすくした。
- 2024-06-22: `scripts/run_sim.py --manifest` でマニフェストを読み込み、RunnerConfig の許容セッション/リスク上限と戦略固有パラメータを `Strategy.on_start` に直結するフローを整備。`tests/test_run_sim_cli.py` で manifest 経由のパラメタ伝播を検証。DoD: [フェーズ1-戦略別ゲート整備](./progress_phase1.md#1-戦略別ゲート整備)。
  - 2026-01-08: `strategies/scalping_template.py` / `strategies/day_template.py` を追加し、`tokyo_micro_mean_reversion`・`session_momentum_continuation` の manifest/実装を新設。`python3 -m pytest tests/test_strategy_manifest.py` で loader 整合性を確認。次ステップは run_sim CLI ドライランと DoD チェック更新。

### ~~P2-02 ルーター拡張~~ ✅ (2026-02-13 クローズ)
- 現行ルールベース (`router/router_v0.py`) を拡張し、カテゴリ配分・相関・キャパ制約を反映。戦略ごとの state/EV/サイズ情報を統合してスコアリングする。
  - 設計ガイド: [docs/router_architecture.md](router_architecture.md)
  - DoD: [docs/checklists/p2_router.md](./checklists/p2_router.md)
  - 2026-01-27: `router/router_v1.select_candidates` がカテゴリ/グロスヘッドルームを参照してスコアへボーナス/ペナルティを適用し、理由ログへ残差状況を記録するよう拡張。`tests/test_router_v1.py` にヘッドルーム差分のスコア回帰を追加し、`docs/checklists/p2_router.md` の DoD を更新。
  - 2026-02-05: `scripts/build_router_snapshot.py` に `--correlation-window-minutes` を追加し、相関行列と併せて窓幅メタデータを `telemetry.json` / ポートフォリオサマリーへ保存。`PortfolioTelemetry` / `PortfolioState` が新フィールドを保持できるよう拡張し、`tests/test_report_portfolio_summary.py` に CLI 回帰とヘルプ出力確認を追加。
  - 2026-02-07: `core/router_pipeline.manifest_category_budget` で manifest `governance.category_budget_pct` を吸い上げつつ、`scripts/build_router_snapshot.py --category-budget-csv` から外部 CSV を取り込んで `telemetry.json` へ集約。`router_v1` はカテゴリ予算超過時に `status=warning|breach` を理由ログへ記録し、段階的にペナルティを強化する。`tests/test_router_pipeline.py` / `tests/test_router_v1.py` へカテゴリ予算ヘッドルームとスコア調整の回帰を追加。
  - 2026-02-08: `core/router_pipeline.build_portfolio_state` が `execution_health` 配下の数値メトリクス（`reject_rate` / `slippage_bps` / `fill_latency_ms` 等）を包括的に取り込み、`router_v1.select_candidates` は各ガード (`max_reject_rate` / `max_slippage_bps` / `max_fill_latency_ms` など) までのマージンを算出して理由ログに記録。閾値に迫るとスコアを段階的に減点し、逸脱時はマージン付きで失格理由を返す。`tests/test_router_v1.py` / `tests/test_router_pipeline.py` に新メトリクスとマージン挙動の回帰を追加し、`docs/router_architecture.md` / `docs/checklists/p2_router.md` を更新して運用手順をリンク。
  - 2026-02-11: `PortfolioTelemetry` / `build_portfolio_state` が `correlation_meta` を保持し、`scripts/build_router_snapshot.py` がテレメトリへメタデータをエクスポートするよう整備。ポートフォリオサマリーの相関ヒートマップには `bucket_category` / `bucket_budget_pct` を含め、`tests/test_report_portfolio_summary.py` / `tests/test_router_pipeline.py` で回帰を追加。`docs/router_architecture.md` / `docs/checklists/p2_router.md` にバケット情報の公開手順を追記。
  - 2026-02-13: Closed the v2 preparation loop by reconciling runner telemetry, documenting the category/correlation scoring path, and marking the DoD checklist complete. Updated `docs/progress_phase2.md` with the English deliverable plan, synced `docs/checklists/p2_router.md`, and ran `python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py` to confirm the final regression set.

- <a id="p2-portfolio-evaluation"></a>**ポートフォリオ評価レポート**: 複数戦略を同時に流した場合の資本使用率・相関・ドローダウンを集計する `analysis/portfolio_monitor.ipynb` と `reports/portfolio_summary.json` を追加。
  - 2026-01-16: `analysis/portfolio_monitor.py` と `scripts/report_portfolio_summary.py` を実装し、`reports/portfolio_samples/router_demo/` のフィクスチャで JSON スキーマを固定。`python3 -m pytest` と CLI ドライランでカテゴリ利用率・相関ヒートマップ・合成ドローダウンの算出を確認し、`docs/logic_overview.md#ポートフォリオ監視` に運用手順と判断基準を追記。
  - 2026-06-15: Re-prioritised for near-term delivery—refresh CLI walkthrough, publish artefact links, and lock regression coverage ahead of P3 automation work。
  - 2026-06-16: `python3 scripts/build_router_snapshot.py --output runs/router_pipeline/latest --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml --manifest-run day_orb_5m_v1=reports/portfolio_samples/router_demo/metrics/day_orb_5m_v1.json --manifest-run tokyo_micro_mean_reversion_v0=reports/portfolio_samples/router_demo/metrics/tokyo_micro_mean_reversion_v0.json --positions day_orb_5m_v1=1 --positions tokyo_micro_mean_reversion_v0=2 --correlation-window-minutes 240 --indent 2` を実行し、続けて `python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/latest --output reports/portfolio_summary.json --indent 2` で最新スキーマを再生成。`budget_status` / `budget_over_pct` / `correlation_window_minutes` / `drawdowns` をレビューしつつ、`docs/logic_overview.md` / `docs/observability_dashboard.md` / `docs/checklists/p2_portfolio_evaluation.md` を更新。`python3 -m pytest` を完走してグリーンを維持し、`docs/todo_next.md` から Archive への移設と `state.md` ログ追記を同期した。
  - 2026-06-18: Follow-up tasks (P2-03〜P2-05) captured in [docs/plans/p2_completion_plan.md](plans/p2_completion_plan.md) to lock regression automation, dataset maintenance, and reviewer hand-off for final sign-off。

### ~~P2-03 Portfolio evaluation regression automation~~ ✅ (2026-06-24 クローズ)
- **DoD**:
  - `scripts/build_router_snapshot.py` と `scripts/report_portfolio_summary.py` の固定フィクスチャ回帰を `python3 -m pytest` へ統合し、カテゴリ予算の warning/breach を検証できること。
  - `docs/logic_overview.md` と `docs/observability_dashboard.md` に再現コマンドと成果物パスを追加して最新ワークフローを共有すること。
  - `docs/checklists/p2_portfolio_evaluation.md` にテスト整備内容とトラブルシュート手順を追記すること。
- **Notes**: artefact はコミットに含めず、生成コマンドとレビュー観点を記録する。
- 2026-06-19: router demo メトリクスを入力に `tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics` を追加し、`tests/test_portfolio_monitor.py::test_build_portfolio_summary_reports_budget_status` / `tests/test_report_portfolio_summary.py::test_report_portfolio_summary_cli_budget_status` と併せて CLI ワークフローの warning/breach 回帰を固定。`docs/logic_overview.md` / `docs/observability_dashboard.md` に pytest コマンドを追記し、チェックリストへトラブルシュート手順を追加した。
- 2026-06-24: レビューで CLI 回帰テストを再実行し、`docs/todo_next.md` → `docs/todo_next_archive.md` / `state.md` を同期して P2-03 を正式にクローズした (`python3 -m pytest`).

### ~~P2-04 Portfolio dataset maintenance & rotation~~ ✅ (2026-06-20 クローズ)
- **DoD**:
  - `reports/portfolio_samples/router_demo/` の更新手順（保持世代・最終更新ログ）を文書化する。
  - サンプルメトリクスと manifest の整合性を検証するスクリプトまたは CLI オプションを用意する。
  - バックログへ更新記録と検証手順を残し、`docs/checklists/p2_portfolio_evaluation.md` から参照できるようにする。
- **Notes**: router snapshot CLI の `--manifest-run` を最新サンプルへ揃え、旧世代 artefact を適切にアーカイブする。
- 2026-06-20: `docs/checklists/p2_portfolio_evaluation.md` に Router demo ローテーション手順と保持ポリシーを追加し、`scripts/validate_portfolio_samples.py` を実装。`python3 scripts/validate_portfolio_samples.py --samples-dir reports/portfolio_samples/router_demo --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml` で manifest 一致・テレメトリ整合性・エクイティカーブ形式を検証できることを確認。`tests/test_validate_portfolio_samples.py` を追加し、pytest から CLI ガードがカバーされるようにした。検証ログは [docs/todo_next_archive.md#portfolio-dataset-maintenance--rotation](./todo_next_archive.md#portfolio-dataset-maintenance--rotation) と `state.md` で追跡。
- 2026-06-26: 再レビューでローテーション手順・検証スクリプト・バックログ参照が最新であることを確認し、P3 観測性オートメーションへ移行できる状態を記録。

### ~~P2-05 Portfolio review hand-off package~~ ✅ (2026-06-22 クローズ)
- **DoD**:
  - `docs/progress_phase2.md` などで回帰テスト・サンプル artefact・運用チェックリストをまとめたレビューパッケージを提供する。
  - `docs/todo_next.md` / `docs/todo_next_archive.md` / `state.md` を同期し、P2 完了時の再現コマンドと結果を記録する。
  - PR サマリで主要指標（予算ステータス、相関窓幅、ドローダウン）を日本語で要約できるようにする。
- **Notes**: P2-03 / P2-04 完了後に着手し、追加課題が見つかった場合は P3 へエスカレーションする。
- 2026-06-21: Authored the reviewer hand-off bundle in `docs/progress_phase2.md#p2-レビューハンドオフパッケージ`, linked the DoD checklist reference, and initiated documentation/state alignment ahead of the closing summary。
- 2026-06-22: Locked the reviewer bundle by recording fixed-budget/correlation/drawdown targets and a Japanese PR summary template in `docs/progress_phase2.md`, synced `docs/todo_next*.md` / `state.md`, and archived the backlog entry for hand-off.
### ~~P2-MS マルチ戦略比較バリデーション~~ ✅ (2026-02-13 クローズ)
- Day ORB と Mean Reversion (`strategies/mean_reversion.py`) を同一 CSV で走らせ、`docs/checklists/multi_strategy_validation.md` に沿ってゲート通過数・EV リジェクト数・期待値差をレビュー。DoD: チェックリストの全項目を完了し、比較サマリをレビュー用ドキュメントへ共有する。
  - 2025-12-02: Mean Reversion 戦略の本実装を `strategies/mean_reversion.py` へ移行し、`configs/strategies/mean_reversion.yaml` / `configs/ev_profiles/mean_reversion.yaml` を整備。`analysis/broker_fills.ipynb` を公開してブローカー別比較を Notebook でも検証可能にし、`tests/test_mean_reversion_strategy.py` を追加してゲート・EV 調整ロジックの回帰を確保。
  - 2026-02-13: `docs/checklists/multi_strategy_validation.md` をフォローして Day ORB / Mean Reversion を最新テンプレで実行。`runs/multi_strategy/` に指標を再生成し、EV プロファイル有無で差分が無いこと（`reversion.json` vs `reversion_no_profile.json`）と、`ev_reject=330` が Mean Reversion の LCB フィルタで律速になっている点を記録。サマリ表と実測コメントを更新し、チェックリスト完了状態を維持。

## ~~P3: 観測性・レポート自動化~~ ✅ (2025-10-11 クローズ)
- **シグナル/レイテンシ監視自動化**: `scripts/analyze_signal_latency.py` を日次ジョブ化し、`ops/signal_latency.csv` をローテーション。SLO違反でアラート。
- **週次レポート生成**: `scripts/summarize_runs.py` を拡張し、ベースライン/ローリング run・カテゴリ別稼働率・ヘルスチェック結果をまとめて Webhook送信。
  - 2026-04-16: `scripts/summarize_runs.py` を通知ペイロード生成フローに刷新し、`--config` での include/宛先制御と Webhook ドライランを追加。`docs/benchmark_runbook.md` に運用手順を記載し、`tests/test_summarize_runs.py` で集計精度と Webhook ペイロードを回帰テスト化。
- **ダッシュボード整備**: EV 推移、滑り推定、勝率 LCB、ターンオーバーの KPI を 1 つの Notebook or BI に集約し、運用判断を迅速化。
  - **DoD チェックリスト**: [docs/checklists/p3_observability_automation.md](checklists/p3_observability_automation.md)
  - 2026-06-15: Kickoff scope drafted—define telemetry refresh cadence, weekly summary payload template, and dashboard data export checklist once P2 reporting refresh is stable.
  - 2026-06-26: P2-03〜P2-05 の DoD を再確認し、`docs/plans/p2_completion_plan.md` のクローズ条件と `docs/progress_phase2.md` のレビューパッケージ整合性を点検済み。次ステップはシグナルレイテンシ監視と週次レポート自動化の実装計画細分化。
  - 2026-06-27: Drafted [docs/plans/p3_observability_automation.md](./plans/p3_observability_automation.md) to codify sampling cadence, webhook payload schema, dataset exports, escalation ownership, and validation checkpoints for implementation hand-off.
  - 2026-06-27: Expanded the blueprint with an executive summary, dependency checklist, implementation milestones, and risk register to clarify DoD expectations ahead of automation hand-off.
  - 2026-06-28: Authored [docs/phase3_detailed_design.md](phase3_detailed_design.md) detailing CLI extensions, data contracts, logging strategy, and test coverage required for automation so implementation can begin without additional scoping.
  - 2026-06-28: Created [docs/checklists/p3_observability_automation.md](checklists/p3_observability_automation.md) covering CLI gates, automation logging, retention policies, validation commands, and documentation updates for the hand-off.
  - 2026-06-29: Kicked off implementation by landing shared automation scaffolding (`scripts/_automation_logging.py`, `scripts/_automation_context.py`) with JSON schema validation and regression tests so downstream CLI work can plug into a common logging/context backbone.
  - 2026-06-30: Implemented the latency automation CLI enhancements (`scripts/analyze_signal_latency.py`, `analysis/latency_rollup.py`, archive schema/config) with retention, rotation, heartbeat, and alert streak handling; refreshed docs and pytest coverage to match the Phase 3 detailed design.
  - 2026-07-01: Delivered the weekly observability payload builder (`analysis/weekly_payload.py`) and CLI wiring (`scripts/summarize_runs.py`) with schema validation, webhook retries, history manifest, and automation logging coverage.
  - 2026-07-02: Completed the dashboard export automation by extending `analysis/export_dashboard_data.py` with dataset-specific outputs, manifest sequencing, heartbeat/history rotation, upload retries, and JSON Schema validation. Added `schemas/dashboard_manifest.schema.json`, documented the new flow in `docs/observability_dashboard.md`, updated the P3 checklist, and introduced regression tests (`tests/test_dashboard_export.py`, `tests/test_dashboard_datasets.py`).
  - 2026-07-03: Connected `run_daily_workflow.py --observability` to chain latency sampling, weekly payload delivery, and dashboard exports using `configs/observability/automation.yaml`. Added default configs for weekly payload/webhook destinations and dashboard exports under `configs/observability/`, documented the automation entrypoint in `docs/observability_dashboard.md`, and expanded `tests/test_run_daily_workflow.py` with coverage for config overrides and failure short-circuiting.
- 2026-07-04: Added `scripts/verify_observability_job.py` to validate automation logs, heartbeat freshness, dashboard manifest schema, and required secrets in one command. Documented nightly verification in `docs/state_runbook.md`, updated the P3 checklist, and introduced regression coverage via `tests/test_verify_observability_job.py`.
  - 2026-07-05: Finalised the observability scheduling package by normalising `configs/observability/automation.yaml` to use `{ROOT}`-aware `args` mappings, adding a global `--dry-run` guard to `run_daily_workflow.py` so latency/weekly jobs skip webhooks during rehearsals, refreshing `configs/observability/*.yaml` defaults, and documenting rollout・rollback steps in `docs/observability_dashboard.md` / `docs/state_runbook.md`.
  - 2026-07-06: Closed the documentation alignment loop—added the observability automation quickstart and log/secrets playbook to `docs/observability_dashboard.md` / `docs/state_runbook.md`, captured implementation status in `docs/plans/p3_observability_automation.md`・`docs/phase3_detailed_design.md`, refreshed the DoD checklist, and synced `docs/todo_next.md` / `state.md` with the next scheduling hand-off.
  - 2026-07-07: Introduced `scripts/verify_dashboard_bundle.py` to re-check dashboard manifests, dataset checksums, and history retention ahead of uploads. Documented the workflow in `docs/observability_dashboard.md`, updated the P3 DoD checklist, refreshed `docs/plans/p3_observability_automation.md` / `docs/phase3_detailed_design.md`, and added regression coverage via `tests/test_verify_dashboard_bundle.py`.
  - 2026-07-08: Refactored `analysis/export_dashboard_data.py` to funnel dataset builder errors, manifest persistence, history retention, upload retries, and heartbeat writes through reusable helpers so fatal paths remain isolated. Confirmed the dashboard export/verification pytest suites stay green.
  - 2026-07-09: Consolidated dashboard dataset builders around a shared finalisation helper to enforce consistent metadata, checksum persistence, and source tracking across `analysis/export_dashboard_data.py`. Extended regression tests to inspect dataset payload contents and keep observability automation maintainable.
  - 2025-10-11: Exercised the observability automation chain end-to-end (pytest, dry-run workflow, verify CLI, dashboard bundle check), persisted the latest weekly payload to `ops/weekly_report_history/2025-10-06.json`/`.sig`, and confirmed automation logs/heartbeats match the detailed design requirements。Remaining ops follow-up (production cron cut-over, secret rotation drills) tracked under P4 operational readiness tasks。

## P4: 検証とリリースゲート

### P4-01 長期バックテスト改善
- **DoD**:
  - Conservative / Bridge の 2018–2025 通しランを最新データで再実行し、Sharpe・最大DD・年間勝率がリリース基準を満たすようパラメータまたはガードを調整する。
  - 改善後のメトリクスと再現コマンドを `docs/progress_phase4.md`・`state.md`・PR 説明に記録し、`reports/long_{mode}.json` / `reports/long_{mode}_daily.csv` を更新する。
  - Paper 判定に向けたエビデンスを `docs/go_nogo_checklist.md`・`docs/progress_phase4.md#運用チェックリスト` に保存し、承認ログのリンクとともに共有する。
- **Notes**:
- 2026-08-19: Guard-relaxed manifest (`configs/strategies/day_orb_5m_guard_relaxed.yaml`) long-runs executed for Conservative / Bridge
  (`runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251014_051935` /
  `runs/phase4/backtests_guard_relaxed/USDJPY_bridge_20251014_052447`).
  Captured metric diffs under `reports/diffs/conservative_guard_relaxed_metrics.json` / `reports/diffs/bridge_guard_relaxed_metrics.json`
  and strategy gate summaries (`reports/diffs/*_strategy_gate.json`) showing 449 `or_filter` blocks concentrated near `min_or_atr_ratio=0.18`.
  Next action is to segment these blocks by ATR band to propose the next threshold adjustments.
- 2026-08-17: Runner 側に EV オフ時のサイジングフォールバックを実装し、`core/runner_entry.SizingGate` が `fallback_win_rate` / `size_floor_mult` を利用してゼロ数量を回避できるよう更新。`tests/test_runner.py::test_sizing_gate_ev_off_uses_fallback_quantity` を追加し、Phase4 シンプル化リブート検証で EV 無効のまま数量が算出されることを確認。`docs/todo_next.md`・`docs/progress_phase4.md`・`state.md` を同期。
- 2026-08-18: Phase4 ガード緩和の試験マニフェスト `configs/strategies/day_orb_5m_guard_relaxed.yaml` を追加。`or_n=4` / `min_or_atr_ratio=0.18` / `allowed_sessions=[TOK,LDN,NY]` を設定し、EV 無効 + フォールバックサイジング構成で Conservative / Bridge の比較ランを取得できる体制を整備。`docs/progress_phase4.md` にハイライトと現状サマリを追記し、`docs/todo_next.md` / `state.md` の次ステップをセッション・ATR 差分計測タスクへ更新。
- 2026-08-16: Conservative / Bridge のデバッグ run（2025-01-01〜2025-10-13）を解析し、`router_gate` が Tokyo セッションの完全拒否、`or_filter` が `min_or_atr_ratio` 未満、`zero_qty` が EV オフ時の Kelly サイジング起因であることを特定。[reports/simulations/day_orb5m_20251013_summary.md](../reports/simulations/day_orb5m_20251013_summary.md) に改善案（Runner フォールバック導入 / セッション緩和 / ATR 閾値調整）と根拠 JSON を追記し、次の実装タスクを `docs/todo_next.md` に展開した。
- 2025-10-13: Manifest 既定条件（EV 無効・auto_state=false）で Conservative / Bridge 長期ランを実行したが、`gate_block` 196,554 件 / `zero_qty` 248,230 件でトレード 0 件。`reports/simulations/day_orb5m_20251013_summary.md` に結果を整理し、ガード解析のフォローアップを `docs/todo_next.md` へ記録。
- 2026-08-07: Re-ran the 2018–2025 long-run baselines for Conservative / Bridge using the refreshed validated dataset, updated `reports/long_{mode}.json` / `_daily.csv`, and archived run artifacts under `runs/phase4/backtests/USDJPY_conservative_20251013_061258` / `USDJPY_bridge_20251013_061509`. Logged metrics and evidence in `docs/progress_phase4.md` and `state.md` per the Phase 4 plan.
- 2026-08-06: `scripts/run_sim.py` に `session.log` 自動出力を組み込み、Run ディレクトリへ CLI コマンド・開始/終了タイムスタンプ・CSV ローダ統計・stderr 警告を保存するよう更新。W1 Step5 のエビデンス確保を自動化し、`tests/test_run_sim_cli.py` にセッションログ検証を追加。
- 2026-08-05: `reports/diffs/README.md` で W1 diff アーティファクト保管手順と `scripts/compare_metrics.py` 実行例を明文化し、長期ラン比較結果を `docs/progress_phase4.md` / `state.md` へ連携する際の証跡テンプレを整備。
- 2026-08-08: `scripts/compare_metrics.py` に webhook 通知フラグを追加し、差分検出時に自動アラートを発火できるようにした。`tests/test_compare_metrics.py` へ回帰を追加し、`docs/plans/phase4_sim_bugfix_plan.md` §5.5 / Open Questions を更新。
- 2026-08-10: `scripts/run_sim.py` が ラン成果物の SHA256 (`checksums.json`) を自動生成し、`session.log` へもダイジェストを同梱。W1 Step6 の手動チェックサム記録を不要化し、Phase4 ロングランの証跡整備を前倒しした。
- 2026-07-15: `data/usdjpy_5m_2018-2024_utc.csv` / `data/usdjpy_5m_2025.csv` / 既存短期スナップショットをマージし、`validated/USDJPY/5m.csv` / `_with_header.csv` を2018–2025通しに更新。短期ビューは `validated/USDJPY/5m_recent*.csv` へ退避し、`scripts/check_data_quality.py --calendar-day-summary` でギャップが週末由来であることを確認（coverage_ratio=0.71）。長期ランは新ファイルで再実行予定。
  - 2026-07-15: `docs/progress_phase4.md` のハイライトを刷新し、Go/No-Go チェックリストに担当者・頻度・証跡列を追加。次回ランからメトリクスと証跡リンクを `docs/progress_phase4.md#運用チェックリスト` に記録する準備を整えた。
  - 2026-07-05: `scripts/run_sim.py --no-auto-state` で Conservative/Bridge ベースラインを再取得したところ、`validated/USDJPY/5m.csv` が 2025-10-02 以降のみであることが判明。2018–2024 の validated スナップショット再構築と `runs/phase4/backtests/` パラメータ探索ディレクトリ整備を優先 TODO として記録。
  - 2026-06-27: [docs/plans/phase4_validation_plan.md](plans/phase4_validation_plan.md) で Sharpe/最大DD/年間勝率の暫定目標とベース再実行コマンド、runs 配下の成果物整理方針を確定。週次レビュー時に `docs/progress_phase4.md` へメトリクス表を追記する運用を開始。
  - 2025-10-11: Baselineレビューで Conservative -243 pips / Bridge -934 pips を確認。パラメータ再調整に着手。

### P4-02 異常系テスト自動化
- **DoD**:
  - スプレッド急拡大・欠損バー・レイテンシ障害など主要異常シナリオを `pytest` 常設テストに組み込み、CI で再現可能にする。
  - 再現 CLI / テストデータ作成手順を `docs/state_runbook.md#incident` と `docs/progress_phase4.md` に追記する。
  - 失敗時のエラーコード／通知フローがログに残ることを `tests/test_data_robustness.py` 等で検証する。
- **Notes**:
  - 2026-06-27: 検証計画でデータ欠損・ボラティリティジャンプ・レイテンシ遅延・状態不整合のシナリオと `pytest -k robustness --maxfail=1` のCIスモークを定義。fixtures共通化と Slack風通知ログの整備をタスクリストへ追加。
  - 2025-10-11: Ready へ昇格予定。既存テストパターンを棚卸しして設計差分をまとめる。

### P4-03 Go/No-Go チェックリスト確定
- **DoD**:
  - `docs/go_nogo_checklist.md` を最新運用手順（state バックアップ、通知 SLO、秘密情報の確認、ローリング検証結果共有）で更新し、Paper 移行時の承認プロセスを定義する。
  - チェック項目ごとに担当者・頻度・検証ログテンプレを付与し、`state.md` と `docs/todo_next_archive.md` へ記録方法を明記する。
  - モックレビューを実施し、記録を残すことで実運用の準備が整っていることを確認する。
- **Notes**:
  - 2026-07-15: `docs/go_nogo_checklist.md` を担当者・頻度・証跡列付きテーブルへ刷新し、Paper 判定ログを `docs/progress_phase4.md` と連携させる更新ルールを追加。
  - 2026-06-27: 検証計画でチェック項目を「データ品質 / シミュレーション / 運用準備 / レビュー体制」に分類し、担当者・頻度・証跡リンク欄を `docs/go_nogo_checklist.md` へ追加する更新ステップとモックレビュー記録先（本ドキュメント／`docs/todo_next_archive.md`）を設定。
  - 2025-10-11: Ready へ昇格予定。P4-01 の結果を踏まえて更新範囲を確定する。

### P4-04 Day ORB シンプル化リブート（2025-10-13追加）
- **目的**: EVゲート凍結後の Day ORB 5m を再構成し、シンプルなフィルタでも一定のトレード頻度・勝率を確保できる状態へ戻す。
- **スコープ**:
  - `configs/strategies/day_orb_5m.yaml` / `strategies/day_orb_5m.py` を中心に、EV依存を排しつつ ATR帯・日次本数・連敗ガードなどの軽量フィルタを設計。
  - `scripts/run_sim.py` 実行フローは `auto_state=false / aggregate_ev=false / use_ev_profile=false / ev_mode="off"` とし、日次ダッシュボードで勝率・PF・連敗数をモニタする運用をまとめる。
  - 新フィルタで 2018–2025 のロングランにて「トレード数>0」「勝率・DDが暫定閾値を満たす」ことを DoD とする（暫定閾値は設計見直しで再定義）。
  - EV再導入の判断材料として、日次レポートに期待値推定/ローリング勝率を残すための記録手順を整理。
- **懸念点 / TODO**:
  - 現状ロングランはトレード0件。シグナル閾値がなお過剰に厳しいため、発火条件の緩和とリスクガード再調整を最優先で進める。
  - 日次/週次モニタリングで使うKPI（勝率・PF・連敗数・日次DDなど）と停止条件を具体化し、Codex Cloud セッション開始時に参照できるよう `docs/progress_phase4.md` へ整理する。
  - Bridgeモード等の派生マニフェストも同方針で更新し、挙動差異を比較レポートに記録する。
- **初期タスク**:
  1. シグナル生成条件の緩和案を洗い出し、テスト用マニフェストに反映。
  2. シンプルトレードガード（連敗停止、日次DD、ATRバンド等）を Runner レベルで整理。
  3. `docs/progress_phase4.md` にシンプル化リブートの計画・暫定DoD・評価指標を追加。
- 2026-08-12: Runner コンテキストへ `loss_streak` / `daily_loss_pips` / `daily_trade_count` を露出し、Day ORB シグナルは EV 依存なしで連敗・日次DD・日次本数ガードを評価するよう更新。マニフェストの OR/ATR 閾値と TP/SL 比率を緩和し、EV フラグ（`ev_mode=off` / `auto_state=false` / `aggregate_ev=false` / `use_ev_profile=false`）を維持したままシンプルリブート検証用のしきい値を反映。
- 2026-08-13: Day ORB のシンプルガード運用でブロック理由を追跡できるよう、クールダウン・日次本数・ATR帯・マイクロトレンド・サイズ失敗時の `_last_gate_reason` を詳細化し、`tests/test_day_orb_retest.py` に EV オフ前提のガード回帰を追加。EV プロファイルを再稼働させずにモニタリング指標を可視化する下準備を整備。
- 2026-08-14: `_last_gate_reason` の内容を Runner デバッグ出力へ連携するため、`core/runner_entry.EntryGate` が戦略ゲート失敗時に連敗ガード・日次損失/本数・ATR帯・マイクロトレンド・サイズ算出情報を `strategy_gate` レコードへ転記するよう拡張。`core/runner.py` と `docs/backtest_runner_logging.md` を同期し、`tests/test_runner.py::test_strategy_gate_metadata_includes_day_orb_guards` で EV 無効化状態のまま可視化を回帰テスト化。
- 2026-08-15: `scripts/run_sim.py` に `--debug` / `--debug-sample-limit` を追加して EV 無効化のまま `strategy_gate` レコードを収集し、`scripts/summarize_strategy_gate.py` で `records.csv` を集計できる分析パスを整備。閾値調整の試行錯誤を EV プロファイル再稼働なしで進めるための観測手段を確立。
- 2026-10-15: Manifest 由来の `ev_mode` / `allow_low_rv` / `threshold_lcb` が `params.json`・`runs/index.csv` に反映されるよう `scripts/run_sim.py` を拡張し、`python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/tmp/day_orb5m_ev_guard --json-out runs/tmp/day_orb5m_ev_guard/metrics.json --out-daily-csv runs/tmp/day_orb5m_ev_guard/daily.csv --no-auto-state` を再実行。新ラン (`runs/USDJPY_conservative_20251015_035143`) では `ev_mode=off` / `allow_low_rv=True` が `runs/index.csv` に残り、`metrics.json` の `runtime.ev_reject=0` と `daily.csv` の `ev_reject` 列で EV リジェクトゼロを確認。`python3 scripts/rebuild_runs_index.py --runs-dir runs --out runs/index.csv` で索引を再構築。

## 継続タスク / 保守
- データスキーマ検証 (`scripts/check_data_quality.py`) を cron 化し、異常リストを `analysis/data_quality.md` に追記。
- 回帰テストセットを拡充（高スプレッド、欠損バー、レイテンシ障害等）し、CI で常時実行。
- 重要な設計・運用変更時は `readme/設計方針（投資_3_）v_1.md` と `docs/state_runbook.md` を更新し、履歴を残す。

> 補足: 着手順は P0 → P1 → P2 の順。途中で運用インシデントが発生した場合は、P1「インシデントリプレイテンプレート」の整備を優先してください。

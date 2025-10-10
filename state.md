# Work State Log

## Workflow Rule
- Review this file before starting any task to confirm the latest context and checklist。
- 2026-06-23: Refined portfolio monitoring docs by adding explicit reproduction commands (`python3 scripts/build_router_snapshot.py` / `python3 scripts/report_portfolio_summary.py`), expected artefact locations, and review checkpoints that link to `runs/router_pipeline/latest/` と `reports/portfolio_summary.json`。
- 2025-10-10: Added router demo budget warning/breach regression that shells out to `scripts/build_router_snapshot.py` and `scripts/report_portfolio_summary.py`, validating telemetry headroom and summary status transitions via pytest. Executed `python3 -m pytest` to confirm suite health.
- 2026-06-22: P2-05 hand-off をクローズ。`docs/progress_phase2.md` へ固定化された予算ステータス・相関窓幅・ドローダウン指標と日本語 PR サマリー例を追記し、`docs/task_backlog.md` / `docs/todo_next*.md` を同期。`python3 scripts/validate_portfolio_samples.py --samples-dir reports/portfolio_samples/router_demo --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml` と `python3 -m pytest` を実行してサンプル整合性と回帰スイートを確認。次フェーズ移行に向けて backlog を更新。
- 2026-06-21: P2-05 reviewer hand-off を開始し、`docs/progress_phase2.md#p2-レビューハンドオフパッケージ` に回帰テストコマンド／サンプル artefact／運用チェックリストを集約。`docs/task_backlog.md`・`docs/todo_next.md`・`docs/todo_next_archive.md` を同期し、`docs/checklists/p2_portfolio_evaluation.md` に参照リンクを追加。`python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/latest --output reports/portfolio_summary.json --indent 2` と `python3 -m pytest` を実行して成果物更新とスイートグリーンを確認。PR 共有用サマリー案: 「ポートフォリオ評価レビュー手順を `docs/progress_phase2.md` に一本化し、router demo サンプルの検証パスと最新 `reports/portfolio_summary.json` を再生成。pytest 317 件が warning のみで完走し、予算ステータス/相関窓幅/ドローダウン指標をレビュワーが即確認できる状態に整えました。」
- 2026-06-20: Documented Router demo sample retention (P2-04) in `docs/checklists/p2_portfolio_evaluation.md`, updated `docs/task_backlog.md` / `docs/plans/p2_completion_plan.md`, and implemented `scripts/validate_portfolio_samples.py` plus `tests/test_validate_portfolio_samples.py` to guard manifest とテレメトリ整合性。
  Executed `python3 scripts/validate_portfolio_samples.py --samples-dir reports/portfolio_samples/router_demo --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml` and `python3 -m pytest tests/test_report_portfolio_summary.py tests/test_portfolio_monitor.py tests/test_validate_portfolio_samples.py` to capture validation logs.
- 2026-06-19: Landed router demo regression coverage by adding `tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics`, updating the existing summary warning/breach tests, and documenting the pytest command suite in `docs/logic_overview.md`, `docs/observability_dashboard.md`, and `docs/checklists/p2_portfolio_evaluation.md`. Synced `docs/task_backlog.md` / `docs/todo_next.md` with the Pending Review status and executed `python3 -m pytest tests/test_portfolio_monitor.py tests/test_report_portfolio_summary.py` for validation.
- 2026-06-18: Broke down remaining P2 deliverables into P2-03〜P2-05, documented the scope in `docs/plans/p2_completion_plan.md`,
  refreshed backlog/todo anchors, and updated `Next Task` to launch the regression automation workstream.
- 2026-06-17: Added regression coverage for router demo budget warnings/breaches by cloning the sample snapshot under `tmp_path`,
  mutating category utilisation/headroom to trigger `budget_status` = warning/breach, and validating both
  `build_portfolio_summary` and the CLI JSON output (`tests/test_portfolio_monitor.py` / `tests/test_report_portfolio_summary.py`).
  Executed `python3 -m pytest tests/test_portfolio_monitor.py tests/test_report_portfolio_summary.py` to confirm the additions.
- 2026-06-16: Refreshed the P2 portfolio evaluation pipeline by cross-checking `runs/index.csv` (Day ORB latest `runs/USDJPY_conservative_20251002_214013`, Tokyo Micro via curated sample metrics), running `python3 scripts/build_router_snapshot.py --output runs/router_pipeline/latest --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml --manifest-run day_orb_5m_v1=reports/portfolio_samples/router_demo/metrics/day_orb_5m_v1.json --manifest-run tokyo_micro_mean_reversion_v0=reports/portfolio_samples/router_demo/metrics/tokyo_micro_mean_reversion_v0.json --positions day_orb_5m_v1=1 --positions tokyo_micro_mean_reversion_v0=2 --correlation-window-minutes 240 --indent 2` and `python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/latest --output reports/portfolio_summary.json --indent 2`, reviewing `budget_status` / `budget_over_pct` / `correlation_window_minutes` / `drawdowns`, updating docs (`docs/logic_overview.md`, `docs/observability_dashboard.md`, `docs/checklists/p2_portfolio_evaluation.md`) plus backlog/todo/archive entries, and logging evidence via `docs/todo_next_archive.md`. Validated the suite with `python3 -m pytest` and captured artefact paths for the PR summary。
- 2026-06-15: Deferred the P0 live-alert validation loop until production emits the first `data_quality_failure`, reorganised docs/todo/backlog to prioritise the P2 portfolio report refresh and scoped the first P3 observability automation milestone.
- 2026-06-14: Blocked duplicate acknowledgement rows by default in `scripts/record_data_quality_alert.py`, added a `--allow-duplicate` escape hatch, refreshed docs/data_quality_ops.md & ops/health/data_quality_alerts.md, synced backlog/todo/checklist updates, and ran `python3 -m pytest` to keep the suite green。
- 2026-06-13: Hardened `scripts/record_data_quality_alert.py` against malformed coverage ratios and timezone-less timestamps, documented the guardrails in docs/data_quality_ops.md, synced backlog/todo entries, and ran `python3 -m pytest` to keep the suite green。
- 2026-06-12: Promoted P2 portfolio evaluation report to Ready by adding deliverable notes in docs/todo_next.md and anchoring the backlog entry for quick reference。
- 2026-06-12: Closed P0-15 data quality alert operations loop by forcing a coverage failure (`--expected-interval-minutes 1`), confirming gap/summary artefacts under `reports/data_quality/`, recording the acknowledgement with `python3 scripts/record_data_quality_alert.py`, updating docs/data_quality_ops.md & docs/todo_next.md, and running `python3 -m pytest` to ensure the suite stays green。
- 2026-06-02: Implemented `scripts/record_data_quality_alert.py` and captured a live log entry to verify Markdown formatting. Updated docs/data_quality_ops.md with CLI usage, synced backlog notes, and ran `python3 -m pytest` to confirm the suite remains green.
- 2026-05-30: Documented the `data_quality_failure` alert operations loop via docs/data_quality_ops.md, seeded ops/health/data_quality_alerts.md for acknowledgement tracking, refreshed README / docs/documentation_portal.md / docs/task_backlog.md / docs/todo_next.md links, and ran `python3 -m pytest` to keep regressions green.
- 2026-06-01: Extended the duplicate saturation controls by adding `--fail-on-duplicate-occurrences` to `scripts/check_data_quality.py`, propagated the new guard and defaults through `scripts/run_daily_workflow.py`, refreshed README / docs/data_quality_ops.md / docs/task_backlog.md guidance, and ran `python3 -m pytest` to keep the suite green.
- 2026-05-31: Added duplicate saturation failure guards to `scripts/check_data_quality.py`, enabled the daily workflow to fail when five or more duplicate timestamp groups persist, refreshed README / docs/data_quality_ops.md guidance, updated the backlog entry, and ran `python3 -m pytest` to confirm the suite stays green.
- 2026-05-30: Ensured `scripts/check_data_quality.py` matches the README invocation flow by restoring the repo-root import path before `_time_utils` is loaded so `python3 scripts/check_data_quality.py` works without extra env vars. Revalidated CLI help and executed `python3 -m pytest` to confirm regressions stay green.
- 2026-05-29: Enabled `scripts/check_data_quality.py --webhook` to deliver `data_quality_failure` alerts, propagated webhook/timeout controls through `run_daily_workflow.py --check-data-quality`, refreshed README / docs/state_runbook.md guidance, updated the backlog entry, and ran `python3 -m pytest` to keep the suite green.
- 2026-05-28: Wired `run_daily_workflow.py --check-data-quality` into the ingest workflow so coverage failures surface as non-zero exits, documented escalation guidance in README/state runbook, refreshed backlog notes, and ran `python3 -m pytest` to confirm the suite remains green.
- 2026-05-27: Added failure guards to `scripts/check_data_quality.py` so audits can exit non-zero when overall coverage falls below a configurable floor or when calendar-day warnings persist, refreshed README/backlog guidance, and ran `python3 -m pytest` to keep the suite green。
- 2026-05-26: Extended `scripts/check_data_quality.py` with a calendar-day coverage summary (`--calendar-day-summary` + threshold/max-report controls) so audits can highlight low-coverage UTC days, refreshed README/backlog guidance, and ran `python3 -m pytest` to confirm the suite stays green.
- 2026-05-25: Added `--min-duplicate-occurrences` filtering to `scripts/check_data_quality.py`, surfaced ignored duplicate counters in summaries/exports, refreshed README/backlog guidance, and ran `python3 -m pytest` to keep regressions green。
- 2026-05-24: Prioritised P0-13 duplicate severity metrics by sorting groups by occurrence count, exposing summary timestamps/spans, refreshing README/backlog notes, and running `python3 -m pytest` to keep the suite green.
- 2026-05-23: Extended P0-13 data quality audits with duplicate timestamp inventories (`--out-duplicates-csv` / `--out-duplicates-json`) and summary truncation controls, refreshed README/backlog guidance, and reran `python3 -m pytest` to confirm the suite stays green.
- 2026-05-21: Extended P0-14 gap reporting with ISO-8601 `--start-timestamp` / `--end-timestamp` filters in `scripts/check_data_quality.py`, refreshed README/backlog guidance, and executed `python3 -m pytest` to verify the suite remains green.
- 2026-05-20: Closed out P0-13 data quality audit enhancements by archiving the Pending Review entry, syncing backlog/todo/state docs, and re-running `python3 -m pytest` to confirm the suite stays green.
- 2026-05-19: Auto-detected `scripts/check_data_quality.py` bar intervals and added an `--expected-interval-minutes` override,
  refreshed README/backlog/todo notes, and re-ran `python3 -m pytest` to keep the suite green.
- 2026-05-18: Normalised `scripts/check_data_quality.py` timestamp parsing to accept trailing `Z`/offset markers, updated the
  pytest fixture plus backlog/todo notes, and re-ran `python3 -m pytest` to confirm coverage remains green.
- 2026-05-17: Closed out P0-12 Codex-first documentation cleanup by archiving the Pending Review entry, completing the remaining DoD checklist action, updating backlog/todo archive notes, and re-running `python3 -m pytest` to keep the suite green.
- 2026-05-16: Finalised P0-14 data quality gap reporting hand-off by archiving the todo entry, capturing reproduction commands/output paths, ticking the DoD checklist, updating backlog notes, and running `python3 -m pytest` to keep regressions green.
- 2026-05-15: Initiated P0-14 data quality gap reporting to extend `scripts/check_data_quality.py` with exportable gap tables and richer metrics; synced backlog/todo checklists before coding.
- 2026-05-13: Revalidated documentation alignment for P0-12, synced `docs/todo_next.md` Pending Review entry with `state.md`, updated `docs/state_runbook.md` command examples to mirror the quickstart/workflow, refreshed the backlog memo, and ran `python3 -m pytest` to confirm regressions remain green.
- 2026-05-14: Enhanced `scripts/check_data_quality.py` with coverage/monotonic metrics and JSON export support, added pytest coverage via `tests/test_check_data_quality.py`, updated the backlog (`P0-13`) and todo-next Pending Review entries, and executed `python3 -m pytest` to keep the suite green.
- 2026-05-12: Drafted docs/checklists/p0-12_doc_cleanup.md and linked it from docs/task_backlog.md plus docs/documentation_portal.md to standardise P0-12 documentation hygiene checks; ran `python3 -m pytest` to keep the regression suite green.
- 2026-05-11: Reviewed README / documentation portal / quickstart / workflow text alignment for P0-12, found no blocking issues
  as of 2025-10-09, confirmed anchors remain in sync for Codex operators, and noted that documentation updates after
  2025-10-09 require a fresh audit (documentation-only review; tests not required).
- 2026-05-10: README の Developer Quickstart から `requirements.txt` 参照を除外し、[docs/dependencies.md](docs/dependencies.md) と推奨 `pip install` コマンド（`pytest` / `pandas matplotlib` / `dukascopy-python` 例）を明示して初回セットアップ手順を整理。
- 2026-05-09: Corrected `docs/dependencies.md` の matplotlib フラグ説明を `--plot-out` / パイプライン伝播に合わせて更新し、CLI 手順との齟齬を解消。
- 2026-05-08: Realigned README doc hub, documentation portal, quickstart/workflow/state runbook cross-references, and added a documentation hygiene checklist so newcomers can follow a single orientation path without duplication。
- 2026-05-07: Expanded `docs/documentation_portal.md` with an orientation cheat sheet and aligned README / quickstart / workflow / state runbook guidance so newcomers can map responsibilities quickly。
- 2026-05-06: Authored `docs/documentation_portal.md` to map all runbooks, reorganised README onboarding flow, and synced quickstart/workflow references plus todo/backlog anchors。
- 2026-05-04: Long-term roadmap links refreshed—expanded `docs/architecture_migration.md`, `docs/observability_plan.md`, and `docs/audit_playbook.md` placeholders and revalidated `docs/development_roadmap.md` references。
- 2026-05-03: Promoted docs/task_backlog.md P0-12 / P0-07 entries to headings with explicit anchors and confirmed docs/development_roadmap.md links resolve.
- 2026-05-02: Updated `docs/todo_next_archive.md` P2-01 DoD 行のリンク表示を `p2_manifest.md` へ揃え、`docs/checklists/` のファイル構成と一致することを確認。
- 2026-05-01: Refreshed `docs/development_roadmap.md` mid-term EV calibration note to link the existing `docs/ev_tuning.md` procedures and drop the placeholder wording。
- 2026-04-30: Updated `docs/todo_next_archive.md` so the P2-01 archive references `./checklists/p2_manifest.md`, fixed remaining `p2-01` checklist slugs, and re-ran `rg 'docs/checklists/' docs/todo_next_archive.md` to confirm link targets。
- 2026-04-29: Converted the docs/task_backlog.md sample entry to link directly to docs/progress_phase1.md, checked for lingering
  docs/progress/ paths, and ensured the target document exists for navigation.
- 2026-04-28: Created placeholder docs for roadmap long-term items referenced in docs/development_roadmap.md and rechecked link resolution.
- 2026-04-28: Inserted explicit anchors for P0-12 / P0-07 in `docs/task_backlog.md` and verified roadmap links resolve to the updated sections.
- 2026-04-27: Corrected the example link in `docs/task_backlog.md` to reference `docs/progress_phase1.md`, keeping backlog guidance aligned with the actual file structure.
- 2026-04-26: README のオンデマンドインジェスト CLI 節で `scripts/fetch_prices_api.py` の REST API ガイダンスを単一の箇条書きに統合し、Sandbox 向け注意点をサブ項目へ整理して重複記述を解消。
- 2026-04-25: Re-verified all `docs/` Markdown for stray `] (docs/...)` links, found none, and updated `docs/codex_workflow.md` with the explicit `docs/docs` failure note so future sessions keep using `./`-style relative paths.
- 2026-04-24: Normalised `docs/` internal links to relative paths, verified cleanup with `rg '\\]\(docs/' docs`, refreshed `docs/task_backlog.md` notes, and added link hygiene guidance to the workflow doc.
- 2026-04-23: README のオンデマンドインジェスト CLI 節で `scripts/fetch_prices_api.py` の案内を再整理し、重複記述を 1 つの箇条書きへ統合したまま API キー運用・Sandbox フォールバックの説明を保持。
- 2026-04-22: `docs/api_ingest_plan.md` の Error Handling & Observability 節で `ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>`
  の説明を一つの箇条書きへ統合し、ローカルバックアップパスの補足を保持したまま重複を解消。
- 2026-04-21: README のオンデマンドインジェスト CLI 節で `scripts/fetch_prices_api.py` の重複箇条書きを統合し、Sandbox フォールバック説明を保持したまま冗長記述を解消。
- 2026-04-20: P1 バックログを docs/task_backlog_p1_archive.md へ移設し、旧アンカー参照をアーカイブへ更新。
- 2026-04-19: `docs/todo_next.md` の Archive セクション文面を整理し、`manage_task_cycle` プレースホルダのみを残したポインタへ刷新。`docs/codex_quickstart.md` / `docs/todo_next_archive.md` も新アーカイブ参照へ揃え、クロスドキュメントの参照先を統一。
- 2026-04-18: `docs/todo_next.md` の Archive セクションを新設した [docs/todo_next_archive.md](docs/todo_next_archive.md) へ移設し、プレースホルダとアンカー検知用コメントを残した。README / codex ワークフロードキュメント / DoD テンプレ類の参照先を新アーカイブへ更新。
- 2026-04-17: Observability dashboard pipeline を実装し、`analysis/dashboard/` のローダーと `analysis/export_dashboard_data.py` CLI で EV/スリッページ/勝率LCB/ターンオーバーを統合。`analysis/portfolio_monitor.ipynb` と `docs/observability_dashboard.md` を追加し、`docs/task_backlog.md` を更新。`python3 -m pytest` と `python3 analysis/export_dashboard_data.py --out-json /tmp/dashboard.json --portfolio-telemetry reports/portfolio_samples/router_demo/telemetry.json` を実行。
- 2026-04-15: Extended `scripts/analyze_signal_latency.py` with JSON/CSV SLO出力と `--failure-threshold`、`ops/rotate_signal_latency.sh` / `ops/signal_latency_rotation.cron` を追加して日次ローテーション手順を整備。`docs/signal_ops.md` / `README.md` を更新し、`tests/test_analyze_signal_latency.py` で SLO 違反検知を回帰。`python3 -m pytest` と CLI 実行例 (`python3 scripts/analyze_signal_latency.py --input /tmp/latency_sample.csv --out-json /tmp/latency.json --out-csv /tmp/latency.csv`) を完了。
- 2026-04-16: `scripts/summarize_runs.py` をベンチマーク/ポートフォリオ/ヘルスチェックの統合サマリーへ拡張し、Webhook 配信（`--dry-run-webhook`/`--fail-on-webhook-error`）と YAML 設定連携を追加。`docs/benchmark_runbook.md` / `docs/task_backlog.md` を同期し、`tests/test_summarize_runs.py` を新設して集計精度と Webhook 送信フォーマットを回帰。`python3 -m pytest` を完走し、CLI 例 (`python3 scripts/summarize_runs.py --runs-root runs --out-json /tmp/weekly_summary.json --webhook-url http://example.com --dry-run-webhook`) を確認。
- 2025-10-08: Corrected `docs/task_backlog.md` sample link to `docs/progress_phase1.md`, confirmed no lingering `docs/progress/` patterns, and rendered the Markdown via `python3 -m markdown docs/task_backlog.md` for preview.
- 2025-10-08: Drafted `docs/codex_quickstart.md`, trimmed `docs/state_runbook.md` checklists, refreshed README/roadmap/backlog links, and ran `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor docs/task_backlog.md#p0-12-codex-first-documentation-cleanup --date 2025-10-08 --note "Refreshed Codex quickstart, state runbook, and roadmap anchors"`.
- 2026-04-14: Hardened `load_bars_csv` strict enforcement to raise when rows are skipped, extended CLI loader regressions for strict vs tolerant parsing, confirmed script helpers keep `strict=False`, and ran `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-04-12: Added manifest instrument selection flags to `scripts/run_sim.py`, refreshed CLI regression/README guidance, and ran `python3 -m pytest`.
- 2026-04-13: Normalised `scripts/run_sim.py` JSON output path resolution for relative values, added a CLI regression verifying repo-root anchoring, refreshed README guidance, and ran `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-04-11: Hardened `scripts/run_sim.py` EV aggregation failure handling to bubble subprocess output with a non-zero exit, added a CLI regression for the failure path, and ran `python3 -m pytest`.
- 2026-04-09: Added CSV loader diagnostics/strict mode to `scripts/run_sim.py`, plumbed stats into CLI outputs/docs, updated grid/compare helpers, extended CLI tests, and ran `python3 -m pytest`.
- 2026-04-10: Refactored `RunnerExecutionManager` entry flow to iterate multiple intents with per-order metrics, updated fill handling, added multi-intent runner regression, and ran `python3 -m pytest tests/test_runner.py`.
- 2025-10-08: Normalised `scripts/run_sim.py` relative out_dir handling to resolve against the repo root, added a CLI regression covering directory creation from a different working directory, and ran `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-04-08: Normalised timeframe handling across `load_bars_csv` and `validate_bar`, plumbed runner timeframe whitelists, extended CLI/runner tests for uppercase bars, and ran `python3 -m pytest`.
- 2026-04-07: Propagated `--local-backup-csv` overrides from `run_daily_workflow.py` to the default `pull_prices` ingest path, added a CLI regression in `tests/test_run_daily_workflow.py`, and ran `python3 -m pytest`.
- 2026-04-03: Added `--skip-yaml` to `scripts/aggregate_ev.py` so CSV summaries can run without writing profiles, updated
  `scripts/run_sim.py` to append the guard when `--no-ev-profile` is set, extended CLI/script pytest coverage, and ran
  `python3 -m pytest tests/test_run_sim_cli.py tests/test_aggregate_ev_script.py`.
- 2026-04-04: Normalised runner EV keys during state restoration and trade finalisation to accept JSON round-tripped payloads,
  updated `RunnerExecutionManager` to pass canonical tuples to `_get_ev_manager`, added a regression covering
  `load_state(json.loads(json.dumps(state)))`, and ran `python3 -m pytest tests/test_runner.py`.
- 2026-03-31: Ensured `scripts/run_sim.py` respects `--no-ev-profile` when manifests set `state.ev_profile`,
  prevented `aggregate_ev.py` from receiving `--out-yaml` under the flag, extended
  `tests/test_run_sim_cli.py` with a regression, and ran `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-04-02: Normalised `scripts/aggregate_ev.py` default EV profile naming to reuse the module tail,
  added regression coverage for prefixed strategy paths in `tests/test_aggregate_ev_script.py`, updated
  `docs/state_runbook.md` with the filename guidance, and ran `python3 -m pytest tests/test_aggregate_ev_script.py`.
- 2026-04-01: Centralised the `--no-ev-profile` guard in `scripts/run_sim.py`, added a CLI regression ensuring
  `aggregate_ev.py` skips `--out-yaml` when the flag is provided alongside `--ev-profile`, updated
  `docs/task_backlog.md`, and ran `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-03-30: Defaulted blank CSV spread/volume fields to 0.0 in `scripts/run_sim.py`,
  extended `tests/test_run_sim_cli.py` to cover tolerant parsing and CLI runs with empty values,
  documented the behaviour in `README.md`, and ran `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-03-29: Filtered `scripts/run_sim.py` bar streaming so only the resolved symbol feeds the runner,
  added a mixed-symbol regression test in `tests/test_run_sim_cli.py`, and ran
  `python3 -m pytest tests/test_run_sim_cli.py` for confirmation.
- 2025-10-07: Normalised `docs/task_backlog.md` anchors in `scripts/sync_task_docs.normalize_anchor`,
  added regression coverage for uppercase fragments in `tests/test_sync_task_template.py`,
  and ran `python3 -m pytest tests/test_manage_task_cycle.py tests/test_sync_task_template.py`.
- 2025-10-07: Hardened `BacktestRunner._session_of_ts` ISO parsing with UTC normalisation, added
  a debug counter for parse failures, extended regressions for session detection, and ran
  `python3 -m pytest tests/test_runner.py`.
- 2025-10-06: Renamed the runner entry/EV/sizing evaluation dataclasses to `EntryEvaluation` / `EVEvaluation` / `SizingEvaluation`,
  updated BacktestRunner pipelines and regression tests to consume the new names, and ran
  `python3 -m pytest tests/test_runner.py` to confirm the refactor.
- 2026-03-24: Seeded `scripts/run_sim.py` CLI namespaces with manifest `runner.cli_args` defaults while
  preserving user overrides, added regression coverage in `tests/test_run_sim_cli.py`, refreshed
  `configs/strategies/README.md`, and executed `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-03-25: Streamed `scripts/run_sim.py` CSV ingestion by making `load_bars_csv` yield filtered bars,
  updated the CLI to forward the iterator to `BacktestRunner.run` while retaining the first bar for symbol
  resolution, adjusted `scripts/run_compare.py` / `scripts/run_grid.py` to materialise lists as needed,
  extended `tests/test_run_sim_cli.py` with streaming coverage, and ran `python3 -m pytest tests/test_run_sim_cli.py`.
- 2026-03-27: Normalised `scripts/run_sim.py` state archive resolution to anchor relative paths at `ROOT`, forwarded the
  absolute archive directory to `aggregate_ev.py`, added regression coverage for launching from a temporary working
  directory, and executed `python3 -m pytest tests/test_run_sim_cli.py` for verification.
- 2026-03-28: Guarded manifest instrument mode overrides in `scripts/run_sim.py` so user-specified `--mode` flags remain
  intact, added a regression in `tests/test_run_sim_cli.py` covering the CLI override behaviour, and executed
  `python3 -m pytest tests/test_run_sim_cli.py` to confirm the fix.
- 2025-10-06: Added `Strategy.get_pending_signal()` so runner execution no longer reaches into
  `_pending_signal`, implemented the accessor across DayORB/mean reversion/scalping templates,
  refreshed docs/test fixtures, and executed `python3 -m pytest` to validate the integration.
- 2026-03-16: Added helpers to serialise/deserialise `ActivePositionState` / `CalibrationPositionState`
  during runner state export/load, refactored calibration resolution to reuse typed dataclasses,
  and extended `tests/test_runner.py` with coverage that verifies metrics/EV updates under the dataclass
  flow. Executed `python3 -m pytest tests/test_runner.py`.
- 2026-03-17: Exported `_equity_live` with runner state snapshots, restored the live equity when
  loading state so sizing inputs remain consistent across resets, added regression
  `tests/test_runner.py::test_export_reset_load_preserves_live_equity_and_sizing`, and ran
  `python3 -m pytest tests/test_runner.py` for confirmation.
- 2026-03-15: Routed runner context updates through ``Strategy.update_context`` so
  signals consume post-gate data without mutating ``cfg`` payloads, refreshed
  DayORB5m-related regressions plus CLI/feature strategy tests for the API
  change, and executed ``python3 -m pytest``.
- 2026-03-14: Routed strategy runtime context through the new ``signals(ctx)``
  API, updated DayORB5m/templates/mean reversion implementations plus runner
  regressions, and refreshed strategy-facing tests for the call signature.
  Ran ``python3 -m pytest``.
- 2026-03-13: Refined the feature pipeline sanitisation by normalising optional
  opening range bounds, expanded `tests/test_runner_features.py` to cover
  realized volatility history updates, session resets, and mapping behaviour of
  `RunnerContext`, and asserted the runner regression flows consume the
  pipeline-provided context. Ran `python3 -m pytest
  tests/test_runner_features.py tests/test_runner.py`.
- 2026-03-12: Re-synced entry/EV/sizing pipelines so strategy-gate TP/SL
  adjustments propagate to EV threshold and sizing calculations by re-running
  `_extract_pending_fields` post-gate, and added a regression covering mutated
  pending signals. Ran `python3 -m pytest tests/test_runner.py`.
- 2026-03-11: Introduced `EntryEvaluationResult` / `EVEvaluationResult` / `SizingEvaluationResult`
  dataclasses for entry gating, updated `BacktestRunner` and `RunnerExecutionManager`
  to pass typed stage outcomes without optional context checks or dictionary copies,
  and refreshed `tests/test_runner.py` to exercise pipeline success and failure paths
  via the structured results. Ran `python3 -m pytest tests/test_runner.py`.
- 2026-03-08: Split `BacktestRunner` responsibilities into `RunnerLifecycleManager`
  and `RunnerExecutionManager`, moved position state helpers into `core/runner_state.py`,
  refreshed runner/CLI regression tests for the delegation, and updated lifecycle
  documentation. Ran `python3 -m pytest`.
- 2026-03-07: Introduced `ActivePositionState` / `CalibrationPositionState` for runner
  state tracking, refactored fill handling and calibration resolution to use the
  typed dataclasses with JSON-compatible persistence, and refreshed
  `tests/test_runner.py` to assert entry/exit/calibration statistics continue to
  update as expected. Ran `python3 -m pytest tests/test_runner.py`.
- 2026-03-06: Added structured `EntryEvaluation`/`EVEvaluation`/`SizingEvaluation`
  and `TradeContextSnapshot` dataclasses to capture gate outcomes and trade context,
  refactored `BacktestRunner._maybe_enter_trade` to route through the new helpers,
  and updated `tests/test_runner.py` to assert the dataclass-based flow while keeping
  debug/daily metrics stable. Ran `python3 -m pytest tests/test_runner.py`.
- 2026-03-03: Refactored feature computation by introducing `core/runner_features.FeaturePipeline`
  and `RunnerContext`, ensuring bar ingestion, realised volatility windows, and strategy ctx updates
  are centralised. Updated `BacktestRunner._compute_features` to delegate to the pipeline, added
  direct unit tests in `tests/test_runner_features.py`, refreshed runner regressions, and executed
  `python3 -m pytest tests/test_runner.py tests/test_runner_features.py` for confirmation.
- 2026-03-05: Decoupled strategy runtime context from configuration by adding
  `Strategy.update_context`, routing BacktestRunner and FeaturePipeline updates through the new API,
  and updating DayORB5m/templated strategies plus runner/CLI regressions. Ran
  `python3 -m pytest tests/test_runner.py tests/test_runner_features.py tests/test_run_sim_cli.py
  tests/test_ev_and_sizing.py tests/test_mean_reversion_strategy.py tests/test_strategy_feature_integration.py`
  to confirm behaviour.
- 2026-03-04: Introduced `core/runner_entry` with structured gate/EV/sizing dataclasses, refactored
  `BacktestRunner._maybe_enter_trade` to compose `EntryGate`/`EVGate`/`SizingGate`, removed ad-hoc
  `None` checks, and expanded `tests/test_runner.py` with pipeline success/failure coverage.
  Confirmed behaviour with `python3 -m pytest tests/test_runner.py`.
- 2026-03-02: Introduced `PositionState` for runner position tracking, refactored
  `BacktestRunner` to store active/calibration positions via the dataclass with
  export/load support, refreshed `tests/test_runner.py` to cover the new state
  flow, and ran `python3 -m pytest tests/test_runner.py`.
- 2026-03-01: Updated `_process_fill_result` so calibration/live TP/SL prices derive from
  filled entries, ensuring slip-adjusted distances persist in runner state, added
  regression `tests/test_runner.py::test_entry_slip_preserves_tp_sl_distances_and_pnl`
  covering realised PnL after non-zero slip, and executed `python3 -m pytest
  tests/test_runner.py`.
- 2026-02-28: Updated `BacktestRunner` so `RunnerConfig(ev_mode="off")` bypasses the EV threshold by
  clamping the recorded threshold LCB to negative infinity, keeping debug/context logs consistent,
  and added regression `tests/test_runner.py::test_ev_gate_off_mode_bypasses_threshold_checks` to
  ensure breakouts are not rejected when EV gating is disabled. Ran `python3 -m pytest
  tests/test_runner.py` and documented the change in `docs/task_backlog.md`.
- 2026-02-27: Weighted trade PnL by executed quantity so pip and currency totals align with risk sizing, stored pip_value in trade snapshots, extended metrics/daily records for currency PnL, added regression `tests/test_runner.py::test_trade_pnl_scales_with_risk_per_trade`, and executed `python3 -m pytest tests/test_runner.py`.
- 2026-02-25: Tracked live equity inside `BacktestRunner` so trade PnL (in quote
  currency) updates position sizing, recorded the currency PnL on metrics,
  refreshed sizing contexts to use the mutable balance, added a regression in
  `tests/test_runner.py::test_position_size_updates_with_live_equity`, and ran
  `python3 -m pytest tests/test_runner.py` for confirmation.
- 2026-02-26: Preserved external runner state snapshots by deep-copying inputs in
  `BacktestRunner.load_state`, restoring warmup/EV/slip state during `run`, added
  regression `tests/test_runner.py::test_run_restores_loaded_state_snapshot`, and
  executed `python3 -m pytest tests/test_runner.py` to verify persistence across
  runs.
- 2026-02-24: Restricted realized volatility inputs to the latest ``n+1`` bars in
  `core/runner._compute_features`, updated `core/feature_store.realized_vol` to accept
  optional windows while re-slicing to ``n+1`` bars, added regression coverage via
  `tests/test_runner.py::test_realized_vol_recent_window_updates_band`, and executed
  `python3 -m pytest tests/test_runner.py`.
- 2026-02-23: Introduced `SelectionContext` to orchestrate per-candidate routing checks in
  `router/router_v1`, delegated session/band/portfolio health/headroom scoring into helper
  methods, updated `select_candidates` to run the shared pipeline, extended
  `tests/test_router_v1.py` with SelectionContext unit coverage (execution-health reason
  dedupe, headroom delta aggregation), and executed `python3 -m pytest tests/test_router_v1.py`
  to confirm regression parity.
- 2026-02-22: Refactored `core/router_pipeline.build_portfolio_state` by introducing helper
  functions for numeric map normalisation, correlation map generation, exposure/headroom
  aggregation, gross exposure calculation, and runtime metric merging. Added regression
  tests in `tests/test_router_pipeline.py` to validate the helper outputs (including the
  existing headroom tolerance) and executed `python3 -m pytest tests/test_router_pipeline.py`
  to confirm behaviour is unchanged.
- 2026-02-21: Refactored `router/router_v1.select_candidates` to delegate per-manifest checks to `evaluate_candidate`, introduced
  `CandidateEvaluation` for aggregating eligibility deltas/reasons, added regression coverage in `tests/test_router_v1.py`, and
  executed `python3 -m pytest tests/test_router_v1.py` to confirm the helper matches previous behaviour.
- 2026-02-20: Reset EV and slip-learning state inside `BacktestRunner.run` to avoid cross-run leakage, added a regression that reuses a runner twice with learned slippage, and executed `python3 -m pytest tests/test_runner.py` to confirm the fix.
- 2026-02-19: Guarded `BacktestRunner._warmup_left` so calibration fills no longer decrement the counter, added a regression test covering the calibration warmup case, and executed `python3 -m pytest tests/test_runner.py` to verify the change.
- 2026-02-18: Documented how `--doc-section In Progress|Pending Review` controls `docs/todo_next.md` placement across `docs/state_runbook.md` and `docs/codex_workflow.md`, added cross-links, refreshed the Pending Review note in `docs/todo_next.md`, and ran `python3 scripts/manage_task_cycle.py --dry-run start-task --doc-section "Pending Review" ...` to capture the dry-run output.
- 2026-02-16: Clarified `--skip-record` guidance in `docs/codex_workflow.md` / `docs/state_runbook.md`, captured recommended scenarios, and verified `python3 scripts/manage_task_cycle.py --dry-run start-task --skip-record ...` emits the skip notice plus `sync_task_docs.py promote` preview.
- 2026-02-17: Captured the `finish-task` dry-run preview for `docs/codex_workflow.md` and `docs/state_runbook.md`, documented the lack of side effects when using `--dry-run`, and executed `npx markdownlint-cli docs/codex_workflow.md docs/state_runbook.md` to review Markdown formatting warnings.
- 2026-02-15: Shifted the warmup decrement in `core/runner._maybe_enter_trade` to occur after processing fill results so only confirmed fills reduce the counter, updated `tests/test_runner.py` to exercise the conservative fill engine for both filled and unfilled scenarios, and executed `python3 -m pytest tests/test_runner.py` to verify the behaviour.
- 2026-02-14: Updated `core/runner._maybe_enter_trade` so warmup trades decrement only after fills, added regression coverage in `tests/test_runner.py` for filled vs. unfilled simulations, and executed `python3 -m pytest tests/test_runner.py` to confirm the behaviour.
- 2026-02-13: Surfaced category budget values/headroom/status in the portfolio summary, updated the router demo telemetry sample, extended `tests/test_report_portfolio_summary.py` to assert the new fields, and executed `python3 -m pytest tests/test_report_portfolio_summary.py`.
- 2026-02-12: Preserved telemetry-sourced bucket metadata when constructing `PortfolioState` so correlation peers without a manifest retain their category/budget hints. Ensured router correlation evaluation consumes bucket metadata even when only telemetry provides it. Added regression tests in `tests/test_router_pipeline.py` and `tests/test_router_v1.py`, then ran `python3 -m pytest tests/test_router_pipeline.py tests/test_router_v1.py` to confirm the fixes.
- 2026-02-10: 相関テレメトリへ `correlation_meta` を追加し、`router_v1.select_candidates` が同一バケット超過をハード失格・異バケット超過を減点へ切り分けるよう更新。`tests/test_router_pipeline.py` / `tests/test_router_v1.py` にバケット別挙動の回帰テストを追加し、`python3 -m pytest tests/test_router_pipeline.py tests/test_router_v1.py` を完走して新ロジックを確認。ドキュメント（`docs/router_architecture.md`, `docs/checklists/p2_router.md`）へテレメトリ契約変更を反映。
- 2026-02-11: `PortfolioTelemetry` / `build_portfolio_state` が `correlation_meta` を保持できるようにし、`scripts/build_router_snapshot.py` がテレメトリへメタデータを保存。ポートフォリオサマリーの相関ヒートマップへ `bucket_category` / `bucket_budget_pct` を追加してオペレーションレビューでバケット差分を判別可能にした。`python3 -m pytest tests/test_router_pipeline.py tests/test_report_portfolio_summary.py` を実行して回帰確認し、`docs/router_architecture.md` / `docs/checklists/p2_router.md` / `docs/task_backlog.md` を同期。
- 2026-02-09: `core/router_pipeline.build_portfolio_state` でテレメトリ予算のベースラインを保持し、manifest や CSV が予算を引き締めた際にカテゴリ予算ヘッドルームを再計算するロジックを追加。`tests/test_router_pipeline.py` に回帰テストを追加し、`python3 -m pytest tests/test_router_pipeline.py tests/test_router_v1.py` を実行して breach ペナルティの適用を確認。
- 2026-02-08: `core/router_pipeline.build_portfolio_state` が `execution_health` の数値メトリクス（`reject_rate` / `slippage_bps` / `fill_latency_ms` など）を包括的に取り込み、`router_v1.select_candidates` で各ガード (`max_reject_rate` / `max_slippage_bps` / `max_fill_latency_ms` or `max_latency_ms`) までのマージンを算出・理由ログへ記録。閾値接近時の減点と逸脱時の詳細失格理由をテスト（`python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py tests/test_strategy_manifest.py`）で確認し、manifest ローダー・テンプレート・ドキュメント（`docs/router_architecture.md`, `docs/checklists/p2_router.md`, `docs/task_backlog.md`）を同期。
- 2026-02-07: manifest `governance.category_budget_pct` を `core/router_pipeline.manifest_category_budget` で吸い上げ、`scripts/build_router_snapshot.py` が `--category-budget-csv` で外部 CSV を統合できるようにした。`router_v1.select_candidates` はカテゴリ予算ヘッドルームに応じて `status=ok|warning|breach` を理由ログへ付与し、超過率に比例したソフトペナルティを適用。`tests/test_router_pipeline.py` / `tests/test_router_v1.py` を実行し、新しいカテゴリ予算ロジックの回帰を確認。
- 2026-02-06: `scripts/build_router_snapshot.py` のドキュメントとヘルプ文に窓幅フラグの利用手順を追記し、`tests/test_router_pipeline.py` へ `correlation_window_minutes` 伝播の回帰テストを追加。
  `docs/router_architecture.md` で CLI 引数の指定箇所を明記し、`python3 -m pytest`（192 件）を完走してスイートの健全性を再確認。
- 2026-02-05: `scripts/build_router_snapshot.py` に `--correlation-window-minutes` を追加して相関行列と窓幅メタデータをテレメトリへ保存し、`PortfolioTelemetry` / `PortfolioState` / ポートフォリオサマリー / ルーター文書を同期。`tests/test_report_portfolio_summary.py` に CLI 回帰（ヘルプ出力含む）を追加し、`python3 -m pytest` を実行して 191 件パスを確認。
- 2026-02-04: Refined `router_v1._check_execution_health` to emit per-metric penalty maps and structured messages, updated `select_candidates` to deduplicate logs while applying the aggregated penalty, refreshed router docs/checklists with the new telemetry contract, extended `tests/test_router_v1.py` for bonus/penalty/disqualification assertions, and executed `python3 -m pytest tests/test_router_v1.py`.
- 2026-02-03: Introduced tiered execution-health scoring in `router_v1._check_execution_health`, plumbed the structured status into `select_candidates`, refreshed router docs/checklist guidance, expanded `tests/test_router_v1.py` with bonus/penalty/disqualification coverage, and ran `python3 -m pytest tests/test_router_v1.py`.
- 2026-02-02: Preserved telemetry-supplied `category_budget_headroom_pct` values when building `PortfolioState`, added regression coverage to `tests/test_router_pipeline.py`, refreshed router docs/checklist guidance, and executed `python3 -m pytest tests/test_router_pipeline.py tests/test_router_v1.py`.
- 2026-02-01: Portfolio telemetry/state now preserves category budgets and headroom. `router_v1.select_candidates` applies soft
  penalties with reason logging when utilisation exceeds budgets, `scripts/build_router_snapshot.py` accepts `--category-budget`
  overrides that persist to telemetry, related docs/checklists were updated, and `python3 -m pytest tests/test_router_pipeline.py
  tests/test_router_v1.py` completed successfully.
- 2026-01-30: Documented router architecture/data-flow expectations in `docs/router_architecture.md`, linked the guidance from `docs/task_backlog.md` (P2 ルーター拡張) and `docs/checklists/p2_router.md`, and noted the publication in `docs/todo_next.md` per the wrap-up workflow.
- 2026-01-29: `scripts/build_router_snapshot.py` を追加し、manifest と最新 run のメトリクスから `runs/router_pipeline/latest`
  に `telemetry.json` / `metrics/*.json` を生成できるようにした。`tests/test_report_portfolio_summary.py` を新設して CLI
  フロー全体を検証し、`docs/logic_overview.md` / `docs/checklists/p2_router.md` にスナップショット更新手順を追記。
  `python3 -m pytest tests/test_report_portfolio_summary.py` を実行して新テストを確認。
- 2026-01-28: `core/runner.Metrics` がトレード記録時にバーの timestamp を保持し、`equity_curve` を `[ts, equity]` 形式で構築するよう更新。
  `scripts/run_sim.py` から出力される `metrics.json` にエクイティカーブを含め、ルーター用サンプルメトリクスと
  `tests/test_runner.py` / `tests/test_router_pipeline.py` のアサーションを新スキーマに合わせて調整。
  `python3 -m pytest tests/test_runner.py tests/test_router_pipeline.py` を実行し 29 件のパスを確認。
- 2026-01-26: `router/router_v1.PortfolioState` にカテゴリ/グロスエクスポージャーのヘッドルームを保持するフィールドを追加し、
  `core/router_pipeline.build_portfolio_state` で利用率・上限からヘッドルームを算出するロジックを実装。
  `analysis/portfolio_monitor` がポートフォリオヘッドルームを参照するよう揃え、対応テスト
  (`tests/test_router_pipeline.py` / `tests/test_portfolio_monitor.py`) を更新。
  `python3 -m pytest tests/test_router_pipeline.py tests/test_portfolio_monitor.py` を実行して 8 件パスを確認。
- 2026-01-27: `router/router_v1.select_candidates` がカテゴリ/グロスヘッドルームを用いてスコアへボーナス/ペナルティを適用し、
  理由ログにヘッドルーム残量を記録するよう拡張。`tests/test_router_v1.py` にヘッドルーム差分の回帰テストを追加し、
  `docs/checklists/p2_router.md` / `docs/task_backlog.md` を更新。`python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py`
  を実行して 16 件パスを確認。
- 2026-01-25: `analysis/portfolio_monitor._load_strategy_series` で manifest の相対パスをメトリクス所在ディレクトリ基準で解決するよう更新し、
  `scripts/report_portfolio_summary.py` の CLI 実行でも同ロジックを共有。
  マニフェスト名を書き換えたフィクスチャを一時ディレクトリへ複製する回帰テスト（`tests/test_portfolio_monitor.py`）を追加し、
  `python3 -m pytest tests/test_portfolio_monitor.py tests/test_router_pipeline.py` で 8 件パスを確認。
- 2026-01-24: `core/router_pipeline.build_portfolio_state` がアクティブポジションの絶対値を利用してカテゴリ利用率・グロスエクスポージャー
  を構成するよう調整し、`router/router_v1._check_concurrency` が非整数入力を防御しつつ絶対値比較するよう更新。ショートカウントが既
  存カテゴリ利用率へ加算される回帰 (`tests/test_router_pipeline.py`) を追加し、`python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py`
  で 15 件パスを確認。
- 2026-01-23: `core/router_pipeline.build_portfolio_state` のグロスエクスポージャー系テレメトリを `_to_float` ガード経由で取り込み、欠損時にカテゴリ利用率からのフォールバックを有効化。`tests/test_router_pipeline.py` に空文字利用率と `reject_rate=None` の回帰テストを追加し、`python3 -m pytest tests/test_router_pipeline.py` を実行して 4 件パスを確認。
- 2026-01-20: `core/router_pipeline.build_portfolio_state` のテレメトリ取り込みで `_to_float` を利用するよう更新し、非数値のカテゴリ利用率や `None` の拒否率を無視する回帰テストを `tests/test_router_pipeline.py` に追加。`python3 -m pytest tests/test_router_pipeline.py` を実行して 2 件パスを確認。
- 2026-01-21: `core/router_pipeline.build_portfolio_state` でショートポジション数も絶対値ベースでカテゴリ利用率・グロスエクスポージャーへ反映し、`router/router_v1._check_concurrency` でも同様に絶対値を用いるよう修正。`tests/test_router_pipeline.py` にショート保有のガード発火テストを追加し、`python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py` を実行して 12 件パスを確認。
- 2026-01-22: `router/router_v1.select_candidates` でシグナルの `score` を優先的に float 化し、`None` の場合のみ `ev_lcb` を用いるよう整理。`tests/test_router_v1.py` にスコア 0.0 と EV LCB 並存ケースを追加し、`python3 -m pytest tests/test_router_v1.py` を実行して 10 件パスを確認。
- 2026-01-19: Updated `router/router_v1.select_candidates` so explicit `score` values (including 0.0) are preferred over EV LCB fallbacks and added a regression in `tests/test_router_v1.py` to lock the behaviour. Executed `python3 -m pytest tests/test_router_v1.py` to confirm all 9 cases pass.
- 2026-01-18: `configs/strategies/templates/base_strategy.yaml` の router ガードを Day テンプレートに揃えて `priority` / `max_gross_exposure_pct` / `max_correlation` / `correlation_tags` / `max_reject_rate` / `max_slippage_bps` をコメント付きで追加し、README へ利用ガイドを追記。`python3 -m pytest tests/test_strategy_manifest.py` を実行してテンプレート読み込み回帰を確認。
- 2026-01-18: `core/runner.py` に `ev_bypass` デバッグレコードを追加してウォームアップ残量 (`warmup_left` / `warmup_total`) をログ化し、`tests/test_runner.py` と `docs/backtest_runner_logging.md` / `docs/task_backlog.md` を同期。`python3 -m pytest tests/test_runner.py` を実行して 23 件パスを確認。
- 2026-01-16: ルーター向けポートフォリオ監視を `analysis/portfolio_monitor.py` と `scripts/report_portfolio_summary.py` で整備し、`reports/portfolio_samples/router_demo/` のテレメトリ/メトリクスを用いたフィクスチャを追加。`python3 -m pytest` と `python3 scripts/report_portfolio_summary.py --input reports/portfolio_samples/router_demo --output reports/portfolio_summary.json --indent 2` を実行し、カテゴリ利用率・相関ヒートマップ・合成ドローダウンの算出と JSON 出力を確認。
- 2026-01-17: `configs/strategies/loader.py` の `StrategyManifest.to_dict` へルーター優先度/エクスポージャ/相関/拒否率/スリッページ上限を含めるよう拡張し、`tests/test_strategy_manifest.py` にテンプレート manifest の round-trip テストを追加。`python3 -m pytest tests/test_strategy_manifest.py` を実行して 3 件パスを確認。
- 2026-01-14: `core/router_pipeline.py` を新設して manifest リスク/ランナー指標から `PortfolioState` を構築し、`scripts/run_sim.py` が manifest 経由起動時に `router_v1.select_candidates` を呼び出すよう更新。`core/runner.Metrics` に runtime 集計（reject_rate / slippage）を追加し、`tests/test_router_pipeline.py` を新設。`python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py` を実行して 9 件パスを確認。
- 2026-01-15: `core/feature_store.py` にマイクロ構造系指標を追加し、`core/runner._compute_features` から `micro_zscore` / `micro_trend` / `mid_price` / `trend_score` / `pullback` を算出。サンプル CSV を再生成して新列を含め、`tests/test_strategy_feature_integration.py` を追加。`python3 -m pytest tests/test_mean_reversion_strategy.py tests/test_strategy_manifest.py tests/test_strategy_feature_integration.py` を実行して 7 件パスを確認。
- 2026-01-13: `core/fill_engine._simulate_bar` を新設して Conservative/Bridge の BUY/SELL 共通処理を集約し、Bridge 固有の `p_tp` 付与をフック関数で調整。`tests/test_fill_engine.py` に SELL ケースを追加して同バー・トレール挙動を確認し、`python3 -m pytest tests/test_fill_engine.py` を実行して 7 件グリーンを確認。
- 2026-01-12: `scripts/ev_vs_actual_pnl._normalize_path` を新設して CLI/保存系の引数正規化を共通化し、`tests/test_ev_vs_actual_pnl.py` で Path 展開ヘルパー共有をモック検証。`python3 -m pytest tests/test_ev_vs_actual_pnl.py` を実行して 1 件パスを確認。
- 2026-01-11: `_run_yfinance_ingest` を `compute_yfinance_fallback_start` で共通化し、`last_ts` 欠損/陳腐化時のルックバックをヘルパーと同じクランプに合わせるテストを追加。`python3 -m pytest tests/test_run_daily_workflow.py` を実行して 37 件パスを確認。
- 2026-01-10: `scripts/run_daily_workflow.run_cmd` に `cwd=ROOT` 既定を追加し、`tests/test_run_daily_workflow.py::test_run_cmd_executes_with_repo_root` でサブプロセスがリポジトリ直下から起動されることを検証。`python3 -m pytest tests/test_run_daily_workflow.py` を実行して 35 件パスを再確認。
- 2026-01-09: Day ORB 5m strategy updated so calibration/warmup signals stamp `last_signal_bar` and mark sessions as broken, preventing immediate re-entries. Added regression tests ensuring warmup cooldown is honored, and ran `python3 -m pytest tests/test_runner.py` to verify 23 passing cases.
- 2026-01-07: `scripts/run_daily_workflow._build_pull_prices_cmd` をシンボル固有の既定 CSV に合わせて修正し、`tests/test_run_daily_workflow.py::test_ingest_pull_prices_uses_symbol_specific_source` を追加。`python3 -m pytest` を実行したところ、`tests/test_fetch_prices_api.py` がサンドボックスのソケット制限でローカル HTTP サーバをバインドできず 8 件エラーとなった（他テストはパス）。
- 2026-01-06: `core/runner._extract_pending_fields` で `.oco` からの TP/SL も float へ正規化して抽出し、`tests/test_runner.py` に OrderIntent の `.oco` 参照のみで EV リジェクト/サイジングガードが動作する回帰テストを追加。`python3 -m pytest tests/test_runner.py` を実行し 21 件パスを確認。
- 2026-01-05: `router/router_v1._check_category_cap` で `category_cap_pct` が `None` の場合のみポートフォリオ定義の上限へフォールバックするよう修正し、`category_cap_pct=0.0` を尊重する回帰テストを追加。`python3 -m pytest tests/test_router_v1.py` を実行して 4 件パスを確認。
- 2026-01-04: `core/runner._build_ctx` で `pip_value_override` / `base_notional` の float キャストに失敗した場合でも 10.0 へフォールバックするよう調整し、数値文字列を許容するテストを追加。`python3 -m pytest tests/test_runner.py` を実行して 20 件パスを確認。
- 2026-01-03: `RunnerConfig.build_sizing_cfg` で `risk_per_trade_pct` を `float(...)` キャスト後に >0 判定するよう更新し、`_build_ctx` がヘルパー経由のサイジング設定を利用するよう整備。`tests/test_runner.py` に文字列入力を許容する回帰テストを追加し、`python3 -m pytest tests/test_runner.py` を実行して 18 件パスを再確認。
- 2026-01-01: `core/runner._extract_pending_fields` ヘルパーを追加して pending シグナルの `side`/`tp_pips`/`sl_pips` 抽出を一元化し、`_evaluate_entry_conditions`・`_evaluate_ev_threshold`・`_check_slip_and_sizing` から重複分岐を排除。`python3 -m pytest tests/test_runner.py` を実行して 17 件パスを再確認。
- 2026-01-02: `core/sizing.compute_qty_from_ctx` を新設して校正/ウォームアップ/本番サイズ算出を共通化し、Day ORB・Mean Reversion 戦略とランナーの重複ロジックを移行。関連テスト (`tests/test_runner.py`, `tests/test_run_sim_cli.py` など) を更新して数量一致を検証し、`python3 -m pytest` を完走。
- 2025-12-31: `core/runner._compute_features` を `FeatureBundle` へ拡張し、`_maybe_enter_trade` 系のヘルパーが事前組立てコンテキストを共有するようリファクタ。`tests/test_runner.py` に校正モード閾値/期待スリップの単体テストを追加し、`python3 -m pytest` を実行して 151 件パスを確認。
- 2025-12-30: `_run_api_ingest` を `_finalize_ingest_result` へ統合し、API 成功/フォールバック時のログ整合性を検証するテストを更新。`python3 -m pytest tests/test_run_daily_workflow.py` を実行して 32 件パスを確認。
- 2025-12-29: `core/feature_store.py` に型ヒントを追加し、NaN ガードをコメント付きで整理。`python3 -m pytest tests/test_runner.py` を実行して 16 件パスを再確認。
- 2025-12-26: `core/runner._resolve_calibration_positions` で `_compute_exit_decision` を使ってキャリブレーションポジションを処理し、`tests/test_runner.py` に同時ヒット/セッション切替時の EV 更新回帰テストを追加。`python3 -m pytest tests/test_runner.py` を実行して 16 件パスを確認。
- 2025-12-27: Dukascopy/yfinance 共通ヘルパー `scripts/ingest_providers.py` を追加し、`run_daily_workflow.py` と `live_ingest_worker.py` を移行。フォールバック鮮度判定・メタデータ付与を共通化するテスト (`tests/test_run_daily_workflow.py` / `tests/test_live_ingest_worker.py`) を拡張し、`python3 -m pytest` を完走してリグレッションを確認。
- 2025-12-28: `scripts/_time_utils.parse_naive_utc` を追加し、`run_daily_workflow.py` と `live_ingest_worker.py` が同一パーサーを参照するよう統一。`tests/test_run_daily_workflow.py` / `tests/test_live_ingest_worker.py` に共有パスの回帰テストを追加し、`python3 -m pytest` で 150 件パスを確認。
- 2025-12-25: `core/runner._check_slip_and_sizing` で `core.sizing` のヘルパーを用いたサイズ算出に置き換え、ゼロサイズ/スリップガードのユニットテストを `tests/test_runner.py` に追加。`python3 -m pytest tests/test_runner.py` を実行して 14 件パスを確認。
- 2025-12-24: `notifications/emit_signal.py` の `log_latency` / `log_fallback` で親ディレクトリが存在しない場合でもファイル名のみで書き込めるようガードを追加し、`tests/test_emit_signal.py` に無ディレクトリ指定の回帰テストを実装。`python3 -m pytest tests/test_emit_signal.py` を実行して 5 件パスを確認。
- 2025-12-20: `scripts/run_daily_workflow.py` の `_run_dukascopy_ingest` をフェッチ処理・yfinance フォールバック・結果永続化ヘルパーへ分離し、`_fetch_dukascopy_records` / `_YFinanceFallbackRunner` / `_finalize_ingest_result` を導入。`_run_yfinance_ingest` と共通ロジックを共有し、`python3 -m pytest tests/test_run_daily_workflow.py` で 27 件パスを確認。
- 2025-12-22: core/runner._maybe_enter_trade をエントリ条件・EV評価・スリップ/サイズ検証・Fill処理のヘルパーへ分割し、tests/test_runner.py にブレイクアウト成功/EVリジェクト/ウォームアップバイパスのユニットテストを追加。python3 -m pytest tests/test_runner.py で 9 件パスを確認。
- 2025-12-23: `core/runner._handle_active_position` を `_compute_exit_decision` で共通化し、トレール/同時ヒット/タイムアウトの BUY・SELL 双方向回帰テストを `tests/test_runner.py` に追加。`python3 -m pytest tests/test_runner.py` を実行して 12 件パスを確認。
- 2025-12-21: `scripts/run_daily_workflow.py` のローカル CSV フォールバック ingest を `_resolve_local_backup_path` / `_ingest_csv_source` / `_extend_with_synthetic_bars` へ分割し、`_execute_local_csv_fallback` から `IngestContext.fallback_kwargs()` をそのまま渡せるよう整理。`tests/test_run_daily_workflow.py` に合成バー有無の分岐を検証するユニットテストを追加し、`python3 -m pytest tests/test_run_daily_workflow.py` で 29 件パスを確認。
- 2025-12-19: `core/runner.py` の `run_partial` をヘルパー関数へ分解し、日次状態更新・特徴量計算・ポジション決済・トレードエントリー処理を整理。`_finalize_trade` でスリップ/決済共通処理を集約し、`tests/test_runner.py` を実行して回帰を確認。
- Update this file after completing work to record outcomes, blockers, and next steps.

- 2025-12-18: `core/runner.py` のスリップ学習処理を `_update_slip_learning` ヘルパーへ集約し、`tests/test_runner.py` に係数検証テストを追加。`python3 -m pytest` を実行して全件パスを確認。
- 2025-12-17: `scripts/run_daily_workflow.py` にベンチマーク/サマリー/鮮度チェックなどのコマンドビルダーとアラート閾値ヘルパーを追加し、`main` をディスパッチテーブル化して `run_cmd` 呼び出しを集約した。`python3 -m pytest tests/test_run_daily_workflow.py` を実行して 27 件パスを確認。
- 2025-12-16: `scripts/run_daily_workflow.py` に `_ingest_with_provider` ヘルパーを追加し、Dukascopy/yfinance/API 経路のフォールバック記録と `source_label` ログを共通化。`ProviderError` と `_log_ingest_summary` でエラー理由と完了ログを整理し、`python3 -m pytest tests/test_run_daily_workflow.py` を実行して 27 件パスを確認した。
- 2025-12-15: `scripts/run_daily_workflow.py` のローカルCSV既定パスをシンボル別に検証し、存在しない場合は `--local-backup-csv` 指定を促すエラーを返すよう更新。`scripts/pull_prices.py` にデフォルトパターン関数を追加し、シンボル不一致アノマリーへ明示メッセージを含めた。`tests/test_run_daily_workflow.py` に EURUSD シナリオのフォールバック失敗/成功ケースを追加し、`python3 -m pytest tests/test_run_daily_workflow.py` を実行して 27 件パスを確認。README へローカルバックアップ命名規則と失敗時挙動を追記。
- 2025-12-14: `scripts/live_ingest_worker.py` の Dukascopy 判定を `ingest_records` が返す `source` に合わせ、成功時のみ `dukascopy_offer_side` を永続化するよう修正。`tests/test_live_ingest_worker.py` と `tests/test_run_daily_workflow.py` を更新し、`python3 -m pytest tests/test_live_ingest_worker.py` を実行して 5 件パスを確認した。
- 2025-12-13: `scripts/run_daily_workflow.py` に `IngestContext` を導入し、Dukascopy/yfinance/API それぞれのハンドラ関数へ分割。`python3 -m pytest tests/test_run_daily_workflow.py` を実行して 24 件パスを確認し、CLI ディスパッチを簡素化した。
- 2025-12-12: `scripts/run_daily_workflow.py` のローカルCSVフォールバック合成バー経路をリファクタし、`_tf_to_minutes` ヘルパーを
  追加。`tests/test_run_daily_workflow.py` を実行して 24 件グリーンを確認し、`result.get("last_ts_now")` の有無を問わずバリデー
  ション済み最新行を単回ロードするよう整理。
- 2025-12-11: `scripts/run_daily_workflow.py` のローカルCSVフォールバック処理を `_execute_local_csv_fallback` ヘルパーへ集約し、
  Dukascopy/yfinance/API 経路のラッパー関数を共通化。フォールバックノートの `stage`/`reason` を呼び出し側で指定できるように
  整理し、`python3 -m pytest tests/test_run_daily_workflow.py` を実行して回帰が通ることを確認（24件パス）。
- 2025-12-10: live ingest worker `_ingest_symbol` で `result.source_name` を確認して `ingest_meta.dukascopy_offer_side` を保存する条件を
  Dukascopy 経路のみに限定。`tests/test_live_ingest_worker.py` に yfinance フォールバックでフィールドが追加されないことを検証
  するケースを追加し、`python3 -m pytest` を実行して全件パスを確認。
- 2025-12-09: Dukascopy 経路のフォールバック結果で `ingest_meta.dukascopy_offer_side` が誤って残らないように、`scripts/run_daily_workflow.py`
  でソース判定ガードを追加。`tests/test_run_daily_workflow.py` にフォールバック時のメタデータ検証ケースを追加し、`python3 -m pytest`
  を完走して既存回帰を確認。
- 2025-12-07: `router/router_v1.select_candidates` で `ev_lcb` 理由文字列の生成時に `float` キャストを挟み、変換失敗時は警告ログへ回して理由に追加しないよう調整。`python3 -m pytest tests/test_router_v1.py` を実行しフォーマット例外が発生しないことを確認。
- 2025-12-06: `core/runner._reset_runtime_state` で `Metrics(starting_equity=self.equity)` を使用し、再初期化時にエクイティカーブが口座初期値から始まるよう調整。`Metrics.record_trade` でも空カーブ時に初期値を補完し、`docs/backtest_runner_logging.md` へベースライン記述を追記。`python3 -m pytest tests/test_runner.py` を実行して Sharpe/最大DD 計算が期待通り維持されることを確認。
- 2025-12-05: `core/runner._build_ctx` で `realized_vol` が `NaN` を返しても RV バンド計算が破綻しないようにガードを追加。`python3 -m pytest tests/test_runner.py tests/test_run_daily_workflow.py` を実行して回帰が維持されることを確認。
- [P1-04] 2025-10-16 価格インジェストAPI基盤整備 — DoD: [docs/task_backlog_p1_archive.md#p1-04-価格インジェストapi基盤整備](docs/task_backlog_p1_archive.md#p1-04-価格インジェストapi基盤整備) — Dukascopy ベースの自動インジェストを正式経路として仕上げ、REST/API ルートは保留ステータスで再開条件を整理する。
  - Backlog Anchor: [価格インジェストAPI基盤整備 (P1-04)](docs/task_backlog_p1_archive.md#p1-04-価格インジェストapi基盤整備)
  - Vision / Runbook References:
    - [readme/設計方針（投資_3_）v_1.md](readme/設計方針（投資_3_）v_1.md)
    - [docs/state_runbook.md](docs/state_runbook.md)
    - [README.md#オンデマンドインジェスト-cli](README.md#オンデマンドインジェスト-cli)
  - Pending Questions:
    - [x] Dukascopy 経路の冪等性・鮮度検証 — `scripts/run_daily_workflow.py --ingest --use-dukascopy` を定常運用フローとして承認。
    - [x] yfinance フォールバックの自動切替・鮮度アラート閾値（例: 90–120 分）をワークフローに組み込む。
    - [x] Alpha Vantage (有償 REST) 再開条件と費用対効果、無料 API 代替の比較検討。
  - Docs note: `docs/api_ingest_plan.md` を更新し、Dukascopy 主経路・API 保留・yfinance 冗長化方針を記録する。
  - 2025-10-22: `scripts/fetch_prices_api.py` と `configs/api_ingest.yml` を整備し、`run_daily_workflow.py --ingest --use-api` で REST → `pull_prices.ingest_records` の直結を実装。`tests/test_fetch_prices_api.py` で成功/リトライの両ケースを固定し、README / state runbook / todo_next を更新。
  - 2025-10-23: `tests/test_run_daily_workflow.py::test_api_ingest_updates_snapshot` を追加し、モックAPIで `--ingest --use-api` フローを通しながら snapshot 更新・CSV 追記・アノマリーログ無しを検証。チェックリストの CLI 項目をクローズし、次ステップを鮮度チェック/認証ローテーション整理へ集約。
  - 2025-10-24: Alpha Vantage FX_INTRADAY がプレミアム専用であることを確認。REST ルートは backlog へ「保留」として移し、Dukascopy を主経路に昇格。万一の障害時は yfinance 変換レイヤーで復旧できるよう要件整理を次イテレーションへ設定。
  - 2025-11-01: `scripts/yfinance_fetch.py` を実装し、USDJPY→JPY=X のシンボル変換・`period="7d"` 取得・60日制限対応を整備。`run_daily_workflow.py --ingest --use-yfinance` で 2025-10-01T14:10 (UTC) までのバーを取り込めることを確認し、`tests/test_yfinance_fetch.py` / `tests/test_run_daily_workflow.py` に回帰を追加。残課題は自動フォールバックと最新時刻乖離のアラート化。
  - 2025-11-02: `scripts/run_daily_workflow.py --ingest --use-dukascopy` に yfinance 自動フェイルオーバー（7 日再取得・シンボル正規化）と `--dukascopy-freshness-threshold-minutes` を実装。`tests/test_run_daily_workflow.py` に障害復旧の回帰を追加し、README / state runbook / ingest plan / チェックリストへ鮮度確認ステップと依存導入ガイドを追記。
  - 2025-11-03: `docs/api_ingest_plan.md` の `activation_criteria` と `credential_rotation` を明文化し、`docs/state_runbook.md` / `README.md` / チェックリストへ `--use-api` 切替手順・エスカレーションを追記。REST 再開条件と鍵ローテーション記録フローを整理。
  - 2025-11-04: `scripts/live_ingest_worker.py` を追加し、Dukascopy→yfinance フォールバックと `update_state` 連携の常駐ジョブを実装。pytest 統合テストで重複バーが発生しないことを検証し、README / state runbook へ運用手順とモニタリング項目を追記。
  - 2025-11-05: Alpha Vantage Premium (49.99 USD/月, 75req/min, 1500req/日) は `target_cost_ceiling_usd=40` を超過するため保留継続とし、無料ティアの FX_INTRADAY 制限を再確認。Twelve Data Free (0 USD, 8req/min, 800req/日, 30日履歴) をフォールバック候補に追加し、`configs/api_ingest.yml` へ `activation_criteria` と候補メモを反映。チェックリスト / todo_next を同期。
  - 2025-11-06: API 鍵の暗号化保管・ローテーション記録フローを整理。`configs/api_ingest.yml` へ `credential_rotation` プレースホルダを追加し、`docs/state_runbook.md` / `README.md` / チェックリストで環境変数設定と記録手順を明文化。Reviewers: ops-security（高橋）, ops-runbook（佐藤）。
  - 2025-11-07: サンドボックスで `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative` を実行。`dukascopy_python` 未導入で主経路が失敗し、自動フェイルオーバーの yfinance も未導入のため ImportError。`ops/runtime_snapshot.json.ingest.USDJPY_5m` は 2025-10-01T14:10:00 のまま据え置き。続けて `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` を実行したところ、最新バーが 18.60h、サマリーが 9.31h 遅延で閾値超過。依存導入後に再取得→鮮度再確認が必要。
  - 2025-11-09: Twelve Data の `status` レスポンスに対応するため `configs/api_ingest.yml` と `scripts/fetch_prices_api.py` を調整し、`status: "ok"` を許容しつつ `status: "error"` を再試行・異常ログに記録できるよう pytest を拡張。
  - 2025-11-10: Twelve Data の `volume` 欠損/空文字に備えて `response.fields` へ `required=false` / `default=0.0` を追加し、`scripts/fetch_prices_api.py` の正規化ヘルパーと pytest を更新。API フォールバック時も冪等 ingest が継続する前提を固めた。
  - 2025-11-11: Twelve Data レスポンス（UTC +00:00 の `datetime` と `volume` 欠損）を再現するモック API テストを `tests/test_fetch_prices_api.py::test_fetch_prices_twelve_data_like_payload` に追加。`fetch_prices_api` の `symbol=USD/JPY` クエリ整形と降順レスポンスの昇順化、`volume` 空文字/NULL の 0.0 フォールバックを固定し、`docs/state_runbook.md` にドライラン確認手順を追記。次アクションは Sandbox へ `dukascopy-python` / `yfinance` を導入して `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy` → `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` を再実行し、鮮度アラート解消を確認すること。
- 2025-11-12: Sandbox で optional dependency が未導入でも `run_daily_workflow.py --ingest --use-dukascopy` が継続するよう、ローカル CSV フェイルオーバーを実装し、`tests/test_run_daily_workflow.py::test_dukascopy_and_yfinance_missing_falls_back_to_local_csv` で snapshot 更新・validated 追記・アノマリーログ抑止を確認。依存導入後の再取得→鮮度チェックは引き続き未完了。
- 2025-11-13: ローカル CSV フォールバック後に `synthetic_local` 合成バーを生成して snapshot を最新 5 分足まで引き上げるロジックを `scripts/run_daily_workflow.py` に追加。`tests/test_run_daily_workflow.py` を更新し、合成バー追記と snapshot 最新化を検証。runbook / checklist / backlog を同期して Sandbox でも鮮度チェックを再開できるようにした。
  - 2025-11-13: Sandbox で `pip install dukascopy-python yfinance` を試行したが、Proxy 403 (Tunnel connection failed) で阻止された。`python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative` はローカル CSV + `synthetic_local` で完走し `ops/runtime_snapshot.json.ingest.USDJPY_5m` を 2025-10-02T03:15:00 まで更新。`python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` はベンチマーク側が 24.29h / 15.00h 遅延で失敗したため、依存導入後に Dukascopy/yfinance 実データで再検証する必要あり。次アクション: PyPI ホワイトリストまたはホイール搬入の段取りを ops と調整。
- 2025-11-13: `ops/health/2025-11-13_dukascopy_ingest_attempt.md` に Proxy 403 ログと再実行結果を保存。ops 側でホイール搬入/プロキシ許可が完了次第、Dukascopy+yfinance 実行と鮮度チェックを再実施する。
- 2025-11-14: README / docs/api_ingest_plan.md / 設計方針 ADR-035 を更新し、Codex Cloud の PyPI ブロックに伴う **Dukascopy → yfinance → ローカルCSV + `synthetic_local`** フォールバックチェーンと鮮度チェック（合成バー環境では informational）の扱いを明文化。依存導入後に CLI/鮮度チェック再実行が必要な旨を Sandbox Known Limitations として記録。
  - 2025-11-16: `run_daily_workflow.py` が `ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>` に `primary_source` / `source_chain` / `freshness_minutes` / `fallbacks` を永続化し、フォールバック経路と合成バー有無を即時確認できるようにした。`docs/state_runbook.md` / `docs/checklists/p1-04_api_ingest.md` へレビュー手順を追記し、`tests/test_run_daily_workflow.py` でメタデータ更新を検証。
  - 2025-11-16: `scripts/check_benchmark_freshness.py` が `ingest_meta` を参照して `synthetic_local` 合成バー時の鮮度遅延を `advisories` へ降格するように調整。`--ingest-timeframe` で参照キーを指定できるようにし、README の Sandbox 運用メモへ `advisories` 表示を追記。
  - 2025-11-18: Sandbox で `benchmark_pipeline.*` が欠損しても `ingest_meta.source_chain` に `synthetic_local` が含まれていれば `check_benchmark_freshness` が `advisories` を返すよう拡張。`tests/test_check_benchmark_freshness.py` に欠損ケースの回帰を追加し、`docs/benchmark_runbook.md` / `docs/checklists/p1-04_api_ingest.md` を更新して `ok=true` + `advisories` の扱いを明文化。
  - 2025-11-19: `scripts/run_daily_workflow.py` に `--local-backup-csv` を追加し、ローカル CSV フォールバックで利用するファイルを差し替え可能にした。Sandbox で最新バックフィルを持ち込む際の運用ガイド（README / state runbook / API ingest plan）も更新し、`tests/test_run_daily_workflow.py` にカスタム CSV 指定の回帰を追加。
  - 2025-11-20: `scripts/run_daily_workflow.py` が `ingest_meta` へ `last_ingest_at` を保存するように調整。`tests/test_run_daily_workflow.py` でフィールドを検証し、`check_benchmark_freshness` の出力から取得時刻を参照できるようになった。
  - 2025-11-21: Dukascopy 経路で BID/ASK を切り替えられる `--dukascopy-offer-side`（daily workflow）と `--offer-side`（live worker）を追加。`ingest_meta.dukascopy_offer_side` に選択内容を永続化し、pytest で既定 BID とフェイルオーバー経路の回帰を更新。README / runbook / checklist へレビュー手順を追記。
  - 2025-11-22: Optional ingestion/reporting dependencies documented in `docs/dependencies.md`, and README/backlog now point operators to the install guidance for dukascopy-python/yfinance/pandas/matplotlib/pytest under proxy constraints.
  - 2025-11-22: `scripts/check_benchmark_freshness.py` で `benchmarks.<target> missing` をサンドボックスでは `advisories` に降格するよう調整。`tests/test_check_benchmark_freshness.py` に回帰を追加し、チェックリストへ Sandbox 運用メモを追記。
- 2025-11-23: `scripts/run_daily_workflow.py` のローカル CSV フォールバックで使用したファイルを `local_backup_path` として `ingest_meta` に保存し、fallback ログへ `local_csv` ステージ（パス付き）を追記。`check_benchmark_freshness` の出力・README・state runbook・チェックリストを同期してレビュー時に参照できるようにした。
- 2025-11-24: ローカル CSV フォールバック時に `synthetic_local` 合成バーを挿入しないオプション（`--disable-synthetic-extension`）を追加。`tests/test_run_daily_workflow.py::test_local_csv_fallback_can_disable_synthetic_extension` で回帰を整備し、README / runbook / ingest plan / checklist を更新して鮮度アラートが `errors` 扱いになるケースを明記。
- 2025-11-25: `run_daily_workflow.py --ingest --use-api` で API 障害や空レスポンスが発生した際にローカル CSV → `synthetic_local` へ自動フォールバックし、`ingest_meta` に `api` → `local_csv` → `synthetic_local` の `fallbacks` / `source_chain` / `local_backup_path` を記録するよう更新。`tests/test_run_daily_workflow.py::test_api_ingest_falls_back_to_local_csv` を追加し、README / state runbook / ingest plan を同期。
- 2025-11-26: `scripts/check_benchmark_freshness.py` で `ingest_meta.fallbacks` のステージ名を正規化し、CLI 出力からフォールバック連鎖を直接確認できるようにした。`tests/test_check_benchmark_freshness.py` に回帰を追加し、Sandbox の advisory ダウングレード仕様が維持されることを確認。
- 2025-11-27: `scripts/run_daily_workflow.py` でベンチマーク鮮度チェックのパイプライン既定値を `pipeline_max_age_hours` に切り出し、`--benchmark-freshness-max-age-hours` を独立引数として `check_benchmark_freshness.py` へ伝播するよう更新。`tests/test_run_daily_workflow.py::test_check_benchmark_freshness_passes_pipeline_and_override` を追加し、両方のフラグがコマンドに含まれることを検証。
- 2025-11-28: `run_daily_workflow.py --check-benchmark-freshness` に `--benchmark-freshness-base-max-age-hours` を追加し、`check_benchmark_freshness.py` へ渡す `--max-age-hours` を CLI から制御可能にした。README / docs/benchmark_runbook.md / docs/logic_overview.md / docs/checklists/p1-01.md / docs/task_backlog.md を更新し、`python3 -m pytest` で回帰テストを通過させた。
- 2025-11-30: yfinance シンボル正規化を見直し、`run_daily_workflow.py` の `=X` 剥離を 6 文字英字の FX ペアに限定。`--symbol JPY=X` が `validated/JPY=X/5m.csv` 等へ展開されることと yfinance へのティッカー伝播を `tests/test_run_daily_workflow.py::test_yfinance_ingest_accepts_short_suffix_symbol` で回帰。README に短いシンボルの保存先/ティッカー記述を追記し、`python3 -m pytest tests/test_run_daily_workflow.py` を実行して成功を確認。
- 2025-12-02: `scripts/live_ingest_worker.py` のモード引数を小文字のまま維持し、`update_state` CLI へ不正値が渡らないよう `_parse_csv_list` の大文字化処理を調整。`tests/test_live_ingest_worker.py` に `_run_update_state` 呼び出し検証を追加し、`python3 -m pytest` で回帰確認。
- 2025-11-29: `run_daily_workflow.py --optimize` で `--symbol` / `--mode` / `--bars` の指定が `auto_optimize.py` へ伝播するよう更新し、`tests/test_run_daily_workflow.py` にシンボル・モード伝播の回帰を追加。README へ `--optimize` フローのデータセット差し替え手順を追記し、`python3 -m pytest tests/test_run_daily_workflow.py` を実行してパスを確認。
  - 2025-11-08: `run_daily_workflow.py --ingest --use-dukascopy` 実行時に `dukascopy_python` が未導入でも yfinance フォールバックで継続できるようにし、pytest (`tests/test_run_daily_workflow.py::test_dukascopy_missing_dependency_falls_back_to_yfinance`) で回帰確認。
  - 2025-11-09: yfinance フォールバック時に `--yfinance-lookback-minutes` を参照して再取得ウィンドウを決定するよう更新。冗長な再処理を抑えつつ長期停止後に手動調整できるよう、README / state runbook / 回帰テスト / backlog メモを同期。

- [P1-07] 2025-12-05 フェーズ1 バグチェック & リファクタリング運用整備 — DoD: [docs/task_backlog_p1_archive.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備](docs/task_backlog_p1_archive.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備) — フェーズ1の資産を対象にバグチェック観点とリファクタリング計画を共通化し、継続作業の引き継ぎを容易にする。
  - Backlog Anchor: [フェーズ1 バグチェック & リファクタリング運用整備 (P1-07)](docs/task_backlog_p1_archive.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備)
  - Vision / Runbook References:
    - [docs/checklists/p1-07_phase1_bug_refactor.md](docs/checklists/p1-07_phase1_bug_refactor.md)
    - [docs/codex_workflow.md](docs/codex_workflow.md)
    - [docs/progress_phase1.md](docs/progress_phase1.md)
  - Pending Questions:
    - [ ] 調査対象モジュールごとの初期スコープ（戦略ロジック / データパイプライン / CLI / ドキュメント）を確定する。
    - [ ] 追加が必要な回帰テストセットの優先順位付けを決める。
  - Docs note: Ready エントリを [docs/todo_next.md](docs/todo_next.md#ready) に追加済み。チェックリストのテーブルを埋めつつ、`scripts/manage_task_cycle.py` のドライラン出力サンプルを [docs/codex_workflow.md#closing-the-task](docs/codex_workflow.md#closing-the-task) に転載済み。
  - 2025-12-05: チェックリスト初版とテンプレート説明を `docs/checklists/p1-07_phase1_bug_refactor.md` に作成し、`docs/codex_workflow.md` へ参照導線を追加。バックログ/Ready/State を同期して、次セッションがチェックボードを更新するだけで継続できるようにした。
    - 2025-12-06: フェーズ1 スクリプトで `datetime.utcnow()` を廃止し、`scripts/_time_utils.py` を介した `datetime.now(timezone.utc)` 起点のヘルパーに統一。`run_daily_workflow.py` / `yfinance_fetch.py` / `fetch_prices_api.py` などの鮮度判定がモンキーパッチにも追従するよう調整し、`python3 -m pytest` で DeprecationWarning が消えたことを確認。
    - 2025-12-07: `scripts/report_benchmark_summary.py` が `main()` 内で `utcnow_iso` を参照する際に import が未解決で NameError になる退行を修正。ヘルパー import をモジュール先頭へ移して CLI 実行時に `generated_at` が確実に設定されることを再確認し、バグチェックログへ反映。

### 運用メモ
- バックログから着手するタスクは先にこのリストへ追加し、ID・着手予定日・DoD リンクを明示する。
- DoD を満たして完了したタスクは `## Log` に成果サマリを移し、`docs/todo_next.md` と整合するよう更新する。
- 継続中に要調整点が出た場合はエントリ内に追記し、完了時にログへ移した後も追跡できるよう関連ドキュメントへリンクを残す。
- 新規に `Next Task` へ追加する際は、方針整合性を確認するために [docs/logic_overview.md](docs/logic_overview.md) や [docs/simulation_plan.md](docs/simulation_plan.md) を参照し、必要なら関連メモへリンクする。

- [P1-01] 2025-09-28 ローリング検証パイプライン — DoD: [docs/task_backlog_p1_archive.md#p1-01-ローリング検証パイプライン](docs/task_backlog_p1_archive.md#p1-01-ローリング検証パイプライン) — DoDを再確認し、365/180/90Dローリング更新と閾値監視の自動運用に向けたタスク整理を開始。
  - Backlog Anchor: [ローリング検証パイプライン (P1-01)](docs/task_backlog_p1_archive.md#p1-01-ローリング検証パイプライン)
  - Vision / Runbook References:
    - [docs/logic_overview.md](docs/logic_overview.md)
    - [docs/simulation_plan.md](docs/simulation_plan.md)
    - 主要ランブック: [docs/benchmark_runbook.md#スケジュールとアラート管理](docs/benchmark_runbook.md#スケジュールとアラート管理)
  - Pending Questions:
    - [ ] なし
  - Docs note: 参照: [docs/logic_overview.md](docs/logic_overview.md) / [docs/simulation_plan.md](docs/simulation_plan.md) / [docs/benchmark_runbook.md#スケジュールとアラート管理](docs/benchmark_runbook.md#スケジュールとアラート管理)
  - 2025-09-28: 手動でローリング 365/180/90D を再生成し、Sharpe・最大DD・勝率が揃って出力されていることと `benchmark_runs.alert` の delta_sharpe トリガーを確認。Slack Webhook が 403 で失敗したため、ランブックへサンドボックス時の扱いを追記する。
  - 2025-09-29: Cron サンプルへ `benchmark_pipeline_daily` を追加し、ランブック閾値 (`--alert-*` / `--min-*` / `--benchmark-windows 365,180,90` / `--benchmark-freshness-max-age-hours 6`) を CLI へ反映。`python3 scripts/run_daily_workflow.py --benchmarks` ドライランで `ops/runtime_snapshot.json` の `benchmark_pipeline` 更新・`threshold_alerts` 記録を確認（Sandbox では Webhook 403 と鮮度アラートは想定内）。
  - 2025-10-16: 最新バーの供給が途絶しているため、P1-04 で API インジェスト基盤を設計・整備し、鮮度チェックのブロッカーを解消する計画。

## Log
- [P0-14] 2026-05-22: Added `--min-gap-minutes` filtering and `--out-gap-json` export to `scripts/check_data_quality.py` so auditors can ignore noise while tracking skipped totals, synced README/backlog guidance, and ran `python3 -m pytest` to confirm the suite stays green.
- [P0-14] 2026-05-15: Extended `scripts/check_data_quality.py` with missing-row estimates, aggregate gap metrics, configurable reporting limits, and `--out-gap-csv`; updated README usage guidance, refreshed the DoD checklist, and ran `python3 -m pytest` to confirm the suite stays green.
- [P0-12] 2026-05-05: Realigned Codex operator documentation into a three-step quickstart/workflow/state-runbook set, refreshed README / docs/development_roadmap.md / docs/todo_next.md / docs/todo_next_archive.md anchors, updated backlog progress, and executed `python3 -m pytest` to confirm regressions stayed green.
- [Ops] 2026-05-03: Reconciled run_sim CLI documentation with the manifest-first workflow by updating backlog notes and repo guidance (AGENTS.md / agent.md / scripts/AGENTS.md), and annotated historical state entries so deprecated flags point to the manifest-driven replacements.
- [P0] 2026-03-23: Fixed the run_sim manifest aggregation regression by plumbing a dedicated
  `--archive-namespace` flag between `scripts/run_sim.py` and `scripts/aggregate_ev.py`, ensuring
  manifest-defined EV archive paths are aggregated correctly. Added targeted pytest coverage
  (`tests/test_run_sim_cli.py::TestRunSimCLI::test_run_sim_manifest_triggers_aggregate_with_namespace`,
  `tests/test_aggregate_ev_script.py::test_aggregate_ev_supports_archive_namespace`) and executed
  `python3 -m pytest tests/test_aggregate_ev_script.py tests/test_run_sim_cli.py`.
- [P1-05] 2026-02-21: Resolved the calibration EV leakage where `_resolve_calibration_positions` stopped settling warmup trades after the calibration window, added regression coverage (`tests/test_runner.py::test_calibration_positions_resolve_after_period`), and ran `python3 -m pytest tests/test_runner.py` to confirm the fix.
- [Ops] 2026-02-15: Captured the `finish-task` dry-run preview in `docs/codex_workflow.md`, cross-linked it from `docs/state_runbook.md`, and noted the update in the P1-07 docs memo.
- [Ops] 2026-02-15: Moved the Workflow Integration Guide entry to In Progress in `docs/todo_next.md`, refreshed the linked `state.md` date list to include the 2026-02-13 update, and dry-ran `scripts/manage_task_cycle.py start-task` to confirm the `doc-section` promotion remains aligned.
- [P1-06] 2026-02-13: Added fill-engine overrides (`fill_same_bar_policy_*`, `fill_bridge_lambda`, `fill_bridge_drift_scale`) to RunnerConfig and `scripts/run_sim.py`, exposed CLI flags, refreshed broker OCO docs/runbooks, and executed `python3 -m pytest tests/test_fill_engine.py tests/test_runner.py tests/test_run_sim_cli.py` to lock regression coverage.
- [Ops] 2026-02-13: Updated `docs/codex_workflow.md` with sandbox/approval guidance (workspace-write + on-request), clarified `scripts/manage_task_cycle.py` dry-run usage, and aligned references with `docs/state_runbook.md` / template links.
- [P2-MS] 2026-02-13: Re-ran Day ORB / Mean Reversion comparisons per `docs/checklists/multi_strategy_validation.md`, regenerated `runs/multi_strategy/` artefacts (`python3 scripts/run_sim.py ...`) including the `--no-ev-profile` variant, updated the checklist/table with the new metrics (`ev_reject=330` for Mean Reversion), and archived the task notes in `docs/todo_next.md` / `docs/task_backlog.md`.
- [P2-02] 2026-02-13: Finalised the router expansion deliverables by syncing `docs/checklists/p2_router.md`, recording the work plan in `docs/progress_phase2.md`, updating the backlog/todo archives, and executing `python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py` to confirm regression coverage.
- [P1-05] 2026-02-13: Closed the backtest runner logging visibility task after revalidating `docs/backtest_runner_logging.md`, updating `docs/task_backlog.md` with the closure note, and executing `python3 -m pytest tests/test_runner.py tests/test_run_sim_cli.py` to confirm the counters/records coverage.
- [P1-07] 2026-01-08: Closed Phase1 bug-check & refactor ops by extending `docs/checklists/p1-07_phase1_bug_refactor.md` with the investigation board, regression command list, refactor planning template, and manage-task-cycle examples. Archived the backlog entry, moved `docs/todo_next.md` Ready item to Archive, and removed the P1-07 anchor from `## Next Task`. Documentation-only update; tests not re-run.
- [P1-07] 2025-12-30: Consolidated `core/runner.BacktestRunner` daily metrics bookkeeping by introducing shared helpers for counter increments and RV threshold refresh. Replaced ad-hoc dictionary guards with `_increment_daily`/`_ensure_daily_entry`, extracted `_update_rv_thresholds` with a reusable quantile helper, and verified `python3 -m pytest` passes (150 tests) after the refactor.
- [P2-01] 2026-01-08: Added category-specific templates (`strategies/scalping_template.py`, `strategies/day_template.py`) and first candidate manifests (`tokyo_micro_mean_reversion`, `session_momentum_continuation`). Ran `python3 -m pytest tests/test_strategy_manifest.py` (2 passed) と `python3 -m pytest tests/test_run_sim_cli.py -k manifest` (1 passed, 4 deselected)。`python3 scripts/run_sim.py --strategy-manifest configs/strategies/tokyo_micro_mean_reversion.yaml --csv data/sample_orb.csv --symbol USDJPY --mode conservative --equity 100000 --json-out /tmp/tokyo_micro.json --dump-csv /tmp/tokyo_micro.csv --dump-daily /tmp/tokyo_micro_daily.csv --no-auto-state --no-aggregate-ev`、`python3 scripts/run_sim.py --strategy-manifest configs/strategies/session_momentum_continuation.yaml --csv data/sample_orb.csv --symbol USDJPY --mode conservative --equity 150000 --json-out /tmp/session_momo.json --dump-csv /tmp/session_momo.csv --dump-daily /tmp/session_momo_daily.csv --no-auto-state --no-aggregate-ev`、`python3 scripts/run_sim.py --strategy-manifest configs/strategies/day_orb_5m.yaml --csv data/sample_orb.csv --symbol USDJPY --mode conservative --equity 100000 --json-out /tmp/day_orb.json --dump-csv /tmp/day_orb.csv --dump-daily /tmp/day_orb_daily.csv --no-auto-state --no-aggregate-ev` を実行し、manifest 経由の CLI 配線とテンプレ整備を検証。戦略テンプレと manifest を整備し、manifest CLI 回帰と run_sim ドライランを完了し、pytest/run_sim で配線確認済み。DoD: [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化). ※ 現在は `--manifest` と manifest 側の `runner.cli_args` で auto_state / aggregate_ev / dump 設定を管理する manifest-first CLI に統合済み。
- [P2-MS] 2025-12-02: Migrated the Mean Reversion strategy from the stub into `strategies/mean_reversion.py`, wiring RV/ADX filters, ATR-based sizing, and EV profile adjustments. Refreshed the manifest/EV profile (`configs/strategies/mean_reversion.yaml`, `configs/ev_profiles/mean_reversion.yaml`), published the broker comparison notebook (`analysis/broker_fills.ipynb`), and added regression coverage (`tests/test_mean_reversion_strategy.py`, updated `tests/test_run_sim_cli.py`). Ran `python3 analysis/broker_fills_cli.py --format markdown` と `python3 -m pytest` で挙動を確認し、`docs/progress_phase1.md` / `docs/task_backlog.md` / `docs/checklists/multi_strategy_validation.md` / `analysis/README.md` を同期。
- [P2-MS] 2025-12-05: Updated `strategies/day_orb_5m.DayORB5m` to persist breakout direction when `require_retest` is enabled, enforcing directional retest checks so sell breakouts no longer auto-approve without touching the OR low. Added regression coverage in `tests/test_day_orb_retest.py` and documented the workflow tweak in `docs/progress_phase1.md`. Ran `python3 -m pytest` to confirm all suites pass.
- [P1-02] 2025-12-01: Documented the incident replay workflow in `docs/state_runbook.md#インシデントリプレイワークフロー` and cross-referenced it from README / `ops/incidents/README.md`. Clarified how to archive `replay_notes.md` / `replay_params.json` / `runs/incidents/...` outputs and where to publish stakeholder digests. Synced `docs/todo_next.md` Archive dates to close the remaining P1-02 documentation deliverables.
- [P1-02] 2025-11-30: `analysis/incident_review.ipynb` のリプレイ手順を刷新し、`incident.json` の `start_ts` / `end_ts` を `scripts/run_sim.py --start-ts --end-ts` に直接渡すセルへ置き換えた。CLI 実行で `source_with_header.csv` を自動生成してヘッダ欠損を補い、`metrics.json` / `daily.csv` の出力と `returncode` を Notebook 内で確認。成果物同期の Markdown 手順を追記し、`python3 -m pytest` を実行して全テストがグリーンであることを確認した。
- [P1-02] 2025-11-29: Captured the 2025-10-02 USDJPY drawdown replay by adding `ops/incidents/20250101-0900_USDJPY_drawdown/` with incident metadata, replay parameters, and analyst notes. Ran `python3 scripts/run_sim.py --csv /tmp/usdjpy_5m_with_header.csv --symbol USDJPY --mode conservative --equity 100000 --start-ts 2025-10-02T15:00:00Z --end-ts 2025-10-02T19:30:00Z --out-dir runs/incidents --json-out /tmp/incident_metrics.json --no-auto-state --no-aggregate-ev` to validate the window and linked the generated `runs/incidents/USDJPY_conservative_20251002_230924/` artifacts for future review。※ 現行 CLI では `--manifest` 必須・auto_state/aggregate_ev トグルは manifest の `runner.cli_args` で制御するため、再現時は manifest-first コマンドへ読み替えること。
- [P1-04] 2025-11-28: Re-ran the full ingest + freshness workflow (`python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative` → `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --ingest-timeframe USDJPY_5m`) after confirming the HTTP yfinance fallback was available. Verified `ops/runtime_snapshot.json.ingest_meta.USDJPY_5m.freshness_minutes=0.614` with `source_chain=["yfinance"]`, and observed `check_benchmark_freshness` returning `ok: true` with empty `errors`/`advisories`. Synced docs/checklist/todo backlog notes and archived the task entry.
- [P1-04] 2025-12-03: Updated `scripts/run_daily_workflow.py` so `--local-backup-csv` expands `~` before resolving paths, enabling operators to reference home-directory CSV backups. Added `tests/test_run_daily_workflow.py::test_local_csv_fallback_expands_user_path` to lock the behaviour and confirmed snapshot metadata captures the absolute path.
- [P1-01] 2025-12-08: Updated `scripts/report_benchmark_summary.py` so webhook notifications are dispatched after plot-related warnings are appended, ensuring missing Matplotlib/pandas dependencies surface through alerts. Added regression test `tests/test_report_benchmark_summary.py::test_missing_plot_dependency_triggers_webhook_warning` and executed `python3 -m pytest tests/test_report_benchmark_summary.py` followed by `python3 -m pytest` to confirm coverage.
- [P1-01] 2025-11-27: Corrected `scripts/check_benchmark_freshness.py` to pass a single concatenated string into `_record_issue` when reporting stale benchmark entries, preventing the CLI from raising `TypeError`. Verified `python3 -m pytest tests/test_check_benchmark_freshness.py` to ensure freshness errors downgrade correctly for synthetic sources.
- [P1-01] 2025-11-27: Executed `python3 scripts/run_benchmark_pipeline.py --windows 365,180,90 --disable-plot` and `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --benchmark-freshness-max-age-hours 6` to refresh rolling metrics and confirm `ops/runtime_snapshot.json.benchmark_pipeline` reported `ok: true` without errors. Updated README / docs/benchmark_runbook.md with the dual-threshold guidance, marked `docs/checklists/p1-01.md` complete, moved the todo entry to Archive, recorded the outcome in docs/task_backlog.md and docs/todo_next.md, and ran `python3 -m pytest tests/test_check_benchmark_freshness.py` to verify the new CLI flag.
- [P1-04] 2025-11-17: Extended `scripts/check_benchmark_freshness.py` to surface ingestion freshness minutes, fallback/source chains, and last ingest timestamps, updated `tests/test_check_benchmark_freshness.py`, and documented the review flow in `docs/benchmark_runbook.md`. Ran `python3 -m pytest` for regression.
- [P1-01] 2025-10-15: Added `--min-win-rate` health threshold to benchmark summary / pipeline / daily workflow CLIs, ensured `threshold_alerts` propagation into runtime snapshots, refreshed README + benchmark runbook + checklist guidance, linked the backlog progress note, and ran `python3 -m pytest`.
- [P1-01] 2025-10-14: Added `scripts/check_benchmark_freshness.py` with regression tests, wired the CLI into `run_daily_workflow.py --check-benchmark-freshness`, and documented the 6h freshness threshold across the benchmark runbook / P1-01 checklist / backlog notes.
- [P1-05] 2025-10-13: Added deterministic hook-failure regression for `run_sim` debug counters/records, updated
  `docs/backtest_runner_logging.md` with the coverage note, and synced `docs/task_backlog.md` progress.
- [P1-01] 2025-10-13: `run_benchmark_pipeline.py` のスナップショット更新でアラートブロックを保存し、`tests/test_run_benchmark_pipeline.py` に delta 保存の回帰テストを追加。`docs/benchmark_runbook.md` にレビュー時の `benchmark_pipeline.<symbol>_<mode>.alert` チェック手順を追記し、`python3 -m pytest tests/test_run_benchmark_pipeline.py` を実行してグリーン確認。
- [P1-01] 2025-10-12: Baseline metrics validation を `_validate_baseline_output` に追加し、win_rate / Sharpe / 最大DD の欠損を捕捉。`tests/test_run_benchmark_pipeline.py` へベースライン欠損時の回帰テストと成功パスの指標整備を行い、`python3 -m pytest tests/test_run_benchmark_pipeline.py` を実行して全件パス。
- [P1-01] 2025-10-11: 強制バリデーションへ勝率を追加し、`run_benchmark_pipeline.py` がローリング/サマリー双方で win_rate・Sharpe・最大DD の欠損を検知するよう更新。`tests/test_run_benchmark_pipeline.py` に成功ケースの勝率出力と勝率欠損エラーの回帰テストを追加し、`docs/checklists/p1-01.md` の DoD に勝率検証ステップを追記。`python3 -m pytest tests/test_run_benchmark_pipeline.py` を実行し全件パス。
- [P1-06] 2025-10-10: `docs/broker_oco_matrix.md` に OANDA / IG / SBI FXトレードの OCO 同足処理・トレール更新間隔を追記し、`analysis/broker_fills_cli.py` で Conservative / Bridge / 実仕様差分を Markdown テーブル化。`core/fill_engine.py` に `SameBarPolicy` とトレール更新ロジックを導入し、`tests/test_fill_engine.py` を新設して代表ケース（Tick 優先 / 保護優先 / トレール更新）を固定。`docs/progress_phase1.md` / `docs/benchmark_runbook.md` を再実行手順・検証フローで更新し、`python3 -m pytest` を完走。
- [P0-15] 2025-10-09: Piloted the `data_quality_failure` acknowledgement workflow by forcing a dry-run failure (`python3 scripts/check_data_quality.py --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --expected-interval-minutes 1 --calendar-day-summary --fail-under-coverage 0.995 --fail-on-calendar-day-warnings --calendar-day-coverage-threshold 0.995 --out-json /tmp/dq_summary_dry_run.json`), recorded the entry in `ops/health/data_quality_alerts.md`, synced `docs/task_backlog.md` / `docs/todo_next.md` with the monitoring follow-up, and ran `python3 -m pytest` to keep regressions green.
- [P2-MS] 2024-06-22: `scripts/run_sim.py --strategy-manifest` を実装し、`RunnerConfig` がマニフェスト経由の許容セッション/リスク上限と戦略パラメータを取り込むよう更新。`core/runner.py` の `StrategyConfig` を汎用辞書対応に拡張し、`tests/test_run_sim_cli.py::test_run_sim_manifest_mean_reversion` で `allow_high_rv` / `zscore_threshold` が `strategy_gate`・`ev_threshold` へ届くことを検証。関連ドキュメント: [docs/task_backlog.md](docs/task_backlog.md)、[docs/progress_phase1.md](docs/progress_phase1.md)。※ 後続アップデートで `--manifest` に統合済み。
- [P0-01] 2024-06-01: Initialized state tracking log and documented the review/update workflow rule.
- [P0-02] 2024-06-02: Targeting P0 reliability by ensuring strategy manifests and CLI runners work without optional dependencies. DoD: pytest passes and run_sim/loader can parse manifests/EV profiles after removing the external PyYAML requirement.
- [P0-03] 2024-06-03: 同期 `scripts/rebuild_runs_index.py` を拡充し、`runs/index.csv` の列網羅性テストを追加。DoD: pytest オールパスと CSV 列の欠損ゼロ。
- [P0-04] 2024-06-04: Sharpe 比・最大 DD をランナー/CLI/ベンチマークに波及させ、runbook とテストを更新。DoD: `python3 -m pytest` パスと `run_sim` JSON に新指標が出力されること。
- [P0-04] 2024-06-04 (完了): `core/runner` でエクイティカーブと Sharpe/最大DD を算出し、`run_sim.py`→`runs/index.csv`→`store_run_summary`→`report_benchmark_summary.py` まで連携。`--min-sharpe`/`--max-drawdown` を追加し、docs・テスト更新後に `python3 -m pytest` を通過。
- [P0-05] 2024-06-05: `scripts/run_benchmark_runs.py` の CLI フローを網羅する pytest を追加し、ドライラン/本番実行/失敗ケースの挙動を検証。DoD: `python3 -m pytest` オールグリーン。
- [P0-06] 2024-06-06: `scripts/run_daily_workflow.py` に `--min-sharpe`/`--max-drawdown` を追加し、ベンチマーク要約呼び出しへ閾値を伝播するテストを新設。DoD: `python3 -m pytest` オールパスで、組み立てコマンドに閾値引数が含まれること。
- [P0-06] 2024-06-07: ベースライン/ローリング run を再実行して Sharpe・最大DD 指標をレポートに含め、`report_benchmark_summary.py` で新指標が集計されることを確認。DoD: ベンチマーク run コマンド完走・サマリー更新後に `python3 -m pytest` を実行しオールパス。
- [P0-07] 2024-06-08: `scripts/run_sim.py` のパラメータ保存に EV ゲート関連引数を追加し、`runs/index.csv` / `rebuild_runs_index.py` / テストを同期。DoD: `python3 -m pytest` オールパスで新列が確認できること。
- [P0-08] 2024-06-09: `scripts/run_benchmark_runs.py` で `rebuild_runs_index.py` の失敗コード伝播とログ詳細出力を追加し、失敗時 JSON にエラー情報を含める回帰テストを作成。DoD: `python3 -m pytest` オールパスで失敗コードが伝播すること。
- [P0-09] 2024-06-10: `scripts/run_daily_workflow.py` の失敗コード伝播と README/pytest を更新。DoD: `python3 -m pytest tests/test_run_daily_workflow.py` パス。
- [P1-03] 2024-06-11: P1「state ヘルスチェック」タスクに着手。DoD: `check_state_health` 用 pytest 追加・履歴ローテーション/警告/Webhook 回帰テストが通り、`python3 -m pytest tests/test_check_state_health.py` を完走すること。
- [P1-03] 2024-06-11 (完了): 追加テストで警告生成・履歴トリム・Webhook を検証し、`python3 -m pytest tests/test_check_state_health.py` がグリーン。docs/task_backlog.md へ進捗を反映。
- [P1-01] 2024-06-12: ベンチマークパイプラインを `scripts/run_benchmark_pipeline.py` として追加し、Webhook 伝播・スナップショット更新・`run_daily_workflow.py --benchmarks` からの一括実行を整備。`tests/test_run_benchmark_pipeline.py` を含む関連 pytest を更新してグリーン確認。
- [P1-01] 2024-06-13: `run_daily_workflow.py` からベンチマークサマリー呼び出し時にも Webhook/閾値を伝播させる対応を実装し、README を追記。`python3 -m pytest tests/test_run_daily_workflow.py` を実行して回帰確認。
- [P1-01] 2024-06-14: `run_daily_workflow.py` の最適化/レイテンシ/状態アーカイブコマンドで絶対パスを使用するよう更新し、pytest でコマンド引数に ROOT が含まれることを検証。
- [P1-02] 2024-06-15: `scripts/run_sim.py` に `--start-ts` / `--end-ts` を追加し、部分期間のリプレイをテスト・README・バックログへ反映。DoD: pytest オールグリーンで Sharpe/最大DD 出力継続を確認。
- [P1-02] 2024-06-16: `tests/test_run_sim_cli.py` の時間範囲テストで `BacktestRunner.run` をモック化した際に JSON へ MagicMock が混入する事象を調査し、ラップ関数で実体を返す形に修正。DoD: `python3 -m pytest` がグリーンで TypeError が再発しないこと。
- [P1-04] 2024-06-18: docs/task_backlog.md 冒頭にワークフロー統合指針を追記し、state.md / docs/todo_next.md 間の同期ルールと参照例を整備。
- [P1-04] 2024-06-19: `docs/todo_next.md` を In Progress / Ready / Pending Review / Archive セクション構成へ刷新し、`state.md` のログ日付とバックログ連携を明示。DoD: ガイドライン/チェックリストの追記と過去成果のアーカイブ保持。
- [P1-04] 2024-06-20: Ready 昇格チェックリストにビジョンガイド再読を追加し、`Next Task` 登録時の参照先として `docs/logic_overview.md` / `docs/simulation_plan.md` を明記。

- 2026-03-16: Skipped EV/warmup restoration when `config_fingerprint` mismatches the active `RunnerConfig`, added a
  regression in `tests/test_runner.py::test_load_state_skips_on_config_fingerprint_mismatch` to lock the guard,
  verified `scripts/run_sim.py` produces trades again under mismatched state snapshots, and executed `python3 -m pytest`.
- 2026-03-18: Persisted slip EWMA quantities when exporting/loading runner state so expected slip projections survive resets,
  added `tests/test_runner.py::test_slip_state_persists_qty_ewma_for_expected_slip` to cover the workflow, and ran
  `python3 -m pytest tests/test_runner.py` for validation.
- 2026-03-19: Normalised spread handling in `core/runner.BacktestRunner._build_ctx` so pip-denominated feeds no longer undergo
  duplicate conversion, added configuration hooks (`spread_input_mode`/`spread_scale`) plus regression tests covering pip
  spreads, expected slip costs, and scaling, and executed `python3 -m pytest tests/test_runner.py tests/test_runner_features.py`.
- 2026-03-20: Routed same-bar TP probability blending through a shared BridgeFill helper so RunnerExecution respects
  `RunnerConfig.fill_bridge_lambda` / `fill_bridge_drift_scale`, exposed the probability in trade debug output, added a
  regression that verifies exit price / probability react to config changes, and ran
  `python3 -m pytest tests/test_runner.py`.
- 2026-03-21: Propagated same-bar TP probabilities through `RunnerExecutionManager` so EV buckets consume
  fractional updates via `update_weighted`, updated trade finalisation to forward the probability, added
  bridge/conservative regressions in `tests/test_runner.py`, and ran `python3 -m pytest tests/test_runner.py`.
- 2026-03-22: Exposed Bridge same-bar TP probability/exit helpers that read `RunnerConfig` parameters,
  refactored `RunnerExecutionManager.compute_exit_decision` to use the shared helper, added bridge collision
  regression in `tests/test_runner.py` confirming `fill_bridge_lambda` / `fill_bridge_drift_scale` influence
  `exit_px` and `p_tp`, and executed `python3 -m pytest tests/test_runner.py`.
- 2026-03-26: Updated `RunnerExecutionManager.compute_exit_decision` to honour conservative same-bar policies,
  extracted a shared helper with `ConservativeFill` so TP-first/SL-first/probabilistic paths align, added
  regressions for conservative `tp_first`/`probabilistic` policies in `tests/test_runner.py`, and ran
  `python3 -m pytest tests/test_runner.py`.
- 2026-03-10: Enabled `RunnerExecutionManager.process_fill_result` to return structured `PositionState` objects, updated
  `BacktestRunner._process_fill_result` delegations and regression tests to assert serialization/identity, and ran
  `python3 -m pytest tests/test_runner.py` to confirm behaviour.
- 2026-03-09: Replaced runner entry/EV/sizing contexts with typed dataclasses, refactored the feature pipeline and gating flow to
  propagate structured contexts, updated trade snapshot helpers, and refreshed runner feature/unit tests to assert the new
  attribute-based API. Ran `python3 -m pytest tests/test_runner_features.py tests/test_runner.py`.

- [OPS-CODEX-GUIDE] 2025-10-08: Aligned workflow docs with review feedback. DoD: [docs/task_backlog.md#codex-session-operations-guide](docs/task_backlog.md#codex-session-operations-guide).
## Next Task
- Kick off [P3 Observability automation](docs/task_backlog.md#p3-観測性・レポート自動化) planning by expanding the scope definition in `docs/plans/p2_completion_plan.md` and preparing initial automation checkpoints for signal latency / weekly reports ahead of implementation.

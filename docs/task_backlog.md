# 作業タスク一覧（バックログ）

このバックログは「最新値動きを取り込みながら継続学習し、複数戦略ポートフォリオでシグナルを出す」ツールを実現するための優先順位付きタスク群です。各タスク完了時は成果物（コード/ドキュメント/レポート）へのリンクを追記してください。

## ワークフロー統合

各タスクに着手する前に、該当するバックログ項目を `state.md` の `Next Task` ブロックへ明示的に引き込み、進行中であることを記録してください。作業完了後は、成果ノートや反省点を `docs/todo_next.md` に反映し、`state.md` の完了ログと整合するよう同期します。

- 例: `[P1-02] 2024-06-18 state.md ログ / docs/progress/phase1.md`

### Codex Session Operations Guide
Document the repeatable workflow that lets Codex keep `state.md`, `docs/todo_next.md`, and `docs/task_backlog.md` synchronized across sessions, including how to use the supporting scripts and templates.

**DoD**
- `docs/codex_workflow.md` explains pre-session checks, the execution loop, wrap-up steps, and how to apply the shared templates.
- The guide covers dry-run and live usage of `scripts/manage_task_cycle.py` for keeping state/doc updates in lockstep.
- Links to related runbooks and templates are included so future sessions can reproduce the same procedure.

**Progress Notes**
- 2025-09-29: Added `docs/codex_workflow.md` to consolidate operational guidance for Codex agents and clarified the relationship with `docs/state_runbook.md` and the template directory.
- 2025-10-16: Supplemented cloud-run guardrails in `docs/codex_cloud_notes.md` and linked them from the workflow guide to improve sandbox handoffs.
- 2026-02-13: Refreshed `docs/codex_workflow.md` with sandbox/approval guidance (workspace-write + on-request approvals), highlighted `--doc-section` usage for aligning `docs/todo_next.md`, and reiterated `scripts/manage_task_cycle.py` dry-run examples. Synced references with `docs/state_runbook.md` and template links.
- 2026-04-17: Implemented the observability dashboard pipeline (`analysis/export_dashboard_data.py`, `analysis/dashboard/*`, `analysis/portfolio_monitor.ipynb`) and documented refresh/reporting expectations in `docs/observability_dashboard.md`.

## P0: 即着手（オンデマンドインジェスト + 基盤整備）
- **P0-12 Codex-first documentation cleanup**
  - **DoD**: Codex operator workflow has a one-page quickstart (`docs/codex_quickstart.md`), the detailed checklist (`docs/state_runbook.md`) is trimmed to actionable bullet lists, README points to both, and `docs/development_roadmap.md` captures immediate→mid-term improvements with backlog links. Backlogとテンプレートは新フローに沿って更新済みであること。
  - **Notes**: Focus on reducing duplication between `docs/codex_quickstart.md`, `docs/codex_workflow.md`, README, and `docs/state_runbook.md`; ensure sandbox/approval rules stay explicit.
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
- ~~**runs/index 再構築スクリプト整備**~~ (完了): `scripts/rebuild_runs_index.py` が `scripts/run_sim.py` の出力列 (k_tr, gate/EV debug など) と派生指標 (win_rate, pnl_per_trade) を欠損なく復元し、`tests/test_rebuild_runs_index.py` で fixtures 検証を追加。
- ~~**ベースライン/ローリング run 起動ジョブ**~~ (2024-06-12 完了): `scripts/run_benchmark_pipeline.py` でベースライン/ローリング run → サマリー → スナップショット更新を一括化し、`run_daily_workflow.py --benchmarks` から呼び出せるようにした。`tests/test_run_benchmark_pipeline.py` で順序・引数伝播・失敗処理を回帰テスト化。
  - 2024-06-05: `tests/test_run_benchmark_runs.py` を追加し、`--dry-run`/通常実行の双方で JSON 出力・アラート生成・スナップショット更新が期待通りであることを検証。
- ~~**P0-09 オンデマンド Day ORB シミュレーション確認**~~ (2026-02-13 完了): `python3 scripts/run_sim.py --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --mode conservative --equity 100000` を実行し、最新の Day ORB 状態で 50 件トレード・総損益 -132.09 pips を確認。`ops/state_archive/day_orb_5m.DayORB5m/USDJPY/conservative/20251005_132055.json` を生成し、EV プロファイルを再集計した。

## P1: ローリング検証 + 健全性モニタリング（Archive）

フェーズ1タスクの詳細な進捗記録は [docs/task_backlog_p1_archive.md](docs/task_backlog_p1_archive.md) に保管されています。歴史的な参照が必要な場合は同アーカイブを参照してください。

## P2: マルチ戦略ポートフォリオ化

### ~~P2-01 戦略マニフェスト整備~~ ✅ (2026-01-08 クローズ)
- スキャル/デイ/スイングの候補戦略ごとに、依存特徴量・セッション・リスク上限を YAML で定義し、ルーターが参照できるようにする (`configs/strategies/*.yaml`)。
  - 2025-10-09: `configs/strategies/templates/base_strategy.yaml` に共通テンプレートと記述ガイドを追加し、新規戦略のマニフェスト整備を着手しやすくした。
- 2024-06-22: `scripts/run_sim.py --manifest` でマニフェストを読み込み、RunnerConfig の許容セッション/リスク上限と戦略固有パラメータを `Strategy.on_start` に直結するフローを整備。`tests/test_run_sim_cli.py` で manifest 経由のパラメタ伝播を検証。DoD: [フェーズ1-戦略別ゲート整備](docs/progress_phase1.md#1-戦略別ゲート整備)。
  - 2026-01-08: `strategies/scalping_template.py` / `strategies/day_template.py` を追加し、`tokyo_micro_mean_reversion`・`session_momentum_continuation` の manifest/実装を新設。`python3 -m pytest tests/test_strategy_manifest.py` で loader 整合性を確認。次ステップは run_sim CLI ドライランと DoD チェック更新。

### ~~P2-02 ルーター拡張~~ ✅ (2026-02-13 クローズ)
- 現行ルールベース (`router/router_v0.py`) を拡張し、カテゴリ配分・相関・キャパ制約を反映。戦略ごとの state/EV/サイズ情報を統合してスコアリングする。
  - 設計ガイド: [docs/router_architecture.md](router_architecture.md)
  - DoD: [docs/checklists/p2_router.md](docs/checklists/p2_router.md)
  - 2026-01-27: `router/router_v1.select_candidates` がカテゴリ/グロスヘッドルームを参照してスコアへボーナス/ペナルティを適用し、理由ログへ残差状況を記録するよう拡張。`tests/test_router_v1.py` にヘッドルーム差分のスコア回帰を追加し、`docs/checklists/p2_router.md` の DoD を更新。
  - 2026-02-05: `scripts/build_router_snapshot.py` に `--correlation-window-minutes` を追加し、相関行列と併せて窓幅メタデータを `telemetry.json` / ポートフォリオサマリーへ保存。`PortfolioTelemetry` / `PortfolioState` が新フィールドを保持できるよう拡張し、`tests/test_report_portfolio_summary.py` に CLI 回帰とヘルプ出力確認を追加。
  - 2026-02-07: `core/router_pipeline.manifest_category_budget` で manifest `governance.category_budget_pct` を吸い上げつつ、`scripts/build_router_snapshot.py --category-budget-csv` から外部 CSV を取り込んで `telemetry.json` へ集約。`router_v1` はカテゴリ予算超過時に `status=warning|breach` を理由ログへ記録し、段階的にペナルティを強化する。`tests/test_router_pipeline.py` / `tests/test_router_v1.py` へカテゴリ予算ヘッドルームとスコア調整の回帰を追加。
  - 2026-02-08: `core/router_pipeline.build_portfolio_state` が `execution_health` 配下の数値メトリクス（`reject_rate` / `slippage_bps` / `fill_latency_ms` 等）を包括的に取り込み、`router_v1.select_candidates` は各ガード (`max_reject_rate` / `max_slippage_bps` / `max_fill_latency_ms` など) までのマージンを算出して理由ログに記録。閾値に迫るとスコアを段階的に減点し、逸脱時はマージン付きで失格理由を返す。`tests/test_router_v1.py` / `tests/test_router_pipeline.py` に新メトリクスとマージン挙動の回帰を追加し、`docs/router_architecture.md` / `docs/checklists/p2_router.md` を更新して運用手順をリンク。
  - 2026-02-11: `PortfolioTelemetry` / `build_portfolio_state` が `correlation_meta` を保持し、`scripts/build_router_snapshot.py` がテレメトリへメタデータをエクスポートするよう整備。ポートフォリオサマリーの相関ヒートマップには `bucket_category` / `bucket_budget_pct` を含め、`tests/test_report_portfolio_summary.py` / `tests/test_router_pipeline.py` で回帰を追加。`docs/router_architecture.md` / `docs/checklists/p2_router.md` にバケット情報の公開手順を追記。
  - 2026-02-13: Closed the v2 preparation loop by reconciling runner telemetry, documenting the category/correlation scoring path, and marking the DoD checklist complete. Updated `docs/progress_phase2.md` with the English deliverable plan, synced `docs/checklists/p2_router.md`, and ran `python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py` to confirm the final regression set.

- **ポートフォリオ評価レポート**: 複数戦略を同時に流した場合の資本使用率・相関・ドローダウンを集計する `analysis/portfolio_monitor.ipynb` と `reports/portfolio_summary.json` を追加。
  - 2026-01-16: `analysis/portfolio_monitor.py` と `scripts/report_portfolio_summary.py` を実装し、`reports/portfolio_samples/router_demo/` のフィクスチャで JSON スキーマを固定。`python3 -m pytest` と CLI ドライランでカテゴリ利用率・相関ヒートマップ・合成ドローダウンの算出を確認し、`docs/logic_overview.md#ポートフォリオ監視` に運用手順と判断基準を追記。
### ~~P2-MS マルチ戦略比較バリデーション~~ ✅ (2026-02-13 クローズ)
- Day ORB と Mean Reversion (`strategies/mean_reversion.py`) を同一 CSV で走らせ、`docs/checklists/multi_strategy_validation.md` に沿ってゲート通過数・EV リジェクト数・期待値差をレビュー。DoD: チェックリストの全項目を完了し、比較サマリをレビュー用ドキュメントへ共有する。
  - 2025-12-02: Mean Reversion 戦略の本実装を `strategies/mean_reversion.py` へ移行し、`configs/strategies/mean_reversion.yaml` / `configs/ev_profiles/mean_reversion.yaml` を整備。`analysis/broker_fills.ipynb` を公開してブローカー別比較を Notebook でも検証可能にし、`tests/test_mean_reversion_strategy.py` を追加してゲート・EV 調整ロジックの回帰を確保。
  - 2026-02-13: `docs/checklists/multi_strategy_validation.md` をフォローして Day ORB / Mean Reversion を最新テンプレで実行。`runs/multi_strategy/` に指標を再生成し、EV プロファイル有無で差分が無いこと（`reversion.json` vs `reversion_no_profile.json`）と、`ev_reject=330` が Mean Reversion の LCB フィルタで律速になっている点を記録。サマリ表と実測コメントを更新し、チェックリスト完了状態を維持。

## P3: 観測性・レポート自動化
- **シグナル/レイテンシ監視自動化**: `scripts/analyze_signal_latency.py` を日次ジョブ化し、`ops/signal_latency.csv` をローテーション。SLO違反でアラート。
- **週次レポート生成**: `scripts/summarize_runs.py` を拡張し、ベースライン/ローリング run・カテゴリ別稼働率・ヘルスチェック結果をまとめて Webhook送信。
  - 2026-04-16: `scripts/summarize_runs.py` を通知ペイロード生成フローに刷新し、`--config` での include/宛先制御と Webhook ドライランを追加。`docs/benchmark_runbook.md` に運用手順を記載し、`tests/test_summarize_runs.py` で集計精度と Webhook ペイロードを回帰テスト化。
- **ダッシュボード整備**: EV 推移、滑り推定、勝率 LCB、ターンオーバーの KPI を 1 つの Notebook or BI に集約し、運用判断を迅速化。

## 継続タスク / 保守
- データスキーマ検証 (`scripts/check_data_quality.py`) を cron 化し、異常リストを `analysis/data_quality.md` に追記。
- 回帰テストセットを拡充（高スプレッド、欠損バー、レイテンシ障害等）し、CI で常時実行。
- 重要な設計・運用変更時は `readme/設計方針（投資_3_）v_1.md` と `docs/state_runbook.md` を更新し、履歴を残す。

> 補足: 着手順は P0 → P1 → P2 の順。途中で運用インシデントが発生した場合は、P1「インシデントリプレイテンプレート」の整備を優先してください。

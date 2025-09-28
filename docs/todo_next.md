# 次のアクション（目標指標達成フロー）

## 更新ルール
- タスクを完了したら、必ず `state.md` の該当項目をログへ移し、本ファイルのセクション（In Progress / Ready / Pending Review / Archive）を同期してください。
- `state.md` に記録されていないアクティビティは、このファイルにも掲載しない方針です。新しい作業を始める前に `state.md` へ日付と目的を追加しましょう。
- Ready または In Progress へ昇格させるタスクは、[docs/templates/dod_checklist.md](docs/templates/dod_checklist.md) を複製し `docs/checklists/<task-slug>.md` へ保存したうえで、該当エントリからリンクするか貼り付けてください。

## Ready 昇格チェックリスト
- 高レベルのビジョンガイド（例: [docs/logic_overview.md](docs/logic_overview.md), [docs/simulation_plan.md](docs/simulation_plan.md)）を再読し、昇格対象タスクが最新戦略方針と整合しているか確認する。
- `docs/progress_phase*.md`（特に対象フェーズの記録）を確認し、未完了の前提条件や検証ギャップがないかレビューする。
- 関連するランブック（例: `docs/state_runbook.md`, `docs/benchmark_runbook.md`）を再読し、必要なオペレーション手順が揃っているかを点検する。
- バックログ該当項目の DoD を最新化し、関係チームへ通知済みであることを確認する。
- DoD チェックリスト テンプレートをコピーし、Ready チェックの進捗とバックログ固有 DoD をチェックボックスで追跡している。

## Current Pipeline

### In Progress

- **ローリング検証パイプライン**（バックログ: `docs/task_backlog.md` → P1「ローリング検証 + 健全性モニタリング」） — `state.md` 2025-09-28, 2024-06-13, 2024-06-14, 2024-06-15, 2024-06-16 <!-- anchor: docs/task_backlog.md#p1-01-ローリング検証パイプライン -->
  - `scripts/run_benchmark_pipeline.py` の整備と `run_daily_workflow.py` 連携、期間指定リプレイ (`--start-ts` / `--end-ts`) の確認を継続中。
  - 次ステップ: ベンチマークランのローリング更新自動化と Sharpe / 最大 DD 指標の回帰監視強化。
  - 2025-09-30: `manage_task_cycle.py start-task` に runbook/pending 資料の上書きオプションを追加し、`sync_task_docs.py` のテンプレ適用を共通ヘルパーへ整理。`docs/codex_workflow.md` と README の手順を更新済み。
  - Backlog Anchor: [ローリング検証パイプライン (P1-01)](docs/task_backlog.md#p1-01-ローリング検証パイプライン)
  - Vision / Runbook References:
    - [docs/logic_overview.md](docs/logic_overview.md)
    - [docs/simulation_plan.md](docs/simulation_plan.md)
    - 主要ランブック: [docs/benchmark_runbook.md#スケジュールとアラート管理](docs/benchmark_runbook.md#スケジュールとアラート管理)
  - Pending Questions:
    - [ ] なし
  - Docs note: 参照: [docs/logic_overview.md](docs/logic_overview.md) / [docs/simulation_plan.md](docs/simulation_plan.md) / [docs/benchmark_runbook.md#スケジュールとアラート管理](docs/benchmark_runbook.md#スケジュールとアラート管理)
  - DoD チェックリスト: [docs/checklists/p1-01.md](docs/checklists/p1-01.md) を更新して進捗を管理する。

### Ready

### Pending Review
- **Workflow Integration Guide** (Backlog: `docs/task_backlog.md` → "ワークフロー統合" section) — `state.md` 2024-06-18, 2025-09-29 <!-- anchor: docs/task_backlog.md#codex-session-operations-guide -->
  - Updated the synchronization rules between `docs/todo_next.md` and `state.md`. Added `docs/codex_workflow.md` to capture Codex session procedures. Confirm readiness for adoption before moving to Archive.

## Archive（達成済み）
- ~~**目標指数の定義**~~ ✅ — `state.md` 2024-06-01 <!-- anchor: docs/task_backlog.md#目標指数の定義 -->
  - `configs/targets.json` と `scripts/evaluate_targets.py` を整備済み。
- ~~**ウォークフォワード検証**~~ ✅ — `state.md` 2024-06-02, 2024-06-03 <!-- anchor: docs/task_backlog.md#ウォークフォワード検証 -->
  - `scripts/run_walk_forward.py` を追加し、`analysis/wf_log.json` に窓別ログを出力。
- ~~**自動探索の高度化**~~ ✅ — `state.md` 2024-06-04 <!-- anchor: docs/task_backlog.md#自動探索の高度化 -->
  - `scripts/run_optuna_search.py` で多指標目的の探索骨子を構築。
- ~~**運用ループへの組み込み**~~ ✅ — `state.md` 2024-06-05 <!-- anchor: docs/task_backlog.md#運用ループへの組み込み -->
  - `scripts/run_target_loop.py` による Optuna → run_sim → 指標計算 → 判定のループを実装。
- ~~**state ヘルスチェック**~~ ✅ — `state.md` 2024-06-11 <!-- anchor: docs/task_backlog.md#state-ヘルスチェック -->
  - `scripts/check_state_health.py` の警告生成・履歴ローテーション・Webhook テストを追加。
- ~~**ベースライン/ローリング run 起動ジョブ**~~ ✅ — `state.md` 2024-06-12 <!-- anchor: docs/task_backlog.md#ベースラインローリング-run-起動ジョブ -->
  - `scripts/run_benchmark_pipeline.py` と `tests/test_run_benchmark_pipeline.py` を整備し、runbook を更新。
- ~~**ベンチマークサマリー閾値伝播**~~ ✅ — `state.md` 2024-06-13 <!-- anchor: docs/task_backlog.md#ベンチマークサマリー閾値伝播 -->
  - `run_daily_workflow.py` からの Webhook/閾値伝播と README 更新を完了。
- ~~**絶対パス整備と CLI テスト強化**~~ ✅ — `state.md` 2024-06-14 <!-- anchor: docs/task_backlog.md#絶対パス整備と-cli-テスト強化 -->
  - `run_daily_workflow.py` 最適化/状態アーカイブコマンドで絶対パスを使用するよう更新し、pytest で検証。

- ~~**インシデントリプレイテンプレート**~~（バックログ: `docs/task_backlog.md` → P1「インシデントリプレイテンプレート」） — `state.md` 2024-06-14, 2024-06-15, 2024-06-21 ✅ <!-- anchor: docs/task_backlog.md#p1-02-インシデントリプレイテンプレート -->
  - 期間指定リプレイ CLI の拡張は完了。Notebook (`analysis/incident_review.ipynb`) と `ops/incidents/` へのテンプレ整備を次イテレーションで着手可能。


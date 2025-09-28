# 次のアクション（目標指標達成フロー）

## 更新ルール
- タスクを完了したら、必ず `state.md` の該当項目をログへ移し、本ファイルのセクション（In Progress / Ready / Pending Review / Archive）を同期してください。
- `state.md` に記録されていないアクティビティは、このファイルにも掲載しない方針です。新しい作業を始める前に `state.md` へ日付と目的を追加しましょう。

## Ready 昇格チェックリスト
- `docs/progress_phase*.md`（特に対象フェーズの記録）を確認し、未完了の前提条件や検証ギャップがないかレビューする。
- 関連するランブック（例: `docs/state_runbook.md`, `docs/benchmark_runbook.md`）を再読し、必要なオペレーション手順が揃っているかを点検する。
- バックログ該当項目の DoD を最新化し、関係チームへ通知済みであることを確認する。

## Current Pipeline

### In Progress
- **ローリング検証パイプライン**（バックログ: `docs/task_backlog.md` → P1「ローリング検証 + 健全性モニタリング」） — `state.md` 2024-06-12, 2024-06-13, 2024-06-14, 2024-06-15, 2024-06-16
  - `scripts/run_benchmark_pipeline.py` の整備と `run_daily_workflow.py` 連携、期間指定リプレイ (`--start-ts` / `--end-ts`) の確認を継続中。
  - 次ステップ: ベンチマークランのローリング更新自動化と Sharpe / 最大 DD 指標の回帰監視強化。

### Ready
- **インシデントリプレイテンプレート**（バックログ: `docs/task_backlog.md` → P1「インシデントリプレイテンプレート」） — `state.md` 2024-06-14, 2024-06-15
  - 期間指定リプレイ CLI の拡張は完了。Notebook (`analysis/incident_review.ipynb`) と `ops/incidents/` へのテンプレ整備を次イテレーションで着手可能。

### Pending Review
- **ワークフロー統合ガイド**（バックログ: `docs/task_backlog.md` → 「ワークフロー統合」セクション） — `state.md` 2024-06-18
  - `docs/todo_next.md` と `state.md` の同期ルール追記を実施済み。レビューで運用フローへの適用可否を確認し、承認後に Archive へ移動する。

## Archive（達成済み）
- ~~**目標指数の定義**~~ ✅ — `state.md` 2024-06-01
  - `configs/targets.json` と `scripts/evaluate_targets.py` を整備済み。
- ~~**ウォークフォワード検証**~~ ✅ — `state.md` 2024-06-02, 2024-06-03
  - `scripts/run_walk_forward.py` を追加し、`analysis/wf_log.json` に窓別ログを出力。
- ~~**自動探索の高度化**~~ ✅ — `state.md` 2024-06-04
  - `scripts/run_optuna_search.py` で多指標目的の探索骨子を構築。
- ~~**運用ループへの組み込み**~~ ✅ — `state.md` 2024-06-05
  - `scripts/run_target_loop.py` による Optuna → run_sim → 指標計算 → 判定のループを実装。
- ~~**state ヘルスチェック**~~ ✅ — `state.md` 2024-06-11
  - `scripts/check_state_health.py` の警告生成・履歴ローテーション・Webhook テストを追加。
- ~~**ベースライン/ローリング run 起動ジョブ**~~ ✅ — `state.md` 2024-06-12
  - `scripts/run_benchmark_pipeline.py` と `tests/test_run_benchmark_pipeline.py` を整備し、runbook を更新。
- ~~**ベンチマークサマリー閾値伝播**~~ ✅ — `state.md` 2024-06-13
  - `run_daily_workflow.py` からの Webhook/閾値伝播と README 更新を完了。
- ~~**絶対パス整備と CLI テスト強化**~~ ✅ — `state.md` 2024-06-14
  - `run_daily_workflow.py` 最適化/状態アーカイブコマンドで絶対パスを使用するよう更新し、pytest で検証。

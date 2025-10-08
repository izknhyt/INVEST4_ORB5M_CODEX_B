# DoD チェックリスト テンプレート

- タスク名: <!-- 例: ローリング検証パイプライン -->
- バックログ ID / アンカー: <!-- 例: P1-01 / docs/task_backlog.md#p1-01-ローリング検証パイプライン -->
- 担当: <!-- 例: operator_name -->
- チェックリスト保存先: <!-- 例: docs/checklists/p1-01.md -->

## Ready 昇格チェック項目
- [ ] 高レベルのビジョンガイド（例: [docs/logic_overview.md](../logic_overview.md), [docs/simulation_plan.md](../simulation_plan.md)）を再読し、タスク方針が整合している。
- [ ] 対象フェーズの進捗ノート（例: `docs/progress_phase*.md`）を確認し、前提条件や未解決の検証ギャップがない。
- [ ] 関連ランブック（例: [docs/state_runbook.md](../state_runbook.md), [docs/benchmark_runbook.md](../benchmark_runbook.md)）を再読し、必要なオペレーション手順が揃っている。
- [ ] [docs/codex_quickstart.md](../codex_quickstart.md) / [docs/codex_workflow.md](../codex_workflow.md) の該当手順を確認し、アンカーやチェックリストの更新が必要か判断した。
- [ ] バックログ該当項目の DoD を最新化し、関係者へ共有済みである。

## バックログ固有の DoD
- [ ] <!-- バックログ DoD 1: 例) 90D ローリング指標を更新 -->
- [ ] <!-- バックログ DoD 2: 例) reports/benchmark_summary.json を再生成 -->
- [ ] <!-- 追加の検証/ドキュメント要件を列挙 -->

## 成果物とログ更新
- [ ] `state.md` の `## Log` へ完了サマリを追記した。
- [ ] [docs/todo_next.md](../todo_next.md) の該当エントリを Archive へ移動した。
- [ ] 関連コード/レポート/Notebook のパスを記録した。
- [ ] レビュー/承認者を記録した。

> テンプレートを複製したら、Ready 昇格チェックの状態と固有 DoD の達成状況を適宜更新してください。完了後は `docs/checklists/` フォルダへ保存し、関連タスクのドキュメントからリンクします。

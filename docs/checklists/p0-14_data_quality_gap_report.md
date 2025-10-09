# DoD チェックリスト — P0-14 Data quality gap reporting

- タスク名: Data quality gap reporting
- バックログ ID / アンカー: [P0-14](../task_backlog.md#p0-14-data-quality-gap-report)
- 担当: codex-operator
- チェックリスト保存先: docs/checklists/p0-14_data_quality_gap_report.md

## Ready 昇格チェック項目
- [x] [docs/logic_overview.md](../logic_overview.md) を再読し、データ監視の役割が整合している。
- [x] `docs/progress_phase1.md` を確認し、データ品質トリアージの前提条件に未完了項目がない。
- [x] [docs/state_runbook.md](../state_runbook.md) の該当節でデータ監査フローを確認し、更新が必要な箇所を把握した。
- [x] [docs/codex_quickstart.md](../codex_quickstart.md) / [docs/codex_workflow.md](../codex_workflow.md) のタスク同期手順を確認した。
- [x] [docs/task_backlog.md#p0-14-data-quality-gap-report](../task_backlog.md#p0-14-data-quality-gap-report) の DoD を定義し、関係者へ共有した。

## バックログ固有の DoD
- [x] `scripts/check_data_quality.py` に gap 詳細出力（missing rows estimate / aggregate metrics）を追加した。
- [x] `scripts/check_data_quality.py` に gap テーブルを外部ファイルへ書き出す CLI オプションを実装した。
- [x] 新しいメトリクスと CLI オプションをカバーする pytest を追加し、`python3 -m pytest` がグリーンである。
- [x] README などの利用ガイドへ新オプションの使い方と想定ワークフローを追記した。

## 成果物とログ更新
- [x] `state.md` の `## Log` へ完了サマリを追記した。
- [ ] [docs/todo_next_archive.md](../todo_next_archive.md) の該当エントリへ移し、`docs/todo_next.md` からは削除した。
- [ ] 生成物（JSON/CSV）の保存先や再現コマンドを記録した。
- [ ] レビュー/承認者を記録した。

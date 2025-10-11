# DoD チェックリスト — P4-02 異常系テスト自動化

- タスク名: P4-02 異常系テスト自動化
- バックログ ID / アンカー: [docs/task_backlog.md#p4-02-異常系テスト自動化](../task_backlog.md#p4-02-異常系テスト自動化)
- 担当: <!-- operator_name -->
- チェックリスト保存先: docs/checklists/p4-02_abnormal_tests.md

## Ready 昇格チェック項目
- [ ] [docs/simulation_plan.md](../simulation_plan.md) / [docs/progress_phase4.md](../progress_phase4.md) の異常系テスト項目を再読した。
- [ ] `docs/state_runbook.md#incident` と `docs/data_quality_ops.md` を確認し、想定するエラー対応フローを把握した。
- [ ] `tests/test_data_robustness.py` 既存ケースとフィクスチャを棚卸しし、カバレッジギャップを整理した。
- [ ] バックログの DoD / Notes を更新し、`docs/todo_next.md` の Ready セクションへ追記した。
- [ ] 必要なテンプレート・チェックリスト（例: ログテンプレ）を準備した。

## バックログ固有の DoD
- [ ] スプレッド急拡大、欠損バー、レイテンシ障害など主要異常パターンの pytest ケースを追加し、CI で常時実行できるようにした。
- [ ] 異常系再現用の CLI コマンドとデータ作成手順を `docs/state_runbook.md#incident` と `docs/progress_phase4.md` に記録した。
- [ ] エラー検知時に通知／ログへ残ることをテストで検証し、必要なガードを実装した。
- [ ] 実施テストコマンドと結果を `state.md` / PR 説明に記録した。

## 成果物とログ更新
- [ ] `state.md` の `## Log` へ完了サマリを追記した。
- [ ] [docs/todo_next_archive.md](../todo_next_archive.md) へ移動し、`docs/todo_next.md` から除外した。
- [ ] 更新したテストファイル・スクリプト・ドキュメントのパスを記録した。
- [ ] レビュー/承認者を記録した。

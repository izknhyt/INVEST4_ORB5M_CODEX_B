# P0-12 Codex-first Documentation Cleanup — DoD Checklist

- タスク名: Codex-first documentation cleanup
- バックログ ID / アンカー: [docs/task_backlog.md#p0-12-codex-first-documentation-cleanup](../task_backlog.md#p0-12-codex-first-documentation-cleanup)
- 担当: <!-- 例: operator_name -->
- チェックリスト保存先: docs/checklists/p0-12_doc_cleanup.md

## Ready 昇格チェック項目
- [x] [docs/logic_overview.md](../logic_overview.md) と [docs/simulation_plan.md](../simulation_plan.md) を再読し、ドキュメント導線が取る前提と一致している。
- [x] [docs/progress_phase0.md](../progress_phase0.md)〜[docs/progress_phase2.md](../progress_phase2.md) の Codex 関連履歴を確認し、再適用が必要なワークフロー更新が残っていない。
- [x] [docs/state_runbook.md](../state_runbook.md) と [docs/codex_workflow.md](../codex_workflow.md) の該当セクションを読み、更新予定のタッチポイントを把握した。
- [x] [docs/codex_quickstart.md](../codex_quickstart.md) で対象チェックリストのアンカーとコマンド例が最新か確認し、必要な修正範囲をメモした。
- [x] `docs/task_backlog.md` の当該エントリにメモ欄を設け、成果物リンク・想定アップデートを記録した。

## バックログ固有の DoD
- [x] README の "ドキュメントハブ" と [docs/documentation_portal.md](../documentation_portal.md) のテーブルが Quickstart / Workflow / State Runbook の説明と一致し、リンクが双方で往復できる。
- [x] [docs/codex_quickstart.md](../codex_quickstart.md) / [docs/codex_workflow.md](../codex_workflow.md) / [docs/state_runbook.md](../state_runbook.md) の参照順序と代表コマンドが一致し、Portal の "Documentation Hygiene Checklist" と整合する。
- [x] [docs/todo_next.md](../todo_next.md)・`state.md`・[docs/task_backlog.md](../task_backlog.md) のアンカー/タスク名称が同期されていることを確認し、差異があれば同じコミットで補正した。
- [x] 新規または改訂したランブック/テンプレートを README・Portal・バックログから辿れるようリンクを追加し、重複説明を統合した。
- [x] ドキュメント更新時に参照される CLI (`python3 scripts/manage_task_cycle.py`, `python3 -m pytest` など) の使用例が README / Quickstart / Workflow で一致している。

## 成果物とログ更新
- [x] `state.md` の `## Log` に完了サマリと実行コマンドを英語で追記し、`## Next Task` の該当項目を整理した。
- [ ] [docs/todo_next.md](../todo_next.md) から当該タスクをアーカイブへ移し、[docs/todo_next_archive.md](../todo_next_archive.md) に成果リンクを残した。
- [x] `docs/task_backlog.md` の進捗メモへ実装した変更と参照ドキュメントのリンクを追加した。
- [x] PR / コミットメッセージで更新したドキュメント一覧と検証コマンドを共有した。

> P0-12 の DoD を満たしたら、本チェックリストをアーカイブせずに保守し、後続セッションが同じ基準で確認できるよう更新履歴を残してください。

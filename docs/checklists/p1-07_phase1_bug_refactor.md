# DoD チェックリスト — フェーズ1 バグチェック & リファクタリング運用整備

- チェックリスト保存先: docs/checklists/p1-07_phase1_bug_refactor.md
- バックログ: [docs/task_backlog.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備](../task_backlog.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備)
- 関連テンプレ: [docs/templates/dod_checklist.md](../templates/dod_checklist.md), [docs/templates/next_task_entry.md](../templates/next_task_entry.md)

> Ready 昇格チェックと固有 DoD は進捗に応じて更新し、完了後は関連ドキュメントから本チェックリストへリンクしてください。

## Ready 昇格チェック
- [ ] `state.md` / `docs/todo_next.md` に本タスクのテンプレートブロックを作成し、アンカーと Pending Questions を設定済み。
- [ ] `docs/codex_workflow.md` / `docs/state_runbook.md` の該当手順を再読し、既存ワークフローと矛盾しないことを確認した。
- [ ] フェーズ1の既存成果 (`docs/progress_phase1.md`) とバグ調査ログ (`ops/incidents/` など) を確認し、抜け漏れがないか把握した。

## バグチェック観点の整備
- [ ] 調査対象ごとのチェックボード（例: `module`, `観点`, `確認状況`, `発見メモ`) を Markdown テーブルで作成し、未着手/進行中/完了を追跡できるようにした。
- [ ] 既存テストカバレッジと CLI ドライランの再現手順を一覧化し、各観点から参照できるリンクを追加した。
- [ ] `scripts/manage_task_cycle.py` を用いた進捗ログ更新手順を明文化し、調査開始前の `--dry-run start-task` 例を残した。

## リファクタリング計画テンプレート
- [ ] リファクタリング候補を「影響範囲」「期待効果」「リスク」「リグレッションテスト」の列で整理するテンプレートを追加した。
- [ ] カバレッジ不足時に追加するテスト種別（ユニット / 統合 / CLI / データスナップショット）を明示したチェックボックスを用意した。
- [ ] 変更後に更新すべきドキュメント（README / runbook / チェックリスト / incident ノート等）を列挙し、リンクを追記した。

## 運用フロー連携
- [ ] `docs/task_backlog.md` に本タスクの DoD とテンプレートリンクを追加し、優先度/前提条件を明示した。
- [ ] `docs/todo_next.md` の Ready または In Progress セクションへ項目を追加し、実装チームが次セッションで着手しやすい状態にした。
- [ ] `state.md` に本タスクを参照するノートを追記し、進捗ログとの同期手順を示した。

## 実行時チェック（サイクルごとに繰り返し）
- [ ] 調査対象ごとに `再現 → 原因分析 → 回避策/修正案 → 検証手順 → ドキュメント更新` のチェックを行い、未完了項目には Pending Questions を設定した。
- [ ] 進捗を `docs/checklists/p1-07_phase1_bug_refactor.md` 内のテーブル/チェックボックスへ逐次反映し、次セッションが継続できるようにした。
- [ ] CLI / pytest 実行コマンドと結果要約を `state.md` のメモに記録し、フォローアップが必要な場合は `docs/todo_next.md` へ転記した。

## クローズ条件
- [ ] 主要バグ観点（実行系、戦略ロジック、データパイプライン、ドキュメントギャップ）について調査完了/未解決/フォローアップのステータスが整理され、`docs/todo_next.md` へリンクされている。
- [ ] リファクタリング候補リストに優先度付けと担当候補が記載され、次フェーズ以降に引き継ぐための TODO が残っていない。
- [ ] 本チェックリストをすべて更新し、`docs/task_backlog.md` / `docs/todo_next.md` / `state.md` の該当エントリを Archive/Log へ移動した。

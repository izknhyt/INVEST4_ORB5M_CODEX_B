# P0-13 Data quality audit enhancements — DoD Checklist

- タスク名: Data quality audit enhancements
- バックログ ID / アンカー: [P0-13](../task_backlog.md#p0-13-data-quality-audit)
- 担当: codex_operator
- チェックリスト保存先: docs/checklists/p0-13_data_quality_audit.md

## Ready 昇格チェック項目
- [x] [docs/logic_overview.md](../logic_overview.md) を再読し、データ品質監視の役割と期待値を確認した。
- [x] [docs/progress_phase0.md](../progress_phase0.md) / [docs/progress_phase1.md](../progress_phase1.md) の関連メモを確認し、前提となるデータ検証手順に未解決事項がないことを確認した。
- [x] [docs/state_runbook.md](../state_runbook.md) のデータ監視/日次ジョブ手順を再読し、CLI 更新時の運用インパクトを把握した。
- [x] [docs/codex_quickstart.md](../codex_quickstart.md) / [docs/codex_workflow.md](../codex_workflow.md) の該当手順を確認し、アンカーや参照先の更新が不要であることを確認した。
- [x] [docs/task_backlog.md](../task_backlog.md) の DoD を追加タスク内容に合わせて更新し、関係者へ共有した。

## バックログ固有の DoD
- [x] `scripts/check_data_quality.py` へカバレッジ統計（row_count, unique_timestamps, start/end, gap_count, max_gap_minutes, coverage_ratio, monotonic_errors）を追加した。
- [x] CLI に `--out-json` オプションを追加し、構造化サマリをファイル出力できるようにした。
- [x] 新フィールドと CLI オプションを回帰する pytest (`tests/test_check_data_quality.py`) を実装し、CSV フィクスチャを生成するテストヘルパーを整備した。
- [x] サマリ出力の後方互換性（標準出力の辞書表記）が維持されていることを確認した。

## 成果物とログ更新
- [x] `state.md` の `## Work State Log` へ完了サマリを追記した。
- [x] `docs/todo_next.md` の該当エントリを Pending Review へ更新し、アーカイブ移行はレビュー完了時に実施する。
- [x] テストコマンド (`python3 -m pytest`) を記録し、PR 概要で報告した。
- [x] バックログ (`docs/task_backlog.md`) の進捗メモを更新し、関連ドキュメントへのリンクを残した。

> チェック完了後は、Ready→In Progress→Pending Review の流れを `docs/todo_next.md` と `state.md` で同期してください。

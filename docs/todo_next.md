# 次のアクション（目標指標達成フロー）

## 更新ルール
- タスクを完了したら、必ず `state.md` の該当項目をログへ移し、本ファイルのセクション（In Progress / Ready / Pending Review / Archive）を同期してください。
- `state.md` に記録されていないアクティビティは、このファイルにも掲載しない方針です。新しい作業を始める前に `state.md` へ日付と目的を追加しましょう。
- フローの全体像は [docs/codex_quickstart.md](./codex_quickstart.md) / [docs/codex_workflow.md](./codex_workflow.md) を参照し、アンカーの整合チェックを忘れずに。
- Ready または In Progress へ昇格させるタスクは、[docs/templates/dod_checklist.md](./templates/dod_checklist.md) を複製し `docs/checklists/<task-slug>.md` へ保存したうえで、該当エントリからリンクするか貼り付けてください。

## Ready 昇格チェックリスト
- [ ] ビジョンガイド（例: [docs/logic_overview.md](./logic_overview.md), [docs/simulation_plan.md](./simulation_plan.md)）を再読し、昇格候補タスクが最新方針と整合していることを確認した。
- [ ] 対象フェーズの記録（`docs/progress_phase*.md`）を確認し、未完了の前提条件や検証ギャップが無い。
- [ ] 関連ランブック（例: `docs/state_runbook.md`, `docs/benchmark_runbook.md`）の手順が最新であることを確認した。
- [ ] バックログ該当項目の DoD / 進捗メモを更新し、関係者へ通知済みである。
- [ ] [docs/templates/dod_checklist.md](./templates/dod_checklist.md) を複製し、Ready 昇格タスクのチェックボックス管理を整備した。

## Current Pipeline

### In Progress



### On Hold

- Monitor for the first production `data_quality_failure` alert to validate the acknowledgement workflow once live signals begin flowing. (P0 ops loop paused until production data triggers an alert.)
### Ready

- [P3 Observability automation kickoff](./task_backlog.md#p3-観測性・レポート自動化) — Define scope for initial automation (signal latency sampling cadence, weekly report webhook payload sketch, dashboard data export checklist) so implementation can start once P2 deliverables stabilise.



### Pending Review

- [P2-03 Portfolio evaluation regression automation](./task_backlog.md#p2-03-portfolio-evaluation-regression-automation) — Router snapshot / portfolio summary pytest coverage landed (`tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics` 等)。ドキュメントとチェックリスト更新を確認してレビューする。
  - レビュワー側で `docs/logic_overview.md` / `docs/observability_dashboard.md` / `docs/checklists/p2_portfolio_evaluation.md` の差分確認と、`python3 -m pytest` / `python3 scripts/validate_portfolio_samples.py` 再実行ログの取得がまだ揃っていないため、DoD の「レビュー完了」チェックが保留になっている。
- レビュー中のタスクを再開する際は `scripts/manage_task_cycle.py --doc-section Pending Review` を用いると、`docs/todo_next.md` の配置を維持したまま `state.md` のテンプレートを再適用できる。

## Archive（達成済み）

> 過去の達成済みログは [docs/todo_next_archive.md](./todo_next_archive.md) に集約しました。履歴が必要な場合はアーカイブファイルを参照してください。
> `manage_task_cycle` のアンカープレースホルダのみ下記に残しています（削除しないでください）。

<!-- manage_task_cycle archive placeholder -->
✅ <!-- anchor placeholder to satisfy manage_task_cycle start-task detection -->
- <!-- docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化 -->
  - DoD チェックリスト: [docs/templates/dod_checklist.md](./templates/dod_checklist.md) を [docs/checklists/p2_manifest.md](./checklists/p2_manifest.md) にコピーし、進捗リンクを更新する。
- 2026-06-12: Closed [P0-15 Data quality alert operations loop](./task_backlog.md#p0-15-data-quality-alert-ops) via simulated coverage failure, acknowledgement log entry (`scripts/record_data_quality_alert.py`), docs/data_quality_ops.md update, and full pytest run。
- 2026-06-13: Completed [P0-16 Data quality acknowledgement input validation](./task_backlog.md#p0-16-data-quality-ack-validation) by hardening the CLI against malformed ratios/timestamps, documenting the guardrails, and extending regression coverage.

# DoD チェックリスト — P4-01 長期バックテスト改善

- タスク名: P4-01 長期バックテスト改善
- バックログ ID / アンカー: [docs/task_backlog.md#p4-01-長期バックテスト改善](../task_backlog.md#p4-01-長期バックテスト改善)
- 担当: <!-- operator_name -->
- チェックリスト保存先: docs/checklists/p4-01_long_backtest.md

## Ready 昇格チェック項目
- [x] [docs/simulation_plan.md](../simulation_plan.md) / [docs/progress_phase4.md](../progress_phase4.md) の該当セクションを再読し、長期バックテストの目的と現在の課題を把握した。
- [x] `docs/state_runbook.md#backtest` を確認し、再現コマンドと artefact 管理手順が最新であることを確認した。
- [x] `docs/task_backlog.md#p4-01-長期バックテスト改善` の DoD と進捗メモを最新化し、関係者へ共有した。
- [ ] `docs/codex_quickstart.md` / `docs/codex_workflow.md` の更新が不要か確認した。
- [x] `docs/todo_next.md` の In Progress セクションへ本タスクを追加した。

## バックログ固有の DoD
- [ ] Conservative / Bridge それぞれ 2018–2025 通しランを最新データで再実行し、`reports/long_{mode}.json`・`reports/long_{mode}_daily.csv` を更新した。
- [ ] パラメータ調整またはガード変更を行い、Sharpe・最大DD・年間勝率がリリース基準を満たすことを確認した。
- [ ] 変更内容と再現コマンドを `docs/progress_phase4.md` に追記し、`state.md` の `## Log` に成果サマリを残した。
- [ ] 実施した検証コマンド（例: `python3 scripts/run_sim.py ...`, `python3 -m pytest tests/test_run_sim_cli.py`）を PR / state へ記録した。

## 成果物とログ更新
- [ ] `state.md` の `## Log` へ完了サマリを追記した。
- [ ] [docs/todo_next_archive.md](../todo_next_archive.md) へ移動し、`docs/todo_next.md` から除外した。
- [ ] 更新した artefact パス（例: `reports/long_conservative.json`）を記録した。
- [ ] レビュー/承認者を記録した。

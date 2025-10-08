# Codex Quickstart (1ページ)

Codex オペレータが 1 セッションで追従すべき流れを 1 ページに圧縮しました。詳細な運用メモは [docs/codex_workflow.md](codex_workflow.md) および [docs/state_runbook.md](state_runbook.md) を参照してください。

## 1. セッション前にやること
- `state.md` → `## Next Task` を確認し、担当タスクと未解決メモを把握する。
- `docs/task_backlog.md` の該当アンカーで DoD と優先度を再確認する。
- `docs/todo_next.md` で同じアンカーが `Ready` / `In Progress` のどちらにあるか確認し、必要なら `scripts/manage_task_cycle.py --dry-run start-task ...` で昇格を検証する。
- 追加の依存や承認が必要な場合は `state.md` に背景と想定コマンドを記録し、Sandbox 制約をレビューする。

## 2. 作業ループ（反復）
1. **設計を確認** — 関連する README / ランブック / チェックリストを開き、影響範囲をメモする。
2. **小さい差分で実装** — ファイルごとにコミット準備し、必要に応じて `python3 -m pytest -k <selector>` などのスモークテストを実行。
3. **ドキュメント即時更新** — 仕様変更や運用手順を触ったら同じブランチ内で `docs/` を更新し、DoD の根拠を残す。
4. **状態同期** — `state.md` と `docs/todo_next.md` に進捗メモを追記し、アンカーがズレていないか確認する。

> 迷ったら `scripts/manage_task_cycle.py --help` を実行して、`record` / `promote` / `complete` の呼び出し順序を確認する。

## 3. セッションを閉じるとき
- 変更をレビュー → `git status` / `git diff` で不要ファイルが無いか確認。
- テスト証跡を整理 → 実行したコマンドを `state.md` ログとコミットメッセージに記録。
- `scripts/manage_task_cycle.py --dry-run finish-task --anchor <docs/task_backlog.md#...>` で close-out をプレビューし、問題なければ `--dry-run` を外して適用。
- `docs/todo_next.md` の該当ブロックを [docs/todo_next_archive.md](todo_next_archive.md) へ移動し、`README.md` / ランブックのリンクが最新であることを確認。

## 4. よく使うコマンド
| 目的 | コマンド例 |
| --- | --- |
| Ready → In Progress 昇格（確認） | `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` |
| タスク完了の確認 | `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` |
| 代表的なテスト | `python3 -m pytest tests/test_run_sim_cli.py` / `python3 -m pytest tests/test_runner.py` |
| フルテスト | `python3 -m pytest` |

## 5. ドキュメントリンク
- **詳細ワークフロー:** [docs/codex_workflow.md](codex_workflow.md)
- **state 運用・チェックリスト詳細:** [docs/state_runbook.md](state_runbook.md)
- **優先順位と DoD:** [docs/task_backlog.md](task_backlog.md)
- **近々のアクションメモ:** [docs/todo_next.md](todo_next.md)
- **開発ロードマップ:** [docs/development_roadmap.md](development_roadmap.md)

---
このクイックスタートの要点は `README.md` の Codex セクションにも要約しています。更新時は README / ランブック / テンプレートのアンカーを同じコミットで揃えてください。

# Codex Quickstart (1ページ)

Codex オペレータが 1 セッションで辿るべき流れを、チェックリスト主体で 1 ページにまとめました。詳細ガイドや補足テンプレートは [docs/codex_workflow.md](codex_workflow.md) / [docs/state_runbook.md](state_runbook.md) を参照してください。

## 1. セッション前チェック
- [ ] [docs/documentation_portal.md](documentation_portal.md) を開き、関連ランブックや設計ドキュメントの位置を確認する。
- [ ] `state.md` → `## Next Task` の担当タスクと Pending Questions を確認する。
- [ ] [docs/task_backlog.md](task_backlog.md) で該当アンカーの DoD / 進捗ノートを再確認する。
- [ ] [docs/todo_next.md](todo_next.md) でアンカー位置（Ready / In Progress / Pending Review）を確認し、必要なら `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` で昇格手順をプレビューする。
- [ ] 追加の承認や依存がある場合は `state.md` に背景・想定コマンドを記載し、[docs/codex_cloud_notes.md](codex_cloud_notes.md) で Sandbox 制約を再確認する。

## 2. 実装ループ（反復）
| ステップ | アクション | 参照 |
| --- | --- | --- |
| 1. 設計レビュー | README / ランブック / チェックリストで影響範囲を洗い出し、必要なテストや出力ファイルをメモする。 | [docs/codex_workflow.md](codex_workflow.md#pre-session-routine) |
| 2. 小さく実装 | 差分を細かく区切り、影響単位で `python3 -m pytest -k <selector>` 等のテストを即時実行する。 | [docs/codex_workflow.md](codex_workflow.md#session-loop-detail) |
| 3. ドキュメント即時更新 | 仕様や運用手順を変えたら同じブランチで `docs/` を更新し、DoD の根拠を残す。 | [docs/codex_workflow.md](codex_workflow.md#change-sync) |
| 4. 状態同期 | `state.md` と `docs/todo_next.md` に進捗を追記し、アンカーが揃っているか確認する。 | [docs/codex_workflow.md](codex_workflow.md#change-sync) |

> `python3 scripts/manage_task_cycle.py --help` を実行すると、`record` / `promote` / `complete` の順序を即座に確認できます。

## 3. Wrap-up（セッション終了）
- [ ] `git status` / `git diff` で不要ファイルや差分漏れが無いか確認する。
- [ ] 実行したテストコマンドを `state.md` のログとコミットメッセージに記録する。
- [ ] `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <docs/task_backlog.md#...>` で close-out をプレビューし、問題なければ `--dry-run` を外して適用する。
- [ ] `docs/todo_next.md` のブロックを [docs/todo_next_archive.md](todo_next_archive.md) へ移し、README / ランブックのリンクが最新か再確認する。

## 4. 代表コマンド
| 目的 | コマンド例 |
| --- | --- |
| Ready → In Progress 昇格（確認） | `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` |
| Ready → In Progress 昇格（適用） | `python3 scripts/manage_task_cycle.py start-task --anchor <...>` |
| タスク完了（確認） | `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` |
| タスク完了（適用） | `python3 scripts/manage_task_cycle.py finish-task --anchor <...>` |
| 代表的なテスト | `python3 -m pytest tests/test_run_sim_cli.py` / `python3 -m pytest tests/test_runner.py` |
| フルテスト | `python3 -m pytest` |

## 5. 関連ドキュメント
- [docs/codex_workflow.md](codex_workflow.md) — 詳細ワークフロー、テンプレ利用手順、Sandbox ガードレール。
- [docs/state_runbook.md](state_runbook.md) — state 保存/復元・インシデントリプレイのアクションチェックリスト。
- [docs/task_backlog.md](task_backlog.md) — 優先順位と DoD。進捗メモもここに集約。
- [docs/todo_next.md](todo_next.md) — 直近の作業キュー。`manage_task_cycle` で同期。
- [docs/development_roadmap.md](development_roadmap.md) — 即応〜中期の改善計画。

---
このクイックスタートは `README.md` の Codex セクションと常に同期させます。内容を更新した場合は README / ランブック / テンプレートのアンカーも同じコミットで調整してください。

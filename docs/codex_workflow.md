# Codex Session Operations Guide

One-page の流れは [docs/codex_quickstart.md](codex_quickstart.md) に集約しています。本ガイドはクイックスタートで触れた各ステップを深掘りし、アンカー/テンプレート/スクリプトの使い分けを整理した詳細版です。

## このガイドの使い方
- **まずクイックスタートを確認** — `state.md`・`docs/task_backlog.md`・`docs/todo_next.md` の同期手順はクイックスタートで概観できます。
- **作業前の再読ポイント** — 影響するランブック（例: `docs/state_runbook.md` / `docs/benchmark_runbook.md`）と該当チェックリストを開いた状態で着手する。
- **作業後のクロスチェック** — `README.md` の Codex セクションと本ドキュメントの記述が揃っているかを確認し、差異があれば同じコミットで修正する。

## Quickstart の補足
クイックスタートの 3 ステップ（準備 → 実装ループ → Wrap-up）を以下の観点から補足します。

1. **準備**
   - `state.md` と `docs/todo_next.md` のアンカーが一致しているか確認し、ズレていたら `scripts/manage_task_cycle.py --dry-run start-task ...` で出力をチェックしてから整合させる。
   - Ready から In Progress へ引き上げる場合は、DoD チェックリストを `docs/checklists/<task>.md` に配置し、リンクを `docs/todo_next.md` に追加する。
2. **実装ループ**
   - テストは最小単位で即時に実行する（例: CLI を触ったら `python3 -m pytest tests/test_run_sim_cli.py`）。
   - 仕様変更に伴うドキュメント更新は「同じ PR / コミット内で完結」が原則。特にランブックと README の差異が残らないよう注意する。
   - 進捗を `state.md` と `docs/todo_next.md` の両方に書く。クイックスタートに記載した順番（state → todo）を守ると `manage_task_cycle` でも衝突しない。
3. **Wrap-up**
   - `scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` で close-out を確認し、出力が `sync_task_docs.py complete` の呼び出しになっているか見る。
   - `docs/task_backlog.md` の該当項目に進捗ノートを追加し、完了した場合はバックログから削除する。DoD が残っている場合は未完了扱いにする。

## Session Loop（詳細）

### <a id="pre-session-routine"></a>1. Pre-session routine
- `state.md` → `## Next Task` のメモ・Pending Questions・承認待ちを確認。
- `docs/task_backlog.md` の DoD と進捗ノートを読み、達成条件・レビュー観点を共有理解にする。
- テンプレ適用:
  - `docs/templates/next_task_entry.md` → `state.md` の追記に使用。
  - `docs/templates/dod_checklist.md` → `docs/checklists/<task-slug>.md` として保存。
- Sandbox 条件（ファイル書き込み/ネットワーク/承認フロー）を `docs/codex_cloud_notes.md` で再確認する。

### 2. While implementing
- **優先順位:** P0 → P1 → P2 の順で対応。新しい課題が見つかったら backlog に登録してから着手する。
- **スコープ管理:** 大規模変更は feature flag を利用し、`README.md` と該当ランブックにフラグ利用手順を残す。
- **承認ログ:** 依頼した承認内容（コマンド・目的・結果）を `state.md` に追記。
- **データプロダクト:** `runs/` / `reports/` / `ops/` など成果物を触る場合はコミットメッセージに再現コマンドを記録。

### 3. Wrap-up
- `state.md` → `## Log` にセッション結果を追記し、`## Next Task` から完了したタスクを除外。
- `docs/todo_next.md` の該当ブロックを [docs/todo_next_archive.md](docs/todo_next_archive.md) へ移動し、アンカーコメント（`<!-- anchor: ... -->`）が残っているか確認。
- `docs/task_backlog.md` の対象項目にリンクやノートを追加する。完了済みなら該当タスクを打ち消し線で囲み、進捗メモを最終ログとして残す。
- テスト証跡（実行コマンド）はコミットメッセージと PR テンプレの両方に記録する。

## Sandbox & Approval Guardrails
- 既定のハーネスは `workspace-write` / `restricted` / approvals `on-request`。
- 以下の操作は事前承認が必要: 追加パッケージのインストール、外部 API 呼び出し、リポジトリ外書き込み、破壊的な git 操作再実行。
- 承認リクエストは `state.md` へ「背景・想定コマンド・結果」を記録。
- Read-only 環境ではパッチ提案に切り替え、触ったファイルと手順を明示する。

## Command Cheatsheet

| 目的 | コマンド |
| --- | --- |
| Ready 昇格（プレビュー） | `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` |
| Ready 昇格（適用） | `python3 scripts/manage_task_cycle.py start-task --anchor <...>` |
| Ready → In Progress のみ | `python3 scripts/manage_task_cycle.py promote --anchor <...>` |
| タスク完了（プレビュー） | `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` |
| タスク完了（適用） | `python3 scripts/manage_task_cycle.py finish-task --anchor <...>` |
| 手動同期（record/promote/complete） | `python3 scripts/sync_task_docs.py <subcommand> ...` |
| 代表的な pytest | `python3 -m pytest tests/test_run_sim_cli.py` / `python3 -m pytest tests/test_runner.py` |
| フルテスト | `python3 -m pytest` |

### Finish-task dry-run example

```bash
python3 scripts/manage_task_cycle.py --dry-run finish-task \
    --anchor docs/task_backlog.md#codex-session-operations-guide \
    --date 2026-02-14 \
    --note "Captured finish-task dry-run sample for documentation"
```

プレビューでは `sync_task_docs.py complete` がエコーされ、副作用なくコマンドを確認できます。問題なければ `--dry-run` を外して実行してください。

## <a id="doc-section-options"></a>Doc Section Options

`--doc-section` フラグで `docs/todo_next.md` の挿入先を制御します。

| `--doc-section` 値 | 挿入先 | 使いどころ |
| --- | --- | --- |
| `Ready` | `## Ready` | 受付待ちタスクを登録するとき。
| `In Progress` | `### In Progress` | 現在進行中のメモを更新するとき。
| `Pending Review` | `### Pending Review` | レビュー待ちの共有や再開時に利用。

既存アンカーを持つタスクを再開する際は必ず `--dry-run` で確認し、重複が出る場合はアンカーコメントを修正してから再実行します。

## Reference Map
- `docs/codex_quickstart.md` — 1 ページの流れ、セッション全体のチェックリスト。
- `docs/state_runbook.md` — state 保存/復元とインシデント運用の詳細な手順。
- `docs/task_backlog.md` — 優先順位付きタスク一覧と DoD。
- `docs/todo_next.md` — 直近の作業キューとメモ。
- `docs/codex_cloud_notes.md` — Sandbox/承認フローの補足。
- `docs/development_roadmap.md` — 即応〜中期の改善方針。
- `docs/checklists/*` — タスク固有の DoD。Ready 昇格時にリンクを設定する。

クイックスタートと本ガイドを常に同期させ、手順の乖離が生じた場合は最優先で修正してください。

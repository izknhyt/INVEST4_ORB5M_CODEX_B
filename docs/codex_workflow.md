# Codex Session Operations Guide

1 ページ版の流れは [docs/codex_quickstart.md](codex_quickstart.md) に集約されています。本ガイドではクイックスタートの各ステップを深掘りし、テンプレート・スクリプト・ランブックの使い分けを整理します。

## ガイド活用法
- **ドキュメントハブで位置関係を確認** — [docs/documentation_portal.md](documentation_portal.md) の Orientation Cheat Sheet でランブック / チェックリスト / バックログの役割を把握してから作業に入る。
- **まずクイックスタートを参照** — `state.md` / `docs/task_backlog.md` / `docs/todo_next.md` の同期手順と優先度はクイックスタートで俯瞰できます。
- **作業前の再読ポイント** — 影響するランブック（例: `docs/state_runbook.md`, `docs/benchmark_runbook.md`）と該当チェックリストを開いた状態で着手する。
- **作業後のクロスチェック** — README の Codex 節と本ドキュメントの内容が整合しているか確認し、差異があれば同じコミットで修正する。

## Quickstart 補足
クイックスタートの 3 ステップ（準備 → 実装ループ → Wrap-up）を、実務で迷いやすい観点から補足します。

### 1. 準備フェーズ
- `state.md` と `docs/todo_next.md` のアンカー一致を確認。ズレていたら `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` で整合をプレビュー。
- Ready → In Progress 昇格時は [docs/templates/dod_checklist.md](templates/dod_checklist.md) を複製して `docs/checklists/<task>.md` に保存し、アンカーから参照する。
- Sandbox 条件や承認要否は [docs/codex_cloud_notes.md](codex_cloud_notes.md) を再読し、必要な背景・想定コマンドを `state.md` に残す。

### 2. 実装ループ
- CLI やロジックを触った直後に `python3 -m pytest -k <selector>` 等のスモークを即実行し、差分の粒度を小さく保つ。
- 仕様変更と同じコミットで README / ランブックを更新し、DoD の根拠がバックログやチェックリストに残るようリンクを追加する。
- 進捗メモは `state.md` → `docs/todo_next.md` の順で記録。`manage_task_cycle` からの自動更新と競合しないよう順序を固定する。

### 3. Wrap-up
- `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` で close-out をプレビューし、`sync_task_docs.py complete` が呼ばれることを確認する。
- `docs/task_backlog.md` の該当項目に進捗リンクを追加し、完了なら打ち消し線でアーカイブ化。未達成の DoD があれば進行中のまま残す。

## <a id="pre-session-routine"></a>Session Loop（詳細）

### 1. Pre-session routine
- `state.md` → `## Next Task` の Pending Questions / 承認待ちを確認。
- [docs/task_backlog.md](task_backlog.md) の DoD / 進捗ノートでレビュー観点を共有理解にする。
- テンプレ適用:
  - [docs/templates/next_task_entry.md](templates/next_task_entry.md) — `state.md` や `docs/todo_next.md` への新規エントリ。
  - [docs/templates/dod_checklist.md](templates/dod_checklist.md) — `docs/checklists/<task-slug>.md` として複製。
- Sandbox 条件（ファイル書き込み / ネットワーク / 承認フロー）は [docs/codex_cloud_notes.md](codex_cloud_notes.md) で再確認。

### <a id="session-loop-detail"></a>2. While implementing
- **優先順位:** P0 → P1 → P2 の順で着手。新しい課題は backlog に登録してから対応する。
- **スコープ管理:** 大規模変更は feature flag で段階投入し、README / ランブックにフラグ利用手順を追記する。
- **承認ログ:** 依頼した承認内容（コマンド・目的・結果）を `state.md` に明記し、後続セッションが追跡できるようにする。
- **データ成果物:** `runs/`・`reports/`・`ops/` などを更新した場合は再現コマンドをコミットメッセージと PR に記録する。

### 3. Wrap-up
- `state.md` → `## Log` にセッション結果を追記し、`## Next Task` から完了項目を除外。
- `docs/todo_next.md` の該当ブロックを [docs/todo_next_archive.md](todo_next_archive.md) へ移動し、アンカーコメント（`<!-- anchor: ... -->`）が残っているか確認。
- `docs/task_backlog.md` の対象項目にリンク/ノートを追加し、完了時は打ち消し線でアーカイブ化。
- テスト証跡（実行コマンド）はコミットメッセージと PR テンプレ双方に残す。

## <a id="change-sync"></a>Change sync & ドキュメント整備
- ドキュメント内リンクはリポジトリ基準の相対パス（例: `./codex_quickstart.md`, `checklists/<task>.md`）へ統一し、`rg '\]\(docs/' docs` で誤った `docs/docs` リンクが無いか確認する。
- `docs/todo_next.md` / `state.md` は `manage_task_cycle` かテンプレートを利用して編集し、手動編集時はアンカーコメントを削除しない。
- README・ランブック・テンプレートで同じ内容を扱う場合、差分が出たセクションに「更新日」「再確認ポイント」を併記し、次回の再レビューを容易にする。
- 新しいチェックリストやテンプレを追加した場合は、`docs/checklists/` 配下のガイドとバックログ DoD を同じコミットで更新する。

## Sandbox & Approval Guardrails
- 既定ハーネス: `workspace-write` / `restricted` / approvals `on-request`。
- 事前承認が必要な操作: 追加パッケージのインストール、外部 API 呼び出し、リポジトリ外書き込み、破壊的な git 操作再実行。
- 承認リクエストは `state.md` へ「背景・想定コマンド・結果」を記録し、後続セッションへ引き継ぐ。
- Read-only 環境ではパッチ提案へ切り替え、触ったファイルと手順を必ず共有する。

## Command Cheatsheet

| 目的 | コマンド |
| --- | --- |
| Ready 昇格（プレビュー） | `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` |
| Ready 昇格（適用） | `python3 scripts/manage_task_cycle.py start-task --anchor <...>` |
| Ready → In Progress のみ | `python3 scripts/manage_task_cycle.py promote --anchor <...>` |
| タスク完了（プレビュー） | `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` |
| タスク完了（適用） | `python3 scripts/manage_task_cycle.py finish-task --anchor <...>` |
| 手動同期 | `python3 scripts/sync_task_docs.py <record|promote|complete> ...` |
| 代表的な pytest | `python3 -m pytest tests/test_run_sim_cli.py` / `python3 -m pytest tests/test_runner.py` |
| フルテスト | `python3 -m pytest` |

### Finish-task dry-run example

```bash
python3 scripts/manage_task_cycle.py --dry-run finish-task \
    --anchor docs/task_backlog.md#codex-session-operations-guide \
    --date 2026-02-14 \
    --note "Captured finish-task dry-run sample for documentation"
```

プレビューでは `sync_task_docs.py complete` がエコーされ、副作用なくコマンド内容を確認できます。問題なければ `--dry-run` を外して実行してください。

## <a id="doc-section-options"></a>Doc Section Options

`--doc-section` フラグで [docs/todo_next.md](todo_next.md) の挿入先を制御します。

| `--doc-section` 値 | 挿入先 | 使いどころ |
| --- | --- | --- |
| `Ready` | `## Ready` | 受付待ちタスクの登録。
| `In Progress` | `### In Progress` | 進行中タスクの更新。
| `Pending Review` | `### Pending Review` | レビュー待ちタスクや共有事項の保持。

既存アンカーを持つタスクを再開するときは必ず `--dry-run` で確認し、重複が発生する場合はアンカーコメントを調整してから再実行します。

## Reference Map
- [docs/codex_quickstart.md](codex_quickstart.md) — 1 ページの流れ、セッション全体のチェックリスト。
- [docs/state_runbook.md](state_runbook.md) — state 保存/復元とインシデント運用のアクション指針。
- [docs/task_backlog.md](task_backlog.md) — 優先タスクと DoD の中枢。
- [docs/todo_next.md](todo_next.md) — 直近の作業キューと Pending Questions。
- [docs/codex_cloud_notes.md](codex_cloud_notes.md) — Sandbox / 承認フローの補足。
- [docs/development_roadmap.md](development_roadmap.md) — 即応〜中期の改善方針。
- [docs/checklists/*](checklists) — タスク固有の DoD。Ready 昇格時にリンクを貼る。

クイックスタートと本ガイドを常に同期させ、手順の乖離が生じた場合は最優先で修正してください。

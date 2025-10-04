# DoD チェックリスト — フェーズ1 バグチェック & リファクタリング運用整備

- チェックリスト保存先: docs/checklists/p1-07_phase1_bug_refactor.md
- バックログ: [docs/task_backlog.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備](../task_backlog.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備)
- 関連テンプレ: [docs/templates/dod_checklist.md](../templates/dod_checklist.md), [docs/templates/next_task_entry.md](../templates/next_task_entry.md)

> Ready 昇格チェックと固有 DoD は進捗に応じて更新し、完了後は関連ドキュメントから本チェックリストへリンクしてください。

## Ready 昇格チェック
- [x] `state.md` / `docs/todo_next.md` に本タスクのテンプレートブロックを作成し、アンカーと Pending Questions を設定済み。
- [x] `docs/codex_workflow.md` / `docs/state_runbook.md` の該当手順を再読し、既存ワークフローと矛盾しないことを確認した。
- [x] フェーズ1の既存成果 (`docs/progress_phase1.md`) とバグ調査ログ (`ops/incidents/` など) を確認し、抜け漏れがないか把握した。

> Ready 昇格時に参照したログ: `state.md` 2025-12-05 エントリ、`docs/todo_next.md#ready` の P1-07 ノート、`ops/incidents/` 直近 3 件のリプレイ記録。

## バグチェック観点の整備
- [x] 調査対象ごとのチェックボード（例: `module`, `観点`, `確認状況`, `発見メモ`) を Markdown テーブルで作成し、未着手/進行中/完了を追跡できるようにした。
- [x] 既存テストカバレッジと CLI ドライランの再現手順を一覧化し、各観点から参照できるリンクを追加した。
- [x] `scripts/manage_task_cycle.py` を用いた進捗ログ更新手順を明文化し、調査開始前の `--dry-run start-task` 例を残した。

### 調査チェックボード

| Module / Doc | 観点 | 確認状況 | 発見メモ | 最終更新 |
| --- | --- | --- | --- | --- |
| `scripts/run_daily_workflow.py` | 価格インジェストのフォールバック鎖と CLI 引数解決 | ✅ 2026-01-07 | `tests/test_run_daily_workflow.py` のフォールバック系シナリオが全緑。`state.md` 2026-01-07 ログでシンボル固有 CSV を再検証済み。 | 2026-01-07 |
| `core/runner.py` / sizing | 日次メトリクス集計とサイジングガード | ✅ 2025-12-30 | `_increment_daily` / `_update_rv_thresholds` 抽出後に `python3 -m pytest tests/test_runner.py` 150 件が成功。 | 2025-12-30 |
| データパイプライン (`scripts/pull_prices.py`, `check_benchmark_freshness.py`) | 欠損・遅延ハンドリングと鮮度アラート | ✅ 2025-11-18 | `ingest_meta` の `synthetic_local` 取扱いを `tests/test_check_benchmark_freshness.py` で固定。合成バー時は advisory へ降格。 | 2025-11-18 |
| ドキュメント (`docs/benchmark_runbook.md`, `docs/state_runbook.md`) | 再実行手順とフォールバック手順の整合 | ✅ 2025-11-20 | フォールバックチェーンと CLI 例を runbook に統合済み。今後の更新は `docs/codex_workflow.md` にリンク。 | 2025-11-20 |

調査済み項目は ✅ と更新日を記載し、未完了の場合は「⏳ yyyy-mm-dd」を記入する。新たなバグ観点を追加した際は本テーブルへ行を追記し、`state.md` のログと照合する。

### 回帰テストと CLI ドライラン

- 単体テスト: `python3 -m pytest tests/test_run_daily_workflow.py tests/test_runner.py tests/test_check_benchmark_freshness.py`
- 日次ワークフロー全体確認（ドライラン）: `python3 scripts/run_daily_workflow.py --ingest --update-state --benchmarks --state-health --benchmark-summary --symbol USDJPY --mode conservative --dry-run`
- ベンチマーク鮮度チェック: `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --ingest-timeframe USDJPY_5m`
- リファクタリング後の最小再現: 対象モジュールの pytest セレクタを `-k` で限定し、ログを `analysis/` または `ops/` の調査ノートへ記録する。

### `scripts/manage_task_cycle.py` 手順

```
python3 scripts/manage_task_cycle.py --dry-run start-task \
    --anchor docs/task_backlog.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備 \
    --record-date $(date +%Y-%m-%d) \
    --task-id P1-07 \
    --title "フェーズ1 バグチェック & リファクタリング運用整備" \
    --state-note "対象モジュールとテスト範囲を再スキャン" \
    --doc-note "docs/checklists/p1-07_phase1_bug_refactor.md を更新" \
    --doc-section Ready

python3 scripts/manage_task_cycle.py --dry-run finish-task \
    --anchor docs/task_backlog.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備 \
    --date $(date +%Y-%m-%d) \
    --note "チェックボード更新と state/docs の同期完了" \
    --task-id P1-07
```

ドライランで内容を確認したうえで `--dry-run` を外す。完了後は `state.md` と `docs/todo_next.md` の該当ブロックを Archive/Log へ移動する。

## リファクタリング計画テンプレート
- [x] リファクタリング候補を「影響範囲」「期待効果」「リスク」「リグレッションテスト」の列で整理するテンプレートを追加した。
- [x] カバレッジ不足時に追加するテスト種別（ユニット / 統合 / CLI / データスナップショット）を明示したチェックボックスを用意した。
- [x] 変更後に更新すべきドキュメント（README / runbook / チェックリスト / incident ノート等）を列挙し、リンクを追記した。

### 現行の候補リスト

| Candidate | 影響範囲 | 期待効果 | リスク | Regression | 備考 |
| --- | --- | --- | --- | --- | --- |
| BacktestRunner daily metrics helper | `core/runner.py`, `tests/test_runner.py` | 重複除去とデバッグ可視化の一貫性 | ハンドル漏れによるメトリクス欠損 | ✅ `python3 -m pytest tests/test_runner.py` | 完了 (2025-12-30)。
| Ingest fallback metadata normalization | `scripts/run_daily_workflow.py`, `tests/test_run_daily_workflow.py` | フォールバック経路の透明性向上 | snapshot schema 破壊 | ✅ `python3 -m pytest tests/test_run_daily_workflow.py` | 完了 (2026-01-07)。
| （空欄） | | | | | 新規候補が出たら追記。

### 今後追加する候補用テンプレート

| Candidate | 影響範囲 | 期待効果 | リスク | Regression | 備考 |
| --- | --- | --- | --- | --- | --- |
| <!-- name --> | <!-- module paths --> | <!-- 描述 --> | <!-- Failure mode --> | [ ] Unit / [ ] Integration / [ ] CLI / [ ] Data snapshot | <!-- notes --> |

### ドキュメント更新チェックボックス

- [ ] README / readme/配下
- [ ] docs/state_runbook.md
- [ ] docs/benchmark_runbook.md
- [ ] docs/codex_workflow.md
- [ ] docs/task_backlog.md
- [ ] state.md
- [ ] docs/todo_next.md
- [ ] 関連 incident ノート / progress ノート

候補を完了したら該当項目へチェックを入れ、更新したコミットや PR のリンクを併記する。

## 運用フロー連携
- [x] `docs/task_backlog.md` に本タスクの DoD とテンプレートリンクを追加し、優先度/前提条件を明示した。
- [x] `docs/todo_next.md` の Ready または In Progress セクションへ項目を追加し、実装チームが次セッションで着手しやすい状態にした。
- [x] `state.md` に本タスクを参照するノートを追記し、進捗ログとの同期手順を示した。

> バックログ: `docs/task_backlog.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備`
> Ready ノート: `docs/todo_next.md#ready`
> State 参照: `state.md` 2025-12-05 / 2025-12-30 エントリ

## 実行時チェック（サイクルごとに繰り返し）
- [x] 調査対象ごとに `再現 → 原因分析 → 回避策/修正案 → 検証手順 → ドキュメント更新` のチェックを行い、未完了項目には Pending Questions を設定した。
- [x] 進捗を `docs/checklists/p1-07_phase1_bug_refactor.md` 内のテーブル/チェックボックスへ逐次反映し、次セッションが継続できるようにした。
- [x] CLI / pytest 実行コマンドと結果要約を `state.md` のメモに記録し、フォローアップが必要な場合は `docs/todo_next.md` へ転記した。

## クローズ条件
- [x] 主要バグ観点（実行系、戦略ロジック、データパイプライン、ドキュメントギャップ）について調査完了/未解決/フォローアップのステータスが整理され、`docs/todo_next.md` へリンクされている。
- [x] リファクタリング候補リストに優先度付けと担当候補が記載され、次フェーズ以降に引き継ぐための TODO が残っていない。
- [x] 本チェックリストをすべて更新し、`docs/task_backlog.md` / `docs/todo_next.md` / `state.md` の該当エントリを Archive/Log へ移動した。

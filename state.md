# Work State Log

## Workflow Rule
- Review this file before starting any task to confirm the latest context and checklist.
- Update this file after completing work to record outcomes, blockers, and next steps.

## Next Task
- [P1-01] 2024-06-20 ローリング検証パイプライン — DoD: [docs/task_backlog.md#p1-01-ローリング検証パイプライン](docs/task_backlog.md#p1-01-ローリング検証パイプライン)
  - Backlog Anchor: [ローリング検証パイプライン (P1-01)](docs/task_backlog.md#p1-01-ローリング検証パイプライン)
  - Vision / Runbook References:
    - [docs/logic_overview.md](docs/logic_overview.md)
    - [docs/simulation_plan.md](docs/simulation_plan.md)
    - 主要ランブック: [docs/benchmark_runbook.md](docs/benchmark_runbook.md)
  - Pending Questions:
    - [ ] ローリング365/180/90Dレポートの更新頻度とアラート閾値をどう連動させるか整理する。
  - 2025-09-30: `manage_task_cycle.py` の `start-task` で runbook/pending 指定を許可し、`sync_task_docs.py` のテンプレ統合処理をリファクタリング。テンプレ適用後に state/docs 双方へ同じチェックリストが維持されることを手動確認。

### 運用メモ
- バックログから着手するタスクは先にこのリストへ追加し、ID・着手予定日・DoD リンクを明示する。
- DoD を満たして完了したタスクは `## Log` に成果サマリを移し、`docs/todo_next.md` と整合するよう更新する。
- 継続中に要調整点が出た場合はエントリ内に追記し、完了時にログへ移した後も追跡できるよう関連ドキュメントへリンクを残す。
- 新規に `Next Task` へ追加する際は、方針整合性を確認するために [docs/logic_overview.md](docs/logic_overview.md) や [docs/simulation_plan.md](docs/simulation_plan.md) を参照し、必要なら関連メモへリンクする。

## Log
- [P0-01] 2024-06-01: Initialized state tracking log and documented the review/update workflow rule.
- [P0-02] 2024-06-02: Targeting P0 reliability by ensuring strategy manifests and CLI runners work without optional dependencies. DoD: pytest passes and run_sim/loader can parse manifests/EV profiles after removing the external PyYAML requirement.
- [P0-03] 2024-06-03: 同期 `scripts/rebuild_runs_index.py` を拡充し、`runs/index.csv` の列網羅性テストを追加。DoD: pytest オールパスと CSV 列の欠損ゼロ。
- [P0-04] 2024-06-04: Sharpe 比・最大 DD をランナー/CLI/ベンチマークに波及させ、runbook とテストを更新。DoD: `python3 -m pytest` パスと `run_sim` JSON に新指標が出力されること。
- [P0-04] 2024-06-04 (完了): `core/runner` でエクイティカーブと Sharpe/最大DD を算出し、`run_sim.py`→`runs/index.csv`→`store_run_summary`→`report_benchmark_summary.py` まで連携。`--min-sharpe`/`--max-drawdown` を追加し、docs・テスト更新後に `python3 -m pytest` を通過。
- [P0-05] 2024-06-05: `scripts/run_benchmark_runs.py` の CLI フローを網羅する pytest を追加し、ドライラン/本番実行/失敗ケースの挙動を検証。DoD: `python3 -m pytest` オールグリーン。
- [P0-06] 2024-06-06: `scripts/run_daily_workflow.py` に `--min-sharpe`/`--max-drawdown` を追加し、ベンチマーク要約呼び出しへ閾値を伝播するテストを新設。DoD: `python3 -m pytest` オールパスで、組み立てコマンドに閾値引数が含まれること。
- [P0-06] 2024-06-07: ベースライン/ローリング run を再実行して Sharpe・最大DD 指標をレポートに含め、`report_benchmark_summary.py` で新指標が集計されることを確認。DoD: ベンチマーク run コマンド完走・サマリー更新後に `python3 -m pytest` を実行しオールパス。
- [P0-07] 2024-06-08: `scripts/run_sim.py` のパラメータ保存に EV ゲート関連引数を追加し、`runs/index.csv` / `rebuild_runs_index.py` / テストを同期。DoD: `python3 -m pytest` オールパスで新列が確認できること。
- [P0-08] 2024-06-09: `scripts/run_benchmark_runs.py` で `rebuild_runs_index.py` の失敗コード伝播とログ詳細出力を追加し、失敗時 JSON にエラー情報を含める回帰テストを作成。DoD: `python3 -m pytest` オールパスで失敗コードが伝播すること。
- [P0-09] 2024-06-10: `scripts/run_daily_workflow.py` の失敗コード伝播と README/pytest を更新。DoD: `python3 -m pytest tests/test_run_daily_workflow.py` パス。
- [P1-03] 2024-06-11: P1「state ヘルスチェック」タスクに着手。DoD: `check_state_health` 用 pytest 追加・履歴ローテーション/警告/Webhook 回帰テストが通り、`python3 -m pytest tests/test_check_state_health.py` を完走すること。
- [P1-03] 2024-06-11 (完了): 追加テストで警告生成・履歴トリム・Webhook を検証し、`python3 -m pytest tests/test_check_state_health.py` がグリーン。docs/task_backlog.md へ進捗を反映。
- [P1-01] 2024-06-12: ベンチマークパイプラインを `scripts/run_benchmark_pipeline.py` として追加し、Webhook 伝播・スナップショット更新・`run_daily_workflow.py --benchmarks` からの一括実行を整備。`tests/test_run_benchmark_pipeline.py` を含む関連 pytest を更新してグリーン確認。
- [P1-01] 2024-06-13: `run_daily_workflow.py` からベンチマークサマリー呼び出し時にも Webhook/閾値を伝播させる対応を実装し、README を追記。`python3 -m pytest tests/test_run_daily_workflow.py` を実行して回帰確認。
- [P1-01] 2024-06-14: `run_daily_workflow.py` の最適化/レイテンシ/状態アーカイブコマンドで絶対パスを使用するよう更新し、pytest でコマンド引数に ROOT が含まれることを検証。
- [P1-02] 2024-06-15: `scripts/run_sim.py` に `--start-ts` / `--end-ts` を追加し、部分期間のリプレイをテスト・README・バックログへ反映。DoD: pytest オールグリーンで Sharpe/最大DD 出力継続を確認。
- [P1-02] 2024-06-16: `tests/test_run_sim_cli.py` の時間範囲テストで `BacktestRunner.run` をモック化した際に JSON へ MagicMock が混入する事象を調査し、ラップ関数で実体を返す形に修正。DoD: `python3 -m pytest` がグリーンで TypeError が再発しないこと。
- [P1-04] 2024-06-18: docs/task_backlog.md 冒頭にワークフロー統合指針を追記し、state.md / docs/todo_next.md 間の同期ルールと参照例を整備。
- [P1-04] 2024-06-19: `docs/todo_next.md` を In Progress / Ready / Pending Review / Archive セクション構成へ刷新し、`state.md` のログ日付とバックログ連携を明示。DoD: ガイドライン/チェックリストの追記と過去成果のアーカイブ保持。
- [P1-04] 2024-06-20: Ready 昇格チェックリストにビジョンガイド再読を追加し、`Next Task` 登録時の参照先として `docs/logic_overview.md` / `docs/simulation_plan.md` を明記。

- [P1-02] 2024-06-21: incident ノートテンプレを整備し、ops/incidents/ へ雛形を配置. DoD: [docs/task_backlog.md#p1-02-インシデントリプレイテンプレート](docs/task_backlog.md#p1-02-インシデントリプレイテンプレート).
- [P1-04] 2024-06-22: `scripts/manage_task_cycle.py` を追加し、`sync_task_docs.py` の record/promote/complete をラップする `start-task` / `finish-task` を整備。README / state_runbook を更新し、pytest でドライラン出力を検証。
- [P1-04] 2025-09-28: Ready/DoD チェックリスト テンプレートと `sync_task_docs.py` の自動リンク挿入を整備し、`docs/todo_next.md` / `docs/state_runbook.md` に運用手順を追記。DoD: [docs/task_backlog.md#ワークフロー統合ガイド](docs/task_backlog.md#ワークフロー統合ガイド).
- [P1-04] 2025-09-28: `docs/templates/next_task_entry.md` を新設し、`manage_task_cycle.py start-task` がテンプレを自動適用するよう拡張。DoD: [docs/task_backlog.md#ワークフロー統合ガイド](docs/task_backlog.md#ワークフロー統合ガイド).
- [P1-04] 2025-09-29: Published `docs/codex_workflow.md` to outline Codex session operations and clarified references to `docs/state_runbook.md` and the shared templates. DoD: [docs/task_backlog.md#codex-session-operations-guide](docs/task_backlog.md#codex-session-operations-guide).
- [P1-01] 2025-09-28: Normalized benchmark summary max drawdown thresholds to accept negative CLI inputs, added regression coverage, and revalidated with targeted pytest.
- [P1-01] 2025-09-29: Refined drawdown threshold normalization via helper, captured warning logs for negative CLI input in regression tests, and reran targeted pytest & CLI verification.
- [P1-01] 2025-09-30: Propagated `--alert-pips` / `--alert-winrate` through benchmark pipeline + daily workflow CLIs, refreshed pytest coverage, and synced runbook CLI examples.
- [P1-01] 2025-10-01: 固定パス参照の `aggregate_ev.py` をリファクタし、リポジトリルートを `sys.path` と I/O 基準に統一する REPO_ROOT を導入。CLI 回帰テストを追加し、`python3 -m pytest tests/test_aggregate_ev_script.py` とベンチマーク実行を再確認。

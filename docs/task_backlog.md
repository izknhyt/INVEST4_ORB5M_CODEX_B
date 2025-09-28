# 作業タスク一覧（バックログ）

このバックログは「最新値動きを取り込みながら継続学習し、複数戦略ポートフォリオでシグナルを出す」ツールを実現するための優先順位付きタスク群です。各タスク完了時は成果物（コード/ドキュメント/レポート）へのリンクを追記してください。

## ワークフロー統合

各タスクに着手する前に、該当するバックログ項目を `state.md` の `Next Task` ブロックへ明示的に引き込み、進行中であることを記録してください。作業完了後は、成果ノートや反省点を `docs/todo_next.md` に反映し、`state.md` の完了ログと整合するよう同期します。

- 例: `[P1-02] 2024-06-18 state.md ログ / docs/progress/phase1.md`

### Codex Session Operations Guide
Document the repeatable workflow that lets Codex keep `state.md`, `docs/todo_next.md`, and `docs/task_backlog.md` synchronized across sessions, including how to use the supporting scripts and templates.

**DoD**
- `docs/codex_workflow.md` explains pre-session checks, the execution loop, wrap-up steps, and how to apply the shared templates.
- The guide covers dry-run and live usage of `scripts/manage_task_cycle.py` for keeping state/doc updates in lockstep.
- Links to related runbooks and templates are included so future sessions can reproduce the same procedure.

**Progress Notes**
- 2025-09-29: Added `docs/codex_workflow.md` to consolidate operational guidance for Codex agents and clarified the relationship with `docs/state_runbook.md` and the template directory.

## P0: 即着手（オンデマンドインジェスト + 基盤整備）
- ~~**state 更新ワーカー**~~ (完了): `scripts/update_state.py` に部分実行ワークフローを実装し、`BacktestRunner.run_partial` と状態スナップショット/EVアーカイブ連携を整備。`ops/state_archive/<strategy>/<symbol>/<mode>/` へ最新5件を保持し、更新後は `scripts/aggregate_ev.py` を自動起動するようにした。
- ~~**runs/index 再構築スクリプト整備**~~ (完了): `scripts/rebuild_runs_index.py` が `scripts/run_sim.py` の出力列 (k_tr, gate/EV debug など) と派生指標 (win_rate, pnl_per_trade) を欠損なく復元し、`tests/test_rebuild_runs_index.py` で fixtures 検証を追加。
- ~~**ベースライン/ローリング run 起動ジョブ**~~ (2024-06-12 完了): `scripts/run_benchmark_pipeline.py` でベースライン/ローリング run → サマリー → スナップショット更新を一括化し、`run_daily_workflow.py --benchmarks` から呼び出せるようにした。`tests/test_run_benchmark_pipeline.py` で順序・引数伝播・失敗処理を回帰テスト化。
  - 2024-06-05: `tests/test_run_benchmark_runs.py` を追加し、`--dry-run`/通常実行の双方で JSON 出力・アラート生成・スナップショット更新が期待通りであることを検証。

## P1: ローリング検証 + 健全性モニタリング

### P1-01 ローリング検証パイプライン
直近365D/180D/90Dのシミュレーションを起動バッチで更新し、Rolling 指標を継続監視できるよう整備する。`scripts/run_benchmark_runs.py` と `scripts/report_benchmark_summary.py` を組み合わせて `reports/rolling/<window>/*.json`・`reports/benchmark_summary.json` を生成し、勝率/Sharpe/DD のトレンドを可視化する仕込みを進める。→ `run_sim.py` 出力に Sharpe / max drawdown を追加済み（2024-06-03）。

**DoD**
- `scripts/run_benchmark_runs.py` / `scripts/report_benchmark_summary.py` による365D・180D・90Dローリング run が定期更新されること。
- `reports/rolling/<window>/*.json` と `reports/benchmark_summary.json` に勝率・Sharpe・最大DDが揃って出力されていること。
- ジョブ実行フローとアラート閾値を README もしくは runbook に追記し、再実行手順が明文化されていること。

**進捗メモ**
- 2025-10-08: Added helper-based dispatch and logging reference. See [docs/backtest_runner_logging.md](docs/backtest_runner_logging.md) for counter/record definitions and EV investigation flow.
- 2024-06-04: `core/runner` でエクイティカーブを蓄積し Sharpe / 最大DD を算出、`run_sim.py`・`store_run_summary`・`report_benchmark_summary.py` に伝搬。ベンチマークサマリーでは `--min-sharpe` / `--max-drawdown` 閾値をチェックし `warnings` に追加するよう更新。
- 2025-09-29: `report_benchmark_summary.py` の重複引数定義（`--min-sharpe`/`--max-drawdown`/`--webhook`）を解消し、`run_daily_workflow.py` から `run_benchmark_pipeline.py` を呼び出すように整合。ワークフローからベンチマークサマリーにしきい値・WebHook を正しく伝搬するよう修正。

### P1-02 インシデントリプレイテンプレート
本番での負けトレードを `ops/incidents/` に保存し、同期間のリプレイを `scripts/run_sim.py --start-ts/--end-ts` で再実行する Notebook (`analysis/incident_review.ipynb`) にメモを残す。

**DoD**
- インシデントケースが `ops/incidents/<incident_id>/` に保存され、期間・戦略・トレード ID などのメタデータが揃っていること。
- `scripts/run_sim.py --start-ts/--end-ts` を利用したリプレイ手順が Notebook にテンプレート化され、検証ログを残せること。
- リプレイ結果と対策メモを共有する記録先（README や ops runbook）が更新され、再発防止の参照場所が明示されていること。

**進捗メモ**
- 2024-06-14: `scripts/run_sim.py` に `--start-ts` / `--end-ts` を追加し、README と pytest を更新。部分期間リプレイの準備が整った。

### P1-03 state ヘルスチェック
最新 state から EV 下限、勝率 LCB、滑り推定値を抽出する `scripts/check_state_health.py` を活用し、結果を `ops/health/state_checks.json` に追記。逸脱時の通知/Runbook 追記を行う。

**DoD**
- `scripts/check_state_health.py` が定期実行され、`ops/health/state_checks.json` に履歴が追記されること。
- 勝率 LCB・滑り・EV 閾値逸脱時に Webhook 通知もしくは運用チャネルへの警告が送出されること。
- デフォルト閾値と対応手順が runbook へ記載され、pytest で警告生成と履歴ローテーションが検証されていること。

**進捗メモ**
- 2024-06-11: `check_state_health` の警告・履歴ローテーション・Webhook 送信を pytest で回帰テスト化し、デフォルト閾値 (勝率LCB/サンプル数/滑り上限) の期待挙動を明記。

### P1-05 バックテストランナーのデバッグ可視化強化
`core/runner.py` のデバッグ計測とログドキュメントを整理し、EV ゲート診断の調査手順を標準化する。

**DoD**
- BacktestRunner の戦略フック呼び出しをヘルパー経由で統一し、エラー時のカウントと記録が揃っていること。
- `debug_counts` / `debug_records` のフィールド構成が列挙され、ドキュメントにも一覧が掲載されていること。
- `strategy_gate` → `ev_threshold` → EV 判定 → サイズ判定の観察手順が docs に追記され、CSV/Daily 出力例と併せた調査フローが示されていること。

**進捗メモ**
- 2025-10-08: Added helper-based dispatch and logging reference. See [docs/backtest_runner_logging.md](docs/backtest_runner_logging.md) for counter/record definitions and EV investigation flow.

## P2: マルチ戦略ポートフォリオ化
- **戦略マニフェスト整備**: スキャル/デイ/スイングの候補戦略ごとに、依存特徴量・セッション・リスク上限を YAML で定義し、ルーターが参照できるようにする (`configs/strategies/*.yaml`)。
  - 2025-10-09: `configs/strategies/templates/base_strategy.yaml` に共通テンプレートと記述ガイドを追加し、新規戦略のマニフェスト整備を着手しやすくした。
- **ルーター拡張**: 現行ルールベース (`router/router_v0.py`) を拡張し、カテゴリ配分・相関・キャパ制約を反映。戦略ごとの state/EV/サイズ情報を統合してスコアリングする。
- **ポートフォリオ評価レポート**: 複数戦略を同時に流した場合の資本使用率・相関・ドローダウンを集計する `analysis/portfolio_monitor.ipynb` と `reports/portfolio_summary.json` を追加。
- **マルチ戦略比較バリデーション**: Day ORB と Mean Reversion (reversion_stub) を同一 CSV で走らせ、`docs/checklists/multi_strategy_validation.md` に沿ってゲート通過数・EV リジェクト数・期待値差をレビュー。DoD: チェックリストの全項目を完了し、比較サマリをレビュー用ドキュメントへ共有する。

## P3: 観測性・レポート自動化
- **シグナル/レイテンシ監視自動化**: `scripts/analyze_signal_latency.py` を日次ジョブ化し、`ops/signal_latency.csv` をローテーション。SLO違反でアラート。
- **週次レポート生成**: `scripts/summarize_runs.py` を拡張し、ベースライン/ローリング run・カテゴリ別稼働率・ヘルスチェック結果をまとめて Webhook送信。
- **ダッシュボード整備**: EV 推移、滑り推定、勝率 LCB、ターンオーバーの KPI を 1 つの Notebook or BI に集約し、運用判断を迅速化。

## 継続タスク / 保守
- データスキーマ検証 (`scripts/check_data_quality.py`) を cron 化し、異常リストを `analysis/data_quality.md` に追記。
- 回帰テストセットを拡充（高スプレッド、欠損バー、レイテンシ障害等）し、CI で常時実行。
- 重要な設計・運用変更時は `readme/設計方針（投資_3_）v_1.md` と `docs/state_runbook.md` を更新し、履歴を残す。

> 補足: 着手順は P0 → P1 → P2 の順。途中で運用インシデントが発生した場合は、P1「インシデントリプレイテンプレート」の整備を優先してください。

# フェーズ2 進捗レポート（最適化・分析パイプライン）

## ヒートマップ/時間帯分析
- `analysis/param_surface.ipynb` を追加。`scripts/utils_runs.py` を利用し、`runs/index.csv` からパラメータごとの総pipsをヒートマップ表示するサンプルコードを用意。

## Sharpe/最大DDサマリ
- `scripts/summarize_runs.py` を作成。`python3 scripts/summarize_runs.py --json-out reports/run_summary.json` でトレード数、勝率、総pipsなどをサマリ。今後の拡張で Sharpe / 最大DD の集計を追記予定。

## 2026-02-13 Router v2 work plan (EN)
- Code deliverables: `core/router_pipeline.build_portfolio_state` runtime-metric ingestion polish, `router/router_v1.select_candidates` capacity/correlation score wiring, optional helpers under `scripts/build_router_snapshot.py` for correlation window + category budgets.
- Doc deliverables: refresh `docs/router_architecture.md` with budget/correlation flow diagrams, update `docs/checklists/p2_router.md` progress, capture assumptions in `docs/progress_phase2.md`.
- Test deliverables: extend `tests/test_router_pipeline.py` for telemetry merges, add `tests/test_router_v1.py` assertions covering score deltas and disqualification reasons, ensure `python3 -m pytest tests/test_router_pipeline.py tests/test_router_v1.py` stays green.

## 自動探索ワークフロー（雛形）
- `scripts/auto_optimize.py` を追加。`optimize_params.py` を呼び出して JSON レポートを保存し、Webhook を指定すれば `notifications/emit_signal.py` で通知可能。
  - 現状は JSON パース周りの調整が必要（`optimize_params.py` の出力形式に依存）。Cron/CI 組み込み時に最終調整予定。

## 今後のTODO
- `analysis/param_surface.ipynb` に時間帯／セッション別の集計を追加する。
- `scripts/summarize_runs.py` に Sharpe・最大DD・日次勝率などの指標計算と、Topランの一覧出力を追加する。
- `scripts/auto_optimize.py` の結果パースを安定化し、CIでの定期実行＋Slack通知に組み込む。

## P2 レビューハンドオフパッケージ

### 回帰テストコマンド
- `python3 -m pytest tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics tests/test_report_portfolio_summary.py::test_report_portfolio_summary_cli_budget_status tests/test_portfolio_monitor.py::test_build_portfolio_summary_reports_budget_status`
- `python3 -m pytest tests/test_validate_portfolio_samples.py`
- `python3 scripts/validate_portfolio_samples.py --samples-dir reports/portfolio_samples/router_demo --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml`
- `python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/latest --output reports/portfolio_summary.json --indent 2`

### サンプルアーティファクト
- ルーター demo スナップショット: `reports/portfolio_samples/router_demo/telemetry.json`
- ルーター demo メトリクス: `reports/portfolio_samples/router_demo/metrics/day_orb_5m_v1.json`, `reports/portfolio_samples/router_demo/metrics/tokyo_micro_mean_reversion_v0.json`
- 最新集計サマリー: `reports/portfolio_summary.json`

### 運用チェックリスト
1. 上記回帰テストコマンドを順番に実行し、router demo 由来の warning/breach 分岐が pytest と CLI 双方で再現されることを確認する。
2. `reports/portfolio_samples/router_demo/` 配下のメトリクス・テレメトリと `configs/strategies/*.yaml` の manifest を照合し、`scripts/validate_portfolio_samples.py` で整合性チェックを通過させる。
3. `reports/portfolio_summary.json` の `budget_status`・`budget_over_pct`・`correlation_window_minutes`・`drawdowns` をレビューし、異常があれば `docs/checklists/p2_portfolio_evaluation.md` のトラブルシュート手順に従って原因を特定する。
4. レビュー結果と再現ログ（pytest / CLI 出力、成果物パス）を `state.md` および `docs/todo_next_archive.md` へ転記し、P2 の完了条件と突合する。

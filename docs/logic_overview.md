# ロジック全体サマリ

## 戦略・ゲート
- **DayORB5m**: ORブレイクアウトを基軸に、`strategy_gate` で OR/ATR や RV を判定。`ev_threshold` でシグナルごとの EV 閾値調整を実装。
- **再現用サンプル**: `strategies/reversion_stub.py` を追加し、共通ゲート上で別戦略を動作させるテンプレートを整備。
- **共通設定**: `RunnerConfig` と `StrategyConfig` で構成。`scripts/config_utils.py` を通じて CLI の上書き処理を共通化。

## データ品質・ベースライン
- `scripts/check_data_quality.py` で 2018–2024 CSV の欠損/重複/週末ギャップを監査。結果は `docs/progress_phase0.md` に記録。
- ベースライン `state.json` は `runs/grid_USDJPY_bridge_or4_ktp1.2_ksl0.4_.../state.json` を採用し、`docs/state_runbook.md` にアーカイブ手順をまとめた。

## EV チューニング
- `scripts/generate_ev_case_study.py` で複数の `threshold_lcb` を一括比較し、結果を `analysis/ev_case_study_*.json` に保存。
- `docs/ev_tuning.md` に手順とケーススタディ（例: 閾値0.0/0.3/0.5）を記載。

## Fill モデル
- Conservative / Bridge を同条件で比較し、差分指標を `reports/long_*` 系ファイルにまとめ。
- ブローカー仕様は `docs/broker_oco_matrix.md` に整理し、今後の Fill 拡張に向けた TODO を記載。

## 最適化・分析
- `scripts/optimize_params.py` + `scripts/utils_runs.py` + `analysis/param_surface.ipynb` でパラメータヒートマップを可視化。
- `scripts/summarize_runs.py` で `runs/index.csv` のトレード数・勝率・総pipsなどを集計。
- `scripts/auto_optimize.py` は最適化レポートと通知自動化の雛形。
- `scripts/run_walk_forward.py` で学習→検証窓の最適化ログを取得。
- `scripts/run_optuna_search.py` と `scripts/run_target_loop.py` でベイズ最適化・目標達成ループの基盤を提供。

## モニタリング／通知
- `notifications/emit_signal.py`（フォールバックログ、複数Webhook）と `scripts/analyze_signal_latency.py`（SLOチェック）で通知フローを構築。
- `scripts/run_daily_workflow.py` と `scripts/cron_schedule_example.json` で最適化・レイテンシ監視・state アーカイブをまとめて実行可能。

## 運用・オプス
- 通知: `notifications/emit_signal.py`（フォールバックログ、複数Webhook）、`scripts/analyze_signal_latency.py`（SLOチェック）。
- state: `docs/state_runbook.md` と `scripts/archive_state.py` により、`ops/state_archive/` へ日次保存。
- オーケストレーション: `scripts/run_daily_workflow.py` と `scripts/cron_schedule_example.json` で最適化・通知・アーカイブを一括実行可能。
- Paper移行前チェック: `docs/go_nogo_checklist.md` に要件をまとめ。

## 長期バックテスト・検証
- Conservative/Bridge の 2018–2024 通し結果を `reports/long_conservative.json` / `reports/long_bridge.json` に保存（Sharpe など現状は改善余地あり）。
- 異常系テストは `tests/test_data_robustness.py` で最低限をカバー。

## 目標指標（提案）
- Sharpe Ratio、最大ドローダウン、Profit Factor、Expectancy（期待値）、CAGR を基準指標として設定予定。
- これらを多目的最適化の評価軸にし、全期間でもウォークフォワードでも達成するパラメータを採択する方針。

## これから
- 目標指標（Sharpe, 最大DD, PF, Expectancy, CAGR）の閾値を設定し、自動探索ルールに組み込む。
- ウォークフォワード検証を導入してオーバーフィットを排除しつつ、最終的に全期間最適化へとつなげる。
- 自動最適化（ベイズなど）やメタ学習を段階的に組み込み、目標達成まで探索を継続するフローを構築。

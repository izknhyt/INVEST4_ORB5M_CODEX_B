# Paper トレード移行チェックリスト

## 1. データ & バックテスト
- [ ] 最新データで `scripts/check_data_quality.py` を実行し、欠損/重複なしを確認。
- [ ] Conservative / Bridge 両モードで最新 `run_sim.py` を実行し、Sharpe・最大DD・年間勝率が基準を満たす。
- [ ] ベースライン `state.json` を `ops/state_archive/` から取得し、バックアップ済み。

## 2. 通知 & オペレーション
- [ ] `scripts/analyze_signal_latency.py` を実行し、p95レイテンシが SLO (≤5s) を満たす。失敗率 ≤1% を確認。
- [ ] Webhook 先に対してテスト通知を送信し、フォールバックログが生成されないことを確認。
- [ ] `scripts/run_daily_workflow.py --optimize --analyze-latency --archive-state` をドライランし、全工程が成功することを確認。

## 3. 最適化 & 戦略
- [ ] 最新の `scripts/auto_optimize.py` (または `optimize_params.py`) の結果レポートをレビューし、採用するパラメータセットを決定。
- [ ] `analysis/param_surface.ipynb` の更新グラフを確認し、極端なオーバーフィット兆候がないかチェック。
- [ ] `docs/broker_oco_matrix.md` と `analysis/broker_fills.ipynb` で Fill モデルの差分確認を完了。

## 4. ガバナンス
- [ ] このチェックリストを最新化し、結果と承認者を記録。
- [ ] 主要ファイル（`state.json`, `reports/*`, `analysis/*`）をバックアップ。
- [ ] 変更履歴/README を更新し、最新の運用手順が反映されていることを確認。

完了後、Paper トレード移行判定を行う。

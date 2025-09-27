# EV ゲート調整メモ

## 閾値 (`threshold_lcb_pip`)
- グローバル設定は `RunnerConfig.threshold_lcb_pip`（CLI `--threshold-lcb`）で変更できます。
- 戦略側で `ev_threshold(ctx, pending, base_threshold)` を実装すると、シグナルごとに閾値を上書きできます。
  - DayORB5m では OR/ATR 比が高いシグナルは閾値を引き下げ、ボーダーラインのシグナルは引き上げる実装が入っています。

## ウォームアップと学習状態
- `warmup_trades` で指定した件数は EV を評価せずに通し、初期学習に利用します。
- `prior_alpha/prior_beta` と `ev_global.decay`（デフォルト 0.02）は EV 更新のスピードを左右します。
  - decay を大きくすると最新データを重視し、小さくすると長期統計を保持します。
- ランの最後に `runner.export_state()` を呼ぶと EV のグローバル／バケット統計が `state.json` として取得できます。
- 次回実行時に `--load-state path/to/state.json` を指定するか、コードから `runner.load_state_file()` を呼べば学習状態を引き継げます。
- 実運用では、日次または週次で state をアーカイブし、起動時に最新の state をロードする運用が推奨です。

## 運用上の推奨
- 閾値やウォームアップを変更したら、`scripts/optimize_params.py` でサマリを取り、`runs/index.csv` の成績と比較してください。
- 学習状態を継続利用する場合は、run 実行後の `state.json` を定期的にアーカイブし、トレード開始時にロードする運用フローを runbook にまとめておくと便利です。

## ケーススタディ例
- `scripts/generate_ev_case_study.py` で複数の閾値を一括比較できます。
- 参考: `analysis/ev_case_study_conservative.json`
  - 閾値0.0 → トレード2646件、`-4641pips`
  - 閾値0.3 → トレード1885件、`-2249pips`
  - 閾値0.5 → トレード1871件、`-1802pips`
- ブリッジモードや他パラメータでも同様の比較を行い、最適な閾値レンジを検証してください。

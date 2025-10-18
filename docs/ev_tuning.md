# EV ゲート調整メモ

## 閾値 (`threshold_lcb_pip`)
- グローバル設定は manifest の `runner.runner_config.threshold_lcb_pip` で変更できます。
- 戦略側で `ev_threshold(ctx, pending, base_threshold)` を実装すると、シグナルごとに閾値を上書きできます。
  - DayORB5m では OR/ATR 比が高いシグナルは閾値を引き下げ、ボーダーラインのシグナルは引き上げる実装が入っています。

## ウォームアップと学習状態
- `warmup_trades` で指定した件数は EV を評価せずに通し、初期学習に利用します。manifest の `runner.runner_config.warmup_trades` で調整し、ケーススタディでは `scripts/generate_ev_case_study.py` の `--warmup` で複数値を一括検証できます。
- `prior_alpha/prior_beta` と `ev_global.decay`（デフォルト 0.02）は EV 更新のスピードを左右します。manifest の `runner.runner_config` に設定するか、ケーススタディでは `scripts/generate_ev_case_study.py` の引数で調整します。
  - decay を大きくすると最新データを重視し、小さくすると長期統計を保持します。
- ランの最後に `runner.export_state()` を呼ぶと EV のグローバル／バケット統計が `state.json` として取得できます。
- 次回実行時に manifest で `runner.cli_args.auto_state: true` を維持する、またはコードから `runner.load_state_file()` を呼べば学習状態を引き継げます。
- 実運用では、日次または週次で state をアーカイブし、起動時に最新の state をロードする運用が推奨です。

## 運用上の推奨
- 閾値やウォームアップを変更したら、`scripts/optimize_params.py` でサマリを取り、`runs/index.csv` の成績と比較してください。
- 学習状態を継続利用する場合は、run 実行後の `state.json` を定期的にアーカイブし、トレード開始時にロードする運用フローを runbook にまとめておくと便利です。

## ケーススタディ例
- `scripts/generate_ev_case_study.py` は manifest に渡す `runner.runner_config.threshold_lcb_pip` 値（`--threshold` 引数）や `--decay` / `--prior-alpha` / `--prior-beta` / `--warmup` を一括掃討し、結果を `analysis/ev_param_sweep.json`（階層化サマリ）と `analysis/ev_param_sweep.csv`（フラットテーブル）に出力します。
  - 例:

    ```bash
    python3 scripts/generate_ev_case_study.py \
        --threshold 0.0 --threshold 0.3 --threshold 0.5 \
        --decay 0.01 --decay 0.02 \
        --prior-alpha 1.0 --prior-beta 3.0 \
        --base-args --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --mode conservative --equity 100000
    ```

  - CSV には `param.threshold_lcb`・`param.decay` と `derived.win_rate`・`derived.pips_per_trade` が整形され、Notebook から直接ヒートマップ化できます。
- 可視化には `analysis/ev_param_sweep.ipynb` を利用し、ヒートマップやしきい値ベースの推奨レンジ抽出を行います。
- ブリッジモードや他パラメータでも同様の比較を行い、最適な閾値レンジを検証してください。必要に応じて Notebook 内のフィルタ基準 (`WIN_RATE_MIN` 等) を調整します。

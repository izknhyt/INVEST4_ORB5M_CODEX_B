# フェーズ2 進捗レポート（最適化・分析パイプライン）

## ヒートマップ/時間帯分析
- `analysis/param_surface.ipynb` を追加。`scripts/utils_runs.py` を利用し、`runs/index.csv` からパラメータごとの総pipsをヒートマップ表示するサンプルコードを用意。

## Sharpe/最大DDサマリ
- `scripts/summarize_runs.py` を作成。`python3 scripts/summarize_runs.py --json-out reports/run_summary.json` でトレード数、勝率、総pipsなどをサマリ。今後の拡張で Sharpe / 最大DD の集計を追記予定。

## 自動探索ワークフロー（雛形）
- `scripts/auto_optimize.py` を追加。`optimize_params.py` を呼び出して JSON レポートを保存し、Webhook を指定すれば `notifications/emit_signal.py` で通知可能。
  - 現状は JSON パース周りの調整が必要（`optimize_params.py` の出力形式に依存）。Cron/CI 組み込み時に最終調整予定。

## 今後のTODO
- `analysis/param_surface.ipynb` に時間帯／セッション別の集計を追加する。
- `scripts/summarize_runs.py` に Sharpe・最大DD・日次勝率などの指標計算と、Topランの一覧出力を追加する。
- `scripts/auto_optimize.py` の結果パースを安定化し、CIでの定期実行＋Slack通知に組み込む。

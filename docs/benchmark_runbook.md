# ベンチマーク / ローリング検証運用メモ

## 目的
- 基準 run（全期間）と直近ウィンドウ（365/180/90 など）のパフォーマンスを定期的に更新し、EV ゲートや勝率が崩れていないか監視する。
- 異常検知時は通知を飛ばし、早期にパラメータ見直しやルーター調整につなげる。

## 手順
1. `run_daily_workflow.py --benchmarks` を日次バッチに組み込み、`validated/<SYMBOL>/5m.csv` を入力として `scripts/run_benchmark_pipeline.py` を呼び出す。
2. パイプラインは以下を順番に実行し、成功時のみ `ops/runtime_snapshot.json` をアトミックに更新する:
   - `scripts/run_benchmark_runs.py`: 通期 run とローリング run を起動し、`reports/baseline/*.json` / `reports/rolling/<window>/*.json` を更新。前回との乖離が大きい場合は Webhook 通知（`benchmark_shift`）。
   - `scripts/report_benchmark_summary.py`: `--windows`・`--min-sharpe`・`--max-drawdown` を受け取り、`reports/benchmark_summary.json` を再生成。閾値違反や欠損があれば `warnings` に追記し、Webhook 通知（`benchmark_summary_warnings`）。
   - `ops/runtime_snapshot.json`: `benchmarks.<symbol>_<mode>` に最新バー時刻を、`benchmark_pipeline.<symbol>_<mode>` に生成時刻と警告一覧を記録。
3. 直近結果と前回結果の差分を `total_pips`・`win_rate`（必要に応じて `sharpe`・`max_drawdown`）で比較し、既定の閾値（`--alert-pips`, `--alert-winrate`）を超えた場合は Webhook 通知を送信する。`report_benchmark_summary.py` は `--min-sharpe`・`--max-drawdown` で設定した健全性閾値を用いて `warnings` を生成し、`benchmark_summary_warnings` Webhook と JSON に書き出す。

## 推奨 CLI
```bash
python3 scripts/run_benchmark_pipeline.py \
  --symbol USDJPY --mode conservative --equity 100000 \
  --bars validated/USDJPY/5m.csv \
  --windows 365,180,90 \
  --runs-dir runs --reports-dir reports \
  --summary-json reports/benchmark_summary.json \
  --summary-plot reports/benchmark_summary.png \
  --min-sharpe 0.5 --max-drawdown 200 \
  --webhook https://hooks.slack.com/services/XXX/YYY/ZZZ
```

厚い CSV で時間がかかる場合は `--dry-run` で構成を確認し、`runs/`・`reports/` の書き込み権限を事前に整える。

## 結果の読み方
- `baseline_metrics.total_pips`: 通期 run の総損益（pips）。大幅悪化時は戦略見直し候補。
- `baseline_metrics.sharpe`: 取引ベースのシャープ比。安定性が低下していないかをウォッチ。
- `baseline_metrics.max_drawdown`: 取引累積損益の最大ドローダウン（pips）。過去ピークからの下落幅を把握する。
- `warnings`: `baseline` と `rolling` について、総損益・Sharpe・最大DDが閾値 (`--alert-*`, `--min-sharpe`, `--max-drawdown`) を超えた場合にメッセージが追加される。閾値は pips 単位で設定し、実際のドローダウン値は符号付きで表示される。パイプライン実行時は `benchmark_pipeline.<symbol>_<mode>.warnings` にも同じ配列が保存される。
- `baseline_metrics.win_rate` / `baseline_metrics.trades`: サンプル不足や勝率低下を早期に発見。
- `alert.triggered`: 通知が送信された場合は `alert.payload` と `alert.deliveries` に詳細が残る。
- `rolling[].path`: それぞれの JSON は `scripts/report_benchmark_summary.py` が集約して `reports/benchmark_summary.json` を生成する想定。

## トラブルシュート
- **CSV が大きすぎて時間内に終わらない**: `--windows` を縮めてテスト→本番は夜間バッチで実行。`--dry-run` で I/O だけ確認。
- **Webhook 失敗**: `alert.deliveries` に HTTP ステータスが記録される。ネットワーク不通時は `ok=false` で残るため、手動復旧後に再実行。
- **runs/index.csv が更新されない**: `--runs-dir` に書き込み権限が無いケース。`rebuild_runs_index.py` の return code を `runs_index_rc` でチェック。

## TODO / 拡張
- `reports/benchmark_summary.json` を Notion/BI に自動掲載する。
- 直近ウィンドウの差分をグラフ化する Notebook (`analysis/rolling_dashboard.ipynb`) を整備する。
- ~~Sharpe と最大DDの閾値チェックを `report_benchmark_summary.py` へ組み込み、Runbook に反映する。~~ (2024-06-04 完了)

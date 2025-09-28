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

## スケジュールとアラート管理

- 運用 Cron は UTC 22:30（JST 07:30）に `python3 scripts/run_daily_workflow.py --benchmarks` を起動し、`--windows 365,180,90` をまとめて更新する。ジョブ定義の引数（`ops` 側のジョブ設定ファイル/インフラ管理リポジトリ）には、下表で示すアラート閾値（`--alert-pips 60` / `--alert-winrate 0.04`）と併せて記録し、このランブックと整合させる。
- それぞれのウィンドウは同一コマンドで更新されるが、レビュー頻度・責任者・アラート確認ポイントは下表の通りに運用する。レビュー結果や例外対応は `docs/todo_next.md` または `state.md` に追記する。

| ウィンドウ | 更新頻度 / 想定タイミング | 主コマンド / 担当 | アラート設定 / 通知チャネル | レビュー観点 |
| --- | --- | --- | --- | --- |
| 365D | 毎日 07:30 JST（Cron `30 22 * * *`）で実行し、毎週月曜 Ops 定例で結果レビュー | `run_daily_workflow.py --benchmarks --windows 365,180,90` （担当: Ops） | `--alert-pips 60` / `--alert-winrate 0.04` → `benchmark_shift`（Slack `#ops-benchmark-critical`） | 長期EVの崩れ、週次での Sharpe・DD トレンド、アラート履歴の確認 |
| 180D | 毎日 07:30 JST 実行、火曜/木曜に Ops チェック | 同上 | `--alert-pips 60` / `--alert-winrate 0.04` → 同上 | 直近半年の勝率ブレと総pips差分、`benchmark_shift` 通知有無 |
| 90D | 毎営業日 07:30 JST 実行、日次モニタリング | 同上（レビュー: 日次担当） | `--alert-pips 60` / `--alert-winrate 0.04` → 同上 | 日次での勝率急落や負け越しトレンド、`benchmark_summary_warnings` の確認 |

### アラート閾値と通知チャネル

- `scripts/run_benchmark_runs.py` の `--alert-pips` / `--alert-winrate` は、Ops Slack の `#ops-benchmark-critical` Webhook を指定して実行する。現在の本番値は `--alert-pips 60`、`--alert-winrate 0.04` で、Cron 実行時は上表の通り全ウィンドウで同じ設定を共有する。どちらかを超えた場合は `benchmark_shift` イベントが `#ops-benchmark-critical` に送信される。
- `scripts/report_benchmark_summary.py` は同じ Cron で `--webhook https://hooks.slack.com/.../ops-benchmark-review` を指定し、Sharpe/最大DD 閾値 (`--min-sharpe`, `--max-drawdown`) 違反や欠損があると `benchmark_summary_warnings` を `#ops-benchmark-review` に送信する。
- 閾値の議論が発生した場合は、本セクションの数値と Cron 定義の両方を同時に更新し、理由を `state.md` / `docs/todo_next.md` の該当タスクへ記録する。

### 成功確認と再実行手順

1. Cron 実行後は `ops/runtime_snapshot.json` の `benchmarks.<symbol>_<mode>` および `benchmark_pipeline.<symbol>_<mode>` に最新タイムスタンプが追記されているか確認する。
2. `reports/rolling/{365,180,90}/<symbol>_<mode>.json` が全て更新され、各 JSON に `sharpe`・`max_drawdown` が存在することをチェックする。欠損があれば `scripts/run_benchmark_pipeline.py` の実行ログと照合する。
3. `reports/benchmark_summary.json` の `generated_at` が Cron 実行時刻以降であることを確認し、`warnings` が出力された場合は Slack の `benchmark_summary_warnings` 通知と突き合わせて対応を判断する。
4. 失敗時は `python3 scripts/run_daily_workflow.py --benchmarks --symbol USDJPY --mode conservative --equity 100000` を手動で再実行し、並行して `/var/log/cron.log`（またはスケジューラのジョブログ）で直前ジョブの exit code を確認する。パラメータ確認だけ行いたい場合は `python3 scripts/run_benchmark_pipeline.py --dry-run ...` を使う。
5. ローリング JSON が欠損したままの場合は `reports/rolling/<window>/` を手動点検し、必要に応じて `python3 scripts/run_benchmark_pipeline.py --windows 365,180,90` を単体で実行して再生成する。復旧後は `ops/runtime_snapshot.json` の `benchmark_pipeline` セクションに反映されているか再確認する。

### スケジュール変更時の整合

- 365/180/90D の実行頻度やアラート閾値を変更したら、`python3 scripts/manage_task_cycle.py start-task --anchor docs/task_backlog.md#p1-01-ローリング検証パイプライン --task-id P1-01 --title "ローリング検証パイプライン"` などで Next Task テンプレートを再適用し、`state.md`・`docs/todo_next.md` のメモと本ランブックを同期する。
- 変更のサマリは `state.md` の `## Log` に追記し、関連する Slack 通知設定ファイルやインフラ設定の更新手順もこのセクションからリンクする。

## 推奨 CLI
```bash
python3 scripts/run_benchmark_pipeline.py \
  --symbol USDJPY --mode conservative --equity 100000 \
  --bars validated/USDJPY/5m.csv \
  --windows 365,180,90 \
  --runs-dir runs --reports-dir reports \
  --alert-pips 60 --alert-winrate 0.04 \
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
- **Sharpe / 最大DD が閾値を外れる**: `reports/benchmark_summary.json` の `warnings` と `threshold_alerts` を確認し、どのウィンドウ・指標が `lt`（下回り）/`gt_abs`（絶対値超過）で検知されたか把握する。同時に Cron ログか `python3 scripts/report_benchmark_summary.py ... --min-sharpe <値> --max-drawdown <値>` 実行時の標準出力で WARN ログが出ているか確認し、Slack の `benchmark_summary_warnings` 通知と照合する。再評価のためには `python3 scripts/run_daily_workflow.py --benchmarks --windows 365,180,90 --alert-pips 60 --alert-winrate 0.04 --min-sharpe <値> --max-drawdown <値>` を手動実行し、復旧後に `ops/runtime_snapshot.json` の `benchmark_pipeline.<symbol>_<mode>.threshold_alerts` がクリアされたことをチェックする。

## TODO / 拡張
- `reports/benchmark_summary.json` を Notion/BI に自動掲載する。
- 直近ウィンドウの差分をグラフ化する Notebook (`analysis/rolling_dashboard.ipynb`) を整備する。
- ~~Sharpe と最大DDの閾値チェックを `report_benchmark_summary.py` へ組み込み、Runbook に反映する。~~ (2024-06-04 完了)

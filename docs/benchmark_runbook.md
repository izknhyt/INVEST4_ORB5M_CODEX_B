# ベンチマーク / ローリング検証運用メモ

## 目的
- 基準 run（全期間）と直近ウィンドウ（365/180/90 など）のパフォーマンスを定期的に更新し、EV ゲートや勝率が崩れていないか監視する。
- 異常検知時は通知を飛ばし、早期にパラメータ見直しやルーター調整につなげる。

## 手順
1. `run_daily_workflow.py --benchmarks` を日次バッチに組み込み、`validated/<SYMBOL>/5m.csv` を入力として `scripts/run_benchmark_pipeline.py` を呼び出す。
2. パイプラインは以下を順番に実行し、成功時のみ `ops/runtime_snapshot.json` をアトミックに更新する:
   - `scripts/run_benchmark_runs.py`: 通期 run とローリング run を起動し、`reports/baseline/*.json` / `reports/rolling/<window>/*.json` を更新。前回との乖離が大きい場合は Webhook 通知（`benchmark_shift`）。
   - `scripts/report_benchmark_summary.py`: `--windows`・`--min-sharpe`・`--min-win-rate`・`--max-drawdown` を受け取り、`reports/benchmark_summary.json` を再生成。閾値違反や欠損があれば `warnings` に追記し、Webhook 通知（`benchmark_summary_warnings`）。Sandbox や軽量実行では `scripts/run_benchmark_pipeline.py --disable-plot` を併用して PNG 生成をスキップし、`pandas` / `matplotlib` 依存を持ち込まなくても済む。
   - `ops/runtime_snapshot.json`: `benchmarks.<symbol>_<mode>` に最新バー時刻を、`benchmark_pipeline.<symbol>_<mode>` に生成時刻・警告一覧・`threshold_alerts`・`alert`（トリガーフラグと delta/deliveries ブロック）を記録。

3. 直近結果と前回結果の差分を `total_pips`・`win_rate`・`sharpe`・`max_drawdown` で比較し、既定の閾値（`--alert-pips`, `--alert-winrate`, `--alert-sharpe`, `--alert-max-drawdown`）を超えた場合は Webhook 通知を送信する。`report_benchmark_summary.py` は `--min-sharpe`・`--min-win-rate`・`--max-drawdown` で設定した健全性閾値を用いて `warnings` を生成し、`benchmark_summary_warnings` Webhook と JSON に書き出す。

## スケジュールとアラート管理

- 運用 Cron は UTC 22:30（JST 07:30）に `python3 scripts/run_daily_workflow.py --benchmarks` を起動し、`--windows 365,180,90` をまとめて更新する。ジョブ定義の引数（`ops` 側のジョブ設定ファイル/インフラ管理リポジトリ）には、下表で示すアラート閾値（`--alert-pips 60` / `--alert-winrate 0.04` / `--alert-sharpe 0.2` / `--alert-max-drawdown 40`）と併せて記録し、このランブックと整合させる。
- それぞれのウィンドウは同一コマンドで更新されるが、レビュー頻度・責任者・アラート確認ポイントは下表の通りに運用する。レビュー結果や例外対応は `docs/todo_next.md` または `state.md` に追記する。
- Cron 後の鮮度確認として `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` を実行し、`benchmarks` および `benchmark_pipeline` のタイムスタンプが許容範囲に収まっているか検証する。日次ワークフローからは `--check-benchmark-freshness` と `--benchmark-freshness-max-age-hours 6` を併用して自動実行する。`ingest_metadata` ブロックには主経路（`primary_source`）、フェイルオーバー履歴（`fallbacks` / `source_chain`）、最新取得時刻（`last_ingest_at`）、鮮度差分（`freshness_minutes`）がまとめて表示されるため、合成バー (`synthetic_local`) やローカル CSV から復旧したケースでも経路を追跡しやすい。Sandbox では `source_chain` に `synthetic_local` が含まれる場合、`benchmark_pipeline.*` の欠損/遅延は `advisories` として報告されるため、実データ再取得後に `errors` が空へ戻ったか確認する。

| ウィンドウ | 更新頻度 / 想定タイミング | 主コマンド / 担当 | アラート設定 / 通知チャネル | レビュー観点 |
| --- | --- | --- | --- | --- |
| 365D | 毎日 07:30 JST（Cron `30 22 * * *`）で実行し、毎週月曜 Ops 定例で結果レビュー | `run_daily_workflow.py --benchmarks --windows 365,180,90` （担当: Ops） | `--alert-pips 60` / `--alert-winrate 0.04` / `--alert-sharpe 0.2` / `--alert-max-drawdown 40` → `benchmark_shift`（Slack `#ops-benchmark-critical`） | 長期EVの崩れ、週次での Sharpe・DD トレンド、アラート履歴の確認 |
| 180D | 毎日 07:30 JST 実行、火曜/木曜に Ops チェック | 同上 | `--alert-pips 60` / `--alert-winrate 0.04` / `--alert-sharpe 0.2` / `--alert-max-drawdown 40` → 同上 | 直近半年の勝率ブレと総pips差分、Sharpe 乖離、`benchmark_shift` 通知有無 |
| 90D | 毎営業日 07:30 JST 実行、日次モニタリング | 同上（レビュー: 日次担当） | `--alert-pips 60` / `--alert-winrate 0.04` / `--alert-sharpe 0.2` / `--alert-max-drawdown 40` → 同上 | 日次での勝率急落・Sharpe の低下や DD 拡大、`benchmark_summary_warnings` の確認 |

### アラート閾値と通知チャネル

- `scripts/run_benchmark_runs.py` の `--alert-pips` / `--alert-winrate` / `--alert-sharpe` / `--alert-max-drawdown` は、Ops Slack の `#ops-benchmark-critical` Webhook を指定して実行する。現在の本番値は `--alert-pips 60`、`--alert-winrate 0.04`、`--alert-sharpe 0.2`、`--alert-max-drawdown 40` で、Cron 実行時は上表の通り全ウィンドウで同じ設定を共有する。いずれかを超えた場合は `benchmark_shift` イベントが `#ops-benchmark-critical` に送信される。
- `scripts/report_benchmark_summary.py` は同じ Cron で `--webhook https://hooks.slack.com/.../ops-benchmark-review` を指定し、勝率/Sharpe/最大DD 閾値 (`--min-win-rate`, `--min-sharpe`, `--max-drawdown`) 違反や欠損があると `benchmark_summary_warnings` を `#ops-benchmark-review` に送信する。
- 閾値の議論が発生した場合は、本セクションの数値と Cron 定義の両方を同時に更新し、理由を `state.md` / `docs/todo_next.md` の該当タスクへ記録する。

### 成功確認と再実行手順

1. Cron 実行後は `ops/runtime_snapshot.json` の `benchmarks.<symbol>_<mode>` および `benchmark_pipeline.<symbol>_<mode>` に最新タイムスタンプが追記され、`alert.payload.deltas` が今回の差分を保持しているか確認する。
2. `reports/rolling/{365,180,90}/<symbol>_<mode>.json` が全て更新され、各 JSON に `sharpe`・`max_drawdown` が存在することをチェックする。欠損があれば `scripts/run_benchmark_pipeline.py` の実行ログと照合する。
3. `reports/baseline/<symbol>_<mode>.json` とローリング各 JSON の `aggregate_ev.returncode` が 0、`aggregate_ev.error` が空であることを確認する。パイプラインが `baseline aggregate_ev failed ...` や `rolling window XXX aggregate_ev failed ...` で停止した場合は、該当 JSON の `aggregate_ev.error` を読み取り、モジュール解決ミスや権限不足など原因を特定する。修正後は `python3 scripts/aggregate_ev.py --strategy <戦略クラス> --symbol USDJPY --mode conservative --archive ops/state_archive --recent 5 --out-csv analysis/ev_profile_summary.csv` を単独で実行して成功（exit code 0）を確認し、続けて `python3 scripts/run_benchmark_pipeline.py --symbol USDJPY --mode conservative --equity 100000 --windows 365,180,90` を再実行する。
4. `scripts/run_benchmark_pipeline.py` の標準出力に含まれる `benchmark_runs.alert` をレビューし、`thresholds`・`metrics_prev`・`metrics_new`・`deltas` が Sharpe や最大DDの変化を捉えているかチェックする。同時に `ops/runtime_snapshot.json` の `benchmark_pipeline.<symbol>_<mode>.alert.payload.deltas` と `alert.payload.deliveries` を追跡し、レビュー時に差分と通知成否を再確認する。ローカル実行では Slack Webhook に到達できないため `deliveries[].ok=false` と `detail=url_error=Tunnel connection failed: 403 Forbidden` が残るが、これは本番 Slack 未接続による想定挙動である。メトリクスが DoD を満たしていれば記録用途としてログ化し、必要に応じて `docs/todo_next.md` / `state.md` にメモを残す。
5. `reports/benchmark_summary.json` の `generated_at` が Cron 実行時刻以降であることを確認し、`warnings` が出力された場合は Slack の `benchmark_summary_warnings` 通知と突き合わせて対応を判断する。
6. `scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` の出力を確認し、`ok` が `true` かつ `errors` が空であることをチェックする。`ingest_metadata.freshness_minutes` と `ingest_metadata.source_chain` を参照すると、前回のインジェスト経路と鮮度差分をワンショットで把握できる。`ok=false` の場合は JSON の `errors` を読み取り、`benchmarks`・`benchmark_pipeline.latest_ts`・`summary_generated_at` のいずれが閾値超過かを特定し、該当処理（ベンチマーク run / サマリー集計 / Cron 時刻）を再実行する。猶予を設ける必要がある場合は `--benchmark-freshness-max-age-hours` を上書きし、理由を `state.md` と Cron 定義に記録する。
7. Fill 挙動の異常が疑われる場合は `python3 analysis/broker_fills_cli.py --format markdown` を実行し、OANDA / IG / SBI FXトレードの同足ヒット・トレール挙動と `core/fill_engine.py` Conservative / Bridge 出力を比較する。`docs/broker_oco_matrix.md` のポリシーと乖離があれば、`SameBarPolicy` やトレール幅を更新して再度 `python3 -m pytest tests/test_fill_engine.py` を走らせる。
8. 失敗時は `python3 scripts/run_daily_workflow.py --benchmarks --symbol USDJPY --mode conservative --equity 100000` を手動で再実行し、並行して `/var/log/cron.log`（またはスケジューラのジョブログ）で直前ジョブの exit code を確認する。パラメータ確認だけ行いたい場合は `python3 scripts/run_benchmark_pipeline.py --dry-run --symbol USDJPY --mode conservative --equity 100000 --windows 365,180,90 --runs-dir runs --reports-dir reports` を使う。
9. ローリング JSON が欠損したままの場合は `reports/rolling/<window>/` を手動点検し、必要に応じて `python3 scripts/run_benchmark_pipeline.py --windows 365,180,90` を単体で実行して再生成する。復旧後は `ops/runtime_snapshot.json` の `benchmark_pipeline` セクションに反映されているか再確認する。

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
  --alert-pips 60 --alert-winrate 0.04 --alert-sharpe 0.2 --alert-max-drawdown 40 \
  --summary-json reports/benchmark_summary.json \
  --summary-plot reports/benchmark_summary.png \
  --min-sharpe 0.5 --min-win-rate 0.55 --max-drawdown 200 \
  --webhook https://hooks.slack.com/services/XXX/YYY/ZZZ
```

厚い CSV で時間がかかる場合は `--dry-run` で構成を確認し、`runs/`・`reports/` の書き込み権限を事前に整える。

## 結果の読み方
- `baseline_metrics.total_pips`: 通期 run の総損益（pips）。大幅悪化時は戦略見直し候補。
- `baseline_metrics.sharpe`: 取引ベースのシャープ比。安定性が低下していないかをウォッチ。
- `baseline_metrics.max_drawdown`: 取引累積損益の最大ドローダウン（pips）。過去ピークからの下落幅を把握する。
- `warnings`: `baseline` と `rolling` について、総損益・勝率・Sharpe・最大DDが閾値 (`--alert-*`, `--min-win-rate`, `--min-sharpe`, `--max-drawdown`) を超えた場合にメッセージが追加される。閾値は pips 単位で設定し、実際のドローダウン値は符号付きで表示される。パイプライン実行時は `benchmark_pipeline.<symbol>_<mode>.warnings` にも同じ配列が保存される。
- `baseline_metrics.win_rate` / `baseline_metrics.trades`: サンプル不足や勝率低下を早期に発見。
- `alert.triggered`: 通知が送信された場合は `alert.payload` と `alert.deliveries` に詳細が残る。`alert.payload.deltas.delta_sharpe` や `delta_max_drawdown` で Sharpe / 最大DD の変化量を把握し、Slack 通知と突き合わせてレビューする。`ops/runtime_snapshot.json` の `benchmark_pipeline.<symbol>_<mode>.alert` にも同じブロックがコピーされるため、過去ログとして確認できる。
- `rolling[].path`: それぞれの JSON は `scripts/report_benchmark_summary.py` が集約して `reports/benchmark_summary.json` を生成する想定。

## トラブルシュート
- **CSV が大きすぎて時間内に終わらない**: `--windows` を縮めてテスト→本番は夜間バッチで実行。`--dry-run` で I/O だけ確認。
- **Webhook 失敗**: `alert.deliveries` に HTTP ステータスが記録される。ネットワーク不通時は `ok=false` で残るため、手動復旧後に再実行。
- **runs/index.csv が更新されない**: `--runs-dir` に書き込み権限が無いケース。`rebuild_runs_index.py` の return code を `runs_index_rc` でチェック。
- **勝率 / Sharpe / 最大DD が閾値を外れる**: `reports/benchmark_summary.json` の `warnings` と `threshold_alerts` を確認し、どのウィンドウ・指標が `lt`（下回り）/`gt_abs`（絶対値超過）で検知されたか把握する。同時に Cron ログか `python3 scripts/report_benchmark_summary.py ... --min-win-rate <値> --min-sharpe <値> --max-drawdown <値>` 実行時の標準出力で WARN ログが出ているか確認し、Slack の `benchmark_summary_warnings` 通知と照合する。再評価のためには `python3 scripts/run_daily_workflow.py --benchmarks --windows 365,180,90 --alert-pips 60 --alert-winrate 0.04 --alert-sharpe 0.2 --alert-max-drawdown 40 --min-win-rate <値> --min-sharpe <値> --max-drawdown <値>` を手動実行し、復旧後に `ops/runtime_snapshot.json` の `benchmark_pipeline.<symbol>_<mode>.threshold_alerts` がクリアされたことをチェックする。
- **Matplotlib が無い / PNG が更新されない**: CLI を `--summary-plot` 付きで実行すると、`matplotlib` / `pandas` が無い環境では `summary plot skipped: missing dependency <module>` という警告が `warnings` 配列と `ops/runtime_snapshot.json` に残る。PNG は生成されないため、グラフが必要ならローカルに `pip install matplotlib pandas` を行ってから再実行するか、PNG なしでレビューする。
- **Sandbox で Slack Webhook が 403 になる**: ローカルや CI サンドボックスでは `https://hooks.slack.com/...` へ到達できず、`benchmark_runs.alert.deliveries[].detail` に `url_error=Tunnel connection failed: 403 Forbidden` が残る。閾値判定そのものは `alert.triggered` と `deltas` で確認できるため、ネットワーク制限下では警告を記録したうえでオペレーションログへ追記し、実運用環境での再試行時に通知が成功することを確認する。

## TODO / 拡張
- `reports/benchmark_summary.json` を Notion/BI に自動掲載する。
- 直近ウィンドウの差分をグラフ化する Notebook (`analysis/rolling_dashboard.ipynb`) を整備する。
- ~~Sharpe と最大DDの閾値チェックを `report_benchmark_summary.py` へ組み込み、Runbook に反映する。~~ (2024-06-04 完了)

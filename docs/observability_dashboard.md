# オブザーバビリティダッシュボード運用メモ

## 目的
- `runs/`・`reports/`・`ops/` に分散している EV 履歴 / スリッページ推定 / 勝率 LCB / ターンオーバー指標を単一のダッシュボードで把握する。
- エンジニアが手動で最新データを確認するときに、CLI と Notebook の双方から同じローダーを呼び出せるようにする。

## リフレッシュ手順
1. `runs/index.csv` の `configs/ev_profiles/day_orb_5m.yaml` 行をチェックして Day ORB 最新ラン（例: `runs/USDJPY_conservative_20251002_214013`）を確認し、Tokyo Micro Mean Reversion についてはサンプルメトリクス `reports/portfolio_samples/router_demo/metrics/tokyo_micro_mean_reversion_v0.json` を利用する。以下のコマンドでルーター snapshot とポートフォリオサマリーを更新し、`budget_status` / `budget_over_pct` / `correlation_window_minutes` / `drawdowns` をレビューする。
   ```bash
   python3 scripts/build_router_snapshot.py \
       --output runs/router_pipeline/latest \
       --manifest configs/strategies/day_orb_5m.yaml \
       --manifest configs/strategies/tokyo_micro_mean_reversion.yaml \
       --manifest-run day_orb_5m_v1=reports/portfolio_samples/router_demo/metrics/day_orb_5m_v1.json \
       --manifest-run tokyo_micro_mean_reversion_v0=reports/portfolio_samples/router_demo/metrics/tokyo_micro_mean_reversion_v0.json \
       --positions day_orb_5m_v1=1 \
       --positions tokyo_micro_mean_reversion_v0=2 \
       --correlation-window-minutes 240 \
       --indent 2
   python3 scripts/report_portfolio_summary.py \
       --input runs/router_pipeline/latest \
       --output reports/portfolio_summary.json \
       --indent 2
   ```
   - 最新スナップショットは [`runs/router_pipeline/latest/`](../runs/router_pipeline/latest/) 配下に保存される。特に [`telemetry.json`](../runs/router_pipeline/latest/telemetry.json) の `category_budget_headroom_pct` / `category_budget_pct` と `strategy_correlations` をレビューし、ヘッドルームが負値の場合は `budget_status` と `budget_over_pct` を記録する。
   - ポートフォリオサマリーは [`reports/portfolio_summary.json`](../reports/portfolio_summary.json) に上書きされるため、`category_utilisation[*].budget_status`・`correlation_heatmap[*].bucket_budget_pct`・`correlation_window_minutes`・`drawdowns.*` を確認し、ダッシュボードで強調すべきアラート項目を整理する。
   - Review checklist (portfolio monitoring):
     - **Budget headroom** — confirm positive `category_budget_headroom_pct` と `category_utilisation[*].budget_headroom_pct`; マイナス値があれば警告/逸脱量をコメントする。
     - **Correlation window width** — `correlation_window_minutes` が想定窓幅（例: 240 分）と一致し、異なる場合は調査ノートを残す。
     - **Drawdowns** — `drawdowns.aggregate.max_drawdown_pct` と `drawdowns.per_strategy[*].max_drawdown_pct` を読み、閾値超過時は対象戦略の期間 (`peak_ts` / `trough_ts`) をレビューする。
   - 回帰テストで CLI フローを確認するには、以下を実行して router snapshot／サマリー双方の warning/breach 分岐を再現する。
     ```bash
     python3 -m pytest \
       tests/test_portfolio_monitor.py::test_build_portfolio_summary_reports_budget_status \
       tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics \
       tests/test_report_portfolio_summary.py::test_report_portfolio_summary_cli_budget_status
     ```
2. リポジトリルートで以下を実行し、データセットごとの JSON を出力する。
   ```bash
   python3 analysis/export_dashboard_data.py \
       --runs-root runs \
       --state-archive-root ops/state_archive \
       --strategy day_orb_5m.DayORB5m \
       --symbol USDJPY \
       --mode conservative \
       --portfolio-telemetry reports/portfolio_samples/router_demo/telemetry.json \
       --latency-rollup ops/signal_latency_rollup.csv \
       --output-dir out/dashboard \
       --manifest out/dashboard/manifest.json \
       --heartbeat-file ops/dashboard_export_heartbeat.json \
       --history-dir ops/dashboard_export_history \
       --archive-manifest ops/dashboard_export_archive_manifest.jsonl
   ```
   - `--dataset` を複数指定すると `ev_history` / `slippage` / `turnover` / `latency` の任意サブセットを生成できる（未指定時は全データセット）。
   - `--archive-dir` を指定すると戦略/シンボル/モードの組み合わせを上書きできる。`--ev-limit`・`--slip-limit`・`--turnover-limit`・`--latency-limit` で履歴件数を調整可能。
   - 実行後は `out/dashboard/<dataset>.json` と `out/dashboard/manifest.json`、ハートビート `ops/dashboard_export_heartbeat.json` が更新され、履歴ディレクトリ `ops/dashboard_export_history/<job_id>/` にコピーが残る。8 週間以上前の履歴は自動的に削除され、削除ログが `ops/dashboard_export_archive_manifest.jsonl` に追記される。
3. Notebook で可視化したい場合は `analysis/portfolio_monitor.ipynb` を開き、最初のセルを実行してデータ構造を更新する。
   - `pandas` が無い環境ではリスト形式で値が返るため、そのまま JSON 出力をレビューするか、必要に応じて `pip install pandas` で依存を追加する。
4. 共有用ストレージへアップロードする際は `out/dashboard/manifest.json` の `sequence` / `generated_at` と `ops/dashboard_export_heartbeat.json` の `last_success_at` をメッセージに添えて通知する。

## データソースの対応付け
| データセット | 参照元 | 出力先 | 補足 |
| ---- | ------ | ------ | ---- |
| `ev_history` | `ops/state_archive/<strategy>/<symbol>/<mode>/*.json` | `out/dashboard/ev_history.json` | `ev_global.alpha/beta/decay/conf` から正規近似で LCB を再計算し `latest` ブロックへ格納。 |
| `slippage` (状態/執行) | `ops/state_archive/**` / `reports/portfolio_samples/*/telemetry.json` | `out/dashboard/slippage.json` | `state` 配列にアーカイブ係数、`execution` に `slippage_bps` / `reject_rate` を格納。 |
| `turnover` | `runs/index.csv` + 各 `runs/<run_id>/daily.csv` | `out/dashboard/turnover.json` | 日次 fills 集計から `avg_trades_per_day`・`avg_trades_active_day` を算出。 |
| `latency` | `ops/signal_latency_rollup.csv` | `out/dashboard/latency.json` | 1 時間ロールアップ (`p50_ms` / `p95_ms` / `p99_ms` / `max_ms`) を最新順に整形。 |

## ステークホルダー向けサマリー要件
- 日次・週次のレビューでは以下の 4 点を必須項目として報告する。
  1. 直近 EV スナップショットの勝率 LCB (`win_rate_lcb`) と、過去 30 件のトレンド。
  2. `slip.a` の narrow/normal/wide 係数、および `execution_health` の slippage_bps / reject_rate。閾値逸脱があれば数値と要因を添える。
  3. 過去 10 run の平均トレード数 (`avg_trades_per_day` / `avg_trades_active_day`) と勝率。
  4. 大幅な変動があった場合は対象日 (`start_date` / `end_date`) を明記し、関連する `runs/<id>` / `ops/state_archive` ファイルをリンクする。
- 共有時は `out/dashboard/manifest.json` の `sequence` / `generated_at` と `provenance.command` を添え、`ops/dashboard_export_heartbeat.json` の `datasets` ステータスを確認してから案内する。
- レポートのアーカイブは `reports/portfolio_summary.json` の `generated_at` を基準に履歴管理し、ダッシュボード JSON を添付して監査証跡を残す。

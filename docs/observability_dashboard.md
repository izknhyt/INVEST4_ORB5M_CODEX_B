# オブザーバビリティダッシュボード運用メモ

## 目的
- `runs/`・`reports/`・`ops/` に分散している EV 履歴 / スリッページ推定 / 勝率 LCB / ターンオーバー指標を単一のダッシュボードで把握する。
- エンジニアが手動で最新データを確認するときに、CLI と Notebook の双方から同じローダーを呼び出せるようにする。

## リフレッシュ手順
1. リポジトリルートで以下を実行し、JSON まとめを生成する。
   ```bash
   python3 analysis/export_dashboard_data.py \
       --runs-root runs \
       --state-archive-root ops/state_archive \
       --strategy day_orb_5m.DayORB5m \
       --symbol USDJPY \
       --mode conservative \
       --portfolio-telemetry reports/portfolio_samples/router_demo/telemetry.json \
       --out-json out/dashboard_snapshot.json
   ```
   - `--archive-dir` を指定すると戦略/シンボル/モードの組み合わせを上書きできる。
   - `--ev-limit`・`--slip-limit`・`--turnover-limit` で履歴件数を調整可能。
2. Notebook で可視化したい場合は `analysis/portfolio_monitor.ipynb` を開き、最初のセルを実行してデータ構造を更新する。
   - `pandas` が無い環境ではリスト形式で値が返るため、そのまま JSON 出力をレビューするか、必要に応じて `pip install pandas` で依存を追加する。
3. 必要に応じて `out/dashboard_snapshot.json` を共有用ストレージへアップロードし、Slack/メールで最新値を通知する。

## データソースの対応付け
| 指標 | 参照元 | 補足 |
| ---- | ------ | ---- |
| EV 履歴・勝率 LCB | `ops/state_archive/<strategy>/<symbol>/<mode>/*.json` | `ev_global.alpha/beta/decay/conf` から正規近似で LCB を再計算。 |
| スリッページ推定 (状態) | 同上 | `slip.a` の係数と EWMA パラメータを取得。 |
| スリッページ実績 (執行) | `reports/portfolio_samples/*/telemetry.json` | `execution_health.<strategy>.slippage_bps` / `reject_rate` を抽出。 |
| ターンオーバー | `runs/index.csv` + 各 `runs/<run_id>/daily.csv` | 日次 fills 集計から平均トレード数を算出。 |

## ステークホルダー向けサマリー要件
- 日次・週次のレビューでは以下の 4 点を必須項目として報告する。
  1. 直近 EV スナップショットの勝率 LCB (`win_rate_lcb`) と、過去 30 件のトレンド。
  2. `slip.a` の narrow/normal/wide 係数、および `execution_health` の slippage_bps / reject_rate。閾値逸脱があれば数値と要因を添える。
  3. 過去 10 run の平均トレード数 (`avg_trades_per_day` / `avg_trades_active_day`) と勝率。
  4. 大幅な変動があった場合は対象日 (`start_date` / `end_date`) を明記し、関連する `runs/<id>` / `ops/state_archive` ファイルをリンクする。
- `out/dashboard_snapshot.json` を共有する際は、生成コマンド・日時 (`generated_at`) をメッセージ本文に含める。
- レポートのアーカイブは `reports/portfolio_summary.json` の `generated_at` を基準に履歴管理し、ダッシュボード JSON を添付して監査証跡を残す。

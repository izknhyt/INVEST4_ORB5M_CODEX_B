# Paper トレード移行チェックリスト

> 各項目は担当者・実行頻度・証跡パスを必ず記録し、モックレビュー時は証跡列へドキュメント/ログのリンクを貼ること。

## 1. データ & バックテスト

| チェック | 担当 | 実行頻度 | 証跡/ログ |
| --- | --- | --- | --- |
| 最新データで `python3 scripts/check_data_quality.py --csv <validated_csv> --symbol USDJPY --out-json reports/data_quality/paper_gate.json --calendar-day-summary --fail-under-coverage 0.995` を実行し、欠損/重複なしを確認 |  | 週次 / 移行判定前 |  |
| Conservative / Bridge 両モードで最新 manifest（例: `configs/strategies/day_orb_5m.yaml`）を用い、`python3 scripts/run_sim.py --manifest ... --csv ... --mode <mode> --out-dir runs/go_nogo --out-json reports/go_nogo_<mode>.json --out-daily-csv reports/go_nogo_<mode>_daily.csv` を再実行し、Sharpe・最大DD・年間勝率が基準を満たす |  | 週次 / パラメータ更新毎 |  |
| ベースライン `state.json` を `ops/state_archive/` から取得し、`ops/state_archive/<strategy>/<symbol>/<mode>/` へ最新5件を保持してバックアップ完了 |  | 週次 |  |

## 2. 通知 & オペレーション

| チェック | 担当 | 実行頻度 | 証跡/ログ |
| --- | --- | --- | --- |
| `python3 scripts/analyze_signal_latency.py --input ops/signal_latency.csv --out-json reports/latency_summary.json --out-csv reports/latency_summary.csv` を実行し、p95レイテンシ ≤5s・失敗率 ≤1% を確認 |  | 週次 |  |
| Webhook 先へテスト通知（`python3 scripts/summarize_runs.py --runs-root runs --out-json /tmp/weekly_summary.json --webhook-url <url> --dry-run-webhook`）を送信し、フォールバックログ未発生を確認 |  | 月次 / 通知設定変更時 |  |
| `python3 scripts/run_daily_workflow.py --optimize --analyze-latency --archive-state --dry-run` を完走させ、全工程が成功することを確認 |  | 月次 / ランブック更新時 |  |

## 3. 最適化 & 戦略

| チェック | 担当 | 実行頻度 | 証跡/ログ |
| --- | --- | --- | --- |
| 最新の `python3 scripts/auto_optimize.py --config configs/strategies/day_orb_5m.yaml --out reports/optimization/day_orb_5m.json` をレビューし、採用パラメータを決定 |  | パラメータ更新毎 |  |
| `analysis/param_surface.ipynb` 最新版を確認し、極端なオーバーフィット兆候がないかチェック |  | 週次レビュー |  |
| `docs/broker_oco_matrix.md` と `analysis/broker_fills.ipynb` で Fill モデル差分を確認し、期待滑り/Fill精度が許容範囲内であることを記録 |  | 月次 / ブローカー設定変更時 |  |

## 4. ガバナンス

| チェック | 担当 | 実行頻度 | 証跡/ログ |
| --- | --- | --- | --- |
| 本チェックリストを更新し、承認者/判定コメントを `docs/progress_phase4.md`「運用チェックリスト」に記録 |  | 判定毎 |  |
| `state.json`, `reports/*`, `analysis/*` をバックアップし、`ops/state_archive/` の世代保持ルールを確認 |  | 週次 / Paper判定前 |  |
| `README.md`・関連ランブックに最新運用手順を反映し、差分を PR サマリへ記載 |  | ドキュメント更新毎 |  |

完了後、Paper トレード移行判定を行う。

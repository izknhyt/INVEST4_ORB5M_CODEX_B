# フェーズ0 進捗レポート（データ品質確認）

## データ監査
- スクリプト: `python3 scripts/check_data_quality.py --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY`
- 必須カラム欠損: 0 行
- 数値パース不可（o/h/l/c）: 0 行
- 重複タイムスタンプ: 0
- タイムフレーム: `5m` のみ（523,743 行）
- シンボル: `USDJPY` のみ
- ギャップ検出: 週末休場（2885分）と一部祝日相当の間隔のみ。営業時間内の欠損や逆順は検出されず。

## オンデマンドインジェスト
- CLI: `python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --tf 5m`
- 成果物: `raw/USDJPY/5m.csv` → `validated/USDJPY/5m.csv` → `features/USDJPY/5m.csv` を順次追記し、再実行でも重複挿入なし。
- スナップショット: `ops/runtime_snapshot.json` の `ingest.USDJPY_5m` に最新バー時刻を保持（ドライラン時は未更新）。
- 異常検知: パースエラー・ギャップ・シンボル/TF不一致などを `ops/logs/ingest_anomalies.jsonl` にJSON Linesで残し、再実行ログとして活用可能。

## ベースライン state
- 既存ランの `state.json` は `runs/grid_USDJPY_bridge_or4_ktp1.2_ksl0.4_20250921_134957/state.json` をベースライン候補とする。
- 運用時は `docs/state_runbook.md` の手順に沿って日次アーカイブを保持し、実験前にバックアップを取得すること。

## 今後のTODO
- OANDA/IGなど他シンボル用データを扱う場合は同様の監査スクリプトを実行してログを残す。
- ギャップリスト（週末など）は `analysis/data_quality.md` に転記し、営業カレンダと照合する。

# フェーズ3 進捗レポート（運用準備）

## 通知SLO運用
- `scripts/analyze_signal_latency.py` を導入済。サンプルcron設定 (`scripts/cron_schedule_example.json`) に日次チェックを追記。
- フォールバックログ（`ops/signal_notifications.log`）と連携し、異常時に手動通知できるよう整備済み。

## state アーカイブ
- `scripts/archive_state.py` を追加。`python3 scripts/archive_state.py --runs-dir runs --output ops/state_archive` で各ランの `state.json` を日次バージョンとして保存。
- `ops/state_archive/` に初期アーカイブ（168件）を作成。`docs/state_runbook.md` と併せて運用手順を明文化。

## スケジューラ統合
- `scripts/run_daily_workflow.py` を追加。最適化 (`--optimize`)、レイテンシ分析 (`--analyze-latency`)、stateアーカイブ (`--archive-state`) をまとめて実行可能。
- Cron 例 (`scripts/cron_schedule_example.json`) を用意。実際の自動化は CI/cron 環境に合わせて設定。

## TODO
- `analysis/broker_fills.ipynb` による Fill 差分可視化と、ブローカー仕様に合わせたモデル調整。
- `run_daily_workflow.py` のログ出力・通知内容を強化し、本番運用フローへ組み込む。
- state アーカイブの保存期間やクリーンアップ方針を `docs/state_runbook.md` に追記。

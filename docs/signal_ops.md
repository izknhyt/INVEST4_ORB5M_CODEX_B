# シグナル通知運用メモ

## 通知スクリプト `notifications/emit_signal.py`
- Webhook URL は `--webhook-url` で指定（カンマ区切りで複数可）。未指定の場合は環境変数 `SIGNAL_WEBHOOK_URLS`（`;` または `,` 区切り）を参照します。
- 通知失敗時は `ops/signal_notifications.log` にフォールバックし、リプレイ時に手動通知できるよう情報を残します。
- `ops/signal_latency.csv` に送信結果を追記（成功/失敗、emit/ackタイムスタンプ、詳細メッセージ）。

## レイテンシ監視
- `scripts/analyze_signal_latency.py` で SLO をチェックできます。

```
python3 scripts/analyze_signal_latency.py \
  --input ops/signal_latency.csv \
  --rollup-output ops/signal_latency_rollup.csv \
  --heartbeat-file ops/latency_job_heartbeat.json \
  --alert-config configs/observability/latency_alert.yaml \
  --archive-dir ops/signal_latency_archive \
  --archive-manifest ops/signal_latency_archive/manifest.jsonl \
  --json-out reports/signal_latency_summary.json
```

- `reports/signal_latency_summary.json` には `samples_analyzed` / `latest_p95_ms` / `breach_streak` が含まれ、SLO 逸脱があった場合は `status="warning"`。
- `ops/latency_job_heartbeat.json` の `pending_alerts` / `breach_streak` を監視することで、連続違反の有無を即座に把握できます。
- 10MB を超えた RAW CSV は自動的に `ops/signal_latency_archive/YYYY/MM/<job_id>.csv.gz` へ退避され、manifest (`manifest.jsonl`) にハッシュとレコード数が追記されます。
- Slack/PagerDuty へ連携する前に payload を確認したい場合は `--dry-run-alert` を付与し、`out/latency_alerts/<job_id>.json` をレビューしてください。

### CSV ローテーション
- `ops/rotate_signal_latency.sh` で `ops/signal_latency.csv` を日次ローテーションし、当日の CSV をヘッダ付きの空ファイルとして再生成します。ローテーション済みファイルは `ops/archive/` に日付付きで保存されます。
- サンプルスケジュールは `ops/signal_latency_rotation.cron` に記載しています。UTC で 00:05 に実行し、ローテーション後に `scripts/analyze_signal_latency.py` を別ジョブで流す想定です。実環境ではパスをリポジトリ設置場所に合わせて書き換えてください。

## 運用のポイント
- 通知に利用する Webhook URL は secrets 管理（環境変数や Vault 等）で扱い、CI/CD で差し替えやすいようにしておくと便利です。
- `ops/signal_notifications.log` は定期的にローテーションし、送信失敗が続く場合は即時対応できるようアラート連携を検討してください。
- latency CSV は日次で `scripts/analyze_signal_latency.py` を実行し、SLO を満たしているか監視する想定です。

# シグナル通知運用メモ

## 通知スクリプト `notifications/emit_signal.py`
- Webhook URL は `--webhook-url` で指定（カンマ区切りで複数可）。未指定の場合は環境変数 `SIGNAL_WEBHOOK_URLS`（`;` または `,` 区切り）を参照します。
- 通知失敗時は `ops/signal_notifications.log` にフォールバックし、リプレイ時に手動通知できるよう情報を残します。
- `ops/signal_latency.csv` に送信結果を追記（成功/失敗、emit/ackタイムスタンプ、詳細メッセージ）。

## レイテンシ監視
- `scripts/analyze_signal_latency.py` で SLO をチェックできます。

```
python3 scripts/analyze_signal_latency.py --input ops/signal_latency.csv --slo-threshold 5
```

- `p95_latency` が閾値を超える、または失敗率が 1% を超えると終了コード 1 になります。
- `--json-out` を指定すると JSON 形式でレポートを保存します。

## 運用のポイント
- 通知に利用する Webhook URL は secrets 管理（環境変数や Vault 等）で扱い、CI/CD で差し替えやすいようにしておくと便利です。
- `ops/signal_notifications.log` は定期的にローテーションし、送信失敗が続く場合は即時対応できるようアラート連携を検討してください。
- latency CSV は日次で `scripts/analyze_signal_latency.py` を実行し、SLO を満たしているか監視する想定です。

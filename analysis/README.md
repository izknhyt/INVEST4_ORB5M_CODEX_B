# Analysis Notes

- `broker_fills.ipynb`: ブローカー約定履歴とシミュレーション結果の差分を可視化するノートブックを配置予定。
- `ops/signal_latency.csv`: `notifications/emit_signal.py` がレイテンシログを追記する想定。SLO: `p95 <= 5s` を目標。

今後の作業
- ブローカー別約定データの収集・加工パイプラインを追加。
- Conservative/Bridge Fill のシナリオテストセットを追加し、回帰テストに組み込む。

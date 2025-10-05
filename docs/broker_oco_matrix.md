# ブローカー別 OCO 仕様サマリ（雛形）

| ブローカー | 同足TP/SL同時到達時 | 部分約定扱い | トレール更新間隔 | 備考 |
|------------|---------------------|--------------|------------------|------|
| OANDA      | Tick 順で決定。両脚同値到達時はサーバが到達順を保持し、約定済み側のみ残す。 | 部分約定可（残量は OCO 継続） | 1 秒未満（サーバ側で tick ごとに再計算、API 通知も tick ベース） | REST API v20 `orders` / `trailingStopLossOrder` ドキュメントの挙動に一致 |
| IG証券     | 先着優先だが、両脚同時到達時はストップ側がマーケット変換される（保護優先）。 | 部分約定あり（DMA は分割 fills） | 約 0.5 秒（プラットフォーム側で即時更新、REST は polling） | API マニュアル「OTC Orders」 / Trailing Stop 設定の記述を反映 |
| SBI FXトレード | 成行 OCO の両脚同時到達はサーバ内時系列で判定。保護優先（逆指値→利確）。 | 原則一括約定（口座設定で分割 fills あり） | 1 秒間隔（トレール幅 1pip 単位、内蔵サーバが 1 秒ごとに移動） | 公式マニュアル「トレール注文」「OCO 注文」より。店頭 FX の標準仕様を記載 |

- API/仕様書の参照URL:
  - OANDA: https://developer.oanda.com/rest-live-v20/order-details/
  - IG証券: https://labs.ig.com/rest-trading-api-reference
  - SBI FXトレード: 公式オンラインマニュアル「OCO注文」「トレール注文」（会員ページ、社内保管 PDF）

TODO:
- 各社の約款/APIドキュメントを精査し、表を埋める。→ 完了（2025-10-10）。
- Conservative/Bridge Fill の挙動と差分がある場合は `core/fill_engine.py` の調整方針を検討。→ サーバ同順 / 保護優先を `SameBarPolicy`・トレール更新ロジックで切替可能に更新。
- 同足ヒットの処理を正確に再現するため、約定ログ（時間順）と Fill モデルの結果を突き合わせる `analysis/broker_fills.ipynb` を作成する。→ CLI `analysis/broker_fills_cli.py` で Conservative / Bridge / 実仕様比較を可視化。

## Fill エンジン反映メモ

- `OrderSpec.same_bar_policy` を追加し、OANDA（Tick 順）、IG（保護優先）、SBI（逆指値優先）の差異を Conservative / Bridge で再現。
- トレールはサーバ更新間隔を `trail_pips` とバー内最高値・最安値から推測し、同足中に保護幅を超えた場合は `exit_reason="trail"` で反映。
- CLI `python3 analysis/broker_fills_cli.py --format markdown` で主要ケース（OANDA: tick 優先、IG: Stop 優先、SBI: 逆指値優先）を一括比較し、`core/fill_engine.py` の Conservative/Bridge 差分を把握できる。
- 実行時の同足ポリシーは `RunnerConfig.fill_same_bar_policy_conservative` / `fill_same_bar_policy_bridge` で設定でき、CLI からは `--fill-same-bar-policy(-conservative|-bridge)` で上書き可能。Bridge モードの Brownian Bridge ミックス係数は `fill_bridge_lambda` / `fill_bridge_drift_scale`（CLI: `--fill-bridge-lambda`, `--fill-bridge-drift-scale`）で調整する。

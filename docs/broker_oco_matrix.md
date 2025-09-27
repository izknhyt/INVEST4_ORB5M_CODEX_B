# ブローカー別 OCO 仕様サマリ（雛形）

| ブローカー | 同足TP/SL同時到達時 | 部分約定扱い | トレール更新間隔 | 備考 |
|------------|---------------------|--------------|------------------|------|
| OANDA      | 先にヒットした注文が優先。両方ヒットは約定順に処理される。 | 部分約定可（残量は継続） | 1秒未満（API通知はtick単位） | REST API v20 `orders` ドキュメント参照 |
| IG証券     | 先着優先。両方ヒットの場合は成行判断となりSlippage有 | 部分約定あり | プラットフォーム側で即時更新 | APIマニュアル「OTC Orders」 |
| XXX証券    | 未調査              | 未調査       | 未調査           | 要問い合わせ |

- API/仕様書の参照URL:
  - OANDA: https://developer.oanda.com/rest-live-v20/order-details/
  - IG証券: https://labs.ig.com/rest-trading-api-reference
  - XXX証券: （未調査。入手次第追記）

TODO:
- 各社の約款/APIドキュメントを精査し、表を埋める。
- Conservative/Bridge Fill の挙動と差分がある場合は `core/fill_engine.py` の調整方針を検討。
- 同足ヒットの処理を正確に再現するため、約定ログ（時間順）と Fill モデルの結果を突き合わせる `analysis/broker_fills.ipynb` を作成する。

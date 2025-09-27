# Ops Incidents

本番トレードで異常やドローダウンが発生した際のログ置き場です。各フォルダは 1 インシデントに対応し、以下のファイルを最低限そろえます。

```
ops/incidents/<incident_id>/
  ├─ incident.json      # メタデータ・期間・当時の指標
  ├─ replay_notes.md    # 解析メモ（原因 / 対応 / TODO）
  ├─ replay_params.json # `scripts/run_sim.py` に渡した引数控え
  └─ artifacts/         # スクリーンショット、チャート、CSV 等（任意）
```

## incident.json テンプレ
- `incident_id`: `YYYYMMDD-HHMM_<symbol>_<short_desc>`
- `symbol`, `mode`, `start_ts`, `end_ts`: リプレイ対象期間（UTC）
- `trigger`: 例) `drawdown`, `slippage`, `latency`
- `severity`: `low` / `medium` / `high`
- `loss_pips`: インシデント期間の約定損益（pips）
- `notes`: 簡単な状況メモ

サンプル: `_template.incident.json` を参照。

## 運用フロー
1. 負けトレード発生 → 即時サマリを incident.json で記録。
2. `analysis/incident_review.ipynb` を開き、incident.json を読み込んで該当期間で `scripts/run_sim.py` を再実行。
3. 得られた結果・ヒートマップ・再現性メモを `replay_notes.md` に追記。
4. 影響範囲が広い場合は、Runbook / 設計方針ドキュメントへ抜粋を移植する。

## 命名規則
- ディレクトリ名と `incident_id` は同一にする。
- 1 つのトレード/イベントに対して複数タイムフレームで追う場合はサブフォルダ `subcases/` を切る。

## ToDo
- 自動 Slack 通知との連携 (`notifications/emit_signal.py`) を検討。
- ノートブックから `replay_params.json` を生成するユーティリティを追加。

# フェーズ4 進捗レポート（検証とリリースゲート）

## 異常系テスト
- `tests/test_data_robustness.py` を追加。
  - 必須カラム欠損行を含むデータでも Runner が落ちないことを確認。
  - スプレッド急拡大（5.0pips）時にトレードを発行せず安全側に振る挙動をテスト。

## 長期バックテスト
- Conservative (`--mode conservative`) で 2018–2024 通しラン実行。
  - `reports/long_conservative.json`: 100 trades, total -243 pips, 日次 Sharpe ≈ -0.076。
- Bridge (`--mode bridge`) 同条件で実行。
  - `reports/long_bridge.json`: 758 trades, total -934 pips, 日次 Sharpe ≈ -0.104。
- 日次ログは `reports/long_*_daily.csv` に保存。さらなる調整が必要（現時点ではマイナス）。

## 運用チェックリスト
- `docs/go_nogo_checklist.md` を作成し、Paper 移行前に確認すべき項目を整理。
  - データ品質・通知SLO・stateバックアップ・最適化結果レビューなどを含む。

## TODO (フェーズ4 継続)
- 長期バックテスト結果を改善するためのパラメータ再検討（Bridge/Conservativeともにマイナスのため）。
- 異常系テストを `pytest` で自動実行可能になるよう環境整備。
- `docs/go_nogo_checklist.md` を実際の運用で更新し、承認履歴を残す。

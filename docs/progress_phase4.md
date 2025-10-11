# フェーズ4 進捗レポート（検証とリリースゲート）

## 異常系テスト
- `tests/test_data_robustness.py` を追加。
  - 必須カラム欠損行を含むデータでも Runner が落ちないことを確認。
  - スプレッド急拡大（5.0pips）時にトレードを発行せず安全側に振る挙動をテスト。

## 長期バックテスト
- Conservative (`--mode conservative`) で 2018–2024 通しラン実行。
  - `reports/long_conservative.json`: 100 trades, total -243 pips, 日次 Sharpe ≈ -0.076。
  - `reports/long_conservative_daily.csv` を再集計すると 2019 以降は fills≦2 / pnl<0 で、`ev_reject` が gate_pass と同等に多く事実上エントリーが成立していないことを確認（2019 年 fills=2、gate_pass=32,686、ev_reject=32,681）。
- Bridge (`--mode bridge`) 同条件で実行。
  - `reports/long_bridge.json`: 758 trades, total -934 pips, 日次 Sharpe ≈ -0.104。
  - 年別概要: 2018 年 fills=175 / pnl -203.6, 2019 年 fills=195 / pnl -260.1, 2020 年 fills=155 / pnl -284.2、と全期間でマイナス圏。
- 日次ログは `reports/long_*_daily.csv` に保存。さらなる調整が必要（現時点ではマイナス）。
- 2025-10-11: `scripts/aggregate_ev.py --archive ops/state_archive --archive-namespace day_orb_5m.DayORB5m/USDJPY/conservative --strategy strategies.day_orb_5m.DayORB5m --symbol USDJPY --mode conservative --recent 30 --out-yaml configs/ev_profiles/strategies.day_orb_5m.yaml` を実行し、EV プロファイルを再構築（files_total=66 / recent_count=30）。Bridge モードも `configs/ev_profiles/strategies.day_orb_5m_bridge.yaml` へ出力して比較材料を整備。
- 次ステップ: Conservative 向けに `threshold_lcb_pip`/`alpha_prior` 調整と OR 窓幅チューニングの実験プランを固め、再シミュレーションを段階的に走らせる（大規模ランはリソース制約のため分割実行）。

## 運用チェックリスト
- `docs/go_nogo_checklist.md` を作成し、Paper 移行前に確認すべき項目を整理。
  - データ品質・通知SLO・stateバックアップ・最適化結果レビューなどを含む。

## TODO (フェーズ4 継続)
- 長期バックテスト結果を改善するためのパラメータ再検討（Bridge/Conservativeともにマイナスのため）。
- 異常系テストを `pytest` で自動実行可能になるよう環境整備。
- `docs/go_nogo_checklist.md` を実際の運用で更新し、承認履歴を残す。
- Conservative 向け EV プロファイルを用いた `threshold_lcb_pip` 探索（0.25〜0.5 pip）と OR 窓幅 (`or_n`) の感度分析を分割ランで実施、結果を `reports/long_conservative*.json` 系へ反映。

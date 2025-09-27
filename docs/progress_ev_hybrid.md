# EVハイブリッド改善メモ (2025-09-22)

## これまでの流れ
- ウォームアップと固定コストだけでは EV ゲートが過剰に閉じる問題があり、Beta-Binomial の初期値を強化する必要があった。
- `scripts/run_sim.py` に state 自動ロード/アーカイブを実装し、ランごとに最新 `state.json` を引き継げるようにした。
- `ops/state_archive/` を活用して `scripts/aggregate_ev.py` を作成。長期・直近期の EV 統計を集計し、`configs/ev_profiles/` に YAML プロファイルとして保存。
- `BacktestRunner` が EV プロファイルを読み込み、グローバル/バケットの Beta パラメータをシード。`ctx["ev_profile_stats"]` でストラテジーに情報を渡す。
- `strategies/day_orb_5m.DayORB5m.ev_threshold` がバケットごとの期待値・観測数に応じて EV 閾値を調整するよう拡張。
- シミュレーション再走 (`run_sim.py --out-dir runs`) でトレード数が増加し、P/L がプラス域へ改善。

## 現状の成果物
- `scripts/aggregate_ev.py`: state archive から EV プロファイル生成。
- `configs/ev_profiles/day_orb_5m.yaml`: USDJPY conservative 用の最新長期/直近期統計。
- `analysis/ev_profile_summary.csv`: バケット別の平均 α/β、勝率、観測数の表。
- `core/runner.py`: EV プロファイルの自動適用と ctx 注入。
- `strategies/day_orb_5m.py`: プロファイルに基づく閾値調整ロジック。
- `docs/state_runbook.md`: プロファイル運用手順を追記。
- `scripts/run_sim.py`: ラン成功時に `scripts/aggregate_ev.py` を自動呼び出しし、EVプロファイル(YAML/CSV)を更新 (`--no-aggregate-ev` で無効化可)。

## 次に検討したい事項
1. `scripts/aggregate_ev.py` を定期的に実行し、自動で YAML を更新するワークフロー化（cron/CI）。
2. プロファイル統計と実績 PnL の乖離を可視化する Notebook/ダッシュボードを整備。
3. バケット信頼度に応じたサイズ調整（`kelly_fraction` や `warmup` の逓減/増加）を導入。
4. プロファイル生成時の長期・直近期ウインドウサイズや重みを調整し、レジーム変化への追従性を検証。

優先順: ①自動更新 → ②可視化 → ③サイズ調整。

## メモ
- `run_sim.py --no-ev-profile` で従来ロジックとの比較ができる。
- `ctx["ev_profile_stats"]` には `long_term` と `recent` が入り、期待値と観測数が参照可能。
- `ev_profile_obs_norm` (default 15) で観測数に対する信頼度スケールを調整可能。

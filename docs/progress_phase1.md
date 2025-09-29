# フェーズ1 進捗レポート（戦略ゲート / EV チューニング / Fill 検証）

## 1. 戦略別ゲート整備
- `strategies/day_orb_5m.py` に `strategy_gate` / `ev_threshold` 実装済み。
- サンプル戦略として `strategies/reversion_stub.py` を追加。低ボラ時の閾値緩和・高ボラ時のブロック動作を確認済み。`
- CLI `run_sim.py --strategy <module.Class>` で任意戦略を注入可能。
- `scripts/run_sim.py --strategy-manifest` が `configs/strategies/*.yaml` を読み込み、RunnerConfig の許容セッション/リスク上限を適用しつつ戦略パラメータ（例: `allow_high_rv` / `zscore_threshold`）を `Strategy.on_start` にそのまま渡すフローを整備。回帰テスト: `tests/test_run_sim_cli.py::test_run_sim_manifest_mean_reversion`。DoD: [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化)。

## 2. EV 閾値ケーススタディ
- ユーティリティ `scripts/generate_ev_case_study.py` を追加し、複数の `threshold_lcb` を一括比較可能。
- Conservative (`or_n=4, k_tp=1.2, k_sl=0.4`) の検証結果 (`analysis/ev_case_study_conservative.json`):
  | 閾値 | トレード数 | 総pips |
  |------|-----------|--------|
  | 0.0  | 2646      | -4641  |
  | 0.3  | 1885      | -2249  |
  | 0.5  | 1871      | -1802  |
- `docs/ev_tuning.md` に手順と結果を追記済み。

## 3. Fill モデル比較
- 同条件 (`threshold_lcb=0.3`) で Conservative / Bridge をラン。
  - Conservative: 1999 trades / -2396pips
  - Bridge:       2168 trades / -2724pips
- 差分ログは `/tmp/daily_*`, `/tmp/records_*` に出力。
- 2025-10-10: `analysis/broker_fills_cli.py` を追加し、OANDA / IG / SBI FXトレードの同足ヒット・トレール挙動を Conservative / Bridge と比較できる Markdown テーブルを生成。`python3 analysis/broker_fills_cli.py --format markdown` で期待順とモデル出力・ポリシー調整後の差分を一覧化。
- 2025-10-10: `core/fill_engine.py` に `SameBarPolicy` / トレール即日更新ロジックを導入し、`tests/test_fill_engine.py` で代表ケース（Tick 優先 / 保護優先 / トレール更新）を固定。`python3 -m pytest tests/test_fill_engine.py` が通過することを確認。

## TODO（フェーズ1 継続）
- ブローカー別の調査内容を notebook 化し、実ログとの突合（`runs/*`）を継続する。
- Mean Reversion など他戦略の本格実装を進め、共通ゲートで動作確認を行う。

# ロジック全体サマリ

## 戦略・ゲート
- **DayORB5m**: ORブレイクアウトを基軸に、`strategy_gate` で OR/ATR や RV を判定。`ev_threshold` でシグナルごとの EV 閾値調整を実装。
- **再現用サンプル**: `strategies/reversion_stub.py` を追加し、共通ゲート上で別戦略を動作させるテンプレートを整備。
- **Mean Reversion**: `strategies/mean_reversion.py` が RV/ADX フィルタ・ATR ベースのリスクリワード計算・EV プロファイル補正を備えた本実装。`configs/strategies/mean_reversion.yaml` でパラメータを管理し、`tests/test_mean_reversion_strategy.py` で挙動を回帰。
- **共通設定**: `RunnerConfig` と `StrategyConfig` で構成。`scripts/config_utils.py` を通じて CLI の上書き処理を共通化。

### Day ORB パラメータ依存マトリクス

| パラメータ/キー | 参照元 | 依存先 | 影響の概要 |
| --- | --- | --- | --- |
| `or_n` | `cfg` | `on_bar` の OR 更新 | OR ウィンドウのバー数を決定し、初期高値/安値の確定タイミングを制御する。【F:strategies/day_orb_5m.py†L32-L44】 |
| `k_tp` / `k_sl` / `k_tr` | `cfg` | `on_bar` の TP/SL/トレール算出 | ATR14 から算出した pips 値に倍率を掛け、OCO パラメータを決定する。`k_tr` が 0 以下ならトレールを無効化。【F:strategies/day_orb_5m.py†L45-L58】 |
| `require_close_breakout` | `cfg` | `on_bar` ブレイク条件 | ブレイク判定を終値基準に引き上げ、ヒゲ抜け時のシグナル発火を抑制する。【F:strategies/day_orb_5m.py†L58-L77】 |
| `require_retest` / `retest_max_bars` / `retest_tol_k` | `cfg` | `on_bar` 再テスト管理 | 初回ブレイク後の再テスト待機と締切、許容トレランスを制御し、擬似フェイクアウト抑制に寄与する。【F:strategies/day_orb_5m.py†L58-L96】 |
| `min_or_atr_ratio` / `or_atr_ratio` | `cfg` / `ctx` | `strategy_gate` と `ev_threshold` | OR 幅に対する ATR 比を下限チェックし、十分なボラティリティが確保できない場合のシグナル棄却や EV 閾値補正に利用する。【F:strategies/day_orb_5m.py†L119-L146】 |
| `allow_low_rv` / `rv_band` | `ctx` | `strategy_gate` | RV バンドが mid/high 以外でも通過させるかを決定し、統計的ボラティリティの不足をフィルタする。【F:strategies/day_orb_5m.py†L135-L141】 |
| `ev_threshold_boost` / `ev_threshold_relief` | `cfg` | `ev_threshold` | OR/ATR 条件に応じて EV 閾値を引き上げ・引き下げし、良条件時のエントリー加速と境界条件での保守運用を切り替える。【F:strategies/day_orb_5m.py†L148-L165】 |
| `ev_profile_stats` / `ev_profile_obs_norm` | `ctx` / `cfg` | `ev_threshold` | 直近・長期の EV プロファイル統計を読み込み、観測数に基づいて期待値差分を平滑化しつつ EV 閾値を再調整する。【F:strategies/day_orb_5m.py†L165-L193】 |
| `cost_pips` | `ctx` | `ev_threshold` | EV プロファイル補正時に取引コストを控除し、期待値の過大評価を避ける。【F:strategies/day_orb_5m.py†L170-L193】 |

#### 再利用時の注意点

- `min_or_atr_ratio` の閾値を引き上げた場合、`ev_threshold_boost` が過剰に高いと閾値が急上昇し約定機会が枯渇するため、両値を同時調整する際は OR 幅の分布を確認する。
- `allow_low_rv=False` のまま RV バンドを低頻度シンボルへ適用するとシグナルが完全に遮断される可能性がある。低 RV でも許容したい場合は `rv_band` のラベルや `allow_low_rv` をシミュレーションで検証する。
- `ev_profile_stats` を供給しない環境では EV 閾値補正が行われず、`ev_threshold_relief` だけが効く構造になる。ベンチマーク run ではプロファイル生成フェーズの完了を確認する。

##### 新戦略転用チェックリスト

1. OR 設計: `or_n`・再テスト関連の挙動が対象シンボルのボラティリティと時間足に合っているかを確認する。
2. ボラティリティゲート: `min_or_atr_ratio` と `allow_low_rv` の両方について、サンプル分布を取得しながら棄却率をモニタする。
3. EV プロファイル連携: `ev_profile_stats` の生成頻度と `ev_profile_obs_norm` のスケールが実データの観測数と乖離していないかをチェックする。
4. コスト・閾値: `cost_pips` や `ev_threshold_boost/relief` が fill モデル（Bridge/Conservative など）と整合しているかを確認し、閾値変更時は `strategy_gate` の棄却理由をログで追跡する。

## データ品質・ベースライン
- `scripts/check_data_quality.py` で 2018–2024 CSV の欠損/重複/週末ギャップを監査。結果は `docs/progress_phase0.md` に記録。
- ベースライン `state.json` は `runs/grid_USDJPY_bridge_or4_ktp1.2_ksl0.4_.../state.json` を採用し、`docs/state_runbook.md` にアーカイブ手順をまとめた。

## EV チューニング
- `scripts/generate_ev_case_study.py` で複数の `threshold_lcb` / `decay` / `prior` / `warmup` を一括比較し、結果を `analysis/ev_param_sweep.{json,csv}` に保存。
- `docs/ev_tuning.md` に手順とケーススタディ（例: 閾値0.0/0.3/0.5）を記載。

## Fill モデル
- Conservative / Bridge を同条件で比較し、差分指標を `reports/long_*` 系ファイルにまとめ。
- ブローカー仕様は `docs/broker_oco_matrix.md` に整理し、今後の Fill 拡張に向けた TODO を記載。

## 最適化・分析
- `scripts/optimize_params.py` + `scripts/utils_runs.py` + `analysis/param_surface.ipynb` でパラメータヒートマップを可視化。
- `scripts/summarize_runs.py` で `runs/index.csv` のトレード数・勝率・総pipsなどを集計。
- `scripts/auto_optimize.py` は最適化レポートと通知自動化の雛形。
- `scripts/run_walk_forward.py` で学習→検証窓の最適化ログを取得。
- `scripts/run_optuna_search.py` と `scripts/run_target_loop.py` でベイズ最適化・目標達成ループの基盤を提供。

## モニタリング／通知
- `notifications/emit_signal.py`（フォールバックログ、複数Webhook）と `scripts/analyze_signal_latency.py`（SLOチェック）で通知フローを構築。
- `scripts/run_daily_workflow.py` と `scripts/cron_schedule_example.json` で最適化・レイテンシ監視・state アーカイブをまとめて実行可能。

## 運用・オプス
- 通知: `notifications/emit_signal.py`（フォールバックログ、複数Webhook）、`scripts/analyze_signal_latency.py`（SLOチェック）。
- state: `docs/state_runbook.md` と `scripts/archive_state.py` により、`ops/state_archive/` へ日次保存。
- オーケストレーション: `scripts/run_daily_workflow.py` と `scripts/cron_schedule_example.json` で最適化・通知・アーカイブを一括実行可能。
  - Cron 例には 22:30 UTC（JST 07:30）の `benchmark_pipeline_daily` ジョブを追記し、`docs/benchmark_runbook.md#スケジュールとアラート管理` で定義された `--alert-*` / `--min-*` 閾値・`--benchmark-windows 365,180,90`・`--benchmark-freshness-max-age-hours 6` をそのまま CLI に反映した。
- Paper移行前チェック: `docs/go_nogo_checklist.md` に要件をまとめ。

## 長期バックテスト・検証
- Conservative/Bridge の 2018–2024 通し結果を `reports/long_conservative.json` / `reports/long_bridge.json` に保存（Sharpe など現状は改善余地あり）。
- 異常系テストは `tests/test_data_robustness.py` で最低限をカバー。

## 目標指標（提案）
- Sharpe Ratio、最大ドローダウン、Profit Factor、Expectancy（期待値）、CAGR を基準指標として設定予定。
- これらを多目的最適化の評価軸にし、全期間でもウォークフォワードでも達成するパラメータを採択する方針。

## これから
- 目標指標（Sharpe, 最大DD, PF, Expectancy, CAGR）の閾値を設定し、自動探索ルールに組み込む。
- ウォークフォワード検証を導入してオーバーフィットを排除しつつ、最終的に全期間最適化へとつなげる。
- 自動最適化（ベイズなど）やメタ学習を段階的に組み込み、目標達成まで探索を継続するフローを構築。

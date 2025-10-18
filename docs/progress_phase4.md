# フェーズ4 進捗レポート（検証とリリースゲート）

- 2026-10-17: Day ORB シンプル化リブートの初期値を再調整し、低 RV 帯のブロック理由を整理。
  `configs/strategies/day_orb_5m.yaml` を `k_tp=1.25` / `k_sl=0.6` / `min_or_atr_ratio=0.16`
  / `rv_band_min_or_atr_ratio={low:0.18,mid:0.16,high:0.12}` / `ny_high_rv_min_or_atr_ratio=0.24`
  / `tokyo_low_rv_micro_trend_min=0.0` に刷新し、`strategies/day_orb_5m.DayORB5m` では
  東京専用の RV フィルタをセッション判定から切り離して低 RV ガードをマイクロトレンドのみに集約した。
  その結果、デバッグランでは `_last_gate_reason` が `rv_filter=14215` / `tokyo_low_rv_guard=5608`
  から `or_filter=24` / `ny_high_rv_or_filter=1` に収束し、Tokyo セッション外で空振りしていた
  ブロックを解消できた（run=`runs/tmp/day_orb5m_debug/USDJPY_conservative_20251017_122719`）。

  ```bash
  python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml \
    --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/tmp/day_orb5m_debug \
    --debug --debug-sample-limit 500000 --no-auto-state
  python3 scripts/summarize_strategy_gate.py \
    --run-dir runs/tmp/day_orb5m_debug/USDJPY_conservative_20251017_122719 --json
  python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml \
    --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/phase4/backtests \
    --no-auto-state
  python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml \
    --csv validated/USDJPY/5m.csv --mode bridge --out-dir runs/phase4/backtests --no-auto-state
  python3 scripts/compare_metrics.py --left reports/long_conservative.json \
    --right runs/phase4/backtests/USDJPY_conservative_20251017_122913/metrics.json \
    --out-json tmp/day_orb_conservative_diff.json
  python3 scripts/compare_metrics.py --left reports/long_bridge.json \
    --right runs/phase4/backtests/USDJPY_bridge_20251017_123055/metrics.json \
    --out-json tmp/day_orb_bridge_diff.json
  python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
report = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "baseline": {
        "conservative": "reports/long_conservative.json",
        "bridge": "reports/long_bridge.json",
    },
    "candidates": {
        "conservative": "runs/phase4/backtests/USDJPY_conservative_20251017_122913/metrics.json",
        "bridge": "runs/phase4/backtests/USDJPY_bridge_20251017_123055/metrics.json",
    },
    "diffs": {
        "conservative": json.load(open("tmp/day_orb_conservative_diff.json")),
        "bridge": json.load(open("tmp/day_orb_bridge_diff.json")),
    },
}
Path("reports/diffs/day_orb_reboot_metrics.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False) + "\n"
)
PY
  ```

  Conservative / Bridge ともに 3 トレードで終了し EV ブロックは発生せず、
  `reports/diffs/day_orb_reboot_metrics.json` に既存ロングランとの差分を集約。
  保守的な TP/SL の再設定によって Sharpe / DD は依然マイナスだが、低 RV 帯の
  ブロック理由が `or_filter` のみとなったため次段の ATR 再校正に集中できる。

- 2026-10-27: Guard-relaxed Day ORB の ATR ガードと損失ガードを再調整し、2018–2025 ロングランを再実行。
  `configs/strategies/day_orb_5m_guard_relaxed.yaml` を `min_or_atr_ratio=0.16`・`rv_band_min_or_atr_ratio={high:0.10,mid:0.12,low:0.16}`・
  `max_loss_streak=4`・`max_daily_loss_pips=180` に更新後、以下を再現。

  ```bash
  python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m_guard_relaxed.yaml \
    --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/phase4/backtests_guard_relaxed \
    --no-auto-state --debug --debug-sample-limit 600000
  python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m_guard_relaxed.yaml \
    --csv validated/USDJPY/5m.csv --mode bridge --out-dir runs/phase4/backtests_guard_relaxed \
    --no-auto-state --debug --debug-sample-limit 600000
  python3 scripts/summarize_strategy_gate.py --run-dir runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251017_112231 --json
  python3 scripts/summarize_strategy_gate.py --run-dir runs/phase4/backtests_guard_relaxed/USDJPY_bridge_20251017_112729 --json
  python3 scripts/compare_metrics.py --left reports/diffs/conservative_guard_relaxed_metrics.json \
    --right runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251017_112231/metrics.json \
    --out-json reports/diffs/conservative_guard_relaxed_metrics_next.json
  python3 scripts/compare_metrics.py --left reports/diffs/bridge_guard_relaxed_metrics.json \
    --right runs/phase4/backtests_guard_relaxed/USDJPY_bridge_20251017_112729/metrics.json \
    --out-json reports/diffs/bridge_guard_relaxed_metrics_next.json
  ```

  Conservative/Bridge 両モードとも 8 トレード（勝率 12.5% / Sharpe≈-5.02）まで発火し、`or_filter` ブロックが 278→208 件へ減少
  （mid 110 / high 60 / low 38）。`reports/diffs/or_filter_guard_relaxed_summary.json` / `.md` に RV 帯別の分布と
  推奨 `min_or_atr_ratio`（現状 0.10 / 0.12 / 0.16 から 0.08 / 0.10 / 0.14 への再調整案）を追記し、
  `reports/diffs/*_metrics_next.json` へメトリクス差分を保存。
  `analysis/or_filter_guard_relaxed_summary.py` は `--params-json` / `--base-drop` / `--floor` オプションに対応し、
  `params.json` からバンド閾値を読み込んで提案値を Markdown/JSON に出力できるよう更新。

- 2026-10-25: Day ORB 最適化バンドルを `scripts/run_daily_workflow.py` に統合し、データ監査→スイープ→Router構築→Paperリハーサル→承認レポートまでの自動判定を JSON へ記録できるよう整備。`configs/day_orb/optimization_bundle.yaml` / `configs/day_orb/paper_validation.yaml` を新設し、`scripts/generate_paper_validation.py` で `update_state --simulate-live` と `compare_metrics` の結果を集約。CI では `.github/workflows/day_orb_bundle.yml` と `ops/cron/day_orb_weekly.yaml` で dry-run/本番スケジュールを登録し、Go/No-Go 基準違反で失敗するよう更新。回帰として `tests/test_run_daily_workflow.py::test_day_orb_bundle_*` と `tests/test_update_state.py` に Paper リハーサル分岐の検証を追加した。

  代表コマンド:

  `python3 scripts/run_daily_workflow.py --day-orb-optimization --day-orb-config configs/day_orb/optimization_bundle.yaml --day-orb-dry-run --day-orb-output reports/day_orb/automation/day_orb_bundle_dry_run.json`

  `python3 scripts/run_daily_workflow.py --day-orb-optimization --day-orb-config configs/day_orb/optimization_bundle.yaml --day-orb-output reports/day_orb/automation/day_orb_bundle_live.json`

  `python3 scripts/generate_paper_validation.py --config configs/day_orb/paper_validation.yaml --out reports/day_orb/paper_validation.json`

  `python3 -m pytest tests/test_run_daily_workflow.py tests/test_update_state.py tests/test_generate_paper_validation.py`

- 2026-10-24: 最適化レビューの承認パケットを自動化。`scripts/generate_experiment_report.py` で best params / gate diagnostics / ポートフォリオテレメトリを Markdown+JSON へ整形し、`scripts/propose_param_update.py` で PR タイトル・本文・レビュー対象ドキュメント・state差分をまとめる CLI を実装。`tests/test_generate_experiment_report.py` / `tests/test_propose_param_update.py` を追加し、Go/No-Go チェックリスト / `docs/state_runbook.md` に作業手順を反映した。

  代表コマンド:

  `python3 scripts/generate_experiment_report.py --best reports/simulations/day_orb_core/best_params.json --gate-json reports/day_orb_core/gate_breakdown.json --portfolio runs/router_pipeline/day_orb_core/telemetry.json --out reports/experiments/day_orb_core_review.md --json-out reports/experiments/day_orb_core_review.json`

  `python3 scripts/propose_param_update.py --best reports/simulations/day_orb_core/best_params.json --report-json reports/experiments/day_orb_core_review.json --state-archive ops/state_archive/day_orb_core/USDJPY_conservative/proposal_20261024_diff.json --out docs/proposals/day_orb_core_20261024.md --json-out docs/proposals/day_orb_core_20261024.json`

  `python3 -m pytest tests/test_generate_experiment_report.py tests/test_propose_param_update.py`

- 2026-10-23: Day ORB パラメータスイープへポートフォリオ評価を統合。`scripts/run_param_sweep.py` の `--portfolio-config` と実験 YAML の `portfolio:` ブロックを解釈し、各トライアルの `result.json` にカテゴリ利用率 / VaR / 相関メトリクスを保存するよう更新。`scripts/select_best_params.py` はランキング JSON へポートフォリオ指標を残しつつ `reports/day_orb/<experiment>/portfolio_candidates.json` を自動生成し、下流の承認レポートで制約状況を確認できるようにした。`tests/test_run_param_sweep.py` / `tests/test_select_best_params.py` / `tests/test_router_pipeline.py` を拡張し、モックされた制約で VaR しきい値やカテゴリ予算が検証されることを確認。関連ドキュメント（`docs/plans/day_orb_optimization.md`, `docs/progress_phase4.md`）へ再現コマンドと指標読み取り手順を追記。

  代表コマンド:

  `python3 scripts/run_param_sweep.py --experiment configs/experiments/day_orb_core.yaml --search random --max-trials 4 --workers 1 --dry-run --portfolio-config configs/experiments/day_orb_core.yaml --out tmp/sweeps/day_orb_core_demo`

  `python3 scripts/select_best_params.py --experiment configs/experiments/day_orb_core.yaml --runs-dir tmp/sweeps/day_orb_core_demo --out tmp/sweeps/day_orb_core_demo/best_params.json --portfolio-out reports/day_orb/day_orb_core`

  `python3 -m pytest tests/test_run_param_sweep.py tests/test_select_best_params.py tests/test_router_pipeline.py`

- 2026-10-22: ユーザーのリセット要望に従い `runs/` 配下のシミュレーション成果物を全削除し、新規検証のための空インデックスを再生成。`rm -rf runs/*` 実行後に `python3 scripts/rebuild_runs_index.py --runs-dir runs --out runs/index.csv` を走らせ、ヘッダーのみの `runs/index.csv` を確認。`docs/task_backlog.md` と `state.md` にリセットログを追記し、次回以降のシミュレーションが新しい成果物パスを前提にするよう整理した。

  代表コマンド:

  `rm -rf runs/*`

  `python3 scripts/rebuild_runs_index.py --runs-dir runs --out runs/index.csv`

- 2026-10-20: Day ORB コア実験の探索パラメータと評価ハーネスを拡張。`configs/experiments/day_orb_core.yaml` に季節性スライスの全面展開と win rate / profit factor などの追加ガードを定義し、`schemas/day_orb_experiment.schema.json` を新設してスキーマコメントを更新した。`scripts/run_param_sweep.py` では per-trial `log.json` を集約し、成功と制約違反を同時に記録する dry-run を `runs/sweeps/day_orb_core` で再実行。`scripts/select_best_params.py` は Pareto front フィルタと `metrics_path` / `dataset_fingerprint` を含むランキング出力へ刷新し、モックテスト (`tests/test_run_param_sweep.py`, `tests/test_select_best_params.py`) で季節性フィルタと制約評価を検証した。

  代表コマンド:

  `python3 scripts/run_param_sweep.py --experiment configs/experiments/day_orb_core.yaml --search random --max-trials 50 --workers 4 --out runs/sweeps/day_orb_core --log-history --dry-run`

  `python3 scripts/select_best_params.py --experiment day_orb_core --runs-dir runs/sweeps/day_orb_core --top-k 5 --out reports/simulations/day_orb_core/best_params.json`

  `python3 -m pytest`

- 2026-10-19: Day ORB 実験履歴 JSON 12 件を `python3 -m json.tool` で形式検証し、`run_id` / `dataset_sha256` / `dataset_rows` / `command` の必須フィールドが揃っていることを確認。`scripts/log_experiment.py` の dry-run で JSON 生成内容と指紋（rows=523,743 / SHA256=e8155a79cab613b9a9d9c72b994328b114f32e4d4b7f354c106e55ab711e4dd1）を再確認し、`metrics.json` 欠損時と既存 JSON への二重投入時に stderr へ警告が出ることを観測した（`Missing metrics.json` / `Run JSON already exists`）。`scripts/recover_experiment_history.py --from-json` で Parquet を再生成し、12 行・SHA256=b82357608b887c9131889e5bb4a9fbbc9e36d201847a71f9e569853a5414f56c を記録。検証として `python3 -m pytest tests/test_log_experiment.py tests/test_recover_experiment_history.py` を CI コマンドセットへ追加。

  代表コマンド:

  `for f in experiments/history/runs/*.json; do python3 -m json.tool "$f"; done`

  `PYTHONPATH=. python3 scripts/log_experiment.py --run-dir runs/USDJPY_conservative_20250922_143631 --manifest-id day_orb_5m_v1 --mode conservative --commit-sha $(git rev-parse HEAD) --dry-run`

  `PYTHONPATH=. python3 scripts/log_experiment.py --run-dir runs/USDJPY_conservative_20250922_143631 --manifest-id day_orb_5m_v1 --mode conservative --commit-sha $(git rev-parse HEAD)`

  `PYTHONPATH=. python3 scripts/recover_experiment_history.py --from-json --parquet experiments/history/records.parquet`

  `sha256sum experiments/history/records.parquet`

  `PYTHONPATH=. python3 -m pytest tests/test_log_experiment.py tests/test_recover_experiment_history.py`

- 2026-10-18: 擬似ライブ更新ガード（[設計 §2.4](plans/day_orb_optimization.md#24-adaptive-update--rollback)）を実装し、`scripts/update_state.py --simulate-live` に VAR / 流動性 / パラメータ差分の制限とロールバック通知を統合。`docs/state_runbook.md` のフローを更新し、オーバーライド/通知ハンドオフ手順を追記した。

  代表コマンド:

  `python3 scripts/update_state.py --simulate-live --dry-run --max-delta 0.2 --var-cap 0.04 --liquidity-cap 5.0 --alert-mode auto --json-out out/state_update_preview.json`

  `python3 scripts/update_state.py --override-action disable --override-reason "phase4_maintenance" --dry-run`

  ドライランは `risk.var` / `risk.liquidity_usage` / `diff.updated` / `decision.status` / `decision.reasons` を含む JSON を出力し、`ops/state_archive/<strategy>/<symbol>/<mode>/<ts>_diff.json` に適用結果（`status=applied|preview|blocked` と `reason[]`）を残す。オーバーライド状態は `ops/state_archive/auto_adjust_override.json` で管理し、異常時は `notifications/emit_signal.py` 経由の `state_update_rollback` 通知が `ops/state_alert_latency.csv` / `ops/state_alerts.log` に記録される。Webhook 未設定時は `note=no_webhook_configured` のフォールバック行が残る。証跡リンクと運用フローは [docs/state_runbook.md#擬似ライブ更新フロー（scriptsupdate_statepy---simulate-live）](state_runbook.md#擬似ライブ更新フローscriptsupdate_statepy---simulate-live) を参照。

- 2026-10-17: Day ORB パラメータ最適化ループの初期版を整備。`configs/experiments/day_orb_core.yaml` を新設し、
  `python3 scripts/run_param_sweep.py --experiment configs/experiments/day_orb_core.yaml --search grid --max-trials 2 --dry-run --out runs/sweeps/day_orb_core_smoke`
  でマニフェスト差し替え・制約評価・季節性メトリクス出力を検証。続いて
  `python3 scripts/select_best_params.py --experiment configs/experiments/day_orb_core.yaml --runs-dir runs/sweeps/day_orb_core_smoke --top-k 3 --out reports/simulations/day_orb_core/best_params.json`
  を実行し、dry-run 設定でもランキング JSON が生成されること、`result.json` に Sharpe・最大DD・月次トレード件数の制約判定/スコア分解が残ることを確認。バックログ (`docs/task_backlog.md#p0-21-day-orb-optimisation-engine-bring-up-open`) と `state.md` に進捗を同期した。
- 2026-10-16: 実験履歴リポジトリ（[設計計画](plans/day_orb_optimization.md) §4.1）を立ち上げ、既存 Day ORB ラン 12 件を
  `experiments/history/runs/*.json` へ移行（バイナリアーカイブは GitHub Web UI で拒否されるため、Parquet は生成物扱いに変更）。
  `data/usdjpy_5m_2018-2024_utc.csv` の指紋は rows=523,743 /
  SHA256=e8155a79cab613b9a9d9c72b994328b114f32e4d4b7f354c106e55ab711e4dd1。

  代表コマンド:

  `python3 scripts/log_experiment.py --run-dir runs/USDJPY_conservative_20250922_143631 --manifest-id day_orb_5m_v1 --mode conservative --commit-sha $(git rev-parse HEAD) --dataset-sha256 e8155a79cab613b9a9d9c72b994328b114f32e4d4b7f354c106e55ab711e4dd1 --dataset-rows 523743 --command "python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --mode conservative --out-dir runs"`

  `python3 scripts/recover_experiment_history.py --from-json --json-dir experiments/history/runs --parquet experiments/history/records.parquet`

  ローカルで履歴 Parquet が必要になった場合は上記 `recover_experiment_history.py` を実行して再生成する。生成物は
  `.gitignore` により除外されるため、コミットするのは `runs/*.json` のみとする。

  検証: `python3 -m pytest tests/test_log_experiment.py tests/test_recover_experiment_history.py`

- 2026-10-15: `scripts/run_sim.py` が manifest 由来の RunnerConfig を `params.json` へ反映するよう調整し、`allow_low_rv` / `ev_mode` /
  `threshold_lcb` などのフィールドが `runs/index.csv` に正しく残ることを確認。再実行コマンドは以下の通り。

  `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/tmp/day_orb5m_ev_guard --json-out runs/tmp/day_orb5m_ev_guard/metrics.json --out-daily-csv runs/tmp/day_orb5m_ev_guard/daily.csv --no-auto-state`

  出力された `runs/tmp/day_orb5m_ev_guard/USDJPY_conservative_20251015_035143/params.json` では `allow_low_rv=true` / `ev_mode="off"`
  / `threshold_lcb=-10.0` を記録し、`runs/index.csv` 上でも `ev_mode=off` / `allow_low_rv=True` が反映された。メトリクスは 3 トレード・総損益
  -6.92 pips・Sharpe=-9.83 で、`metrics.json` の `runtime.ev_reject=0` と `daily.csv` の `ev_reject` 列がゼロで収束していることから EV ブロックが
  抑止されている。`python3 scripts/rebuild_runs_index.py --runs-dir runs --out runs/index.csv` で索引を更新し、構成差分と検証ログを
  `docs/task_backlog.md#p4-04-day-orb-シンプル化リブート` と本ドキュメントに追記。
- 2026-10-15: NY セッション高 RV の暴走を抑止するため `ny_high_rv_min_or_atr_ratio=0.34` を導入し、
  `runs/tmp/day_orb5m_ny_filter/USDJPY_conservative_20251015_041253` とガード無効版
  `runs/tmp/day_orb5m_baseline/USDJPY_conservative_20251015_041634` を比較。
  双方とも `records.csv` における `NY:narrow:high` バケットのトレード件数が 0 件であることを確認し
  （`python3 - <<'PY'` 集計ログ参照）、損失源だった高 RV バケットを完全に遮断できた。
  `analysis/ev_profile_summary.csv` / `analysis/hybrid_ev_stats.csv` の同バケット値を
  `alpha_avg=beta_avg=1.0`・`p_mean=0.5`・`observations=0` に更新し、将来の EV 再集計時に
  無取引扱いとして扱えるよう整備した。推奨パラメータは manifest / runner_config 双方に反映済み。
- 2026-10-17: Manifest と戦略ロジックを更新し、Tokyo 低 RV 許容の分岐を試験。`configs/strategies/day_orb_5m.yaml`
  に `runner.runner_config.allow_low_rv=true` / `min_or_atr_ratio=0.20` / `ny_high_rv_min_or_atr_ratio=0.30`
  / `tokyo_low_rv_micro_trend_min=0.10` を反映し、`strategies/day_orb_5m.DayORB5m` で Tokyo セッションのみ
  低 RV を許容する代わりに `micro_trend` の方向閾値（BUY: ≥0.1 / SELL: ≤-0.1）を追加。埋め込みマニフェストも
  `reports/portfolio_samples/router_demo/metrics/configs/strategies/day_orb_5m.yaml` へ同期。
  `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs --debug --debug-sample-limit 500000 --no-auto-state`
  を再実行し、新ラン `runs/USDJPY_conservative_20251017_005817` では 3 トレード（総損益 -6.92 pips）。
  `python3 scripts/summarize_strategy_gate.py --run-dir runs/USDJPY_conservative_20251017_005817 --json` の結果、
  `rv_filter=14,215` 件（`rv_band=low`）、`tokyo_low_rv_guard=5,608` 件、`or_filter=98` 件、`ny_high_rv_or_filter=29` 件を確認。
  回帰は `python3 -m pytest` で 417 passed / 5 skipped を維持。
- 2026-10-15: `runs/USDJPY_conservative_20251002_214013` を再生成して `scripts/summarize_strategy_gate.py` の JSON 集計を
  `reports/analysis/day_orb5m_20251002_gate_summary.json` / `reports/analysis/day_orb5m_20251002_gate_block_summary.json` に保存。
  `records.csv` ベースの件数は `router_gate=182,198`（86.4%）/`strategy_gate=28,623`（13.6%）で、
  ルーター拒否は全件が LDN/NY 以外の時間帯（UTC 08:00〜21:59 を除外）で発生、セッションガードが主因であることを確認した。
  `strategy_gate` 側は 28,240 件が `rv_filter`（`rv_band=low`・`allow_low_rv=False`）、331 件が `or_filter`
  （`or_atr_ratio` 平均 0.212、上限 0.2499）で、`min_or_atr_ratio=0.25` の閾値ぎりぎりで除外されている。
  `params.json` には `allow_low_rv=false` が残っており（manifest の `runner.allow_low_rv` が `runner_config` に連動していない）、
  低 RV 帯が意図せず遮断されていることも判明した。【F:reports/analysis/day_orb5m_20251002_stage_counts.json†L1-L16】【F:reports/analysis/day_orb5m_20251002_gate_summary.json†L1-L24】【F:runs/USDJPY_conservative_20251002_214013/params.json†L18-L24】
  次ステップでは以下を実施する：
  - Manifest を調整して `runner.runner_config.allow_low_rv=true` / `size_floor_mult=0.05` を反映し、低 RV 帯の拒否を解消する。
  - `min_or_atr_ratio` を 0.20（NY 高 RV 用は 0.30 相当）へ一旦引き下げ、`scripts/summarize_strategy_gate.py` で OR 閾値
    切り下げ後の分布を比較する。
  - ルーターの `allowed_sessions` に TOK を含めるトライアルを行い、`strategies/day_orb_5m.DayORB5m` へ
    「Tokyo 時間のみ低 RV を許容し、`micro_trend` ≥ 0.1 を要求する」仮ロジックを追加してセッション別の挙動を分岐させる。
  - 検証コマンド：`python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs --debug --debug-sample-limit 500000 --no-auto-state`
    の再実行と、`python3 scripts/summarize_strategy_gate.py --run-dir runs/<new_run_id> --json` による再集計、
    `python3 -m pytest` の回帰確認。
  - 変更内容は `docs/task_backlog.md#p4-04-day-orb-シンプル化リブート` に紐付け、次セッションでパラメータ変更とロジック更新を実装する。
-## ハイライト（2026-08-19 更新）
- 2026-08-19: Guard-relaxed Day ORB を 2018–2025 全期間で Conservative / Bridge 両モードに走らせ、
  `runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251014_051935` と
  `runs/phase4/backtests_guard_relaxed/USDJPY_bridge_20251014_052447` に成果物を保存。
  いずれも 3 トレード・勝率0%・総損益 -4.91 pips（Sharpe≈-5.55）と引き続き負圧であるものの、
  `reports/diffs/conservative_guard_relaxed_metrics.json` /
  `reports/diffs/bridge_guard_relaxed_metrics.json` で基準ランとの差分を確保し、
  `reports/diffs/*_strategy_gate.json` には `or_filter` が 449 回（rv_band: high 246 / mid 162 / low 41）発生したことを記録した。
- 2026-08-18: Phase4 ガード調整用に `configs/strategies/day_orb_5m_guard_relaxed.yaml` を作成。`or_n=4` / `min_or_atr_ratio=0.18`
  / `allowed_sessions=[TOK,LDN,NY]` の試験マニフェストでフォールバックサイジングの挙動を保ったままセッション・ATR
  緩和の影響を計測できるようにした。`docs/todo_next.md` / `docs/task_backlog.md` / `state.md` と連携し、`scripts/summarize_strategy_gate.py`
  を用いたブロック理由比較と `scripts/compare_metrics.py` での Conservative / Bridge 差分取得を次ステップとして準備。
- Conservative / Bridge の 2018–2025 ロングランを `validated/USDJPY/5m.csv` で再実行し、`reports/long_{mode}.json` / `_daily.csv` を更新。`runs/phase4/backtests/USDJPY_conservative_20251013_061258` / `USDJPY_bridge_20251013_061509` に `session.log`・`metrics.json`・`daily.csv` を保存し、Sharpe / 最大DD / 勝率が依然として負圧であることを確認（Conservative: Sharpe=-7.79, win_rate=18%、Bridge: Sharpe=-7.17, win_rate≈21.8%）。
- 2026-08-10: `scripts/run_sim.py` が ランディレクトリ配下へ `checksums.json` を生成し、`metrics.json` / `daily.csv` / `records.csv` / `params.json` の SHA256 を自動記録。`session.log` にもダイジェストを埋め込み、Phase4 計画 W1 Step6 の証跡保存をワンコマンド化した。
- `scripts/run_sim.py` が `--out-dir` 実行時に `session.log` を自動生成し、コマンドライン・開始/終了時刻・CSVローダ統計・stderr警告を Run ディレクトリへ保存できるようにした。W1 Step5 のログ保全フローをコード化し、`tests/test_run_sim_cli.py::test_run_sim_session_log_records_aggregate_ev_failure` / `::test_run_sim_creates_run_directory` で回帰。
- `reports/diffs/README.md` を新設し、Phase4 ゴールドラン比較用の diff アーティファクト格納規約と `scripts/compare_metrics.py` 実行例を明文化。
- 自動 state 再開時に設定ハッシュ不一致でも `loaded_state` が出力されてしまう誤報告を解消し、メトリクス JSON が実際に復元した時のみパスを記録するよう `scripts/run_sim.py` / Runner ライフサイクルを修正した（`tests/test_run_sim_cli.py::test_run_sim_cli_omits_loaded_state_on_mismatch` で回帰を追加）。
- `validated/USDJPY/5m.csv` の指紋を記録（579,578 行 / SHA256=85fa08f2224eb6119878f3689a5af617cb666eaab37c5acb7e3603c4bfda48d4）し、`state.md` と同期した。
- 2026-10-26: `tail -n 1 validated/USDJPY/5m.csv` で終端 `2025-10-02T22:15:00` を再確認し、`python3 scripts/check_data_quality.py --csv validated/USDJPY/5m.csv --calendar-day-summary --fail-under-coverage 0.995 --fail-on-duplicate-groups 5` を再実行。`coverage_ratio=0.7108490774310342`（週末/祝日ギャップ起因）のため監査は既定閾値未達で非ゼロ終了だが、行数・SHA256・終端タイムスタンプは据え置き。
- `docs/progress_phase4.md#バグトラッキング` にバグノートのテーブル雛形を追加し、W0 の共有テンプレート整備を完了した。
- `scripts/compare_metrics.py` を新設し、長期ランの `metrics.json` 差分をトレラントに比較できる CLI / JSON レポート出力を整備。Pytest で回帰を追加し、Diff ツール欠如リスクを解消した。
- `scripts/run_sim.py` に `--no-auto-state` / `--auto-state` フラグを追加し、フェーズ4長期ランを過去 state に依存せず再現できるようにした。`configs/strategies/day_orb_5m.yaml` は Bridge モードを併記し、`runs/phase4/backtests/` 配下へベースライン run を保存してパラメータ探索の足場を確保。
- 直近の `validated/USDJPY/5m.csv` が 2025-10-02 以降のみをカバーしていることを確認し、ベースライン結果（Conservative/Bridge 各 1 トレード・-1.50pips）と合わせてデータギャップを記録。2018–2024 の validated スナップショット補完を TODO に登録。
- [フェーズ4検証計画](plans/phase4_validation_plan.md) を策定し、P4-01〜P4-03 の評価軸・マイルストーン・再現コマンドを統合管理できるようにした。
- 長期バックテストの評価基準（Sharpe・最大DD・年間勝率）と再実行コマンドを明文化し、週次レビューでメトリクスを追記する運用を定義。
- 異常系テストのシナリオ棚卸しと CI 実行方針を整理し、`tests/test_data_robustness.py` 拡張時の着地点を共有。
- Go/No-Go チェックリスト更新の担当分解とログ化ルールを確定、モックレビューの証跡化手順を整備。
- Go/No-Go チェックリストを担当者・頻度・証跡列付きテーブルへ刷新し、判定ログを `docs/progress_phase4.md` に紐づける運用を定義。
- 2018–2025 通しの `validated/USDJPY/5m.csv` / `_with_header.csv` を再構築し、既存の短期スナップショットは `validated/USDJPY/5m_recent*.csv` へ退避。`scripts/check_data_quality.py` でギャップ/重複無し（週末ギャップ由来で coverage≈0.71）を確認。

## データ指紋（2026-08-03 更新）
- `validated/USDJPY/5m.csv` — rows=579,578 / SHA256=85fa08f2224eb6119878f3689a5af617cb666eaab37c5acb7e3603c4bfda48d4（2018-01-01T00:00:00Z〜2025-10-02T22:15:00Z）。
- 対応するヘッダ付きスナップショットは現時点で存在しないため、ヘッダが必要な検証では `scripts/run_sim.py --strict` を併用しつつ、既存のヘッダレス CSV を読み込む。
- 長期ラン成果物の索引（計画済みパス）: [`runs/phase4/backtests/index.csv`](../runs/phase4/backtests/index.csv) — 初回ゴールドラン確定後に生成する index で、W0/W1 の基準 run を記録する際はこのファイルへの permalink を併記する。

## バグトラッキング
| Bug ID | Date Logged | Symptom Summary | Impact | Status | Regression Test | Artefact Link | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TBD-001 | 2026-08-03 | Auto-state resume dropped metrics/EV history causing reruns to report zero trades | High | Resolved | tests/test_runner.py::test_auto_state_resume_preserves_metrics_and_skips_processed_bars | runs/phase4/backtests/resume_q1/USDJPY_conservative_20251013_023742/metrics.json | Backtest WG |
| TBD-002 | 2026-08-04 | Auto-state fingerprint mismatches still reported `loaded_state` in metrics JSON even when state was skipped | Medium | Resolved | tests/test_run_sim_cli.py::test_run_sim_cli_omits_loaded_state_on_mismatch | - | Backtest WG |
| TBD-003 | 2026-08-09 | Lowercase CSV symbols were filtered out, leaving manifests with empty runs | Medium | Resolved | tests/test_run_sim_cli.py::test_run_sim_handles_lowercase_symbol_feed | - | Backtest WG |

_2026-08-12 review_: Confirmed W2 バグ掃討後のノートを再確認し、High インパクトの未解決項目は存在しない。`TBD-001`〜`TBD-003` はいずれも回帰テストでガードされ、長期ランの再実行でも再発していないことを `session.log` / diff アーティファクトで確認済み。

## 設計・テスト方針ログ
- 2026-08-08: `scripts/compare_metrics.py` に webhook 通知オプション（`--webhook-url` / `--webhook-url-env` / `--webhook-timeout` / `--dry-run-webhook` / `--fail-on-webhook-error`）を追加し、差分検出時に自動アラートが飛ばせるようにした。`tests/test_compare_metrics.py` へ webhook 配信と設定解決の回帰を追加し、`python3 -m pytest tests/test_compare_metrics.py` を実行してガードを確認。プラン §5.5 と Open Question #4 を更新。
- 2026-08-12: Day ORB シンプル化リブート向けに Runner が `loss_streak` / `daily_loss_pips` / `daily_trade_count` をコンテキストへ供給するよう拡張し、`strategies/day_orb_5m.DayORB5m` は EV を再稼働させずに（`ev_mode=off` / `auto_state=false` / `aggregate_ev=false` / `use_ev_profile=false`）連敗・日次DD・日次トレード数ガードを判定するフローへ更新。`configs/strategies/day_orb_5m.yaml` の ATR 比率/TP・SL 比とクールダウンを緩和し、`python3 -m pytest` で回帰を確認。次ステップのロングラン検証コマンド例: `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --symbol USDJPY --mode conservative --no-auto-state`（マニフェスト側で `aggregate_ev=false` / `use_ev_profile=false` / `ev_mode=off` を維持）。
- 2026-08-13: Day ORB のガード挙動を観測できるよう `_last_gate_reason` にクールダウン・日次シグナル上限・ATR帯・マイクロトレンド・サイズ失敗の詳細を記録するロジックを追加し、`tests/test_day_orb_retest.py` で EV オフ前提のブロック理由回帰を整備。シンプル化リブート中でも EV プロファイルを再稼働させずに停止要因を把握できる体制を確認。
- 2026-08-14: `EntryGate` が戦略ゲート失敗時に `_last_gate_reason` を `strategy_gate` デバッグレコードへそのまま展開するよう調整し、連敗・日次損失・ATR 帯・マイクロトレンド・サイズ情報を EV 無効化のまま `records.csv` で追跡可能にした。`tests/test_runner.py::test_strategy_gate_metadata_includes_day_orb_guards` で回帰、`docs/backtest_runner_logging.md` にフィールド一覧を追記。
- 2026-08-15: `scripts/run_sim.py` に `--debug` / `--debug-sample-limit` を追加し、Day ORB シンプル化リブート検証を EV 無効化のままでも `strategy_gate` レコード付きで実行できるようにした。さらに `scripts/summarize_strategy_gate.py` を新設し、`records.csv` からブロック理由を集計するサマリーを生成。`tests/test_run_sim_cli.py::test_run_sim_debug_records_written` と `tests/test_summarize_strategy_gate.py` で CLI/集計の回帰を整備し、閾値チューニング前の観測系を強化。
- 2026-08-05: Phase4 diff ワークフローを `reports/diffs/README.md` にまとめ、W1 Step 4/7 のエビデンス保存手順（メトリクス diff・日次 CSV 変換補助スクリプト・ハッシュ記録フロー）を整理。バックログ/State 連携も更新。
- 2026-08-03: `scripts/compare_metrics.py` を追加し、`--ignore state_loaded` などのグロブ指定・絶対/相対トレランス・JSON レポート出力に対応させた。`python3 -m pytest tests/test_compare_metrics.py` を実行し、W0 の Diff ツール整備項目を完了。さらに `scripts/manage_task_cycle.py --dry-run start-task --anchor docs/task_backlog.md#p4-01-長期バックテスト改善` を実行し、In Progress 昇格フローを確認。
- 2026-07-05: `configs/strategies/day_orb_5m.yaml` に Bridge モードを追加し、`scripts/run_sim.py --no-auto-state` で Conservative/Bridge のベースラインを `runs/phase4/backtests/` に保存。最新 `validated/USDJPY/5m.csv` が 2025 年 10 月以降のみであることを確認し、2018–2024 の validated データ再発行を TODO に登録。
- 2026-07-15: `data/usdjpy_5m_2018-2024_utc.csv` / `data/usdjpy_5m_2025.csv` / 既存の短期スナップショットをマージし、`validated/USDJPY/5m.csv`（ヘッダ無し）と `validated/USDJPY/5m_with_header.csv`（ヘッダ有り）を更新。従来の短期ビューは `validated/USDJPY/5m_recent*.csv` へ退避し、`scripts/check_data_quality.py --calendar-day-summary` 実行でギャップが週末・祝日由来であることを確認（coverage_ratio=0.71）。
- 2026-06-27: `docs/plans/phase4_validation_plan.md` を新設。長期バックテスト改善・異常系テスト自動化・Go/No-Go チェックリスト確定の3ストリームについて、評価軸、検証コマンド、アーティファクト更新ルール、週次マイルストーン、リスク対応を定義した。
- 2025-10-11: EV プロファイル更新手順を `scripts/aggregate_ev.py` で確認し、Conservative/Bridge 双方の比較材料を整備。

## 異常系テスト
### 現状カバレッジ
- `tests/test_data_robustness.py` を追加し、以下の異常ケースを検証済み。
  - 必須カラム欠損行を含むデータでも Runner が落ちないことを確認。
  - スプレッド急拡大（5.0pips）時にトレードを発行せず安全側に振る挙動をテスト。

### 追加設計（2026-06-27 更新）
- データ欠損（連続1時間欠損）、異常ボラティリティ（3σ超ジャンプ）、レイテンシ遅延、状態ロード不整合などのシナリオを pytest parametrize で追加予定。
- ダミーデータ生成ユーティリティを `tests/fixtures/data_quality.py`（予定）へ共通化し、テストケース間で再利用する。
- CI では `pytest -k robustness --maxfail=1` を最小セットとして実行し、Slack通知（擬似）ログで失敗を検知できるようにする。

### 再現コマンド
- `python3 -m pytest tests/test_data_robustness.py`
- （スモーク）`python3 -m pytest -k robustness --maxfail=1`
- フェーズ4長期ラン（state 自動ロード無効化）: `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode <mode> --start-ts 2018-01-01T00:00:00Z --end-ts 2025-12-31T23:55:00Z --out-json reports/long_<mode>.json --out-daily-csv reports/long_<mode>_daily.csv --out-dir runs/phase4/backtests --no-auto-state`

## 長期バックテスト
### 現状サマリ（2026-10-27 更新）

- 2026-10-27: Guard-relaxed マニフェスト（`min_or_atr_ratio=0.16`、
  `rv_band_min_or_atr_ratio={high:0.10, mid:0.12, low:0.16}`）を Conservative / Bridge 両モードで再実行
  (`runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251018_011918` /
  `USDJPY_bridge_20251018_012216`) し、`trades=8`・`total_pips=-14.38`・`sharpe=-5.02`（両モード共通）のまま
  ガード挙動を再集計。
  `loss_streak_guard` / `daily_loss_guard` は引き続き発火 0 件、
  `or_filter` は 208 件（`rv_band=mid` 110 件 / `high` 60 件 / `low` 38 件、
  `min_or_atr_ratio` 平均 ≈0.1215・範囲 0.10–0.16）まで減少した。
  集計結果を `reports/diffs/conservative_guard_relaxed_guard_stages.json` /
  `reports/diffs/bridge_guard_relaxed_guard_stages.json` に保存し、
  `reports/diffs/guard_stage_summary.json` と
  [Markdown 版](../reports/diffs/guard_stage_summary.md) を更新。
  - Next: OR フィルタ 208 件の内訳（mid/high 帯 81.7%）を踏まえ、
    `rv_band_min_or_atr_ratio` をさらに緩める案（例: high=0.08, mid=0.10, low=0.14）と
    `max_loss_streak` / `max_daily_loss_pips` を上げたフォローオンテストをサンドボックス化し、
    次の長期ラン候補とする。
- 2026-10-19: RV 帯別 `min_or_atr_ratio` 導入後のガード動作を最新 rerun
  (`runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251017_060706` /
  `USDJPY_bridge_20251017_061157`) で再集計。
  `loss_streak_guard` / `daily_loss_guard` は両モードとも発火 0 件、
  `or_filter` は 278 件（`rv_band=mid` 137 件 / `high` 100 件 / `low` 41 件）で据え置きだった。
  集計結果を `reports/diffs/guard_stage_summary.json` と
  [Markdown 版](../reports/diffs/guard_stage_summary.md) に保存し、
  ガード別の稼働状況を共有。
  - Next: OR フィルタ 278 件のうち高・中 RV 帯を中心に再緩和案
    （例: high=0.10, mid=0.12）を試算し、`loss_streak_guard` / `daily_loss_guard`
    が有効に働く閾値（`max_loss_streak=2` / `max_daily_loss_pips=80` 等）の
    サンドボックス検証を行う。
- 2026-10-19: Guard-relaxed マニフェストに RV 帯別 `min_or_atr_ratio`
  （high=0.12 / mid=0.14 / low=0.18）を導入したうえで Conservative / Bridge の
  デバッグランを再実行。`python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m_guard_relaxed.yaml --csv validated/USDJPY/5m.csv --symbol USDJPY --mode conservative --out-dir runs/phase4/backtests_guard_relaxed --no-auto-state --debug --debug-sample-limit 600000`
  と `--mode bridge` で `runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251017_050450` / `USDJPY_bridge_20251017_050746`
  を取得し、`total_pips=-4.91`・`win_rate=0`・`sharpe=-5.55` は従来と同水準ながら
  `or_filter` は 278 件に減少（`rv_band=mid` 137 件 / `high` 100 件 / `low` 41 件、
  `min_or_atr_ratio` 平均 ≈0.1387・最小 0.12・最大 0.18）。
  `reports/diffs/conservative_guard_relaxed_strategy_gate.json` / `bridge_guard_relaxed_strategy_gate.json`
  と [reports/diffs/or_filter_guard_relaxed_summary.md](../reports/diffs/or_filter_guard_relaxed_summary.md)
  ・[JSON](../reports/diffs/or_filter_guard_relaxed_summary.json) を更新し、
  RV 帯別緩和が Tokyo 低RVブロック以外の `or_filter` に効いていることを確認。
- 2026-10-18: `analysis/or_filter_guard_relaxed_summary.py` で guard-relaxed ランの `or_filter` 449 件を再集計し、
  `rv_band=high` が 246 件 (54.8%)、`mid` が 162 件 (36.1%)、`low` が 41 件 (9.1%) と判明。
  全件で `min_or_atr_ratio` は 0.18 に張り付き、実際の `or_atr_ratio` は平均 ≈0.093（最小 0 / 最大 0.179）。
  レポートを [reports/diffs/or_filter_guard_relaxed_summary.md](../reports/diffs/or_filter_guard_relaxed_summary.md)
  と [JSON](../reports/diffs/or_filter_guard_relaxed_summary.json) に保存し、次イテレーションでは RV 帯別に
  `min_or_atr_ratio` を段階化（例: high=0.12, mid=0.14, low=0.18）したうえで、連敗・日次損失ガードも含めた
  追加調整案を検証する。
- 2026-08-19: Guard-relaxed マニフェストでのロングランは Conservative / Bridge とも 3 トレード発生したが、
  `total_pips=-4.91`・`win_rate=0`・`sharpe=-5.55` と依然赤字。
  `reports/diffs/conservative_guard_relaxed_metrics.json` と `reports/diffs/bridge_guard_relaxed_metrics.json` にメトリクス差分を保存し、
  `reports/diffs/conservative_guard_relaxed_strategy_gate.json` では `or_filter` が 449 回（平均 `or_atr_ratio` ≈0.093、最大 0.179）発生、
  Router 側ブロックは確認されなかった。
  次フェーズでは `min_or_atr_ratio` 帯ごとのヒット率を分析し、追加緩和と代替ガード（連敗・日次損失）調整案を策定する。
- 2026-08-18: セッション緩和 + ATR 閾値緩和の比較用に `day_orb_5m_guard_relaxed.yaml` を追加。`or_n=4` / `min_or_atr_ratio=0.18`
  / `allowed_sessions=[TOK,LDN,NY]` を採用し、EV 無効 + フォールバックサイジング状態で Conservative / Bridge 両モードのロングラン
  差分を取得できるよう整備。次手順として `scripts/summarize_strategy_gate.py` で Tokyo/LDN/NY 別ブロック割合を比較し、`reports/diffs/`
  に `scripts/compare_metrics.py` 出力を保存する準備を完了。
- 2026-10-22: Bayes 探索パイプラインを `scripts/run_param_sweep.py` に実装し、`configs/experiments/day_orb_core.yaml` へ `bayes` スキーマ例を追加。`scripts/select_best_params.py` でも `search_metadata` を保持するよう更新し、回帰コマンド `python3 -m pytest tests/test_run_param_sweep.py tests/test_select_best_params.py` を完走してログとサマリの両方で Bayes メタ情報が残ることを確認。
- 2026-08-17: Runner サイジングゲートへ EV オフ時のフォールバック（`fallback_win_rate` / `size_floor_mult`）を実装し、`tests/test_runner.py::test_sizing_gate_ev_off_uses_fallback_quantity` でゼロ数量を防止する回帰を追加。Phase4 シンプル化リブート検証でも EV 無効のままロットが算出できる状態を確認し、`docs/todo_next.md`・`docs/task_backlog.md`・`state.md` を同期。
- 2026-08-16: 2025-01-01〜2025-10-13 のデバッグ run を `scripts/summarize_strategy_gate.py` で解析し、`gate_block=19,091` 件が Tokyo セッション由来の `router_gate`、`strategy_gate=41` 件が `min_or_atr_ratio` 超過、`zero_qty=248,230` 件が EV オフ時の Kelly サイジング失敗であることを確認。改善案（セッション緩和 / ATR 閾値調整 / Runner 側フォールバック導入）を [reports/simulations/day_orb5m_20251013_summary.md](../reports/simulations/day_orb5m_20251013_summary.md) に追記し、次ステップを `docs/todo_next.md`・`docs/task_backlog.md` へ連携した。
- 2025-10-13: Manifest 既定条件（EV 無効・auto_state=false）で再実行したところ、Conservative / Bridge ともに `gate_block` 196,554 件・`zero_qty` 248,230 件によりトレード 0 件となった。詳細は [reports/simulations/day_orb5m_20251013_summary.md](../reports/simulations/day_orb5m_20251013_summary.md) を参照。
- 2018-01-01T00:00:00Z〜2025-12-31T23:55:00Z のロングランを Conservative / Bridge の両モードで再取得した結果（2026-08-07 時点、`runs/phase4/backtests/USDJPY_conservative_20251013_061258` / `runs/phase4/backtests/USDJPY_bridge_20251013_061509`）、Sharpe・勝率ともに依然としてマイナス圏であり調整余地が大きい。
- 直近データだけの分析用途は `validated/USDJPY/5m_recent*.csv`（91 行）へ切り出し済み。長期検証は `validated/USDJPY/5m.csv` を使用する。
- `scripts/check_data_quality.py --csv validated/USDJPY/5m.csv --calendar-day-summary` の結果、週末・祝日ギャップのみ検出（coverage_ratio=0.71, duplicates=0）。必要に応じて日次しきい値を調整して監視する。

| Mode | Trades | Wins | Win Rate | Sharpe | Max Drawdown | Run Dir |
| --- | --- | --- | --- | --- | --- | --- |
| Conservative | 0 | 0.00 | — | — | — | — | `runs/tmp/day_orb5m_20251013_conservative/USDJPY_conservative_20251013_230922` |
| Bridge | 0 | 0.00 | — | — | — | — | `runs/tmp/day_orb5m_20251013_bridge/USDJPY_bridge_20251013_231150` |

### 改善計画（2026-08-07 更新）
- 日次 Sharpe ≥ 0.15 / 最大DD ≥ -8% / 年間勝率 ≥ 52% を暫定目標とし、Bridge/Conservative 双方で達成する。
- `threshold_lcb_pip`・`alpha_prior`・`or_n` を中心にパラメータ探索し、各トライアルを `runs/phase4/backtests/<timestamp>_<mode>_<paramset>/` に保存して比較。
- ベースコマンド：
  - `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode <mode> --start-ts 2018-01-01T00:00:00Z --end-ts 2025-12-31T23:55:00Z --out-json reports/long_<mode>.json --out-daily-csv reports/long_<mode>_daily.csv --out-dir runs/phase4/backtests --no-auto-state`
- 週次レビューで `docs/progress_phase4.md` にメトリクス表を追記し、改善度合いをトラッキングする。
- 成果反映前に `python3 -m pytest tests/test_runner.py tests/test_runner_features.py` を実行し、既存回帰が破損していないかを確認する。

## 運用チェックリスト
- `docs/go_nogo_checklist.md` を作成し、Paper 移行前に確認すべき項目を整理。
  - データ品質・通知SLO・stateバックアップ・最適化結果レビューなどを含む。
- 2026-06-27: フェーズ4検証計画に沿って、チェック項目を「データ品質 / シミュレーション / 運用準備 / レビュー体制」に分類し、担当者・頻度・証跡リンク欄を追加予定。モックレビュー結果は本節でログ化する。
- 2026-07-15: チェックリストを担当者・実行頻度・証跡列付きテーブルへ更新。次の判定では各列を埋め、証跡リンクを記録すること。
- 2026-10-16: 運用チームで Paper Go/No-Go 再監査を実施。
  - データ品質監査：`python3 scripts/check_data_quality.py --csv validated/USDJPY/5m.csv ...` の結果、coverage_ratio=0.7108 と 0.995 の閾値を大幅に下回り NG（ログ: [paper_gate.log](../reports/data_quality/paper_gate.log)、サマリ: [paper_gate.json](../reports/data_quality/paper_gate.json)）。
  - Conservative / Bridge 再シミュレーション：両モードとも Sharpe=-9.83・MaxDD=-69.20 と判定基準未達（証跡: [Conservative session.log](../runs/go_nogo/conservative/USDJPY_conservative_20251016_095757/session.log)、[Bridge session.log](../runs/go_nogo/bridge/USDJPY_bridge_20251016_100035/session.log)、各 JSON: [go_nogo_conservative.json](../reports/go_nogo_conservative.json), [go_nogo_bridge.json](../reports/go_nogo_bridge.json)）。
  - 通知レイテンシ分析：`PYTHONPATH=. python3 scripts/analyze_signal_latency.py ... --rollup-output reports/latency_summary.csv` を実行し、p95=2100ms / failure_rate=0% と SLO 内（ログ: [analyze_signal_latency.log](../reports/analyze_signal_latency.log)、集計: [latency_summary.json](../reports/latency_summary.json)）。
  - 日次ワークフロー dry-run：`python3 scripts/run_daily_workflow.py --optimize --analyze-latency --archive-state --dry-run` は `auto_optimize.py` の JSONDecodeError で途中失敗（ログ: [daily_workflow_dry_run.log](../reports/daily_workflow_dry_run.log)）。`reports/auto_optimize.json` は未更新。
  - State アーカイブ確認：`python3 scripts/prune_state_archive.py --dry-run --keep 5` で Conservative 最新 5 件（20251002_214016.json〜20251005_132519.json）維持、63 件削除候補を確認（ログ: [state_archive_prune_dry_run.log](../reports/state_archive_prune_dry_run.log)）。Bridge 側は 20251004_104302.json のみ保管。
- 承認コメント: データ coverage と Sharpe/最大DD が閾値未達のため **No-Go** 判定。`auto_optimize.py` の JSON 出力異常も解消が必要。

## TODO (フェーズ4 継続)
- 長期バックテスト結果を改善するためのパラメータ再検討（Bridge/Conservativeともにマイナスのため）。
- 異常系テストを `pytest` で自動実行可能になるよう環境整備（新規シナリオのfixtures共通化、CI設定追加）。
- `docs/go_nogo_checklist.md` を実際の運用で更新し、承認履歴を残す（担当者・頻度・証跡リンク欄を整備）。
- Conservative 向け EV プロファイルを用いた `threshold_lcb_pip` 探索（0.25〜0.5 pip）と OR 窓幅 (`or_n`) の感度分析を分割ランで実施、結果を `reports/long_conservative*.json` 系へ反映。
- 新しい 2018–2025 通しデータで Conservative/Bridge の長期ランを再実行し、Sharpe/最大DD/年間勝率を更新。必要に応じて `scripts/check_data_quality.py` の coverage しきい値を週末ギャップ想定に合わせて調整する。

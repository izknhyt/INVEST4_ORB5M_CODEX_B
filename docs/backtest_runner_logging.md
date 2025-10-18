# Backtest Runner Logging Reference

> ⚠️ 2026-04-05 の CLI 簡素化で `--dump-csv` / `--dump-daily` フラグは削除されました。本ノートは Runner のデバッグカウンタ/レコード構造を説明する目的で残しており、実際の出力は `run_sim.py --manifest ... --out-dir <dir>` で生成される `records.csv` / `daily.csv`（manifest 側で有効化した場合）か、`--out-daily-csv <path>` で直接エクスポートした日次サマリに対応させてください。

This note documents how `BacktestRunner` evaluates signals and how to interpret the artifacts historically exposed via dump outputs.

## Lifecycle / execution split

`BacktestRunner` now composes two helper classes so the logging workflow stays focused on reporting:

* `core.runner_lifecycle.RunnerLifecycleManager` resets runtime metrics, restores persisted state, and seeds EV/slip learning before every run. Methods such as `_reset_runtime_state`, `export_state`, and `load_state` simply delegate to the lifecycle manager, which keeps the snapshot logic in one place.
* `core.runner_execution.RunnerExecutionManager` owns the trade lifecycle. Entry evaluation (`_maybe_enter_trade`), fill handling (`_process_fill_result`), and exit processing (`_handle_active_position`) all call into the execution manager. The manager updates daily aggregates, EV pools, and debug records so existing CSV/JSON outputs remain unchanged.

Tests (`tests/test_runner.py::test_runner_delegates_to_lifecycle_and_execution_managers`, `tests/test_run_sim_cli.py::test_run_sim_respects_time_window`) assert that CLI entrypoints still route through the managers. When troubleshooting logs, continue to inspect `BacktestRunner.metrics`—the delegation is transparent to downstream tooling.

## Decision flow (`strategy_gate` → `ev_threshold` → EV → sizing)

`RunnerExecutionManager` first calls `Strategy.get_pending_signal()` after invoking `Strategy.on_bar`. Strategies that buffer the latest setup should expose it through this accessor so the runner never touches private attributes such as `_pending_signal` directly.

1. **Strategy gate hook** – When a pending signal exists, `BacktestRunner` calls `strategy_gate(ctx, pending)` if the strategy exposes it. Hook errors are counted under `strategy_gate_error` and recorded with the `strategy_gate_error` stage so the run never aborts.
2. **Router gate** – If the hook allows the trade, the shared `pass_gates` router validates spread, RV bands, and ATR ratio. Any block increments `gate_block` and produces a `gate_block` record with `reason="router_gate"`.
3. **Strategy EV threshold hook** – The runner resolves a per-signal EV floor via `ev_threshold(ctx, pending, threshold)` when available. Failures increment `ev_threshold_error` and fall back to the CLI threshold.
4. **EV check** – With the resolved threshold the pooled EV manager computes `ev_lcb`. If the run is warming up the trade bypasses EV (`ev_bypass`) and logs the warm-up counters, otherwise the trade is rejected (`ev_reject`) and an `ev_reject` record is emitted.
5. **Slippage guard** – The expected slip estimate is compared with `slip_cap_pip`. When exceeded the trade is blocked (`gate_block`) and a `slip_cap` record is added.
6. **Sizing preview** – Before requesting real orders the runner mirrors the sizing helper. If the computed size is zero it increments `zero_qty`.
7. **Order emission** – Successful intents are filled through the configured fill engine. Immediate fills add a `trade` record, while carried positions log a `trade_exit` record when they close.

## Debug counter keys

| Counter key | Description |
| --- | --- |
| `no_breakout` | Strategy produced no pending signal on that bar. |
| `gate_block` | Blocked either by the shared router or a slippage cap. |
| `ev_reject` | EV lower confidence bound fell below the active threshold. |
| `ev_bypass` | Warm-up bypass that still advanced EV statistics. |
| `zero_qty` | Sizing preview produced zero quantity. |
| `strategy_gate_error` | Exception raised by the strategy gate hook; runner continued with a permissive fallback. |
| `ev_threshold_error` | Exception or non-finite value returned by the EV threshold hook; fell back to the CLI threshold. |

Regression coverage: `tests/test_run_sim_cli.py::test_run_sim_debug_records_capture_hook_failures` boots the CLI with a
deterministic failure strategyを用いて JSON サマリと `records.csv` のサンプルレコード（`--out-dir` 経由で生成）に
debug カウンタが正しく記録されることを確認しています。

## Debug record stages and fields

`run_sim.py --manifest ... --out-dir <dir>` で生成される `records.csv` には、実行されたトレードに対応する `debug_records`
が連結されます。主要なステージごとに以下のフィールドが出力されます。

| Stage | Fields |
| --- | --- |
| `no_breakout` | `ts` |
| `strategy_gate` | `ts`, `side`, `reason_stage`, `or_atr_ratio`, `min_or_atr_ratio`, `rv_band`, `allow_low_rv`, `cooldown_bars`, `bars_since`, `signals_today`, `max_signals_per_day`, `loss_streak`, `max_loss_streak`, `daily_loss_pips`, `max_daily_loss_pips`, `daily_trade_count`, `max_daily_trade_count`, `atr_pips`, `min_atr_pips`, `max_atr_pips`, `micro_trend`, `min_micro_trend`, `qty`, `p_lcb`, `sl_pips` |
| `strategy_gate_error` | `ts`, `side`, `error` |
| `gate_block` | `ts`, `side`, `rv_band`, `spread_band`, `or_atr_ratio`, `reason` |
| `slip_cap` | `ts`, `side`, `expected_slip_pip`, `slip_cap_pip` |
| `ev_reject` | `ts`, `side`, `ev_lcb`, `threshold_lcb`, `cost_pips`, `tp_pips`, `sl_pips` |
| `ev_bypass` | `ts`, `side`, `ev_lcb`, `threshold_lcb`, `warmup_left`, `warmup_total`, `cost_pips`, `tp_pips`, `sl_pips` |
| `ev_threshold_error` | `ts`, `side`, `base_threshold`, `error` |
| `trade` | `ts`, `side`, `tp_pips`, `sl_pips`, `cost_pips`, `slip_est`, `slip_real`, `exit`, `pnl_pips` |
| `trade_exit` | `ts`, `side`, `cost_pips`, `slip_est`, `slip_real`, `exit`, `pnl_pips` |

2026-08-14 アップデート: Day ORB シンプル化リブートの監視強化として、`strategy_gate` レコードは連敗ガード (`loss_streak` / `max_loss_streak`)、日次損失・本数ガード、ATR 帯、マイクロトレンド、サイズ算出 (`qty` / `p_lcb` / `sl_pips`) など `_last_gate_reason` のサマリをすべて含むよう拡張した。EV を無効化したままでもブロック理由を `records.csv` から直接追跡できる。

Example: `tests/data/runner_sample_records.csv` contains the appended debug rows that match the table above, starting with `no_breakout` entries for the Tokyo session.【F:tests/data/runner_sample_records.csv†L1-L6】

## Daily roll-ups (`run_dir/daily.csv`)

`daily.csv` は `metrics.daily` の集計結果で、`breakouts`, `gate_pass`, `gate_block`, `ev_pass`, `ev_reject`, `fills`, `wins`, `pnl_pips` などの列を含みます。長期ランの例は `reports/long_conservative_daily.csv` を参照してください。【F:reports/long_conservative_daily.csv†L1-L5】

2026-07-16 の修正で、トレール決済（`exit_reason="trail"`）がコスト控除後もプラスで終わった場合は勝ちトレードとして `wins` / `win_rate` に加算され、同時に EV バケットも成功（`alpha` 増分）として更新されるよう統一しました。従来はトレールで利益確定しても負け扱いとなり EV 推定が不当に悪化していたため、日次サマリと `metrics.win_rate` の乖離に注意してください。

## Equity curve baseline

`Metrics` now seeds `equity_curve` with the runner's starting equity (paired with the first trade's timestamp) whenever `_reset_runtime_state` is invoked. The structure is a list of `[timestamp, equity]` pairs so downstream tools can align fills with the bar chronology. Each subsequent trade appends the updated account equity using the bar timestamp supplied to `record_trade`, ensuring drawdown and Sharpe calculations reference the same baseline even after state resets.

## Investigation workflow example (EV rejection)

1. **Check counter deltas** – `metrics.json` もしくは `daily.csv` を確認して `ev_reject` / `gate_block` のスパイクを把握する。
2. **Inspect debug slices** – `records.csv` を `stage == "ev_reject"` でフィルタし、EV 赤字と関連する TP/SL・コストを確認する。
3. **Trace the gating reason** – If `ev_reject` aligns with a recent surge in `strategy_gate` records (e.g., `reason_stage="rv_filter"`), combine both views to determine whether inputs such as RV calibration or OR quality are the root cause.
4. **Validate hook health** – Confirm that `strategy_gate_error` and `ev_threshold_error` remain zero; non-zero counts indicate the hooks are misconfigured and that fallback logic was used.
5. **Decide next steps** – Use the daily CSV to prioritize dates for reruns, then feed the filtered record set back into notebooks or notebooks that replay the offending window.

## 日本語サマリ

- `strategy_gate` → 共通ゲート → `ev_threshold` → EV 判定 → スリップ判定 → サイズ確認 → Fill という順で評価し、各段階で失敗理由をカウントとレコードに残す。
- `debug_counts` にはフック例外用の `strategy_gate_error` / `ev_threshold_error` を含め、`gate_block` がルーター/スリップ双方の遮断を表す。
- EV ウォームアップによるバイパスは `ev_bypass` レコードとして `warmup_left` / `warmup_total` を残し、ウォームアップ消化状況を CSV 上で追跡できる。
- `records.csv` は段階別の詳細を記録し、`daily.csv` は日別サマリ (`reports/long_conservative_daily.csv` 等) を提供する。
- EV リジェクト調査は日次サマリで異常を見つけ、`ev_reject` 行と `strategy_gate` 行の突合せで原因を掘り下げ、フックエラーの有無を確認する流れ。

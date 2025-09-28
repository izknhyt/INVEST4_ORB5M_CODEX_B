# Backtest Runner Logging Reference

This note documents how `BacktestRunner` evaluates signals and how to interpret the artifacts that appear when `--dump-csv` / `--dump-daily` are enabled.

## Decision flow (`strategy_gate` → `ev_threshold` → EV → sizing)

1. **Strategy gate hook** – When a pending signal exists, `BacktestRunner` calls `strategy_gate(ctx, pending)` if the strategy exposes it. Hook errors are counted under `strategy_gate_error` and recorded with the `strategy_gate_error` stage so the run never aborts.
2. **Router gate** – If the hook allows the trade, the shared `pass_gates` router validates spread, RV bands, and ATR ratio. Any block increments `gate_block` and produces a `gate_block` record with `reason="router_gate"`.
3. **Strategy EV threshold hook** – The runner resolves a per-signal EV floor via `ev_threshold(ctx, pending, threshold)` when available. Failures increment `ev_threshold_error` and fall back to the CLI threshold.
4. **EV check** – With the resolved threshold the pooled EV manager computes `ev_lcb`. If the run is warming up the trade bypasses EV (`ev_bypass`), otherwise the trade is rejected (`ev_reject`) and an `ev_reject` record is emitted.
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

## Debug record stages and fields

The CSV produced by `--dump-csv` appends `debug_records` after executed trades. Each stage only emits the fields listed below.

| Stage | Fields |
| --- | --- |
| `no_breakout` | `ts` |
| `strategy_gate` | `ts`, `side`, `reason_stage`, `or_atr_ratio`, `min_or_atr_ratio`, `rv_band`, `allow_low_rv` |
| `strategy_gate_error` | `ts`, `side`, `error` |
| `gate_block` | `ts`, `side`, `rv_band`, `spread_band`, `or_atr_ratio`, `reason` |
| `slip_cap` | `ts`, `side`, `expected_slip_pip`, `slip_cap_pip` |
| `ev_reject` | `ts`, `side`, `ev_lcb`, `threshold_lcb`, `cost_pips`, `tp_pips`, `sl_pips` |
| `ev_threshold_error` | `ts`, `side`, `base_threshold`, `error` |
| `trade` | `ts`, `side`, `tp_pips`, `sl_pips`, `cost_pips`, `slip_est`, `slip_real`, `exit`, `pnl_pips` |
| `trade_exit` | `ts`, `side`, `cost_pips`, `slip_est`, `slip_real`, `exit`, `pnl_pips` |

Example: `runs/USDJPY_conservative_20250922_175708/records.csv` contains the appended debug rows that match the table above, starting with `no_breakout` entries for the Tokyo session.【F:runs/USDJPY_conservative_20250922_175708/records.csv†L1-L4】

## Daily roll-ups (`--dump-daily`)

`--dump-daily` writes the aggregated daily counters from `metrics.daily`. Columns include `breakouts`, `gate_pass`, `gate_block`, `ev_pass`, `ev_reject`, `fills`, `wins`, and `pnl_pips`. See `reports/long_conservative_daily.csv` for a long-run example populated by the automation.【F:reports/long_conservative_daily.csv†L1-L5】

## Investigation workflow example (EV rejection)

1. **Check counter deltas** – Start with the JSON summary or `--dump-daily` CSV to spot spikes in `ev_reject` or `gate_block`.
2. **Inspect debug slices** – Filter the `--dump-csv` output for `stage == "ev_reject"` to review the EV deficit, associated TP/SL, and cost assumptions for the affected bars.
3. **Trace the gating reason** – If `ev_reject` aligns with a recent surge in `strategy_gate` records (e.g., `reason_stage="rv_filter"`), combine both views to determine whether inputs such as RV calibration or OR quality are the root cause.
4. **Validate hook health** – Confirm that `strategy_gate_error` and `ev_threshold_error` remain zero; non-zero counts indicate the hooks are misconfigured and that fallback logic was used.
5. **Decide next steps** – Use the daily CSV to prioritize dates for reruns, then feed the filtered record set back into notebooks or notebooks that replay the offending window.

## 日本語サマリ

- `strategy_gate` → 共通ゲート → `ev_threshold` → EV 判定 → スリップ判定 → サイズ確認 → Fill という順で評価し、各段階で失敗理由をカウントとレコードに残す。
- `debug_counts` にはフック例外用の `strategy_gate_error` / `ev_threshold_error` を含め、`gate_block` がルーター/スリップ双方の遮断を表す。
- `--dump-csv` はテーブルのフィールド構成で段階別の詳細を記録し、`--dump-daily` は日別サマリ (`reports/long_conservative_daily.csv` 等) を提供する。
- EV リジェクト調査は日次サマリで異常を見つけ、`ev_reject` 行と `strategy_gate` 行の突合せで原因を掘り下げ、フックエラーの有無を確認する流れ。

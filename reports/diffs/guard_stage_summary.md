# Guard-relaxed guard stage summary

Aggregated guard-stage metrics derived from the latest guard-relaxed reruns:
`runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251018_011918`
(conservative) and `runs/phase4/backtests_guard_relaxed/USDJPY_bridge_20251018_012216`
(bridge). Source JSON: [`reports/diffs/guard_stage_summary.json`](guard_stage_summary.json).

## Stage totals

| Mode | Stage | Blocks | Notes |
| --- | --- | ---: | --- |
| conservative | loss_streak_guard | 0 | No loss-streak shutdowns observed. |
| conservative | daily_loss_guard | 0 | No daily drawdown guard activations. |
| conservative | or_filter | 208 | All strategy gate rejections stem from the OR ATR filter. |
| bridge | loss_streak_guard | 0 | Matches conservative mode. |
| bridge | daily_loss_guard | 0 | Matches conservative mode. |
| bridge | or_filter | 208 | Identical distribution to conservative mode. |

## OR filter distribution

Both modes share the same RV-band breakdown for the 208 OR-filter rejections:

| RV band | Count | Share (%) |
| --- | ---: | ---: |
| mid | 110 | 52.88 |
| high | 60 | 28.85 |
| low | 38 | 18.27 |

All rejected bars carried `allow_low_rv=True`; the `min_or_atr_ratio` mean settled
at ≈0.1215 (range 0.10–0.16), reflecting the relaxed thresholds used in this run.

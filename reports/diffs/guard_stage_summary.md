# Guard-relaxed guard stage summary

Aggregated guard-stage metrics derived from the latest guard-relaxed reruns:
`runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251017_060706`
(conservative) and `runs/phase4/backtests_guard_relaxed/USDJPY_bridge_20251017_061157`
(bridge). Source JSON: [`reports/diffs/guard_stage_summary.json`](guard_stage_summary.json).

## Stage totals

| Mode | Stage | Blocks | Notes |
| --- | --- | ---: | --- |
| conservative | loss_streak_guard | 0 | No loss-streak shutdowns observed. |
| conservative | daily_loss_guard | 0 | No daily drawdown guard activations. |
| conservative | or_filter | 278 | All strategy gate rejections stem from the OR ATR filter. |
| bridge | loss_streak_guard | 0 | Matches conservative mode. |
| bridge | daily_loss_guard | 0 | Matches conservative mode. |
| bridge | or_filter | 278 | Identical distribution to conservative mode. |

## OR filter distribution

Both modes share the same RV-band breakdown for the 278 OR-filter rejections:

| RV band | Count | Share (%) |
| --- | ---: | ---: |
| mid | 137 | 49.28 |
| high | 100 | 35.97 |
| low | 41 | 14.75 |

All rejected bars carried `allow_low_rv=True`; the `min_or_atr_ratio` mean remained
≈0.1387 (range 0.12–0.18), matching the RV-band threshold targets.

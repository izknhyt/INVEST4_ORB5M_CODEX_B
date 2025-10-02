# USDJPY Drawdown Replay — 2025-10-02

## Loss Window
- Peak close: 2025-10-02T15:35:00Z at 147.50999 (validated/USDJPY/5m.csv)
- Trough close: 2025-10-02T19:20:00Z at 147.13099
- Net move: -0.37900 JPY (≈ -37.9 pips) over 3h45m
- Trigger: Max drawdown alert after repeated failures to reclaim 147.30 during NY handover

## Replay Checklist
1. Export validated bars with header (adds `timestamp,symbol,tf,o,h,l,c,v,spread` row) before feeding `scripts/run_sim.py`.
2. Execute the replay command recorded in `replay_params.json`.
3. Review outputs stored under `runs/incidents/USDJPY_conservative_20251002_230924/`:
   - [`metrics.json`](../../../runs/incidents/USDJPY_conservative_20251002_230924/metrics.json)
   - [`params.json`](../../../runs/incidents/USDJPY_conservative_20251002_230924/params.json)
   - [`records.csv`](../../../runs/incidents/USDJPY_conservative_20251002_230924/records.csv)
   - [`daily.csv`](../../../runs/incidents/USDJPY_conservative_20251002_230924/daily.csv)
4. Inspect `state.json` within the run folder for EV context captured during the replay.

## Observations
- Strategy closed 40/40 winning trades across the window (no realised drawdown) despite the price slide, indicating the simulated EV filters sidelined risk before the selloff accelerated.
- Gate diagnostics show four `gate_block` events and nineteen `ev_bypass` entries; further inspection is needed to confirm if router bands filtered the bearish signals too aggressively.
- Next steps: align the incident state snapshot (`ops/state_archive/day_orb_5m/USDJPY/conservative/20250924_121238_state.json`) with post-selloff EV updates once real fills become available.

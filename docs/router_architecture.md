# Router architecture and data flow

This note captures how the portfolio router evolves from the legacy v0 gate to the current v1 scoring stage, and what telemetry, manifests, and runtime metrics must feed the planned v2 features. The goal is to make it obvious which artefact owns each responsibility and where new category budgets, correlation guards, and execution health controls will plug in.

## Version responsibilities at a glance

| Version | Entry point | Primary responsibilities | Key inputs |
|---------|-------------|--------------------------|-----------|
| v0 | [`router/router_v0.pass_gates`](../router/router_v0.py) | Binary gating based on market context (session whitelist, spread band, RV band, news freeze). | `market_ctx` only. |
| v1 | [`router/router_v1.select_candidates`](../router/router_v1.py) | Merge manifest metadata, live telemetry, and signal quality to decide eligibility, apply soft penalties/bonuses, and emit ranked `SelectionResult` records. | `market_ctx`, manifests, [`PortfolioState`](../router/router_v1.py), strategy signals. |
| v2 (planned) | (TBD, reusing `select_candidates` API) | Layer category budget awareness, richer correlation suppression, and execution health escalation on top of v1 while remaining backwards compatible for callers of `select_candidates`. | Everything v1 consumes plus new budget/correlation/health fields described below. |

## Building portfolio context

`core/router_pipeline.build_portfolio_state` is the single place where strategy manifests, portfolio telemetry snapshots, and runner metrics are fused into the [`PortfolioState`](../router/router_v1.py) structure consumed by v1 and the future v2 router.【F:core/router_pipeline.py†L1-L127】 The helper expects three inputs:

1. **Manifests**: the iterable of `StrategyManifest` objects. Risk metadata such as `risk_per_trade_pct`, `router.priority`, `router.category_cap_pct`, `router.max_gross_exposure_pct`, `router.correlation_tags`, and guard thresholds (reject, slippage, correlation) are authoritative here.
2. **Telemetry**: optional [`PortfolioTelemetry`](../core/router_pipeline.py) snapshot (typically produced by `scripts/build_router_snapshot.py`). Expected fields:
   - `active_positions[strategy_id]` → open position counts (signed, v1 uses absolute values when deriving exposure).
   - `category_utilisation_pct[category]` / `category_caps_pct[category]` → live utilisation and externally supplied caps.
   - `category_budget_pct[category]` / `category_budget_headroom_pct[category]` → governance budgets and optional pre-computed headroom. When budgets are missing from telemetry the pipeline falls back to manifest defaults (budget → `router.category_budget_pct` or the cap when unset).
   - `gross_exposure_pct` / `gross_exposure_cap_pct` → overall gross usage and cap.
   - `strategy_correlations[key][peer]` → pairwise correlations keyed by strategy ID or correlation tag.
   - `correlation_window_minutes` → rolling window (in minutes) used when building `strategy_correlations`; set via `scripts/build_router_snapshot.py --correlation-window-minutes` so reviewers know which lookback produced the heatmap.
   - `execution_health[strategy_id]` → runtime health aggregates (see below for field names).
3. **Runtime metrics**: optional runner exports keyed by manifest ID. When present, the function pulls every numeric entry under `execution_health` (e.g. `reject_rate`, `slippage_bps`, `fill_latency_ms`) into the aggregated telemetry so the router can gate/score on current execution quality and emerging latency issues.【F:core/router_pipeline.py†L99-L211】

The function normalises floats via `_to_float`, backfills utilisation from active position exposure (count × `risk_per_trade_pct`), and calculates headroom values:

- `category_headroom_pct[category] = cap - usage` for every known category.
- `category_budget_headroom_pct[category] = budget - usage` once budget values are known (manifest defaults ensure every manifest category receives a budget even when telemetry omits it). When telemetry already provides headroom values they are preserved as-is.【F:core/router_pipeline.py†L44-L125】
- `gross_exposure_headroom_pct = gross_cap_pct - gross_exposure_pct` when both inputs exist.【F:core/router_pipeline.py†L55-L98】

These derived numbers are critical for v1 scoring bonuses and will become the inputs for v2 category budget tracking (see below).

## Candidate evaluation in v1

`router/router_v1.select_candidates` consumes market context, manifests, the populated `PortfolioState`, and the optional `strategy_signals` map to emit sorted `SelectionResult` rows with eligibility, score, and human-readable reasons.【F:router/router_v1.py†L116-L213】 The evaluation pipeline is:

1. **Market gating**: enforce session, spread band, and RV band checks from manifest router settings (`allowed_sessions`, `allow_spread_bands`, `allow_rv_bands`). These controls mirror the original v0 behaviour for continuity.【F:router/router_v1.py†L118-L146】
2. **Portfolio hard guards** (fail-fast when violated):
   - Category utilisation vs. caps (`category_utilisation_pct`, `category_caps_pct`).【F:router/router_v1.py†L49-L69】
   - Per-strategy concurrency (`active_positions` and `risk.max_concurrent_positions`).【F:router/router_v1.py†L71-L88】
   - Gross exposure vs. cap (`gross_exposure_pct`, `gross_exposure_cap_pct`).【F:router/router_v1.py†L90-L107】
   - Correlation cap breaches using the highest absolute correlation across strategy IDs and correlation tags.【F:router/router_v1.py†L109-L140】
   - Execution health guardrails comparing each metric present in the portfolio snapshot (reject rate, slippage, fill latency, etc.) against the manifest's guard (`max_reject_rate`, `max_slippage_bps`, `max_fill_latency_ms`/`max_latency_ms`). The helper now returns an `ExecutionHealthStatus` payload with disqualification reasons, per-metric penalty entries, and cumulative score deltas while recording the remaining `margin` (distance to the guard) in every log entry.【F:router/router_v1.py†L256-L381】
3. **Signal scoring**:
   - Start from the strategy `score` (or fall back to `ev_lcb`) and add manifest `priority` to bias tiering.【F:router/router_v1.py†L169-L196】
   - Apply soft correlation penalties: subtract the amount by which the max correlation exceeds the configured limit (if any).【F:router/router_v1.py†L198-L203】
   - Apply headroom bonuses/penalties using `_headroom_score_adjustment` for both category and gross headroom, appending formatted reasons so operators see utilisation, cap, headroom, and score deltas in telemetry logs.【F:router/router_v1.py†L205-L257】
   - Layer category budget awareness on top of headroom checks: `_resolve_category_budget` pulls telemetry/manifests, `_budget_score_adjustment` applies tiered penalties when utilisation exceeds the budget but remains under the hard cap, and `_format_headroom_reason` records the resulting headroom/score delta in the reasons list.【F:router/router_v1.py†L105-L257】
   - Blend execution-health adjustments from `_check_execution_health`: metrics well under guard thresholds earn small bonuses, readings approaching the guard incur penalties, and overages continue to disqualify candidates while logging ratio/threshold context.【F:router/router_v1.py†L142-L257】
4. **Reason logging**: propagate `ev_lcb` and headroom messages so downstream telemetry (e.g., `runs/router_pipeline/latest/telemetry.json`) preserves why a manifest was accepted or rejected.【F:router/router_v1.py†L244-L260】

Expected `strategy_signals` fields:

- `score`: preferred scoring signal (already float-normalised by the caller).
- `ev_lcb`: fallback when `score` is missing plus a diagnostic reason entry.

Every `SelectionResult.as_dict()` carries the manifest ID, eligibility, final score, accumulated reasons, and routing metadata (category, tags) so down-stream reporting stays structured.【F:router/router_v1.py†L27-L46】

## Planned v2 enhancements

To extend v1 without breaking callers, v2 will reuse the `PortfolioState`/`select_candidates` interface while enriching telemetry contracts and guard logic.

### Category budgets

- **Goal**: reserve and enforce per-category budget ceilings (e.g., "momentum strategies must not exceed 40% utilisation even when headroom exists elsewhere") and surface budget burn-down in the reasons list.
- **Data requirements**:
  - Extend `PortfolioTelemetry` with `category_budget_pct[category]` and optional `category_budget_headroom_pct[category]` when portfolio governance publishes target allocations. When budgets are absent, manifest defaults (including governance overrides in `manifest.raw['governance']['category_budget_pct']`) populate `PortfolioState.category_budget_pct` so downstream logic always has a value to compare against.【F:core/router_pipeline.py†L19-L138】
  - Populate `PortfolioState` with a derived `category_budget_headroom_pct` so scoring can compare live utilisation against both hard caps and softer budget targets, retaining telemetry-supplied overrides when provided.【F:core/router_pipeline.py†L104-L138】
  - `scripts/build_router_snapshot.py` ingests governance budgets from manifests, merges optional CSV inputs passed via `--category-budget-csv`, and honours explicit CLI overrides so `telemetry.json` preserves the canonical budgets that downstream processes expect.【F:scripts/build_router_snapshot.py†L35-L185】
- **Router behaviour**:
  - Maintain existing hard guard (cap breach → ineligible) but add a soft budget guard that gradually penalises score once utilisation crosses the budget threshold even if the cap allows additional trades. `_budget_score_adjustment` now applies progressive penalties, warns when headroom dwindles to a few percent, and escalates deductions as overage grows while cap headroom collapses.【F:router/router_v1.py†L181-L512】
  - Include budget utilisation ratios in the reasons string to keep telemetry dashboards aligned with governance thresholds (see `category budget headroom` entries in `SelectionResult.reasons`). Budget reasons now annotate `status=ok|warning|breach` alongside overage magnitudes so monitoring can distinguish between near-threshold caution and outright budget breaches.【F:router/router_v1.py†L205-L512】

### Correlation guards

- **Goal**: treat correlation data as a first-class guard by combining manifest-level correlation tags, observed pairwise correlations, and category awareness.
- **Data requirements**:
  - Continue reading `strategy_correlations[strategy_id or tag][peer]` from telemetry, but require that upstream metrics calculate rolling correlations in a consistent window (now tracked by `correlation_window_minutes` from `scripts/build_router_snapshot.py`).
  - Publish `correlation_meta[source][peer]` alongside the raw matrix so each entry records the peer manifest ID, category, and governance budget bucket. `scripts/build_router_snapshot.py` persists this block into `telemetry.json`, and `analysis.portfolio_monitor` surfaces the `bucket_category` / `bucket_budget_pct` fields inside the correlation heatmap so reviewers can distinguish same-bucket breaches from cross-bucket pressure during offline analysis.【F:scripts/build_router_snapshot.py†L504-L523】【F:analysis/portfolio_monitor.py†L138-L170】
- **Router behaviour**:
  - Treat correlation breaches differently based on bucket alignment: same-bucket pairs trigger hard disqualification, while cross-bucket pairs incur score penalties equal to the excess above the cap.
  - Deduplicate penalties per peer so overlapping `correlation_tags` do not stack multiple deductions for the same relationship.
  - Publish `reason` entries such as `"correlation 0.72 > cap 0.60 (bucket momentum (35.0%))"` with `score_delta` annotations when penalties apply, ensuring monitoring can distinguish blocking breaches from cross-bucket pressure.

### Execution health integration

- **Goal**: unify runtime metrics from `core.runner.BacktestRunner` with live router decisions, ensuring unhealthy execution automatically suppresses allocations.
- **Data requirements**:
  - Keep ingesting `reject_rate` and `slippage_bps` from `runtime_metrics`, and automatically merge any additional numeric fields such as `fill_latency_ms` or `avg_price_deviation_bps` when they become available so downstream consumers retain a single contract.【F:core/router_pipeline.py†L99-L211】
  - Ensure `scripts/build_router_snapshot.py` persists these metrics under `execution_health[strategy_id]` so the router and downstream monitoring dashboards observe the same numbers.
- **Router behaviour**:
  - `_check_execution_health` now provides a tiered response: metrics below 50% of the guard earn bonuses, values drifting into the 90–97% band incur soft penalties, and breaches still mark the candidate ineligible while logging the offending ratio and remaining `margin` to the guard.【F:router/router_v1.py†L275-L381】
  - The helper returns a structured payload that records per-metric penalties in `ExecutionHealthStatus.penalties`, attaches readable messages (value, guard, margin, ratio, `score_delta`), and accumulates the net score delta consumed by `select_candidates` when adjusting candidate scores.【F:router/router_v1.py†L256-L381】

## Integration checklist

When publishing new router capabilities, update the following artefacts to maintain the handoff contract:

- `docs/task_backlog.md` → link to this architecture note from the P2 router section so future sessions can find the design context.
- `docs/checklists/p2_router.md` → reference this document under Ready/DoD guidance.
- `state.md` / `docs/todo_next.md` → log when the architecture note is updated, keeping the shared workflow loop consistent with the Codex session rules.

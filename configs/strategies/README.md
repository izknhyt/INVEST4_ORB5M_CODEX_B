# Strategy Manifest Format

Each YAML file in this directory describes a single strategy in a router-friendly
format. The loader lives at `configs/strategies/loader.py` and exposes
`load_manifest(path)` / `load_manifests(dir)` returning dataclass instances with
basic validation.

## Top-level blocks

| Key        | Required | Description |
|------------|----------|-------------|
| `meta`     | ✅        | Identification (`id`, `name`, `category`, `version`, `description`, `tags`) |
| `strategy` | ✅        | Python class (`class_path`), `instruments` list, default parameters |
| `router`   | ✅        | Allowed sessions, spread & RV bands, latency caps, routing tags, and guardrails |
| `risk`     | ✅        | Risk budgets (risk per trade, DD guard, notional caps, warm-up trades) |
| `features` | ❌        | Required & optional feature names used for gating/sizing |
| `runner`   | ❌        | Recommended runner configuration overrides / CLI args |
| `state`    | ❌        | Archive namespace & EV profile hints |
| `notes`    | ❌        | Free-form operator notes |

### Required blocks
- `meta` — Identify the strategy with stable IDs, human-readable names, category, version, descriptive text, and discovery tags.
- `strategy` — Point to the Python implementation (`class_path`), enumerate tradable instruments, and supply default parameter values used by loaders and runners.
- `router` — Define execution guardrails such as allowed sessions, spread/realized-volatility bands, latency caps, routing tags, and per-manifest guard thresholds.
- `risk` — Capture sizing guardrails including risk-per-trade, drawdown limits, notional caps, concurrency limits, and warm-up counts.

### Optional blocks
- `features` — Document required/optional feature columns for gating or sizing so data pipelines can validate coverage.
- `runner` — Recommend `RunnerConfig` overrides and CLI defaults that orchestration tools can adopt when bootstrapping simulations.
- `state` — Describe EV state archive namespaces and the EV profile seed to help automation locate persisted context.
- `notes` — Leave free-form operational reminders or playbooks that do not belong in structured fields.

### Category
`meta.category` must be one of `scalping`, `day`, or `swing`. This allows the
router to enforce portfolio caps per bucket.

### Instruments
Each instrument entry contains a `symbol` (upper case), `timeframe` (e.g. `5m`),
and optionally a `mode` (e.g. `conservative`, `bridge`). Multiple symbols can be
listed when a strategy is multi-instrument.

### Runner defaults
`runner.runner_config` mirrors the arguments accepted by `RunnerConfig`, while
`runner.cli_args` captures CLI defaults used by orchestration tools. With the
new minimal interface (`scripts/run_sim.py --manifest ...`), the CLI resolves
CSV/Equity/state設定などを manifest から読み込み、必要最低限の引数だけを受け取ります。`runner.cli_args`
に `csv` / `equity` / `auto_state` / `aggregate_ev` / `state_archive` などを記載しておくと、Codex や手動実行で
同じ設定を再現しやすくなります。

#### Router guard fields

The router block also supports guardrails that help operators tune portfolio-level
controls when manifests compete for capacity:

- `priority` — Relative scheduling weight. Lower values execute first; leave at the default `0.0` until you need to down-rank
  a strategy that should yield to higher conviction plays.
- `max_gross_exposure_pct` — Strategy-specific gross exposure cap. Omit to inherit the portfolio default; set explicitly when the
  strategy must run at tighter limits than the category budget.
- `max_correlation` — Pairwise correlation ceiling applied against other manifests that share `correlation_tags`. Configure when you
  have historical co-movement estimates; omit to disable correlation-based throttling.
- `correlation_tags` — Buckets correlation checks. Only manifests sharing at least one tag will be compared, so keep tags broad enough
  to reflect genuinely linked strategies and omit for isolated plays.
- `max_reject_rate` — Upper bound on acceptable order rejection ratio (e.g. `0.05` = 5%). Leave unset until you have execution metrics
  to calibrate the threshold, then tighten to pause manifests suffering persistent rejects.
- `max_slippage_bps` — Execution quality limit expressed in basis points. Provide when the strategy has a known slip tolerance; otherwise
  the router falls back to its global safeguard.

### Example
See `day_orb_5m.yaml` for a reference manifest covering the Day ORB 5m strategy.

### Templates
Start new manifests from `templates/base_strategy.yaml`, which contains inline
guidance for each field plus suggested runner defaults inspired by the Day ORB
manifest. Category-specific scaffolding is also available:

- `scalping_template.yaml` + `strategies/scalping_template.py`
- `day_template.yaml` + `strategies/day_template.py`

These template pairs integrate with the sizing/router pipeline out of the box
while leaving `_maybe_build_signal` for concrete strategy logic.

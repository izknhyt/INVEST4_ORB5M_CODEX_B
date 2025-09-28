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
| `router`   | ✅        | Allowed sessions / spread & RV bands / latency caps / tags |
| `risk`     | ✅        | Risk budgets (risk per trade, DD guard, notional caps, warm-up trades) |
| `features` | ❌        | Required & optional feature names used for gating/sizing |
| `runner`   | ❌        | Recommended runner configuration overrides / CLI args |
| `state`    | ❌        | Archive namespace & EV profile hints |
| `notes`    | ❌        | Free-form operator notes |

### Required blocks
- `meta` — Identify the strategy with stable IDs, human-readable names, category, version, descriptive text, and discovery tags.
- `strategy` — Point to the Python implementation (`class_path`), enumerate tradable instruments, and supply default parameter values used by loaders and runners.
- `router` — Define execution guardrails such as allowed sessions, spread/realized-volatility bands, latency caps, and routing tags.
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
`runner.cli_args` matches CLI flags (e.g. `scripts/run_sim.py`). These sections
are advisory and can be used by orchestration tools to bootstrap runs.

### Example
See `day_orb_5m.yaml` for a reference manifest covering the Day ORB 5m strategy.

### Templates
Start new manifests from `templates/base_strategy.yaml`, which contains inline
guidance for each field plus suggested runner defaults inspired by the Day ORB
manifest.

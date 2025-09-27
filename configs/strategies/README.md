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

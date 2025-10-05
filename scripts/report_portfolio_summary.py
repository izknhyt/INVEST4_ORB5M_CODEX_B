#!/usr/bin/env python3
"""Generate a router portfolio summary JSON file.

Expected input layout (mirrors the sample fixtures in
`reports/portfolio_samples/router_demo/`):

```
<base_dir>/
  telemetry.json      # PortfolioTelemetry fields
  metrics/
    <manifest_id>.json  # Contains `manifest_path` and `equity_curve`
```

Each metrics file must provide an `equity_curve` iterable describing
`[timestamp, equity]` pairs (lists or objects with `ts`/`equity` keys). The
`manifest_path` is resolved via `configs.strategies.loader.load_manifest` so the
summary can surface category and risk metadata directly from the manifests.

The script writes a JSON payload to `reports/portfolio_summary.json` by default.
The output mirrors the schema returned by
`analysis.portfolio_monitor.build_portfolio_summary`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.portfolio_monitor import build_portfolio_summary

DEFAULT_INPUT = Path("runs/router_pipeline/latest")
DEFAULT_OUTPUT = Path("reports/portfolio_summary.json")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Directory containing telemetry.json and metrics/*.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path to the JSON file that will receive the summary",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indent level for the generated JSON (use 0 for compact)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = build_portfolio_summary(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    indent = None if args.indent <= 0 else args.indent
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=indent, sort_keys=False)
        handle.write("\n")
    print(f"wrote portfolio summary to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

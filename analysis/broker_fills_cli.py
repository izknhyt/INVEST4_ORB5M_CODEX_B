"""CLI to compare fill engine outputs against broker-specific expectations."""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("REPO_ROOT", str(REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.fill_engine import (  # noqa: E402
    BridgeFill,
    ConservativeFill,
    OrderSpec,
    SameBarPolicy,
)


@dataclass
class Scenario:
    name: str
    broker: str
    bar: Dict[str, float]
    spec: OrderSpec
    expected_reason: str
    expected_px: float
    expected_policy: SameBarPolicy
    notes: str


SCENARIOS: Tuple[Scenario, ...] = (
    Scenario(
        name="oanda_tick_bias",
        broker="OANDA",
        bar={"o": 149.95, "h": 150.20, "l": 149.82, "c": 150.12, "pip": 0.01, "spread": 0.001},
        spec=OrderSpec(
            side="BUY",
            entry=150.00,
            tp_pips=8.0,
            sl_pips=12.0,
            trail_pips=0.0,
            slip_cap_pip=3.0,
        ),
        expected_reason="tp",
        expected_px=150.08,
        expected_policy=SameBarPolicy.PROBABILISTIC,
        notes="Positive drift; tick ordering favours TP first on v20 (documented sequence).",
    ),
    Scenario(
        name="ig_stop_priority",
        broker="IG",
        bar={"o": 110.10, "h": 110.18, "l": 109.95, "c": 110.02, "pip": 0.01, "spread": 0.001},
        spec=OrderSpec(
            side="BUY",
            entry=110.05,
            tp_pips=6.0,
            sl_pips=8.0,
            trail_pips=0.0,
            slip_cap_pip=2.0,
        ),
        expected_reason="sl",
        expected_px=109.97,
        expected_policy=SameBarPolicy.SL_FIRST,
        notes="IG OTC converts protective leg to market when both hit; SL executes first.",
    ),
    Scenario(
        name="sbi_trailing_guard",
        broker="SBI FXトレード",
        bar={"o": 132.40, "h": 132.78, "l": 132.30, "c": 132.55, "pip": 0.01, "spread": 0.001},
        spec=OrderSpec(
            side="BUY",
            entry=132.42,
            tp_pips=20.0,
            sl_pips=15.0,
            trail_pips=10.0,
            slip_cap_pip=2.5,
        ),
        expected_reason="trail",
        expected_px=132.68,
        expected_policy=SameBarPolicy.SL_FIRST,
        notes="Server trailing updates every ~1s; stop ratchets to 10p below high then fires.",
    ),
)


def _format_result(
    result: Dict[str, float],
    pip: float,
    expected_px: Optional[float],
) -> str:
    if not result.get("fill"):
        return "no-fill"
    if "exit_px" not in result:
        return "carry"
    reason = result.get("exit_reason", "?")
    px = result["exit_px"]
    diff = None
    if expected_px is not None:
        diff = (px - expected_px) / pip
    diff_str = ""
    if diff is not None:
        diff_str = f" ({diff:+.1f}p)"
    return f"{reason}@{px:.5f}{diff_str}"


def _format_expected(reason: str, px: float) -> str:
    return f"{reason}@{px:.5f}"


def compare_fill_scenarios() -> Tuple[Sequence[str], List[Tuple[str, ...]]]:
    """Return the broker comparison table used by both the CLI and notebooks."""

    conservative = ConservativeFill()
    bridge = BridgeFill()
    header: Tuple[str, ...] = (
        "scenario",
        "broker",
        "expected",
        "conservative(default)",
        "bridge(default)",
        "conservative(aligned)",
        "bridge(aligned)",
        "notes",
    )
    rows: List[Tuple[str, ...]] = []
    for sc in SCENARIOS:
        pip = sc.bar.get("pip", 0.01) or 0.01
        cons_default = conservative.simulate(sc.bar, sc.spec)
        bridge_default = bridge.simulate(sc.bar, sc.spec)
        spec_aligned = replace(sc.spec, same_bar_policy=sc.expected_policy)
        cons_aligned = conservative.simulate(sc.bar, spec_aligned)
        bridge_aligned = bridge.simulate(sc.bar, spec_aligned)
        rows.append(
            (
                sc.name,
                sc.broker,
                _format_expected(sc.expected_reason, sc.expected_px),
                _format_result(cons_default, pip, sc.expected_px),
                _format_result(bridge_default, pip, sc.expected_px),
                _format_result(cons_aligned, pip, sc.expected_px),
                _format_result(bridge_aligned, pip, sc.expected_px),
                sc.notes,
            )
        )
    return header, rows


def iter_comparison_rows() -> Iterable[Dict[str, str]]:
    """Yield the comparison table as dictionaries for DataFrame conversion."""

    header, rows = compare_fill_scenarios()
    for row in rows:
        yield {header[i]: row[i] for i in range(len(header))}


def comparison_dataframe():
    """Return the comparison table as a pandas DataFrame if pandas is available."""

    try:
        import pandas as pd  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        return None
    return pd.DataFrame(list(iter_comparison_rows()))


def run_scenarios(format_: str = "markdown") -> None:
    header, rows = compare_fill_scenarios()

    if format_ == "markdown":
        widths = [max(len(row[i]) for row in [header] + rows) for i in range(len(header))]
        line = "| " + " | ".join(str(header[i]).ljust(widths[i]) for i in range(len(header))) + " |"
        sep = "| " + " | ".join("-" * widths[i] for i in range(len(header))) + " |"
        print(line)
        print(sep)
        for row in rows:
            print("| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(header))) + " |")
    else:
        for row in rows:
            print("- " + ", ".join(f"{header[i]}: {row[i]}" for i in range(len(header))))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare fill engines with broker behaviour")
    parser.add_argument("--format", choices=["markdown", "plain"], default="markdown")
    args = parser.parse_args()
    run_scenarios(format_=args.format)


if __name__ == "__main__":
    main()

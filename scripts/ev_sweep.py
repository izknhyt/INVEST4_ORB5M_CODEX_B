"""Utilities for orchestrating EV parameter sweeps."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Dict, Iterable, Iterator, List, Mapping


@dataclass(frozen=True)
class SweepDimension:
    """Represents a single CLI flag and the set of values to iterate over."""

    flag: str
    key: str
    values: List[Any]

    def cleaned_values(self) -> List[Any]:
        """Filter out Nones and return the values as a list."""

        return [v for v in self.values]


def build_dimensions(args) -> List[SweepDimension]:
    """Translate CLI arguments into sweep dimensions."""

    dims: List[SweepDimension] = []

    if getattr(args, "threshold", None):
        dims.append(SweepDimension("--threshold-lcb", "threshold_lcb", list(args.threshold)))
    if getattr(args, "decay", None):
        dims.append(SweepDimension("--decay", "decay", list(args.decay)))
    if getattr(args, "prior_alpha", None):
        dims.append(SweepDimension("--prior-alpha", "prior_alpha", list(args.prior_alpha)))
    if getattr(args, "prior_beta", None):
        dims.append(SweepDimension("--prior-beta", "prior_beta", list(args.prior_beta)))

    warmup_values: List[int] = []
    if not getattr(args, "no_warmup", False):
        if getattr(args, "warmup", None):
            warmup_values = list(args.warmup)
        else:
            warmup_values = [10]
    if warmup_values:
        dims.append(SweepDimension("--warmup", "warmup", warmup_values))

    return dims


def iter_param_combinations(dimensions: Iterable[SweepDimension]) -> Iterator[Dict[str, Any]]:
    dims = list(dimensions)
    if not dims:
        yield {}
        return
    keys = [dim.key for dim in dims]
    value_lists = [dim.cleaned_values() or [None] for dim in dims]
    for combo in product(*value_lists):
        yield {key: value for key, value in zip(keys, combo)}


def flatten_metrics(metrics: Mapping[str, Any], *, prefix: str = "metrics") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, Mapping):
            nested = flatten_metrics(value, prefix=f"{prefix}.{key}")
            flat.update(nested)
        else:
            flat[f"{prefix}.{key}"] = value
    return flat


def compute_derived(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    derived: Dict[str, Any] = {}
    trades = metrics.get("trades")
    wins = metrics.get("wins")
    total_pips = metrics.get("total_pips")
    if isinstance(trades, (int, float)) and trades:
        if isinstance(wins, (int, float)):
            derived["win_rate"] = wins / trades
        if isinstance(total_pips, (int, float)):
            derived["pips_per_trade"] = total_pips / trades
    decay_val = metrics.get("decay")
    if isinstance(decay_val, (int, float)):
        derived["decay"] = decay_val
    return derived


def build_csv_row(params: Mapping[str, Any], metrics: Mapping[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {f"param.{k}": v for k, v in params.items()}
    row.update(flatten_metrics(metrics))
    derived = compute_derived(metrics)
    row.update({f"derived.{k}": v for k, v in derived.items()})
    return row


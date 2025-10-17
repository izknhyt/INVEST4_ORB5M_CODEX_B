"""Aggregate guard-relaxed OR filter gate stats across rv bands and ATR ratios."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

NumericValue = Union[int, float]


def _format_number(value: object, decimals: int = 6) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric.is_integer():
            return str(int(round(numeric)))
        return f"{numeric:.{decimals}f}"
    return str(value)


@dataclass
class ModeSummary:
    """Container for aggregated gate statistics per mode."""

    label: str
    path: Path
    total_count: int
    rv_band: List[Tuple[str, int]]
    numeric: Mapping[str, Mapping[str, NumericValue]]

    def rv_band_share(self) -> List[Tuple[str, int, float]]:
        if self.total_count <= 0:
            return [(name, count, 0.0) for name, count in self.rv_band]
        return [
            (name, count, (count / self.total_count) * 100.0)
            for name, count in self.rv_band
        ]


@dataclass
class AggregateResult:
    modes: List[ModeSummary]

    def average_band_distribution(self) -> Tuple[Dict[str, float], float]:
        band_totals: Counter[str] = Counter()
        for mode in self.modes:
            for band, count in mode.rv_band:
                band_totals[band] += float(count)

        mode_count = len(self.modes) or 1
        average_counts: Dict[str, float] = {
            band: total / mode_count for band, total in band_totals.items()
        }
        total = sum(average_counts.values())
        return average_counts, total

    def to_json(
        self,
        *,
        recommendations: Optional[Mapping[str, object]] = None,
        heuristics: Optional[Mapping[str, object]] = None,
    ) -> MutableMapping[str, object]:
        rv_band_table: List[Mapping[str, object]] = []
        numeric_summary: MutableMapping[str, MutableMapping[str, object]] = {}
        for mode in self.modes:
            for band, count, share in mode.rv_band_share():
                rv_band_table.append(
                    {
                        "mode": mode.label,
                        "rv_band": band,
                        "count": count,
                        "share_pct": share,
                    }
                )
            numeric_payload: MutableMapping[str, object] = {}
            for key, stats in mode.numeric.items():
                numeric_payload[key] = dict(stats)
                if key == "min_or_atr_ratio" and stats.get("min") == stats.get("max"):
                    numeric_payload[key]["constant"] = stats.get("min")
            numeric_summary[mode.label] = {
                "total_count": mode.total_count,
                "numeric": numeric_payload,
            }
        payload: MutableMapping[str, object] = {
            "modes": [
                {
                    "label": mode.label,
                    "path": str(mode.path),
                    "total_count": mode.total_count,
                    "rv_band": [
                        {"name": name, "count": count, "share_pct": share}
                        for name, count, share in mode.rv_band_share()
                    ],
                    "numeric": {
                        key: dict(value) for key, value in mode.numeric.items()
                    },
                }
                for mode in self.modes
            ],
            "rv_band_table": rv_band_table,
            "numeric_summary": numeric_summary,
        }
        if recommendations:
            payload["recommendations"] = dict(recommendations)
        if heuristics:
            payload["heuristics"] = dict(heuristics)
        return payload

    def to_markdown(
        self,
        *,
        recommendations: Optional["RecommendationSet"] = None,
    ) -> str:
        lines: List[str] = []
        lines.append("# Guard-relaxed OR filter summary")
        lines.append("")
        lines.append(
            "This report aggregates `or_filter` counts from guard-relaxed strategy gate diffs "
            "across rv_band segments and min_or_atr_ratio statistics."
        )
        lines.append("")
        lines.append("## RV band distribution")
        lines.append("")
        lines.append("| Mode | RV band | Count | Share (%) |")
        lines.append("| --- | --- | ---: | ---: |")
        for mode in self.modes:
            for band, count, share in mode.rv_band_share():
                lines.append(
                    f"| {mode.label} | {band} | {count} | {share:.2f} |"
                )
        lines.append("")
        lines.append("## min_or_atr_ratio summary")
        lines.append("")
        lines.append("| Mode | Count | Mean | Min | Max | Notes |")
        lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
        for mode in self.modes:
            stats = mode.numeric.get("min_or_atr_ratio", {})
            count = stats.get("count")
            mean = stats.get("mean")
            min_value = stats.get("min")
            max_value = stats.get("max")
            if min_value is not None and min_value == max_value:
                note = f"constant at {min_value}"
            else:
                note = ""
            lines.append(
                "| {mode} | {count} | {mean} | {min} | {max} | {note} |".format(
                    mode=mode.label,
                    count=_format_number(count),
                    mean=_format_number(mean),
                    min=_format_number(min_value),
                    max=_format_number(max_value),
                    note=note,
                )
            )
        lines.append("")
        lines.append("## or_atr_ratio summary")
        lines.append("")
        lines.append("| Mode | Count | Mean | Min | Max |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for mode in self.modes:
            stats = mode.numeric.get("or_atr_ratio", {})
            count = stats.get("count")
            mean = stats.get("mean")
            min_value = stats.get("min")
            max_value = stats.get("max")
            lines.append(
                "| {mode} | {count} | {mean} | {min} | {max} |".format(
                    mode=mode.label,
                    count=_format_number(count),
                    mean=_format_number(mean),
                    min=_format_number(min_value),
                    max=_format_number(max_value),
                )
            )
        lines.append("")
        if recommendations and recommendations.bands:
            lines.append("## Proposed min_or_atr_ratio adjustments")
            lines.append("")
            lines.append("| RV band | Current | Proposed | Δ | Share (%) |")
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for entry in recommendations.bands:
                lines.append(
                    "| {band} | {current} | {proposed} | {delta} | {share} |".format(
                        band=entry.rv_band,
                        current=_format_number(entry.current, decimals=3),
                        proposed=_format_number(entry.proposed, decimals=3),
                        delta=_format_number(entry.delta, decimals=3),
                        share=f"{entry.share_pct:.2f}",
                    )
                )
            lines.append("")
            if (
                recommendations.global_current is not None
                and recommendations.global_proposed is not None
            ):
                delta_value = (
                    recommendations.global_proposed - recommendations.global_current
                )
                lines.append(
                    "Suggested global `min_or_atr_ratio`: {proposed} (current {current}, Δ {delta}).".format(
                        proposed=_format_number(
                            recommendations.global_proposed, decimals=3
                        ),
                        current=_format_number(
                            recommendations.global_current, decimals=3
                        ),
                        delta=_format_number(delta_value, decimals=3),
                    )
                )
                lines.append("")
            note_bits: List[str] = []
            if recommendations.params_source:
                note_bits.append(
                    f"Thresholds sourced from {recommendations.params_source}"
                )
            note_bits.append(
                f"base_drop={recommendations.base_drop} / floor={recommendations.floor}"
            )
            lines.append("Heuristic: " + ", ".join(note_bits) + ".")
            lines.append("")
        lines.append("Generated by `analysis/or_filter_guard_relaxed_summary.py`.")
        return "\n".join(lines) + "\n"


def _load_mode_summary(label: str, path: Path) -> ModeSummary:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if "or_filter" not in payload:
        raise ValueError(f"{path} does not include 'or_filter' statistics")
    data = payload["or_filter"]
    total_count = int(data.get("count", 0))
    categorical = data.get("categorical", {})
    rv_band_raw: Sequence[Sequence[object]] = categorical.get("rv_band", [])  # type: ignore[assignment]
    rv_band: List[Tuple[str, int]] = []
    for entry in rv_band_raw:
        if not isinstance(entry, Sequence) or len(entry) != 2:
            raise ValueError(f"Unexpected rv_band entry: {entry!r}")
        name, count = entry
        rv_band.append((str(name), int(count)))
    numeric = data.get("numeric", {})
    numeric_stats: Dict[str, Dict[str, NumericValue]] = {}
    for key, stats in numeric.items():
        if not isinstance(stats, Mapping):
            raise ValueError(f"Numeric stats for {key} must be a mapping: {stats!r}")
        converted: Dict[str, NumericValue] = {}
        for stat_key, stat_value in stats.items():
            if isinstance(stat_value, (int, float)):
                if stat_key == "count":
                    converted[stat_key] = int(stat_value)
                else:
                    converted[stat_key] = float(stat_value)
            else:
                raise ValueError(
                    f"Expected numeric value for {key}.{stat_key}, got {stat_value!r}"
                )
        numeric_stats[key] = converted
    return ModeSummary(label=label, path=path, total_count=total_count, rv_band=rv_band, numeric=numeric_stats)


def _parse_input_pairs(pairs: Iterable[str]) -> List[Tuple[str, Path]]:
    inputs: List[Tuple[str, Path]] = []
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid input format '{pair}'. Expected label=path.")
        label, path_str = pair.split("=", 1)
        label = label.strip()
        if not label:
            raise ValueError(f"Missing label in '{pair}'")
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input path not found: {path}")
        inputs.append((label, path))
    if not inputs:
        raise ValueError("At least one --input must be provided")
    return inputs


@dataclass
class BandRecommendation:
    rv_band: str
    current: float
    proposed: float
    delta: float
    share_pct: float


@dataclass
class RecommendationSet:
    bands: List[BandRecommendation]
    params_source: Optional[str]
    base_drop: float
    floor: float
    global_current: Optional[float]
    global_proposed: Optional[float]

    def to_json(self) -> Mapping[str, object]:
        return {
            "bands": [
                {
                    "rv_band": entry.rv_band,
                    "current": entry.current,
                    "proposed": entry.proposed,
                    "delta": entry.delta,
                    "share_pct": entry.share_pct,
                }
                for entry in self.bands
            ],
            "params_source": self.params_source,
            "base_drop": self.base_drop,
            "floor": self.floor,
            "global": {
                "current": self.global_current,
                "proposed": self.global_proposed,
                "delta": (
                    None
                    if self.global_current is None or self.global_proposed is None
                    else self.global_proposed - self.global_current
                ),
            },
        }


def _load_params(path: Path) -> Mapping[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_band_thresholds(params: Mapping[str, object]) -> Mapping[str, float]:
    mapping = params.get("rv_band_min_or_atr")
    if not isinstance(mapping, Mapping):
        return {}
    result: Dict[str, float] = {}
    for band, value in mapping.items():
        if isinstance(value, (int, float)):
            result[str(band)] = float(value)
    return result


def _compute_recommendations(
    result: AggregateResult,
    *,
    params: Mapping[str, object],
    params_source: Optional[str],
    base_drop: float,
    floor: float,
) -> RecommendationSet:
    band_thresholds = _extract_band_thresholds(params)
    average_counts, total = result.average_band_distribution()

    recommendations: List[BandRecommendation] = []
    for band, current in band_thresholds.items():
        share = 0.0
        if total > 0:
            share = (average_counts.get(band, 0.0) / total) * 100.0
        proposed = max(current - base_drop, floor)
        recommendations.append(
            BandRecommendation(
                rv_band=band,
                current=float(current),
                proposed=float(proposed),
                delta=float(proposed - current),
                share_pct=float(share),
            )
        )

    global_current: Optional[float] = None
    global_proposed: Optional[float] = None
    min_or_atr = params.get("min_or_atr")
    if isinstance(min_or_atr, (int, float)):
        global_current = float(min_or_atr)
        if recommendations:
            global_proposed = max(entry.proposed for entry in recommendations)
        else:
            global_proposed = max(global_current - base_drop, floor)

    return RecommendationSet(
        bands=recommendations,
        params_source=params_source,
        base_drop=base_drop,
        floor=floor,
        global_current=global_current,
        global_proposed=global_proposed,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate guard-relaxed OR filter counts across rv_band and min_or_atr_ratio "
            "segments."
        )
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Mode label and JSON path pair in the form label=path",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path to write aggregated JSON output",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="Optional path to write Markdown summary",
    )
    parser.add_argument(
        "--params-json",
        type=Path,
        help="Optional params.json file containing rv_band_min_or_atr thresholds",
    )
    parser.add_argument(
        "--base-drop",
        type=float,
        default=0.02,
        help="Amount to subtract from each band threshold when proposing adjustments",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=0.05,
        help="Lower bound for proposed thresholds",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = _parse_input_pairs(args.input)
    summaries = [_load_mode_summary(label, path) for label, path in inputs]
    result = AggregateResult(modes=summaries)
    recommendations: Optional[RecommendationSet] = None
    heuristics: Optional[Mapping[str, object]] = None
    if args.params_json:
        params_path = args.params_json.expanduser().resolve()
        params = _load_params(params_path)
        recommendations = _compute_recommendations(
            result,
            params=params,
            params_source=str(params_path),
            base_drop=args.base_drop,
            floor=args.floor,
        )
        heuristics = {
            "base_drop": args.base_drop,
            "floor": args.floor,
            "params_source": str(params_path),
        }
    if args.json_output:
        json_output_path = args.json_output.expanduser().resolve()
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        with json_output_path.open("w", encoding="utf-8") as handle:
            json.dump(
                result.to_json(
                    recommendations=None if recommendations is None else recommendations.to_json(),
                    heuristics=heuristics,
                ),
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
    if args.markdown_output:
        markdown_output_path = args.markdown_output.expanduser().resolve()
        markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_output_path.write_text(
            result.to_markdown(recommendations=recommendations),
            encoding="utf-8",
        )
    if not args.json_output and not args.markdown_output:
        print(
            json.dumps(
                result.to_json(
                    recommendations=None if recommendations is None else recommendations.to_json(),
                    heuristics=heuristics,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

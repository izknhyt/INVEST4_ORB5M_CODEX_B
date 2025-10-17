"""Aggregate guard-relaxed OR filter gate stats across rv bands and ATR ratios."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple, Union

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

    def to_json(self) -> MutableMapping[str, object]:
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
        return {
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

    def to_markdown(self) -> str:
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = _parse_input_pairs(args.input)
    summaries = [_load_mode_summary(label, path) for label, path in inputs]
    result = AggregateResult(modes=summaries)
    if args.json_output:
        json_output_path = args.json_output.expanduser().resolve()
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        with json_output_path.open("w", encoding="utf-8") as handle:
            json.dump(result.to_json(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    if args.markdown_output:
        markdown_output_path = args.markdown_output.expanduser().resolve()
        markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_output_path.write_text(result.to_markdown(), encoding="utf-8")
    if not args.json_output and not args.markdown_output:
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

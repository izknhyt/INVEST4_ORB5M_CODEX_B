"""Utilities for turning optimisation artefacts into review-ready reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:  # pragma: no cover - surfaced in tests via SystemExit
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc


def _ensure_parent(path: Path) -> None:
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _format_table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    header_list = list(headers)
    rendered = ["| " + " | ".join(header_list) + " |"]
    rendered.append("| " + " | ".join("---" for _ in header_list) + " |")
    for row in rows:
        rendered.append("| " + " | ".join(_format_value(cell) for cell in row) + " |")
    return "\n".join(rendered)


def _render_summary_section(best_payload: Dict[str, Any]) -> str:
    summary = best_payload.get("summary", {})
    commands = best_payload.get("commands", [])
    lines = ["## Summary"]
    if summary:
        objective = summary.get("objective")
        if objective:
            lines.append(f"- Objective: {objective}")
        trial_id = summary.get("best_trial_id")
        if trial_id:
            score = summary.get("best_score")
            baseline = summary.get("baseline_score")
            score_suffix = f" (baseline {baseline})" if baseline is not None else ""
            if score is not None:
                lines.append(f"- Best Trial: {trial_id} — score {score}{score_suffix}")
            else:
                lines.append(f"- Best Trial: {trial_id}{score_suffix}")
    if commands:
        lines.append("")
        lines.append("```bash")
        for command in commands:
            lines.append(command)
        lines.append("```")
    return "\n".join(lines)


def _render_metrics_section(best_payload: Dict[str, Any]) -> str:
    metrics = best_payload.get("metrics") or {}
    if not metrics:
        return "## Metrics\n_No metric payload provided._"
    rows: List[List[Any]] = []
    for metric, values in metrics.items():
        if isinstance(values, dict):
            candidate = values.get("candidate")
            baseline = values.get("baseline")
            delta = None
            if candidate is not None and baseline is not None:
                try:
                    delta = candidate - baseline
                except TypeError:
                    delta = None
            rows.append([
                metric,
                "" if baseline is None else _format_value(baseline),
                "" if candidate is None else _format_value(candidate),
                "" if delta is None else _format_value(delta),
            ])
        else:
            rows.append([metric, "", _format_value(values), ""])
    table = _format_table(["Metric", "Baseline", "Candidate", "Δ"], rows)
    return "## Metrics\n" + table


def _render_constraints_section(best_payload: Dict[str, Any]) -> str:
    constraints = best_payload.get("constraints") or []
    if not constraints:
        return "## Constraint Compliance\n_No constraint data provided._"
    rows = []
    for item in constraints:
        rows.append([
            item.get("name", "(unknown)"),
            item.get("status", "unknown"),
            item.get("details", ""),
        ])
    table = _format_table(["Constraint", "Status", "Notes"], rows)
    return "## Constraint Compliance\n" + table


def _render_gate_section(gate_payload: Dict[str, Any]) -> str:
    lines = ["## Gate Diagnostics"]
    summary = gate_payload.get("summary")
    if summary:
        rows = [[key, value] for key, value in summary.items()]
        lines.append(_format_table(["Metric", "Value"], rows))
    top_reasons = gate_payload.get("top_reasons") or gate_payload.get("top_block_reasons")
    if top_reasons:
        lines.append("")
        reason_rows = []
        for item in top_reasons:
            reason_rows.append([item.get("reason", "(unknown)"), item.get("count", 0)])
        lines.append(_format_table(["Reason", "Blocks"], reason_rows))
    recent_blocks = gate_payload.get("recent_blocks")
    if recent_blocks:
        lines.append("")
        rows = []
        for entry in recent_blocks:
            rows.append([
                entry.get("timestamp", ""),
                entry.get("symbol", ""),
                entry.get("reason", ""),
            ])
        lines.append(_format_table(["Timestamp", "Symbol", "Reason"], rows))
    if len(lines) == 1:
        lines.append("_No gate diagnostics provided._")
    return "\n".join(lines)


def _render_risk_section(telemetry_payload: Dict[str, Any]) -> str:
    lines = ["## Risk Snapshot"]
    risk_metrics = telemetry_payload.get("risk_metrics") or {}
    if risk_metrics:
        rows = [[key, value] for key, value in risk_metrics.items()]
        lines.append(_format_table(["Metric", "Value"], rows))
    portfolio_return = telemetry_payload.get("portfolio_return_pct")
    if portfolio_return is not None:
        lines.append("")
        lines.append(f"- Portfolio Return (%): {_format_value(portfolio_return)}")
    strategies = telemetry_payload.get("strategies") or telemetry_payload.get("exposures")
    if strategies:
        lines.append("")
        rows = []
        for strategy in strategies:
            rows.append([
                strategy.get("name") or strategy.get("strategy", "(unknown)"),
                strategy.get("weight"),
                strategy.get("pnl_pct") or strategy.get("pnl"),
            ])
        lines.append(_format_table(["Strategy", "Weight", "PnL (%)"], rows))
    notes = telemetry_payload.get("notes")
    if notes:
        lines.append("")
        lines.append(notes)
    if len(lines) == 1:
        lines.append("_No portfolio telemetry provided._")
    return "\n".join(lines)


def _render_next_steps(best_payload: Dict[str, Any]) -> str:
    steps = best_payload.get("next_steps") or []
    if not steps:
        return "## Next Steps\n_No follow-up items recorded._"
    lines = ["## Next Steps"]
    lines.extend(f"- {step}" for step in steps)
    return "\n".join(lines)


def _build_front_matter(best_payload: Dict[str, Any]) -> str:
    experiment_id = best_payload.get("experiment_id", "(unknown)")
    label = best_payload.get("experiment_label", experiment_id)
    header = f"# Experiment Report — {label}"
    rows = []
    meta_fields = {
        "Experiment ID": experiment_id,
        "Commit": best_payload.get("commit_sha", "(unknown)"),
        "Dataset Fingerprint": best_payload.get("dataset_fingerprint", "(unknown)"),
        "Optimisation Window": best_payload.get("optimization_window", "(unknown)"),
    }
    for key, value in meta_fields.items():
        rows.append([key, value])
    table = _format_table(["Field", "Value"], rows)
    return "\n".join([header, "", table])


def build_markdown_report(
    best_payload: Dict[str, Any],
    gate_payload: Dict[str, Any],
    telemetry_payload: Dict[str, Any],
) -> str:
    sections = [
        _build_front_matter(best_payload),
        _render_summary_section(best_payload),
        _render_metrics_section(best_payload),
        _render_constraints_section(best_payload),
        _render_gate_section(gate_payload),
        _render_risk_section(telemetry_payload),
        _render_next_steps(best_payload),
    ]
    return "\n\n".join(sections) + "\n"


def generate_report(
    best_params_path: Path,
    gate_path: Path,
    telemetry_path: Path,
    markdown_path: Path,
    json_path: Path,
) -> Dict[str, Any]:
    try:
        best_payload = _load_json(best_params_path, "best parameters")
        gate_payload = _load_json(gate_path, "gate diagnostics")
        telemetry_payload = _load_json(telemetry_path, "portfolio telemetry")
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    markdown = build_markdown_report(best_payload, gate_payload, telemetry_payload)
    _ensure_parent(markdown_path)
    markdown_path.write_text(markdown, encoding="utf-8")

    attachment: Dict[str, Any] = {
        "experiment": {
            "id": best_payload.get("experiment_id"),
            "label": best_payload.get("experiment_label"),
            "commit": best_payload.get("commit_sha"),
            "dataset_fingerprint": best_payload.get("dataset_fingerprint"),
            "optimization_window": best_payload.get("optimization_window"),
        },
        "reports": {
            "markdown": str(markdown_path),
            "sections": [
                "Summary",
                "Metrics",
                "Constraint Compliance",
                "Gate Diagnostics",
                "Risk Snapshot",
                "Next Steps",
            ],
        },
        "best_parameters": best_payload.get("parameters"),
        "metrics": best_payload.get("metrics"),
        "constraints": best_payload.get("constraints"),
        "gate_diagnostics": gate_payload,
        "portfolio_telemetry": telemetry_payload,
        "next_steps": best_payload.get("next_steps"),
    }
    _ensure_parent(json_path)
    json_path.write_text(json.dumps(attachment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return attachment


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--best", "--best-params", required=True, type=Path, help="Path to best_params JSON")
    parser.add_argument("--gate-json", required=True, type=Path, help="Path to gate diagnostics JSON")
    parser.add_argument("--portfolio", required=True, type=Path, help="Path to portfolio telemetry JSON")
    parser.add_argument("--out", "--output-markdown", required=True, type=Path, help="Markdown output path")
    parser.add_argument("--json-out", required=True, type=Path, help="Attachment JSON output path")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    generate_report(args.best, args.gate_json, args.portfolio, args.out, args.json_out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

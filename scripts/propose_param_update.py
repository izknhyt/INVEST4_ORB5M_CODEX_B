"""Compose a pull-request packet for parameter updates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_DOCS = [
    "docs/go_nogo_checklist.md",
    "docs/progress_phase4.md",
    "docs/state_runbook.md",
]


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc


def _ensure_parent(path: Path) -> None:
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def _render_parameter_table(parameters: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> str:
    headers = ["Parameter", "Current", "Proposed"]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for name, proposed in sorted(parameters.items()):
        current = ""
        if previous is not None:
            current_value = previous.get(name)
            current = "" if current_value is None else _format_value(current_value)
        lines.append("| " + " | ".join([
            name,
            current,
            _format_value(proposed),
        ]) + " |")
    return "\n".join(lines)


def _build_pr_title(experiment_label: str, experiment_id: str) -> str:
    prefix = experiment_label or experiment_id
    return f"[{prefix}] Parameter update proposal"


def _build_pr_body(
    experiment_label: str,
    experiment_id: str,
    metrics: Optional[Dict[str, Any]],
    docs_to_update: List[str],
) -> str:
    lines = [
        f"## Summary\n- Experiment: {experiment_label or experiment_id} (`{experiment_id}`)",
        "- Review docs: " + ", ".join(docs_to_update),
    ]
    if metrics:
        lines.append("\n## Metrics Snapshot")
        lines.append("| Metric | Baseline | Candidate | Δ |")
        lines.append("| --- | --- | --- | --- |")
        for name, payload in metrics.items():
            if isinstance(payload, dict):
                baseline = payload.get("baseline")
                candidate = payload.get("candidate")
                delta = None
                if baseline is not None and candidate is not None:
                    try:
                        delta = candidate - baseline
                    except TypeError:
                        delta = None
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(name),
                            "" if baseline is None else _format_value(baseline),
                            "" if candidate is None else _format_value(candidate),
                            "" if delta is None else _format_value(delta),
                        ]
                    )
                    + " |"
                )
            else:
                lines.append(f"| {name} |  | {_format_value(payload)} | |")
    lines.append("\n## Checklist")
    lines.append("- [ ] Validate dataset fingerprint and optimisation window")
    lines.append("- [ ] Confirm gate diagnostics improvements match expectations")
    lines.append("- [ ] Review state archive diff and rerun smoke tests")
    return "\n".join(lines)


def build_markdown(
    experiment_payload: Dict[str, Any],
    best_payload: Dict[str, Any],
    report_payload: Optional[Dict[str, Any]],
    state_diff: Dict[str, Any],
    docs_to_update: List[str],
) -> Dict[str, str]:
    experiment_id = experiment_payload.get("experiment_id") or best_payload.get("experiment_id", "(unknown)")
    label = experiment_payload.get("experiment_label") or best_payload.get("experiment_label", experiment_id)
    parameters = best_payload.get("parameters", {})
    previous = report_payload.get("state", {}).get("current_parameters") if report_payload else None
    metrics = best_payload.get("metrics")

    pr_title = _build_pr_title(label, experiment_id)
    pr_body = _build_pr_body(label, experiment_id, metrics, docs_to_update)

    lines = [f"# Parameter Update Proposal — {label}"]
    lines.append("")
    lines.append(f"**Pull Request Title**: {pr_title}")
    lines.append("")
    lines.append("## Documentation Touchpoints")
    for doc in docs_to_update:
        lines.append(f"- {doc}")
    lines.append("")
    lines.append("## Parameter Changes")
    lines.append(_render_parameter_table(parameters, previous))
    lines.append("")
    lines.append("## State Archive Diff")
    lines.append("```json")
    lines.append(json.dumps(state_diff, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")
    lines.append("## Pull Request Body")
    lines.append(pr_body)

    return {
        "markdown": "\n".join(lines) + "\n",
        "title": pr_title,
        "body": pr_body,
    }


def create_proposal(
    best_params_path: Path,
    report_json_path: Optional[Path],
    state_archive_path: Path,
    markdown_path: Path,
    json_out_path: Optional[Path],
    docs_to_update: List[str],
    force: bool = False,
) -> Dict[str, Any]:
    if markdown_path.exists() and not force:
        print("Output markdown already exists; rerun with --force to overwrite.", file=sys.stderr)
        raise SystemExit(2)
    if json_out_path and json_out_path.exists() and not force:
        print("JSON output already exists; rerun with --force to overwrite.", file=sys.stderr)
        raise SystemExit(2)

    try:
        best_payload = _load_json(best_params_path, "best parameters")
        report_payload = _load_json(report_json_path, "report attachment") if report_json_path else None
        state_diff = _load_json(state_archive_path, "state archive diff")
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    package = build_markdown(best_payload, best_payload, report_payload, state_diff, docs_to_update)

    _ensure_parent(markdown_path)
    markdown_path.write_text(package["markdown"], encoding="utf-8")

    if json_out_path:
        _ensure_parent(json_out_path)
        json_payload = {
            "pull_request": {
                "title": package["title"],
                "body": package["body"],
            },
            "docs_updated": docs_to_update,
            "state_archive": state_diff,
        }
        json_out_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        package["json_payload"] = json_payload
    return package


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--best", "--best-params", required=True, type=Path, help="Path to best_params JSON")
    parser.add_argument("--report-json", type=Path, help="Optional path to generate_experiment_report JSON output")
    parser.add_argument("--state-archive", required=True, type=Path, help="Path to state archive diff JSON")
    parser.add_argument("--out", "--output-markdown", required=True, type=Path, help="Markdown output path")
    parser.add_argument("--json-out", type=Path, help="Optional JSON output path")
    parser.add_argument("--doc", dest="docs", action="append", default=[], help="Doc path to record in the proposal")
    parser.add_argument("--force", action="store_true", help="Overwrite outputs if they already exist")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    docs = args.docs if args.docs else list(DEFAULT_DOCS)
    create_proposal(
        args.best,
        args.report_json,
        args.state_archive,
        args.out,
        args.json_out,
        docs,
        force=args.force,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

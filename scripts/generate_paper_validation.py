#!/usr/bin/env python3
"""Generate Day ORB paper rehearsal validation reports."""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import yaml_compat as yaml  # noqa: E402
from scripts import compare_metrics, update_state  # noqa: E402


_DEFAULT_CONFIG = ROOT / "configs/day_orb/paper_validation.yaml"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalise_token(value: Any) -> str:
    if isinstance(value, bool):
        token = str(value).lower()
    elif isinstance(value, (int, float)):
        token = str(value)
    elif isinstance(value, Path):
        token = value.as_posix()
    else:
        token = str(value)
    token = token.replace("{ROOT}", str(ROOT))
    return token


def _resolve_path(value: Any) -> Path:
    token = _normalise_token(value)
    path = Path(token).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        path = path.resolve()
    return path


def _build_cli(tokens: Sequence[Any]) -> list[str]:
    argv: list[str] = []
    for token in tokens:
        if token is None:
            continue
        argv.append(_normalise_token(token))
    return argv


def _load_config(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, Mapping):
        raise ValueError("Paper validation config must be a mapping")
    return data


def _extract_json_out(argv: Sequence[str]) -> Path | None:
    for index, token in enumerate(argv):
        if token == "--json-out" and index + 1 < len(argv):
            return _resolve_path(argv[index + 1])
    return None


def _ensure_simulate_live(argv: list[str]) -> None:
    if "--simulate-live" not in argv:
        argv.append("--simulate-live")


def _evaluate_paper_status(update_payload: Mapping[str, Any], diff_payload: Mapping[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    paper_blockers = []

    paper_meta = update_payload.get("paper_validation")
    if isinstance(paper_meta, Mapping):
        status = str(paper_meta.get("status") or "").lower()
        if status != "go":
            paper_blockers.append(f"update_state:{status or 'unknown'}")
        extra_reasons = paper_meta.get("reasons")
        if isinstance(extra_reasons, Sequence):
            reasons.extend(str(item) for item in extra_reasons if item)
    else:
        paper_blockers.append("update_state:missing_paper_validation")

    summary = diff_payload.get("summary")
    if isinstance(summary, Mapping):
        if summary.get("significant_differences"):
            paper_blockers.append("metrics_diff:significant_differences")
        if summary.get("missing_in_left") or summary.get("missing_in_right"):
            paper_blockers.append("metrics_diff:missing_keys")
    else:
        paper_blockers.append("metrics_diff:summary_missing")

    if paper_blockers:
        reasons.extend(paper_blockers)
        return "no-go", reasons
    return "go", reasons


def _run_update_state(argv: list[str]) -> tuple[int, Mapping[str, Any]]:
    stdout_buffer = StringIO()
    with redirect_stdout(stdout_buffer):
        exit_code = update_state.main(argv)
    output = stdout_buffer.getvalue().strip()
    payload = json.loads(output) if output else {}
    if not isinstance(payload, Mapping):
        raise ValueError("update_state returned non-object payload")
    return exit_code, payload


def _run_compare_metrics(argv: list[str], out_path: Path) -> tuple[int, Mapping[str, Any]]:
    exit_code = compare_metrics.main(argv)
    if not out_path.exists():
        raise FileNotFoundError(f"compare_metrics did not create {out_path}")
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("compare_metrics produced non-object JSON")
    return exit_code, payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG),
        help="YAML file describing update_state / compare_metrics invocations",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for the consolidated validation report",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip command execution and only validate existing artefacts",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = _resolve_path(args.config)
    config = _load_config(config_path)

    update_cfg = config.get("update_state", {})
    if not isinstance(update_cfg, Mapping):
        raise SystemExit("update_state section must be a mapping")
    update_args = _build_cli(update_cfg.get("args", []))
    _ensure_simulate_live(update_args)
    json_out_path = _extract_json_out(update_args)
    if json_out_path is None:
        json_out_path = _resolve_path("reports/day_orb/update_state_simulation.json")
        update_args.extend(["--json-out", str(json_out_path)])

    diff_cfg = config.get("compare_metrics", {})
    if not isinstance(diff_cfg, Mapping):
        raise SystemExit("compare_metrics section must be a mapping")
    left_path = diff_cfg.get("left")
    right_path = diff_cfg.get("right")
    if left_path is None or right_path is None:
        raise SystemExit("compare_metrics.left and compare_metrics.right must be provided")

    diff_args: list[str] = [
        "--left",
        str(_resolve_path(left_path)),
        "--right",
        str(_resolve_path(right_path)),
    ]
    ignore_patterns = diff_cfg.get("ignore", [])
    if isinstance(ignore_patterns, Sequence):
        for pattern in ignore_patterns:
            diff_args.extend(["--ignore", _normalise_token(pattern)])
    abs_tol = diff_cfg.get("abs_tol")
    if abs_tol is not None:
        diff_args.extend(["--abs-tol", str(abs_tol)])
    rel_tol = diff_cfg.get("rel_tol")
    if rel_tol is not None:
        diff_args.extend(["--rel-tol", str(rel_tol)])
    diff_out_path = _resolve_path(
        diff_cfg.get("out_json", "reports/day_orb/paper_validation_metrics_diff.json")
    )
    diff_args.extend(["--out-json", str(diff_out_path)])

    report_cfg = config.get("report", {})
    if not isinstance(report_cfg, Mapping):
        report_cfg = {}
    report_target = args.out or report_cfg.get("path", "reports/day_orb/paper_validation.json")
    report_path = _resolve_path(report_target)

    update_exit = 0
    update_payload: Mapping[str, Any]
    if args.dry_run:
        if not json_out_path.exists():
            raise SystemExit("--dry-run requested but update_state JSON artefact is missing")
        update_payload = json.loads(json_out_path.read_text(encoding="utf-8"))
        if not isinstance(update_payload, Mapping):
            raise SystemExit("update_state JSON artefact is not a mapping")
    else:
        update_exit, update_payload = _run_update_state(update_args)
        if update_exit:
            print(json.dumps(update_payload, ensure_ascii=False, indent=2))
            return update_exit

    diff_exit = 0
    diff_payload: Mapping[str, Any]
    if args.dry_run:
        if not diff_out_path.exists():
            raise SystemExit("--dry-run requested but compare_metrics JSON artefact is missing")
        diff_payload = json.loads(diff_out_path.read_text(encoding="utf-8"))
        if not isinstance(diff_payload, Mapping):
            raise SystemExit("compare_metrics JSON artefact is not a mapping")
    else:
        diff_exit, diff_payload = _run_compare_metrics(diff_args, diff_out_path)
        if diff_exit:
            print(json.dumps(diff_payload, ensure_ascii=False, indent=2))
            return diff_exit

    status, reasons = _evaluate_paper_status(update_payload, diff_payload)

    report = {
        "generated_at": _utcnow_iso(),
        "config_path": str(config_path),
        "commands": {
            "update_state": update_args,
            "compare_metrics": diff_args,
        },
        "artefacts": {
            "update_state": str(json_out_path),
            "metrics_diff": str(diff_out_path),
            "report": str(report_path),
        },
        "update_state": update_payload,
        "metrics_comparison": diff_payload,
        "paper_rehearsal": {
            "status": status,
            "reasons": reasons,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if status == "go" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

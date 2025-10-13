"""Compare run_sim metrics JSON outputs and highlight differences.

This CLI is designed for Phase 4 long-run parity checks. It loads the left and
right metrics payloads, flattens nested dictionaries using dot notation, and
compares numeric values with configurable absolute/relative tolerances. String
and boolean values must match exactly unless ignored. Missing keys are reported
explicitly so operators can triage schema drift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._webhook import deliver_webhook


@dataclass(slots=True)
class MetricDifference:
    key: str
    left: Any
    right: Any
    abs_delta: float | None = None
    rel_delta: float | None = None
    within_tolerance: bool = False
    reason: str = "value_mismatch"


@dataclass(slots=True)
class ComparisonResult:
    left_path: Path
    right_path: Path
    matched_keys: list[str] = field(default_factory=list)
    ignored_keys: list[str] = field(default_factory=list)
    missing_in_left: list[str] = field(default_factory=list)
    missing_in_right: list[str] = field(default_factory=list)
    differences: list[MetricDifference] = field(default_factory=list)

    @property
    def significant_differences(self) -> Sequence[MetricDifference]:
        return [diff for diff in self.differences if not diff.within_tolerance]

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": str(self.left_path),
            "right": str(self.right_path),
            "summary": {
                "matched": len(self.matched_keys),
                "ignored": len(self.ignored_keys),
                "missing_in_left": len(self.missing_in_left),
                "missing_in_right": len(self.missing_in_right),
                "differences": len(self.differences),
                "significant_differences": len(self.significant_differences),
            },
            "missing_in_left": self.missing_in_left,
            "missing_in_right": self.missing_in_right,
            "ignored": self.ignored_keys,
            "differences": [
                {
                    "key": diff.key,
                    "left": diff.left,
                    "right": diff.right,
                    "abs_delta": diff.abs_delta,
                    "rel_delta": diff.rel_delta,
                    "within_tolerance": diff.within_tolerance,
                    "reason": diff.reason,
                }
                for diff in self.differences
            ],
        }


@dataclass(frozen=True)
class WebhookConfig:
    """Resolved webhook delivery options."""

    urls: tuple[str, ...]
    timeout: float
    secret: str | None
    dry_run: bool
    fail_on_error: bool


MAX_WEBHOOK_DIFFS = 20


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _flatten(prefix: str, payload: Any) -> dict[str, Any]:
    key_prefix = f"{prefix}." if prefix else ""
    if isinstance(payload, Mapping):
        flattened: dict[str, Any] = {}
        for key, value in payload.items():
            flattened.update(_flatten(f"{key_prefix}{key}", value))
        return flattened
    if isinstance(payload, list):
        flattened: dict[str, Any] = {}
        for index, value in enumerate(payload):
            flattened.update(_flatten(f"{key_prefix}[{index}]", value))
        if not payload:
            flattened[prefix] = []
        return flattened
    return {prefix: payload}


def _should_ignore(key: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch(key, pattern) for pattern in patterns)


def _split_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [url.strip() for url in raw.split(",") if url and url.strip()]


def _deduplicate_preserving_order(urls: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _has_significant_issues(result: ComparisonResult) -> bool:
    return bool(result.significant_differences or result.missing_in_left or result.missing_in_right)


def _resolve_webhook_config(args: argparse.Namespace) -> WebhookConfig | None:
    raw_urls: list[str] = []
    if args.webhook_url:
        for value in args.webhook_url:
            raw_urls.extend(_split_urls(value))
    if getattr(args, "webhook_url_env", None):
        env_value = os.getenv(args.webhook_url_env)
        raw_urls.extend(_split_urls(env_value))

    urls = _deduplicate_preserving_order(raw_urls)
    if not urls:
        return None

    timeout = float(args.webhook_timeout)
    if timeout <= 0.0:
        raise ValueError("--webhook-timeout must be positive")

    secret: str | None = None
    if getattr(args, "webhook_secret_env", None):
        env_secret = os.getenv(args.webhook_secret_env)
        if env_secret:
            trimmed = env_secret.strip()
            if trimmed:
                secret = trimmed

    return WebhookConfig(
        urls=tuple(urls),
        timeout=timeout,
        secret=secret,
        dry_run=bool(getattr(args, "dry_run_webhook", False)),
        fail_on_error=bool(getattr(args, "fail_on_webhook_error", False)),
    )


def _build_webhook_payload(result: ComparisonResult) -> dict[str, Any]:
    summary = {
        "matched": len(result.matched_keys),
        "ignored": len(result.ignored_keys),
        "missing_in_left": len(result.missing_in_left),
        "missing_in_right": len(result.missing_in_right),
        "differences": len(result.differences),
        "significant_differences": len(result.significant_differences),
    }
    payload: dict[str, Any] = {
        "type": "compare_metrics.diff",
        "status": "diff_detected" if _has_significant_issues(result) else "ok",
        "left": str(result.left_path),
        "right": str(result.right_path),
        "summary": summary,
        "missing_in_left": result.missing_in_left,
        "missing_in_right": result.missing_in_right,
    }

    if result.significant_differences:
        truncated = max(len(result.significant_differences) - MAX_WEBHOOK_DIFFS, 0)
        payload["significant_differences"] = [
            {
                "key": diff.key,
                "left": diff.left,
                "right": diff.right,
                "abs_delta": diff.abs_delta,
                "rel_delta": diff.rel_delta,
                "reason": diff.reason,
            }
            for diff in result.significant_differences[:MAX_WEBHOOK_DIFFS]
        ]
        if truncated:
            payload["significant_differences_truncated"] = truncated

    return payload


def dispatch_diff_webhooks(result: ComparisonResult, config: WebhookConfig) -> list[dict[str, Any]]:
    payload = _build_webhook_payload(result)
    deliveries: list[dict[str, Any]] = []

    for url in config.urls:
        if config.dry_run:
            print(f"[compare_metrics] Dry-run webhook -> {url}")
            deliveries.append({"url": url, "status": "dry_run"})
            continue

        delivery = deliver_webhook(url, payload, timeout=config.timeout, secret=config.secret)
        record = {
            "url": url,
            "status": delivery.status,
            "attempts": delivery.attempts,
            "status_code": delivery.status_code,
            "response_ms": delivery.response_ms,
            "error": delivery.error,
        }
        deliveries.append(record)

        if delivery.status == "ok":
            latency = f"{delivery.response_ms:.1f} ms" if delivery.response_ms is not None else "n/a"
            print(
                f"[compare_metrics] webhook {url} delivered (attempts={delivery.attempts}, "
                f"status_code={delivery.status_code}, latency={latency})"
            )
        else:
            message = delivery.error or f"HTTP {delivery.status_code or 'unknown'}"
            print(f"[compare_metrics] webhook {url} failed: {message}", file=sys.stderr)

    return deliveries


def _load_json(path: Path) -> Any:
    if not path.exists():
        msg = f"Metrics file not found: {path}"
        raise FileNotFoundError(msg)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def compare_metrics(
    left_payload: Mapping[str, Any],
    right_payload: Mapping[str, Any],
    *,
    left_path: Path,
    right_path: Path,
    ignore_patterns: Sequence[str] | None = None,
    abs_tolerance: float = 0.0,
    rel_tolerance: float = 0.0,
) -> ComparisonResult:
    ignore_patterns = tuple(ignore_patterns or ())
    left_flat = _flatten("", left_payload)
    right_flat = _flatten("", right_payload)

    result = ComparisonResult(left_path=left_path, right_path=right_path)
    all_keys = sorted(set(left_flat) | set(right_flat))

    for key in all_keys:
        if _should_ignore(key, ignore_patterns):
            result.ignored_keys.append(key)
            continue
        left_has = key in left_flat
        right_has = key in right_flat
        if not left_has:
            result.missing_in_left.append(key)
            continue
        if not right_has:
            result.missing_in_right.append(key)
            continue
        left_value = left_flat[key]
        right_value = right_flat[key]
        if _is_number(left_value) and _is_number(right_value):
            left_float = float(left_value)
            right_float = float(right_value)
            delta = right_float - left_float
            magnitude = max(abs(left_float), abs(right_float))
            if delta == 0.0:
                result.matched_keys.append(key)
                continue
            within_abs = abs(delta) <= abs_tolerance
            within_rel = False
            if rel_tolerance > 0.0:
                within_rel = magnitude == 0.0 or abs(delta) <= rel_tolerance * magnitude
            within = within_abs or within_rel
            rel_delta = None
            if magnitude > 0.0:
                rel_delta = delta / magnitude
            result.differences.append(
                MetricDifference(
                    key=key,
                    left=left_value,
                    right=right_value,
                    abs_delta=delta,
                    rel_delta=rel_delta,
                    within_tolerance=within,
                )
            )
            result.matched_keys.append(key)
            continue
        if left_value == right_value:
            result.matched_keys.append(key)
            continue
        result.differences.append(
            MetricDifference(
                key=key,
                left=left_value,
                right=right_value,
                within_tolerance=False,
                reason="type_mismatch" if type(left_value) != type(right_value) else "value_mismatch",
            )
        )

    return result


def _format_difference(diff: MetricDifference) -> str:
    if diff.reason == "value_mismatch" and diff.abs_delta is not None:
        rel_display = (
            f", rel_delta={diff.rel_delta:+.4f}"
            if diff.rel_delta is not None
            else ""
        )
        status = "within tolerance" if diff.within_tolerance else "exceeds tolerance"
        return (
            f"- {diff.key}: left={diff.left!r}, right={diff.right!r}, "
            f"abs_delta={diff.abs_delta:+.6f}{rel_display} ({status})"
        )
    return (
        f"- {diff.key}: left={diff.left!r}, right={diff.right!r} "
        f"({diff.reason})"
    )


def _print_summary(result: ComparisonResult) -> None:
    print("=== Metrics Comparison ===")
    print(f"Left : {result.left_path}")
    print(f"Right: {result.right_path}")
    print()
    print("Summary:")
    print(f"  Matched keys         : {len(result.matched_keys)}")
    print(f"  Ignored keys         : {len(result.ignored_keys)}")
    print(f"  Missing in left      : {len(result.missing_in_left)}")
    print(f"  Missing in right     : {len(result.missing_in_right)}")
    print(f"  Total differences    : {len(result.differences)}")
    print(f"  Significant diffs    : {len(result.significant_differences)}")
    if result.ignored_keys:
        print("  Ignored patterns:")
        for key in result.ignored_keys:
            print(f"    - {key}")
    if result.missing_in_left:
        print("\nMissing in left:")
        for key in result.missing_in_left:
            print(f"  - {key}")
    if result.missing_in_right:
        print("\nMissing in right:")
        for key in result.missing_in_right:
            print(f"  - {key}")
    if result.differences:
        print("\nDifferences:")
        for diff in result.differences:
            print(_format_difference(diff))
    else:
        print("\nNo differences detected.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two run_sim metrics payloads")
    parser.add_argument("--left", required=True, help="Path to baseline metrics.json")
    parser.add_argument("--right", required=True, help="Path to candidate metrics.json")
    parser.add_argument(
        "--ignore",
        action="append",
        default=None,
        help="Glob pattern for keys to ignore (can be provided multiple times)",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=0.0,
        help="Absolute tolerance for numeric differences",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=0.0,
        help="Relative tolerance for numeric differences (0-1 range)",
    )
    parser.add_argument(
        "--out-json",
        help="Optional path to write the comparison result as JSON",
    )
    parser.add_argument(
        "--webhook-url",
        action="append",
        help="Webhook URL(s) for diff alerts. Can be provided multiple times or as comma-separated values.",
    )
    parser.add_argument(
        "--webhook-url-env",
        help="Environment variable containing additional webhook URL(s).",
    )
    parser.add_argument(
        "--webhook-timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds when delivering webhook payloads.",
    )
    parser.add_argument(
        "--webhook-secret-env",
        help="Environment variable containing an optional webhook signing secret.",
    )
    parser.add_argument(
        "--dry-run-webhook",
        action="store_true",
        help="Log the webhook payload without sending it.",
    )
    parser.add_argument(
        "--fail-on-webhook-error",
        action="store_true",
        help="Exit non-zero when webhook delivery fails (default: continue).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    left_path = Path(args.left)
    right_path = Path(args.right)

    left_payload = _load_json(left_path)
    right_payload = _load_json(right_path)

    if not isinstance(left_payload, Mapping) or not isinstance(right_payload, Mapping):
        parser.error("Metrics payloads must be JSON objects at the top level")

    result = compare_metrics(
        left_payload,
        right_payload,
        left_path=left_path,
        right_path=right_path,
        ignore_patterns=args.ignore,
        abs_tolerance=args.abs_tol,
        rel_tolerance=args.rel_tol,
    )

    _print_summary(result)

    webhook_results: list[dict[str, Any]] | None = None
    try:
        webhook_config = _resolve_webhook_config(args)
    except ValueError as exc:
        parser.error(str(exc))
        return 2  # pragma: no cover - parser.error raises SystemExit
    if webhook_config:
        if _has_significant_issues(result):
            webhook_results = dispatch_diff_webhooks(result, webhook_config)
            if webhook_config.fail_on_error:
                has_failure = any(
                    entry.get("status") not in {"ok", "dry_run"} for entry in webhook_results
                )
                if has_failure:
                    print(
                        "[compare_metrics] Aborting due to webhook delivery failure (see stderr above).",
                        file=sys.stderr,
                    )
                    return 2
        else:
            print("[compare_metrics] No significant differences detected; skipping webhook delivery.")
            webhook_results = []

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        if webhook_results is not None:
            payload["webhook_delivery"] = webhook_results
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nWrote diff report to {out_path}")

    return 0 if not result.significant_differences and not result.missing_in_left and not result.missing_in_right else 1


if __name__ == "__main__":
    sys.exit(main())

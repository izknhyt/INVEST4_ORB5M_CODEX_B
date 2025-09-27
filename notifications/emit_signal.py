#!/usr/bin/env python3
"""Slackなどへのシグナル通知を担当するスタブ実装。"""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable, Optional

try:
    import urllib.request
    import urllib.error
except Exception:  # pragma: no cover
    urllib = None


@dataclass
class SignalPayload:
    signal_id: str
    timestamp_utc: str
    side: str
    entry: float
    tp: float
    sl: float
    trail: float
    confidence: float
    meta: Optional[dict] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def send_webhook(url: str, payload: SignalPayload, timeout: float = 5.0) -> tuple[bool, str]:
    if urllib is None:
        return False, "urllib not available"
    data = payload.to_json().encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"status={resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"http_error={e.code}"
    except urllib.error.URLError as e:
        return False, f"url_error={e.reason}"
    except Exception as e:  # pragma: no cover
        return False, f"unexpected_error={type(e).__name__}:{e}"


def log_latency(output_path: str, signal_id: str, ts_emit: str, success: bool, detail: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    ts_ack = datetime.now(timezone.utc).isoformat()
    line = ",".join([
        signal_id,
        ts_emit,
        ts_ack,
        "success" if success else "failure",
        detail,
    ])
    header = "signal_id,ts_emit,ts_ack,status,detail\n"
    need_header = not os.path.exists(output_path)
    with open(output_path, "a", encoding="utf-8") as f:
        if need_header:
            f.write(header)
        f.write(line + "\n")


def log_fallback(path: str, payload: SignalPayload, note: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    record = {
        "ts": ts,
        "note": note,
        **asdict(payload),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def resolve_webhook_urls(cli_value: Optional[str]) -> list[str]:
    sources: Iterable[str] = []
    if cli_value:
        sources = [cli_value]
    elif os.getenv("SIGNAL_WEBHOOK_URLS"):
        sources = os.getenv("SIGNAL_WEBHOOK_URLS").split(";")
    urls: list[str] = []
    for src in sources:
        for part in src.split(","):
            part = part.strip()
            if part:
                urls.append(part)
    return urls


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Emit signal notification via webhook")
    p.add_argument("--signal-id", required=True)
    p.add_argument("--side", required=True, choices=["BUY", "SELL"])
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--tp", type=float, required=True)
    p.add_argument("--sl", type=float, required=True)
    p.add_argument("--trail", type=float, default=0.0)
    p.add_argument("--confidence", type=float, default=0.0)
    p.add_argument("--timestamp", default=None, help="ISO8601 timestamp (UTC). default=now")
    p.add_argument("--webhook-url", default=None, help="Slack等のwebhook URL (複数指定はカンマ区切り)")
    p.add_argument("--latency-log", default="ops/signal_latency.csv")
    p.add_argument("--fallback-log", default="ops/signal_notifications.log")
    p.add_argument("--meta", default=None, help="追加情報(JSON文字列)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    ts = args.timestamp or datetime.now(timezone.utc).isoformat()
    meta = None
    if args.meta:
        try:
            meta = json.loads(args.meta)
        except json.JSONDecodeError:
            print("meta must be valid JSON", file=sys.stderr)
            return 2
    payload = SignalPayload(
        signal_id=args.signal_id,
        timestamp_utc=ts,
        side=args.side,
        entry=args.entry,
        tp=args.tp,
        sl=args.sl,
        trail=args.trail,
        confidence=args.confidence,
        meta=meta,
    )

    urls = resolve_webhook_urls(args.webhook_url)
    success = False
    detail = "noop"
    for url in urls:
        ok, detail = send_webhook(url, payload)
        if ok:
            success = True
            break
    if not urls:
        detail = "no_webhook"
    log_latency(args.latency_log, args.signal_id, ts, success, detail)
    if not success:
        log_fallback(args.fallback_log, payload, detail)
    print(payload.to_json())
    return 0 if success or not urls else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Webhook delivery helpers supporting HMAC signatures and retries."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__all__ = ["WebhookDeliveryResult", "deliver_webhook", "sign_payload"]


class WebhookError(RuntimeError):
    """Raised when a webhook request fails irrecoverably."""


@dataclass(frozen=True)
class WebhookDeliveryResult:
    """Structured webhook delivery metadata."""

    url: str
    status: str
    attempts: int
    status_code: Optional[int] = None
    response_ms: Optional[float] = None
    error: Optional[str] = None
    body: Optional[str] = None


def sign_payload(payload: bytes, secret: str) -> str:
    """Return the hexadecimal HMAC-SHA256 signature for *payload*."""

    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    return digest.hexdigest()


def deliver_webhook(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Optional[Mapping[str, str]] = None,
    secret: Optional[str] = None,
    timeout: float = 10.0,
    max_retries: int = 3,
    retry_wait_seconds: float = 60.0,
    opener: Callable[..., Any] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> WebhookDeliveryResult:
    """Send *payload* to *url* with retries.

    Retries are attempted for HTTP 5xx responses and network errors. A
    ``Retry-After`` header is honoured when present.
    """

    attempts = 0
    wait_seconds = max(retry_wait_seconds, 0.0)
    last_error: Optional[str] = None
    extra_headers = dict(headers or {})

    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if secret:
        extra_headers["X-OBS-Signature"] = sign_payload(payload_bytes, secret)

    while attempts < max_retries:
        attempts += 1
        start = time.perf_counter()
        try:
            status_code, body_text = _post_json(
                url,
                payload_bytes,
                headers=extra_headers,
                timeout=timeout,
                opener=opener,
            )
        except WebhookError as exc:
            last_error = str(exc)
            if attempts >= max_retries:
                return WebhookDeliveryResult(
                    url=url,
                    status="error",
                    attempts=attempts,
                    error=last_error,
                )
            if wait_seconds:
                sleeper(wait_seconds)
                wait_seconds *= 2
            continue

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if 200 <= status_code < 300:
            return WebhookDeliveryResult(
                url=url,
                status="ok",
                attempts=attempts,
                status_code=status_code,
                response_ms=elapsed_ms,
                body=body_text,
            )
        if status_code in {429, 503}:
            retry_after = _parse_retry_after(body_text)
            if retry_after is not None:
                wait_seconds = retry_after
        if status_code >= 500 and attempts < max_retries:
            if wait_seconds:
                sleeper(wait_seconds)
                wait_seconds *= 2
            continue
        return WebhookDeliveryResult(
            url=url,
            status="error",
            attempts=attempts,
            status_code=status_code,
            response_ms=elapsed_ms,
            error=body_text or f"HTTP {status_code}",
            body=body_text,
        )

    return WebhookDeliveryResult(
        url=url,
        status="error",
        attempts=attempts,
        error=last_error or "max_retries_exhausted",
    )


def _post_json(
    url: str,
    payload_bytes: bytes,
    *,
    headers: Mapping[str, str],
    timeout: float,
    opener: Callable[..., Any],
) -> tuple[int, str]:
    request_headers = {"Content-Type": "application/json", "User-Agent": "observability-automation/1.0"}
    request_headers.update(headers)
    request = Request(url, data=payload_bytes, headers=request_headers, method="POST")
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            body_bytes = response.read() if hasattr(response, "read") else b""
            return int(status or 0), body_bytes.decode("utf-8", "ignore")
    except HTTPError as err:
        body_bytes = err.read() if hasattr(err, "read") else b""
        return err.code, body_bytes.decode("utf-8", "ignore")
    except URLError as err:  # pragma: no cover - network errors are rare in tests
        raise WebhookError(str(err)) from err


def _parse_retry_after(body: str) -> Optional[float]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    retry_after = data.get("retry_after") if isinstance(data, Mapping) else None
    if isinstance(retry_after, (int, float)):
        return float(retry_after)
    return None

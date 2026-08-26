"""Razorpay status reconciliation, intentionally separate from webhook ingress."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from .settings import Settings


class ReconciliationError(RuntimeError):
    pass


def fetch_payment_status(settings: Settings, payment_id: str) -> dict[str, Any]:
    """Read Razorpay's permitted payment-status path without logging credentials."""

    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise ReconciliationError("Razorpay API credentials are not configured")
    try:
        response = httpx.get(
            f"{settings.razorpay_api_base_url}/payments/{payment_id}",
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            timeout=settings.reconciliation_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ReconciliationError(f"Razorpay status lookup failed: {exc.__class__.__name__}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
        raise ReconciliationError("Razorpay status response is malformed")
    return payload


def reconciliation_event_payload(payment: dict[str, Any], requested_at: datetime) -> dict[str, Any]:
    """Translate an API response to the same evidence vocabulary as webhooks."""

    status = payment.get("status")
    event_type = {
        "created": "payment.created",
        "authorized": "payment.authorized",
        "captured": "payment.captured",
        "failed": "payment.failed",
    }.get(status, "payment.processing")
    return {
        "event": event_type,
        # The API's ``created_at`` is the payment creation time, not the time this
        # status observation was made.  Reducer ordering must use the latter.
        "created_at": int(requested_at.timestamp()),
        "account_id": payment.get("merchant_id") or payment.get("account_id"),
        "payload": {"payment": {"entity": payment}},
    }

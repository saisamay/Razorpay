from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .models import RawEvent
from .schemas import CanonicalEvent, FailureEvidence


class NormalizationError(ValueError):
    pass


class QuarantineError(ValueError):
    """Raised when an authenticated payload fails semantic constraints and should be quarantined."""
    pass


def _timestamp(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, (int, float)):
        # Check bounds: timestamp < 2020 or > +24h in future
        if value < 1577836800 or value > (datetime.now(timezone.utc).timestamp() + 86400):
            raise QuarantineError(f"timestamp out of valid range: {value}")
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.year < 2020 or dt > (datetime.now(timezone.utc) + timedelta(days=1)):
                raise QuarantineError(f"timestamp string out of valid range: {value}")
            return dt
        except ValueError:
            pass
    return fallback


def normalize_razorpay_event(event: RawEvent) -> CanonicalEvent:
    payload = event.raw_payload
    webhook_type = payload.get("event")
    if not isinstance(webhook_type, str) or not webhook_type:
        raise NormalizationError("missing event name")

    entities = payload.get("payload")
    if not isinstance(entities, dict):
        raise NormalizationError("missing payload object")
    payment = entities.get("payment")
    payment_entity = payment.get("entity") if isinstance(payment, dict) else None
    if not isinstance(payment_entity, dict):
        raise NormalizationError("payment entity is required for payment-state reconstruction")

    payment_id = payment_entity.get("id")
    if not isinstance(payment_id, str) or not payment_id:
        raise NormalizationError("missing payment id")
    if len(payment_id) > 255:
        raise QuarantineError("payment id exceeds maximum length of 255 characters")

    amount = payment_entity.get("amount")
    if isinstance(amount, (int, float)) and amount < 0:
        raise QuarantineError(f"invalid negative monetary amount: {amount}")

    currency = payment_entity.get("currency")
    if currency is not None:
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            raise QuarantineError(f"invalid ISO 4217 currency representation: {currency}")

    failure = None
    if webhook_type == "payment.failed":
        failure = FailureEvidence(
            source=payment_entity.get("error_source"),
            step=payment_entity.get("error_step"),
            reason=payment_entity.get("error_reason") or payment_entity.get("error_description"),
            code=payment_entity.get("error_code"),
        )

    return CanonicalEvent(
        event_id=event.source_event_id,
        environment=event.environment,
        event_type=webhook_type,
        occurred_at=_timestamp(payload.get("created_at"), event.received_at),
        received_at=event.received_at,
        merchant_id=payload.get("account_id"),
        order_id=payment_entity.get("order_id"),
        payment_id=payment_id,
        amount=amount,
        currency=currency.upper() if isinstance(currency, str) else None,
        payment_method=payment_entity.get("method"),
        raw_reference=f"db://raw-events/{event.id}",
        failure=failure,
    )


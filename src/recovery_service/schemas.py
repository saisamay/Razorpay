from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FailureEvidence(BaseModel):
    source: str | None = None
    step: str | None = None
    reason: str | None = None
    code: str | None = None


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    source: str = "razorpay"
    environment: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    merchant_id: str | None = None
    order_id: str | None = None
    payment_id: str
    amount: int | None = Field(default=None, ge=0)
    currency: str | None = None
    payment_method: str | None = None
    raw_reference: str
    failure: FailureEvidence | None = None
    schema_version: str = "1.0"


class RecoveryGate(BaseModel):
    recovery_eligible: bool
    reason: str
    state: str
    state_confidence: float


class StateView(BaseModel):
    payment_id: str
    merchant_id: str | None
    order_id: str | None
    amount: int | None
    currency: str | None
    state: str
    state_confidence: float
    anomalies: list[dict[str, Any]]
    first_seen_at: datetime
    last_seen_at: datetime
    state_version: int
    recovery_gate: RecoveryGate


from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="uq_raw_event_source_id"),
        Index("ix_raw_events_payment_occurred_at", "payment_id", "occurred_at"),
        Index("ix_raw_events_payment_received_at", "payment_id", "received_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="razorpay")
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    normalized_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # These are deliberately copied at ingress.  They make payment reconstruction
    # and timelines indexed database queries instead of application-side scans.
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    processing_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    processing_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaymentState(Base):
    __tablename__ = "payment_states"

    payment_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    state_confidence: Mapped[float] = mapped_column(nullable=False)
    anomalies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PaymentProcessingLock(Base):
    """A durable per-payment mutex used by independently running workers."""

    __tablename__ = "payment_processing_locks"

    payment_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    __table_args__ = (UniqueConstraint("payment_id", "recovery_episode_id", name="uq_case_payment_episode"),)

    case_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recovery_episode_id: Mapped[str] = mapped_column(String(80), nullable=False)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    state_confidence: Mapped[float] = mapped_column(nullable=False)
    failure_evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recovery_eligible: Mapped[bool] = mapped_column(nullable=False)
    eligibility_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    failure_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_error: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, nullable=False)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ReconciliationAttempt(Base):
    __tablename__ = "reconciliation_attempts"
    __table_args__ = (UniqueConstraint("payment_id", "attempt", name="uq_reconciliation_payment_attempt"),)

    reconciliation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="razorpay_api")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

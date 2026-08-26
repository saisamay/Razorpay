from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import DeadLetterEvent, PaymentProcessingLock, PaymentState, RawEvent, ReconciliationAttempt, RecoveryCase, utc_now
from .normalizer import NormalizationError, normalize_razorpay_event
from .observability import CONTRADICTIONS, DLQ_EVENTS, LATE_EVENTS, OUT_OF_ORDER_EVENTS, PROCESSING_LATENCY, PROCESSED_EVENTS, RECOVERY_CASES, STATE_TRANSITIONS, UNKNOWN_STATES, structured_log
from .reconciliation import ReconciliationError, fetch_payment_status, reconciliation_event_payload
from .schemas import CanonicalEvent, RecoveryGate, StateView
from .settings import Settings
from .state_machine import recovery_gate, reduce_events


logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class ProcessingResult:
    event_id: str
    payment_id: str | None
    status: str


def _canonical_events(session: Session, payment_id: str) -> list[CanonicalEvent]:
    """Load only the indexed evidence set for one payment, in reducer order."""
    rows = session.scalars(
        select(RawEvent)
        .where(RawEvent.payment_id == payment_id, RawEvent.processing_status != "DLQ")
        .order_by(RawEvent.occurred_at, RawEvent.received_at, RawEvent.source_event_id)
    ).all()
    return [CanonicalEvent.model_validate(row.normalized_payload) for row in rows if row.normalized_payload]


def _case_id(payment_id: str, episode_event_id: str) -> str:
    digest = hashlib.sha256(f"{payment_id}:{episode_event_id}".encode()).hexdigest()[:32]
    return f"rc_{digest}"


def _utc(value: datetime) -> datetime:
    # SQLite does not round-trip timezone offsets for DateTime columns even when
    # SQLAlchemy declares timezone=True; production PostgreSQL does.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _record_reduction_metrics(previous_state: str | None, reduction) -> None:
    if previous_state != reduction.state:
        STATE_TRANSITIONS.labels(previous_state or "NONE", reduction.state).inc()
    for anomaly in reduction.anomalies:
        kind = anomaly.get("type", "UNKNOWN")
        if kind == "OUT_OF_ORDER_ARRIVAL":
            OUT_OF_ORDER_EVENTS.inc()
        elif kind.startswith("LATE_"):
            LATE_EVENTS.labels(kind).inc()
        elif "EVIDENCE" in kind or kind.startswith("STALE_"):
            CONTRADICTIONS.labels(kind).inc()


def _upsert_recovery_case(session: Session, state: PaymentState, reduction) -> None:
    gate = recovery_gate(reduction)
    existing_cases = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == state.payment_id).with_for_update()).all()
    for existing_case in existing_cases:
        was_eligible = existing_case.recovery_eligible
        existing_case.last_seen_at = state.last_seen_at
        existing_case.state = state.state
        existing_case.state_confidence = state.state_confidence
        existing_case.recovery_eligible = gate.recovery_eligible
        existing_case.eligibility_reason = gate.reason
        if was_eligible and not gate.recovery_eligible:
            RECOVERY_CASES.labels("revoked").inc()

    if not gate.recovery_eligible or not reduction.recovery_episode_event_id:
        return
    case_id = _case_id(state.payment_id, reduction.recovery_episode_event_id)
    recovery_case = session.get(RecoveryCase, case_id, with_for_update=True)
    if recovery_case is None:
        session.add(RecoveryCase(
            case_id=case_id, payment_id=state.payment_id, recovery_episode_id=reduction.recovery_episode_event_id,
            merchant_id=state.merchant_id, order_id=state.order_id, amount=state.amount, currency=state.currency,
            state=state.state, state_confidence=state.state_confidence,
            failure_evidence=reduction.failure_evidence.model_dump(mode="json"), first_seen_at=state.first_seen_at,
            last_seen_at=state.last_seen_at, recovery_eligible=True, eligibility_reason=gate.reason,
        ))
        RECOVERY_CASES.labels("created").inc()
    else:
        recovery_case.failure_evidence = reduction.failure_evidence.model_dump(mode="json")


def _move_to_dlq(session: Session, event: RawEvent, error: str) -> None:
    event.processing_status = "DLQ"
    event.last_error = error
    existing = session.get(DeadLetterEvent, event.id)
    if existing is None:
        session.add(DeadLetterEvent(event_id=event.id, failure_type="NORMALIZATION", attempt_count=event.processing_attempts, first_error=error, last_error=error))
    else:
        existing.attempt_count = event.processing_attempts
        existing.last_error = error
        existing.last_failed_at = utc_now()
    DLQ_EVENTS.inc()


def _acquire_payment_lock(session: Session, payment_id: str) -> None:
    """Serialize projections even when no PaymentState row exists yet."""
    lock = session.get(PaymentProcessingLock, payment_id, with_for_update=True)
    if lock is not None:
        return
    try:
        with session.begin_nested():
            session.add(PaymentProcessingLock(payment_id=payment_id))
            session.flush()
    except IntegrityError:
        # A competing worker created the lock.  Fetching it with FOR UPDATE waits
        # until that transaction has committed and prevents a stale projection.
        pass
    session.get(PaymentProcessingLock, payment_id, with_for_update=True)


def process_event(session: Session, event_id: str, *, worker_id: str | None = None) -> ProcessingResult:
    """Process one event inside the caller's transaction; commit must precede ACK."""
    event = session.get(RawEvent, event_id, with_for_update=True)
    if event is None:
        return ProcessingResult(event_id, None, "MISSING")
    if event.processing_status == "PROCESSED":
        return ProcessingResult(event_id, event.payment_id, "ALREADY_PROCESSED")

    event.processing_attempts += 1
    try:
        canonical = normalize_razorpay_event(event)
        event.normalized_payload = canonical.model_dump(mode="json")
        event.merchant_id = canonical.merchant_id
        event.order_id = canonical.order_id
        event.payment_id = canonical.payment_id
        event.occurred_at = canonical.occurred_at
        session.flush()  # the indexed query below must include this event
        _acquire_payment_lock(session, canonical.payment_id)
        state = session.get(PaymentState, canonical.payment_id, with_for_update=True)
        previous_state = state.state if state else None
        evidence = _canonical_events(session, canonical.payment_id)
        reduction = reduce_events(evidence)
        first_seen = min(item.received_at for item in evidence)
        last_seen = max(item.received_at for item in evidence)

        if state is None:
            state = PaymentState(payment_id=canonical.payment_id, merchant_id=canonical.merchant_id, order_id=canonical.order_id,
                                 amount=canonical.amount, currency=canonical.currency, state=reduction.state,
                                 state_confidence=reduction.confidence, anomalies=reduction.anomalies,
                                 first_seen_at=first_seen, last_seen_at=last_seen)
            session.add(state)
        else:
            state.merchant_id = canonical.merchant_id or state.merchant_id
            state.order_id = canonical.order_id or state.order_id
            state.amount = canonical.amount if canonical.amount is not None else state.amount
            state.currency = canonical.currency or state.currency
            state.state = reduction.state
            state.state_confidence = reduction.confidence
            state.anomalies = reduction.anomalies
            state.first_seen_at = first_seen
            state.last_seen_at = last_seen
            state.state_version += 1

        _upsert_recovery_case(session, state, reduction)
        event.processing_status = "PROCESSED"
        event.last_error = None
        dead_letter = session.get(DeadLetterEvent, event.id)
        if dead_letter is not None:
            session.delete(dead_letter)
        _record_reduction_metrics(previous_state, reduction)
        PROCESSED_EVENTS.inc()
        PROCESSING_LATENCY.observe(max(0.0, (utc_now() - _utc(event.received_at)).total_seconds()))
        structured_log(logger, "event_processed", event_id=event.source_event_id, payment_id=canonical.payment_id,
                       order_id=canonical.order_id, merchant_id=canonical.merchant_id, worker_id=worker_id,
                       correlation_id=event.id, state_before=previous_state, state_after=state.state,
                       state_version=state.state_version)
        return ProcessingResult(event_id, canonical.payment_id, "PROCESSED")
    except (NormalizationError, ValidationError) as exc:
        error = str(exc)
        event.last_error = error
        if event.processing_attempts >= MAX_ATTEMPTS:
            _move_to_dlq(session, event, error)
            return ProcessingResult(event_id, event.payment_id, "DLQ")
        event.processing_status = "PENDING"
        return ProcessingResult(event_id, event.payment_id, "RETRY")


def mark_processing_timeouts(session: Session, timeout_seconds: int) -> list[str]:
    """PROCESSING -> UNKNOWN; no recovery case is created by this timeout."""
    cutoff = utc_now() - timedelta(seconds=timeout_seconds)
    states = session.scalars(select(PaymentState).where(PaymentState.state == "PROCESSING", PaymentState.last_seen_at < cutoff).with_for_update()).all()
    payment_ids: list[str] = []
    for state in states:
        state.state = "UNKNOWN"
        state.state_confidence = 0.41
        state.state_version += 1
        state.anomalies = [*state.anomalies, {"type": "PROCESSING_TIMEOUT", "at": utc_now().isoformat()}]
        attempt = (session.scalar(select(func.max(ReconciliationAttempt.attempt)).where(ReconciliationAttempt.payment_id == state.payment_id)) or 0) + 1
        session.add(ReconciliationAttempt(payment_id=state.payment_id, attempt=attempt))
        STATE_TRANSITIONS.labels("PROCESSING", "UNKNOWN").inc()
        UNKNOWN_STATES.inc()
        payment_ids.append(state.payment_id)
    return payment_ids


def run_reconciliation(factory: sessionmaker[Session], settings: Settings, payment_id: str, *, worker_id: str | None = None) -> bool:
    """Audit a status request, then persist its result as ordinary reducer evidence."""
    with factory() as session:
        attempt = session.scalar(select(ReconciliationAttempt).where(
            ReconciliationAttempt.payment_id == payment_id, ReconciliationAttempt.status == "PENDING"
        ).order_by(ReconciliationAttempt.attempt).with_for_update())
        if attempt is None:
            return True
        state = session.get(PaymentState, payment_id, with_for_update=True)
        if state is None or state.state != "UNKNOWN":
            attempt.status = "SKIPPED"
            attempt.response_at = utc_now()
            attempt.result = {"reason": "PAYMENT_NO_LONGER_AMBIGUOUS"}
            session.commit()
            return True
        attempt.status = "IN_PROGRESS"
        attempt.requested_at = utc_now()
        reconciliation_id, requested_at = attempt.reconciliation_id, attempt.requested_at
        session.commit()

    try:
        result = fetch_payment_status(settings, payment_id)
    except ReconciliationError as exc:
        with factory() as session:
            attempt = session.get(ReconciliationAttempt, reconciliation_id, with_for_update=True)
            if attempt is not None:
                attempt.status, attempt.response_at, attempt.error = "FAILED", utc_now(), str(exc)
                session.commit()
        from .observability import RECONCILIATION_ATTEMPTS
        RECONCILIATION_ATTEMPTS.labels("failure").inc()
        return True  # error is audited; payment truth remains unchanged

    with factory() as session:
        attempt = session.get(ReconciliationAttempt, reconciliation_id, with_for_update=True)
        if attempt is None or attempt.status == "SUCCEEDED":
            return True
        payload = reconciliation_event_payload(result, requested_at)
        raw_event = RawEvent(source="razorpay_reconciliation", source_event_id=f"reconciliation:{reconciliation_id}",
                             event_type=payload["event"], environment=settings.environment, raw_payload=payload)
        session.add(raw_event)
        session.flush()
        process_event(session, raw_event.id, worker_id=worker_id)
        attempt.response_at, attempt.result, attempt.error, attempt.status = utc_now(), {"status": result.get("status"), "event_id": raw_event.id}, None, "SUCCEEDED"
        session.commit()
    from .observability import RECONCILIATION_ATTEMPTS
    RECONCILIATION_ATTEMPTS.labels("success").inc()
    return True


def state_view(state: PaymentState) -> StateView:
    if state.state == "FAILED":
        gate = RecoveryGate(recovery_eligible=True, reason="DEFINITIVE_FAILED_PAYMENT", state=state.state, state_confidence=state.state_confidence)
    elif state.state == "CAPTURED":
        gate = RecoveryGate(recovery_eligible=False, reason="PAYMENT_ALREADY_CAPTURED", state=state.state, state_confidence=state.state_confidence)
    else:
        gate = RecoveryGate(recovery_eligible=False, reason="PAYMENT_STATE_UNRESOLVED", state=state.state, state_confidence=state.state_confidence)
    return StateView(payment_id=state.payment_id, merchant_id=state.merchant_id, order_id=state.order_id,
                     amount=state.amount, currency=state.currency, state=state.state,
                     state_confidence=state.state_confidence, anomalies=state.anomalies,
                     first_seen_at=state.first_seen_at, last_seen_at=state.last_seen_at,
                     state_version=state.state_version, recovery_gate=gate)

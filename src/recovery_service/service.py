from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DeadLetterEvent, PaymentState, RawEvent, RecoveryCase, utc_now
from .normalizer import NormalizationError, normalize_razorpay_event
from .schemas import CanonicalEvent, RecoveryGate, StateView
from .state_machine import recovery_gate, reduce_events

MAX_ATTEMPTS = 5


def _canonical_events(session: Session, payment_id: str) -> list[CanonicalEvent]:
    rows = session.scalars(select(RawEvent).where(RawEvent.processing_status != "DLQ")).all()
    result: list[CanonicalEvent] = []
    for row in rows:
        if row.normalized_payload:
            event = CanonicalEvent.model_validate(row.normalized_payload)
        else:
            try:
                event = normalize_razorpay_event(row)
            except NormalizationError:
                continue
        if event.payment_id == payment_id:
            result.append(event)
    return result


def _case_id(payment_id: str, episode_event_id: str) -> str:
    digest = hashlib.sha256(f"{payment_id}:{episode_event_id}".encode()).hexdigest()[:32]
    return f"rc_{digest}"


def _upsert_recovery_case(session: Session, state: PaymentState, event: CanonicalEvent, reduction) -> None:
    gate = recovery_gate(reduction)
    # A case is a view of current Stage-1 truth, not an irrevocable decision.  Later
    # authorization/capture evidence must revoke any prior failed-payment candidate.
    existing_cases = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == state.payment_id)).all()
    for existing_case in existing_cases:
        existing_case.last_seen_at = state.last_seen_at
        existing_case.state = state.state
        existing_case.state_confidence = state.state_confidence
        existing_case.recovery_eligible = gate.recovery_eligible
        existing_case.eligibility_reason = gate.reason

    if not gate.recovery_eligible or not reduction.recovery_episode_event_id:
        return
    case_id = _case_id(state.payment_id, reduction.recovery_episode_event_id)
    recovery_case = session.get(RecoveryCase, case_id)
    if recovery_case is None:
        recovery_case = RecoveryCase(
            case_id=case_id,
            payment_id=state.payment_id,
            recovery_episode_id=reduction.recovery_episode_event_id,
            merchant_id=state.merchant_id,
            order_id=state.order_id,
            amount=state.amount,
            currency=state.currency,
            state=state.state,
            state_confidence=state.state_confidence,
            failure_evidence=reduction.failure_evidence.model_dump(mode="json"),
            first_seen_at=state.first_seen_at,
            last_seen_at=state.last_seen_at,
            recovery_eligible=True,
            eligibility_reason=gate.reason,
        )
        session.add(recovery_case)
    else:
        recovery_case.failure_evidence = reduction.failure_evidence.model_dump(mode="json")


def _move_to_dlq(session: Session, event: RawEvent, error: str) -> None:
    event.processing_status = "DLQ"
    event.last_error = error
    existing = session.get(DeadLetterEvent, event.id)
    if existing is None:
        session.add(DeadLetterEvent(event_id=event.id, failure_type="NORMALIZATION", attempt_count=event.processing_attempts, last_error=error))
    else:
        existing.attempt_count = event.processing_attempts
        existing.last_error = error
        existing.last_failed_at = utc_now()


def process_event(session: Session, event_id: str) -> None:
    event = session.get(RawEvent, event_id)
    if event is None or event.processing_status == "PROCESSED":
        return
    event.processing_attempts += 1
    try:
        canonical = normalize_razorpay_event(event)
        event.normalized_payload = canonical.model_dump(mode="json")
        state = session.get(PaymentState, canonical.payment_id, with_for_update=True)
        evidence = _canonical_events(session, canonical.payment_id)
        reduction = reduce_events(evidence)
        first_seen = min(item.received_at for item in evidence)
        last_seen = max(item.received_at for item in evidence)

        if state is None:
            state = PaymentState(
                payment_id=canonical.payment_id,
                merchant_id=canonical.merchant_id,
                order_id=canonical.order_id,
                amount=canonical.amount,
                currency=canonical.currency,
                state=reduction.state,
                state_confidence=reduction.confidence,
                anomalies=reduction.anomalies,
                first_seen_at=first_seen,
                last_seen_at=last_seen,
            )
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

        _upsert_recovery_case(session, state, canonical, reduction)
        event.processing_status = "PROCESSED"
        event.last_error = None
    except NormalizationError as exc:
        event.last_error = str(exc)
        if event.processing_attempts >= MAX_ATTEMPTS:
            _move_to_dlq(session, event, str(exc))
        else:
            event.processing_status = "PENDING"
        # This is a durable processing outcome, not a transaction failure.  Committing it
        # lets subsequent deliveries advance the retry counter and eventually reach the DLQ.
        return


def state_view(state: PaymentState) -> StateView:
    if state.state == "FAILED":
        gate = RecoveryGate(
            recovery_eligible=True,
            reason="DEFINITIVE_FAILED_PAYMENT",
            state=state.state,
            state_confidence=state.state_confidence,
        )
    elif state.state == "CAPTURED":
        gate = RecoveryGate(
            recovery_eligible=False,
            reason="PAYMENT_ALREADY_CAPTURED",
            state=state.state,
            state_confidence=state.state_confidence,
        )
    else:
        gate = RecoveryGate(
            recovery_eligible=False,
            reason="PAYMENT_STATE_UNRESOLVED",
            state=state.state,
            state_confidence=state.state_confidence,
        )
    return StateView(
        payment_id=state.payment_id,
        merchant_id=state.merchant_id,
        order_id=state.order_id,
        amount=state.amount,
        currency=state.currency,
        state=state.state,
        state_confidence=state.state_confidence,
        anomalies=state.anomalies,
        first_seen_at=state.first_seen_at,
        last_seen_at=state.last_seen_at,
        state_version=state.state_version,
        recovery_gate=gate,
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schemas import CanonicalEvent, FailureEvidence, RecoveryGate


@dataclass(frozen=True)
class Reduction:
    state: str
    confidence: float
    anomalies: list[dict]
    failure_evidence: FailureEvidence | None
    recovery_episode_event_id: str | None


_CONFIDENCE = {"CREATED": 0.70, "PROCESSING": 0.75, "AUTHORIZED": 0.98, "CAPTURED": 1.0, "FAILED": 0.99, "UNKNOWN": 0.41, "ABANDONED": 0.60}


def reduce_events(events: Iterable[CanonicalEvent]) -> Reduction:
    ordered = sorted(events, key=lambda e: (e.occurred_at, e.received_at, e.event_id))
    state = "CREATED"
    anomalies: list[dict] = []
    failed_event: CanonicalEvent | None = None

    received_order = [event.event_id for event in sorted(ordered, key=lambda e: (e.received_at, e.event_id))]
    if received_order != [event.event_id for event in ordered]:
        anomalies.append({"type": "OUT_OF_ORDER_ARRIVAL", "event_ids": received_order})

    for event in ordered:
        if event.event_type in {"payment.created", "checkout.created"}:
            if state == "CREATED":
                state = "CREATED"
        elif event.event_type in {"payment.processing", "payment.pending"}:
            if state not in {"CAPTURED", "FAILED"}:
                state = "PROCESSING"
        elif event.event_type == "payment.failed":
            if state == "CAPTURED":
                anomalies.append({"type": "NEGATIVE_EVIDENCE_AFTER_CAPTURE", "event_id": event.event_id})
            else:
                state = "FAILED"
                failed_event = event
        elif event.event_type == "payment.authorized":
            if state == "CAPTURED":
                anomalies.append({"type": "STALE_AUTHORIZATION_AFTER_CAPTURE", "event_id": event.event_id})
            else:
                if state == "FAILED":
                    anomalies.append({"type": "LATE_POSITIVE_AFTER_FAILURE", "event_id": event.event_id})
                state = "AUTHORIZED"
                failed_event = None
        elif event.event_type in {"payment.captured", "order.paid"}:
            if state == "FAILED":
                anomalies.append({"type": "LATE_CAPTURE_AFTER_FAILURE", "event_id": event.event_id})
            state = "CAPTURED"
            failed_event = None

    return Reduction(
        state=state,
        confidence=_CONFIDENCE[state],
        anomalies=anomalies,
        failure_evidence=failed_event.failure if failed_event else None,
        recovery_episode_event_id=failed_event.event_id if failed_event else None,
    )


def recovery_gate(reduction: Reduction) -> RecoveryGate:
    if reduction.state == "FAILED" and reduction.failure_evidence is not None:
        return RecoveryGate(recovery_eligible=True, reason="DEFINITIVE_FAILED_PAYMENT", state="FAILED", state_confidence=reduction.confidence)
    if reduction.state == "CAPTURED":
        return RecoveryGate(recovery_eligible=False, reason="PAYMENT_ALREADY_CAPTURED", state="CAPTURED", state_confidence=reduction.confidence)
    return RecoveryGate(recovery_eligible=False, reason="PAYMENT_STATE_UNRESOLVED", state=reduction.state, state_confidence=reduction.confidence)


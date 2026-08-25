from datetime import datetime, timedelta, timezone

from recovery_service.schemas import CanonicalEvent, FailureEvidence
from recovery_service.state_machine import recovery_gate, reduce_events


BASE = datetime(2026, 8, 24, tzinfo=timezone.utc)


def event(event_id: str, event_type: str, second: int, received_second: int | None = None) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        environment="test",
        event_type=event_type,
        occurred_at=BASE + timedelta(seconds=second),
        received_at=BASE + timedelta(seconds=received_second if received_second is not None else second),
        merchant_id="acc_1",
        order_id="order_1",
        payment_id="pay_1",
        amount=50000,
        currency="INR",
        raw_reference=f"db://{event_id}",
        failure=FailureEvidence(source="bank", reason="payment_failed") if event_type == "payment.failed" else None,
    )


def test_failed_payment_is_recovery_eligible():
    reduction = reduce_events([event("evt_1", "payment.failed", 1)])
    assert reduction.state == "FAILED"
    assert recovery_gate(reduction).recovery_eligible is True


def test_late_authorization_supersedes_failure():
    reduction = reduce_events([event("failed", "payment.failed", 1), event("authorized", "payment.authorized", 2)])
    assert reduction.state == "AUTHORIZED"
    assert recovery_gate(reduction).recovery_eligible is False
    assert any(anomaly["type"] == "LATE_POSITIVE_AFTER_FAILURE" for anomaly in reduction.anomalies)


def test_capture_cannot_be_downgraded_by_later_failure():
    reduction = reduce_events([event("captured", "payment.captured", 1), event("failed", "payment.failed", 2)])
    assert reduction.state == "CAPTURED"
    assert recovery_gate(reduction).reason == "PAYMENT_ALREADY_CAPTURED"


def test_out_of_order_arrival_is_reconstructed_by_occurrence_time():
    reduction = reduce_events([event("captured", "payment.captured", 2, 1), event("authorized", "payment.authorized", 1, 2)])
    assert reduction.state == "CAPTURED"
    assert any(anomaly["type"] == "OUT_OF_ORDER_ARRIVAL" for anomaly in reduction.anomalies)


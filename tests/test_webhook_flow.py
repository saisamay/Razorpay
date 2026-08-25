import hashlib
import hmac

from sqlalchemy.exc import IntegrityError

from recovery_service.database import Base, build_session_factory
from recovery_service.main import _signature_is_valid
from recovery_service.models import PaymentState, RawEvent, RecoveryCase
from recovery_service.service import process_event
from recovery_service.settings import Settings


SECRET = "test-webhook-secret"


def payload(event_type: str) -> dict:
    return {
        "entity": "event",
        "account_id": "acc_1",
        "event": event_type,
        "created_at": 1_724_000_000,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_1",
                    "amount": 50000,
                    "currency": "INR",
                    "order_id": "order_1",
                    "method": "upi",
                    "error_source": "bank" if event_type == "payment.failed" else None,
                    "error_reason": "payment_failed" if event_type == "payment.failed" else None,
                }
            }
        },
    }


def raw_event(event_id: str, webhook_type: str) -> RawEvent:
    return RawEvent(source_event_id=event_id, event_type=webhook_type, environment="test", raw_payload=payload(webhook_type))


def test_signature_verification_uses_raw_bytes():
    raw = b'{"event":"payment.failed","payload":{}}'
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert _signature_is_valid(raw, signature, (SECRET,))
    assert not _signature_is_valid(raw + b" ", signature, (SECRET,))
    assert not _signature_is_valid(raw, "bad", (SECRET,))


def test_persisted_events_are_idempotent_and_late_capture_blocks_recovery(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/recovery.sqlite3", redis_url="redis://unused", webhook_secrets=(SECRET,), environment="test", max_webhook_bytes=1024)
    factory = build_session_factory(settings)
    Base.metadata.create_all(factory.kw["bind"])

    with factory() as session:
        failed = raw_event("evt_failed", "payment.failed")
        session.add(failed)
        session.commit()
        process_event(session, failed.id)
        session.commit()
        assert session.get(PaymentState, "pay_1").state == "FAILED"
        recovery_case = session.query(RecoveryCase).one()
        assert recovery_case.recovery_eligible is True

        session.add(raw_event("evt_failed", "payment.failed"))
        try:
            session.commit()
            raise AssertionError("duplicate source event id must be rejected")
        except IntegrityError:
            session.rollback()

        captured = raw_event("evt_captured", "payment.captured")
        session.add(captured)
        session.commit()
        process_event(session, captured.id)
        session.commit()
        state = session.get(PaymentState, "pay_1")
        assert state.state == "CAPTURED"
        assert any(item["type"] == "LATE_CAPTURE_AFTER_FAILURE" for item in state.anomalies)
        assert session.query(RecoveryCase).one().recovery_eligible is False

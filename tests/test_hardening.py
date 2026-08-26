from datetime import timedelta

from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.models import DeadLetterEvent, PaymentState, RawEvent, ReconciliationAttempt, RecoveryCase, utc_now
from recovery_service.service import MAX_ATTEMPTS, mark_processing_timeouts, process_event, run_reconciliation
from recovery_service.settings import Settings
from recovery_service.worker import _handle_event_entries, worker_identity


def _settings(tmp_path) -> Settings:
    return Settings(database_url=f"sqlite:///{tmp_path}/hardening.sqlite3", redis_url="redis://unused", webhook_secrets=("test",), environment="test", max_webhook_bytes=1024)


def _payload(event_type: str, payment_id: str = "pay_1") -> dict:
    return {
        "entity": "event", "account_id": "acc_1", "event": event_type, "created_at": 1_724_000_000,
        "payload": {"payment": {"entity": {"id": payment_id, "amount": 50000, "currency": "INR", "order_id": "order_1"}}},
    }


def _event(event_id: str, event_type: str, payment_id: str = "pay_1", **kwargs) -> RawEvent:
    return RawEvent(source_event_id=event_id, event_type=event_type, environment="test", raw_payload=_payload(event_type, payment_id), **kwargs)


def test_indexed_correlation_and_duplicate_processing_are_stable(tmp_path):
    factory = build_session_factory(_settings(tmp_path))
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as session:
        failed = _event("failed", "payment.failed")
        other = _event("other", "payment.captured", "pay_other")
        session.add_all([failed, other])
        session.commit()
        process_event(session, failed.id)
        process_event(session, other.id)
        session.commit()

    # A reclaimed duplicate is a no-op after the first commit, regardless of worker order.
    with factory() as session:
        assert process_event(session, failed.id).status == "ALREADY_PROCESSED"
        session.commit()
        assert session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_1")).recovery_eligible is True
        assert session.scalars(select(RawEvent).where(RawEvent.payment_id == "pay_1")).one().source_event_id == "failed"
        assert session.get(PaymentState, "pay_1").state == "FAILED"


def test_processing_timeout_moves_to_unknown_and_reconciliation_reuses_reducer(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    factory = build_session_factory(settings)
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as session:
        processing = _event("processing", "payment.processing", received_at=utc_now() - timedelta(minutes=20))
        session.add(processing)
        session.commit()
        process_event(session, processing.id)
        session.commit()
        assert session.get(PaymentState, "pay_1").state == "PROCESSING"
        assert mark_processing_timeouts(session, 1) == ["pay_1"]
        session.commit()
        assert session.get(PaymentState, "pay_1").state == "UNKNOWN"
        assert session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_1")) is None

    monkeypatch.setattr("recovery_service.service.fetch_payment_status", lambda *_: {"id": "pay_1", "status": "captured", "amount": 50000, "currency": "INR", "order_id": "order_1"})
    assert run_reconciliation(factory, settings, "pay_1") is True
    with factory() as session:
        assert session.get(PaymentState, "pay_1").state == "CAPTURED"
        attempt = session.scalar(select(ReconciliationAttempt))
        assert attempt.status == "SUCCEEDED"
        api_event = session.scalars(select(RawEvent).where(RawEvent.source == "razorpay_reconciliation")).one()
        assert api_event.payment_id == "pay_1"


def test_dlq_records_failure_and_successful_replay_clears_it(tmp_path):
    factory = build_session_factory(_settings(tmp_path))
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as session:
        malformed = RawEvent(source_event_id="bad", event_type="payment.failed", environment="test", raw_payload={"event": "payment.failed"})
        session.add(malformed)
        session.commit()
        for _ in range(MAX_ATTEMPTS):
            process_event(session, malformed.id)
            session.commit()
        assert session.get(RawEvent, malformed.id).processing_status == "DLQ"
        dead = session.get(DeadLetterEvent, malformed.id)
        assert dead.attempt_count == MAX_ATTEMPTS
        assert dead.first_error and dead.last_error

        malformed.raw_payload = _payload("payment.failed")
        malformed.processing_status = "PENDING"
        malformed.processing_attempts = 0
        session.commit()
        assert process_event(session, malformed.id).status == "PROCESSED"
        session.commit()
        assert session.get(DeadLetterEvent, malformed.id) is None


def test_worker_acks_only_after_the_transaction_commits(tmp_path):
    factory = build_session_factory(_settings(tmp_path))
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as session:
        event = _event("evt", "payment.failed")
        session.add(event)
        session.commit()

    class Client:
        def __init__(self):
            self.acks = []

        def xack(self, *args):
            self.acks.append(args)

    class Queue:
        client = Client()

    queue = Queue()
    _handle_event_entries(queue, factory, [("1-0", {"event_id": event.id})], "worker-test")
    assert queue.client.acks == [("recovery:events", "state-reconstructors", "1-0")]
    with factory() as session:
        assert session.get(RawEvent, event.id).processing_status == "PROCESSED"


def test_worker_identity_is_unique_per_instance():
    assert worker_identity() != worker_identity()

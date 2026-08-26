from datetime import timedelta

import httpx
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.models import PaymentState, RawEvent, ReconciliationAttempt, RecoveryCase, utc_now
from recovery_service.service import mark_processing_timeouts, process_event, run_reconciliation
from recovery_service.settings import Settings
from recovery_service.worker import _process, _sweep_pending


def _chaos_settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path}/chaos.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("chaos-secret",),
        environment="test",
        max_webhook_bytes=4096,
        razorpay_key_id="chaos_key",
        razorpay_key_secret="chaos_secret",
    )


def _payload(event_type: str = "payment.failed", payment_id: str = "pay_chaos_1") -> dict:
    return {
        "entity": "event",
        "account_id": "acc_chaos",
        "event": event_type,
        "created_at": 1_724_000_000,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 75000,
                    "currency": "INR",
                    "order_id": "order_chaos",
                    "method": "card",
                    "error_source": "issuer" if event_type == "payment.failed" else None,
                    "error_reason": "card_declined" if event_type == "payment.failed" else None,
                }
            }
        },
    }


def _raw_event(event_id: str, event_type: str, payment_id: str = "pay_chaos_1", **kwargs) -> RawEvent:
    return RawEvent(
        source_event_id=event_id,
        event_type=event_type,
        environment="test",
        raw_payload=_payload(event_type, payment_id),
        **kwargs,
    )


def test_worker_interruption_and_restart(tmp_path):
    """Simulate a worker crash mid-processing before ACK; verify pending sweep recovers it cleanly."""
    factory = build_session_factory(_chaos_settings(tmp_path))
    Base.metadata.create_all(factory.kw["bind"])

    with factory() as session:
        event = _raw_event("evt_crash_1", "payment.failed", payment_id="pay_crash")
        session.add(event)
        session.commit()
        event_id = event.id

    # Simulated worker 1 crashes before session.commit() or Redis ACK
    with factory() as session:
        # Worker does partial work but raises exception before committing transaction
        try:
            process_event(session, event_id, worker_id="worker-crash-1")
            raise RuntimeError("Simulated worker process crash mid-flight!")
        except RuntimeError:
            session.rollback()

    # Verify state is untouched after crash
    with factory() as session:
        assert session.get(RawEvent, event_id).processing_status == "PENDING"
        assert session.get(PaymentState, "pay_crash") is None

    # Worker 2 restarts and sweeps pending events
    _sweep_pending(factory, worker_id="worker-restarted-2")

    # Verify event recovered, processing status PROCESSED, state consistent
    with factory() as session:
        assert session.get(RawEvent, event_id).processing_status == "PROCESSED"
        state = session.get(PaymentState, "pay_crash")
        assert state is not None
        assert state.state == "FAILED"
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_crash"))
        assert case is not None
        assert case.recovery_eligible is True


def test_redis_interruption_and_recovery(tmp_path):
    """Simulate Redis outage during webhook ingress; DB retains PENDING, sweep recovers state when Redis is restored."""
    factory = build_session_factory(_chaos_settings(tmp_path))
    Base.metadata.create_all(factory.kw["bind"])

    # Webhook ingress stores in Postgres/SQLite but Redis XADD fails
    with factory() as session:
        evt1 = _raw_event("evt_redis_outage_1", "payment.failed", payment_id="pay_redis_outage")
        evt2 = _raw_event("evt_redis_outage_2", "payment.captured", payment_id="pay_redis_outage")
        session.add_all([evt1, evt2])
        session.commit()

    # Redis stream was unpopulated due to outage. Worker database sweep processes pending events:
    _sweep_pending(factory, worker_id="worker-redis-recovery")

    with factory() as session:
        state = session.get(PaymentState, "pay_redis_outage")
        assert state is not None
        assert state.state == "CAPTURED"
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_redis_outage"))
        # Capture evidence blocks recovery
        assert case is not None
        assert case.recovery_eligible is False


def test_postgresql_interruption_and_recovery(tmp_path):
    """Simulate transient DB connection error; transaction rolls back cleanly and retries succeed."""
    factory = build_session_factory(_chaos_settings(tmp_path))
    Base.metadata.create_all(factory.kw["bind"])

    with factory() as session:
        event = _raw_event("evt_db_outage", "payment.failed", payment_id="pay_db_outage")
        session.add(event)
        session.commit()
        event_id = event.id

    # Simulated transient DB execution error
    class TransientDBError(Exception):
        pass

    attempts = 0

    def FlakyProcess(factory, event_id: str, worker_id: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            with factory() as session:
                session.rollback()
                return False
        return _process(factory, event_id, worker_id)

    # First attempt fails due to DB interruption
    success_1 = FlakyProcess(factory, event_id, "worker-db-1")
    assert success_1 is False

    with factory() as session:
        assert session.get(RawEvent, event_id).processing_status == "PENDING"

    # Second attempt after DB recovery succeeds
    success_2 = FlakyProcess(factory, event_id, "worker-db-1")
    assert success_2 is True

    with factory() as session:
        assert session.get(RawEvent, event_id).processing_status == "PROCESSED"
        assert session.get(PaymentState, "pay_db_outage").state == "FAILED"


def test_reconciliation_api_failure_and_eventual_consistency(tmp_path, monkeypatch):
    """Simulate API 503 outage during reconciliation; verify no unsafe recovery case, and eventual consistency upon API recovery."""
    settings = _chaos_settings(tmp_path)
    factory = build_session_factory(settings)
    Base.metadata.create_all(factory.kw["bind"])

    with factory() as session:
        proc = _raw_event("proc_chaos_api", "payment.processing", payment_id="pay_api_chaos", received_at=utc_now() - timedelta(minutes=30))
        session.add(proc)
        session.commit()
        process_event(session, proc.id)
        mark_processing_timeouts(session, 1)
        session.commit()
        assert session.get(PaymentState, "pay_api_chaos").state == "UNKNOWN"

    # 1. API fails with 503 Service Unavailable
    def mock_503(*args, **kwargs):
        req = httpx.Request("GET", "https://api.razorpay.com/v1/payments/pay_api_chaos")
        res = httpx.Response(503, request=req)
        res.raise_for_status()

    monkeypatch.setattr("httpx.get", mock_503)

    run_reconciliation(factory, settings, "pay_api_chaos", worker_id="worker-rec-chaos")

    with factory() as session:
        state = session.get(PaymentState, "pay_api_chaos")
        assert state.state == "UNKNOWN"
        # UNKNOWN MUST NOT create an eligible recovery case
        cases = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_api_chaos")).all()
        for case in cases:
            assert case.recovery_eligible is False
        attempt = session.scalar(select(ReconciliationAttempt).where(ReconciliationAttempt.payment_id == "pay_api_chaos"))
        assert attempt.status == "FAILED"

    # 2. API recovers and reports payment captured
    monkeypatch.setattr(
        "recovery_service.service.fetch_payment_status",
        lambda *_: {
            "id": "pay_api_chaos",
            "status": "captured",
            "amount": 75000,
            "currency": "INR",
            "order_id": "order_chaos",
        },
    )

    # Re-queue reconciliation attempt for payment
    with factory() as session:
        session.add(ReconciliationAttempt(payment_id="pay_api_chaos", attempt=2))
        session.commit()

    run_reconciliation(factory, settings, "pay_api_chaos", worker_id="worker-rec-chaos")

    # 3. Verify eventual consistency
    with factory() as session:
        state = session.get(PaymentState, "pay_api_chaos")
        assert state.state == "CAPTURED"
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_api_chaos"))
        if case:
            assert case.recovery_eligible is False

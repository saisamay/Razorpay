from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.main import app
from recovery_service.models import DeadLetterEvent, PaymentState, RawEvent, ReconciliationAttempt, RecoveryCase, utc_now
from recovery_service.service import mark_processing_timeouts, process_event, run_reconciliation
from recovery_service.settings import Settings


SECRET = "matrix-test-secret"


def _build_test_app(tmp_path, max_bytes: int = 1024, internal_token: str | None = "secret-token"):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/matrix.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=(SECRET,),
        environment="test",
        max_webhook_bytes=max_bytes,
        internal_api_token=internal_token,
        razorpay_key_id="key_test_123",
        razorpay_key_secret="sec_test_123",
    )
    factory = build_session_factory(settings)
    # Give SQLite sufficient busy timeout for concurrent multi-threaded execution
    factory.kw["bind"].dialect.server_version_info = None
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    app.state.settings = settings
    app.state.sessions = factory

    class DummyQueue:
        def publish(self, event_id: str) -> None:
            pass

        def publish_reconciliation(self, payment_id: str) -> None:
            pass

    app.state.queue = DummyQueue()
    return TestClient(app), factory, settings


def _payload(event_type: str = "payment.failed", payment_id: str = "pay_matrix_1", amount: int = 50000) -> dict:
    return {
        "entity": "event",
        "account_id": "acc_matrix",
        "event": event_type,
        "created_at": 1_724_000_000,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount,
                    "currency": "INR",
                    "order_id": "order_matrix",
                    "method": "upi",
                    "error_source": "bank" if event_type == "payment.failed" else None,
                    "error_reason": "payment_failed" if event_type == "payment.failed" else None,
                }
            }
        },
    }


def _raw_event(event_id: str, event_type: str, payment_id: str = "pay_matrix_1", **kwargs) -> RawEvent:
    return RawEvent(
        source_event_id=event_id,
        event_type=event_type,
        environment="test",
        raw_payload=_payload(event_type, payment_id),
        **kwargs,
    )


def test_payload_size_enforcement(tmp_path):
    client, factory, settings = _build_test_app(tmp_path, max_bytes=100)
    large_payload = json.dumps(_payload()).encode("utf-8") + b" " * 200
    assert len(large_payload) > 100

    response = client.post(
        "/webhooks/razorpay",
        content=large_payload,
        headers={
            "x-razorpay-signature": "dummy",
            "x-razorpay-event-id": "evt_large",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


def test_malformed_payload_enforcement(tmp_path):
    client, factory, settings = _build_test_app(tmp_path, max_bytes=4096)

    # Invalid JSON
    import hashlib, hmac
    raw_bad_json = b"{invalid_json"
    sig = hmac.new(SECRET.encode(), raw_bad_json, hashlib.sha256).hexdigest()
    res = client.post(
        "/webhooks/razorpay",
        content=raw_bad_json,
        headers={"x-razorpay-signature": sig, "x-razorpay-event-id": "evt_malformed_1"},
    )
    assert res.status_code == 422

    # Missing top-level 'event' field
    raw_no_event = b'{"payload": {}}'
    sig2 = hmac.new(SECRET.encode(), raw_no_event, hashlib.sha256).hexdigest()
    res2 = client.post(
        "/webhooks/razorpay",
        content=raw_no_event,
        headers={"x-razorpay-signature": sig2, "x-razorpay-event-id": "evt_malformed_2"},
    )
    assert res2.status_code == 422


def test_reconciliation_http_5xx_handling(tmp_path, monkeypatch):
    client, factory, settings = _build_test_app(tmp_path)
    with factory() as session:
        processing = _raw_event("proc_5xx", "payment.processing", payment_id="pay_5xx", received_at=utc_now() - timedelta(minutes=20))
        session.add(processing)
        session.commit()
        process_event(session, processing.id)
        mark_processing_timeouts(session, 1)
        session.commit()
        assert session.get(PaymentState, "pay_5xx").state == "UNKNOWN"

    def mock_500(*args, **kwargs):
        req = httpx.Request("GET", "https://api.razorpay.com/v1/payments/pay_5xx")
        res = httpx.Response(500, request=req)
        res.raise_for_status()

    monkeypatch.setattr("httpx.get", mock_500)
    assert run_reconciliation(factory, settings, "pay_5xx") is True

    with factory() as session:
        assert session.get(PaymentState, "pay_5xx").state == "UNKNOWN"
        attempt = session.scalar(select(ReconciliationAttempt).where(ReconciliationAttempt.payment_id == "pay_5xx"))
        assert attempt.status == "FAILED"
        assert "500" in attempt.error or "HTTPError" in attempt.error or "HTTPStatusError" in attempt.error


def test_reconciliation_timeout_handling(tmp_path, monkeypatch):
    client, factory, settings = _build_test_app(tmp_path)
    with factory() as session:
        processing = _raw_event("proc_timeout", "payment.processing", payment_id="pay_timeout", received_at=utc_now() - timedelta(minutes=20))
        session.add(processing)
        session.commit()
        process_event(session, processing.id)
        mark_processing_timeouts(session, 1)
        session.commit()

    def mock_timeout(*args, **kwargs):
        raise httpx.ReadTimeout("Connection timed out", request=httpx.Request("GET", "https://api.razorpay.com/v1/payments/pay_timeout"))

    monkeypatch.setattr("httpx.get", mock_timeout)
    assert run_reconciliation(factory, settings, "pay_timeout") is True

    with factory() as session:
        assert session.get(PaymentState, "pay_timeout").state == "UNKNOWN"
        attempt = session.scalar(select(ReconciliationAttempt).where(ReconciliationAttempt.payment_id == "pay_timeout"))
        assert attempt.status == "FAILED"
        assert "ReadTimeout" in attempt.error or "timed out" in attempt.error


def test_reconciliation_unknown_to_failed(tmp_path, monkeypatch):
    client, factory, settings = _build_test_app(tmp_path)
    with factory() as session:
        processing = _raw_event("proc_fail", "payment.processing", payment_id="pay_rec_failed", received_at=utc_now() - timedelta(minutes=20))
        session.add(processing)
        session.commit()
        process_event(session, processing.id)
        mark_processing_timeouts(session, 1)
        session.commit()
        assert session.get(PaymentState, "pay_rec_failed").state == "UNKNOWN"

    monkeypatch.setattr(
        "recovery_service.service.fetch_payment_status",
        lambda *_: {
            "id": "pay_rec_failed",
            "status": "failed",
            "amount": 50000,
            "currency": "INR",
            "order_id": "order_matrix",
            "error_source": "bank",
            "error_reason": "payment_failed",
        },
    )

    assert run_reconciliation(factory, settings, "pay_rec_failed") is True

    with factory() as session:
        state = session.get(PaymentState, "pay_rec_failed")
        assert state.state == "FAILED"
        recovery_case = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_rec_failed"))
        assert recovery_case is not None
        assert recovery_case.recovery_eligible is True


def test_reconciliation_unknown_to_captured_revokes_case(tmp_path, monkeypatch):
    client, factory, settings = _build_test_app(tmp_path)
    with factory() as session:
        failed = _raw_event("evt_fail_1", "payment.failed", payment_id="pay_rec_captured")
        session.add(failed)
        session.commit()
        process_event(session, failed.id)
        session.commit()
        case_before = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_rec_captured"))
        assert case_before.recovery_eligible is True

        # Manually force state to UNKNOWN to simulate ambiguity sweep
        state = session.get(PaymentState, "pay_rec_captured")
        state.state = "UNKNOWN"
        session.add(ReconciliationAttempt(payment_id="pay_rec_captured", attempt=1))
        session.commit()

    monkeypatch.setattr(
        "recovery_service.service.fetch_payment_status",
        lambda *_: {
            "id": "pay_rec_captured",
            "status": "captured",
            "amount": 50000,
            "currency": "INR",
            "order_id": "order_matrix",
        },
    )

    assert run_reconciliation(factory, settings, "pay_rec_captured") is True

    with factory() as session:
        state = session.get(PaymentState, "pay_rec_captured")
        assert state.state == "CAPTURED"
        case_after = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_rec_captured"))
        assert case_after.recovery_eligible is False
        assert case_after.eligibility_reason == "PAYMENT_ALREADY_CAPTURED"


def test_unresolved_unknown_state_has_no_recovery_case(tmp_path, monkeypatch):
    client, factory, settings = _build_test_app(tmp_path)
    with factory() as session:
        processing = _raw_event("proc_unres", "payment.processing", payment_id="pay_unresolved", received_at=utc_now() - timedelta(minutes=20))
        session.add(processing)
        session.commit()
        process_event(session, processing.id)
        mark_processing_timeouts(session, 1)
        session.commit()

    # Reconciliation API returns an unrecognized status e.g. "disputed"
    monkeypatch.setattr(
        "recovery_service.service.fetch_payment_status",
        lambda *_: {
            "id": "pay_unresolved",
            "status": "disputed",
            "amount": 50000,
            "currency": "INR",
            "order_id": "order_matrix",
        },
    )

    assert run_reconciliation(factory, settings, "pay_unresolved") is True

    with factory() as session:
        state = session.get(PaymentState, "pay_unresolved")
        # Should fall back to payment.processing reducer logic or keep state without opening case
        assert state.state in {"PROCESSING", "UNKNOWN"}
        cases = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_unresolved")).all()
        for case in cases:
            assert case.recovery_eligible is False


def test_dlq_replay_authorization_and_flow(tmp_path):
    client, factory, settings = _build_test_app(tmp_path, internal_token="secret-token-123")
    with factory() as session:
        event = RawEvent(
            source_event_id="bad_evt_dlq",
            event_type="payment.failed",
            environment="test",
            raw_payload={"invalid": "no_event"},
            processing_status="DLQ",
            processing_attempts=5,
            last_error="missing event name",
        )
        session.add(event)
        session.flush()
        session.add(
            DeadLetterEvent(
                event_id=event.id,
                failure_type="NORMALIZATION",
                attempt_count=5,
                first_error="missing event name",
                last_error="missing event name",
            )
        )
        session.commit()
        event_id = event.id

    # Test unauthorized access
    unauth_res = client.get(f"/internal/dlq/{event_id}")
    assert unauth_res.status_code == 403

    unauth_replay = client.post(f"/internal/replay/{event_id}")
    assert unauth_replay.status_code == 403

    # Test authorized access
    auth_headers = {"x-internal-token": "secret-token-123"}
    dlq_res = client.get(f"/internal/dlq/{event_id}", headers=auth_headers)
    assert dlq_res.status_code == 200
    assert dlq_res.json()["event_id"] == event_id

    replay_res = client.post(f"/internal/replay/{event_id}", headers=auth_headers)
    assert replay_res.status_code == 202
    assert replay_res.json()["accepted"] is True

    with factory() as session:
        replayed = session.get(RawEvent, event_id)
        assert replayed.processing_status == "PENDING"
        assert replayed.processing_attempts == 0
        assert replayed.last_error is None


def test_concurrent_duplicate_event_processing(tmp_path):
    client, factory, settings = _build_test_app(tmp_path)
    with factory() as session:
        event = _raw_event("evt_concurrent", "payment.failed", payment_id="pay_concurrent")
        session.add(event)
        session.commit()
        event_id = event.id

    def worker_task(worker_name: str):
        for _ in range(5):
            try:
                with factory() as session:
                    res = process_event(session, event_id, worker_id=worker_name)
                    session.commit()
                    return res
            except Exception:
                import time
                time.sleep(0.05)
        return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_task, f"worker-{i}") for i in range(5)]
        results = [f.result() for f in futures if f.result() is not None]

    statuses = [r.status for r in results]
    assert "PROCESSED" in statuses or "ALREADY_PROCESSED" in statuses

    with factory() as session:
        state = session.get(PaymentState, "pay_concurrent")
        assert state is not None
        assert state.state == "FAILED"
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_concurrent"))
        assert case is not None
        assert case.recovery_eligible is True

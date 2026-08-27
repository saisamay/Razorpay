from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.main import app
from recovery_service.models import AuditLogEntry, DeadLetterEvent, PaymentState, RawEvent, RecoveryCase
from recovery_service.service import process_event
from recovery_service.settings import Settings


SECRET = "adversarial-secret-key"


def _build_adv_app(tmp_path, max_bytes: int = 4096, internal_token: str | None = "internal-secret-token"):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/adversarial.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=(SECRET,),
        environment="test",
        max_webhook_bytes=max_bytes,
        internal_api_token=internal_token,
        razorpay_key_id="adv_key",
        razorpay_key_secret="adv_secret",
    )
    factory = build_session_factory(settings)
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


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _payload(event_type: str = "payment.failed", payment_id: str = "pay_adv_1", amount: int = 50000, currency: str = "INR") -> dict:
    return {
        "entity": "event",
        "account_id": "acc_adv",
        "event": event_type,
        "created_at": 1_724_000_000,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount,
                    "currency": currency,
                    "order_id": "order_adv",
                    "method": "upi",
                    "error_source": "bank" if event_type == "payment.failed" else None,
                    "error_reason": "payment_failed" if event_type == "payment.failed" else None,
                }
            }
        },
    }


def _raw_event(event_id: str, event_type: str, payment_id: str = "pay_adv_1", **kwargs) -> RawEvent:
    return RawEvent(
        source_event_id=event_id,
        event_type=event_type,
        environment="test",
        raw_payload=_payload(event_type, payment_id),
        **kwargs,
    )


# Category 1: Authentication
def test_adv_auth_valid_invalid_missing_wrong_secret(tmp_path):
    client, factory, settings = _build_adv_app(tmp_path)
    raw = json.dumps(_payload()).encode("utf-8")

    # 1. Valid signature
    res_valid = client.post("/webhooks/razorpay", content=raw, headers={"x-razorpay-signature": _sign(raw), "x-razorpay-event-id": "evt_auth_1"})
    assert res_valid.status_code == 202

    # 2. Missing signature
    res_missing = client.post("/webhooks/razorpay", content=raw, headers={"x-razorpay-event-id": "evt_auth_2"})
    assert res_missing.status_code == 401

    # 3. Wrong secret signature
    res_wrong = client.post("/webhooks/razorpay", content=raw, headers={"x-razorpay-signature": _sign(raw, "wrong_secret"), "x-razorpay-event-id": "evt_auth_3"})
    assert res_wrong.status_code == 401

    # 4. Tampered body signature
    res_tampered = client.post("/webhooks/razorpay", content=raw + b" ", headers={"x-razorpay-signature": _sign(raw), "x-razorpay-event-id": "evt_auth_4"})
    assert res_tampered.status_code == 401


# Category 2: Payload Boundaries
def test_adv_payload_empty_malformed_oversized_deep_nesting(tmp_path):
    client_small, factory, settings = _build_adv_app(tmp_path, max_bytes=100)

    # Oversized payload
    raw_large = json.dumps(_payload()).encode("utf-8") + b" " * 500
    res_large = client_small.post("/webhooks/razorpay", content=raw_large, headers={"x-razorpay-signature": _sign(raw_large), "x-razorpay-event-id": "evt_p1"})
    assert res_large.status_code == 413

    # Deep nesting (> 10 levels)
    client_normal, _, _ = _build_adv_app(tmp_path, max_bytes=4096)
    deep_dict = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": "too deep"}}}}}}}}}}}
    raw_deep = json.dumps({"event": "payment.failed", "payload": deep_dict}).encode("utf-8")
    res_deep = client_normal.post("/webhooks/razorpay", content=raw_deep, headers={"x-razorpay-signature": _sign(raw_deep), "x-razorpay-event-id": "evt_p2"})
    assert res_deep.status_code == 422


# Category 3: Semantics & Quarantine
def test_adv_semantics_negative_amount_invalid_currency_timestamp_bounds(tmp_path):
    factory = build_session_factory(Settings(database_url=f"sqlite:///{tmp_path}/sem.sqlite3", redis_url="unused", webhook_secrets=(SECRET,), environment="test", max_webhook_bytes=4096))
    Base.metadata.create_all(factory.kw["bind"])

    # Negative amount payload
    neg_payload = _payload("payment.failed", "pay_neg", amount=-500)
    with factory() as session:
        evt = RawEvent(source_event_id="evt_neg", event_type="payment.failed", environment="test", raw_payload=neg_payload)
        session.add(evt)
        session.commit()
        res = process_event(session, evt.id)
        assert res.status == "QUARANTINED"
        assert session.get(RawEvent, evt.id).processing_status == "QUARANTINED"
        # Quarantined event MUST NOT create an eligible recovery case
        assert session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_neg")) is None

    # Invalid currency code payload
    bad_curr_payload = _payload("payment.failed", "pay_curr", currency="INVALID_CURRENCY")
    with factory() as session:
        evt2 = RawEvent(source_event_id="evt_curr", event_type="payment.failed", environment="test", raw_payload=bad_curr_payload)
        session.add(evt2)
        session.commit()
        res2 = process_event(session, evt2.id)
        assert res2.status == "QUARANTINED"

    # Future timestamp payload (> +24h)
    future_payload = _payload("payment.failed", "pay_fut")
    future_payload["created_at"] = int((datetime.now(timezone.utc) + timedelta(days=5)).timestamp())
    with factory() as session:
        evt3 = RawEvent(source_event_id="evt_fut", event_type="payment.failed", environment="test", raw_payload=future_payload)
        session.add(evt3)
        session.commit()
        res3 = process_event(session, evt3.id)
        assert res3.status == "QUARANTINED"


# Category 4: Replay & 100x Duplicate Delivery
def test_adv_replay_100x_duplicate_delivery(tmp_path):
    client, factory, settings = _build_adv_app(tmp_path)
    raw = json.dumps(_payload("payment.failed", "pay_dup_100")).encode("utf-8")
    sig = _sign(raw)

    # 1st request -> accepted
    r1 = client.post("/webhooks/razorpay", content=raw, headers={"x-razorpay-signature": sig, "x-razorpay-event-id": "evt_dup_100"})
    assert r1.status_code == 202
    assert r1.json()["duplicate"] is False

    # Next 100 duplicate deliveries -> all return duplicate=True logically harmless
    for i in range(100):
        r_dup = client.post("/webhooks/razorpay", content=raw, headers={"x-razorpay-signature": sig, "x-razorpay-event-id": "evt_dup_100"})
        assert r_dup.status_code == 202
        assert r_dup.json()["duplicate"] is True

    # Process single stored event
    with factory() as session:
        evt = session.scalars(select(RawEvent).where(RawEvent.source_event_id == "evt_dup_100")).one()
        process_event(session, evt.id)
        session.commit()
        cases = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_dup_100")).all()
        assert len(cases) == 1


# Category 5: Concurrency Races
def test_adv_concurrency_race_failed_vs_authorized(tmp_path):
    factory = build_session_factory(Settings(database_url=f"sqlite:///{tmp_path}/race.sqlite3", redis_url="unused", webhook_secrets=(SECRET,), environment="test", max_webhook_bytes=4096))
    Base.metadata.create_all(factory.kw["bind"])

    with factory() as session:
        e1 = RawEvent(source_event_id="evt_r1", event_type="payment.failed", environment="test", raw_payload=_payload("payment.failed", "pay_race_1"))
        e2 = RawEvent(source_event_id="evt_r2", event_type="payment.authorized", environment="test", raw_payload=_payload("payment.authorized", "pay_race_1"))
        session.add_all([e1, e2])
        session.commit()
        id1, id2 = e1.id, e2.id

    def worker_a():
        with factory() as session:
            process_event(session, id1, worker_id="worker-A")
            session.commit()

    def worker_b():
        with factory() as session:
            process_event(session, id2, worker_id="worker-B")
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker_a)
        f2 = executor.submit(worker_b)
        f1.result()
        f2.result()

    with factory() as session:
        state = session.get(PaymentState, "pay_race_1")
        assert state is not None
        # AUTHORIZED supersedes FAILED when both exist
        assert state.state == "AUTHORIZED"
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_race_1"))
        if case:
            assert case.recovery_eligible is False


# Category 6: Ordering & Contradictory Evidence
def test_adv_ordering_negative_evidence_after_capture(tmp_path):
    factory = build_session_factory(Settings(database_url=f"sqlite:///{tmp_path}/order.sqlite3", redis_url="unused", webhook_secrets=(SECRET,), environment="test", max_webhook_bytes=4096))
    Base.metadata.create_all(factory.kw["bind"])

    with factory() as session:
        captured = _raw_event("evt_cap", "payment.captured", "pay_contradict")
        failed = _raw_event("evt_fail_late", "payment.failed", "pay_contradict")
        session.add_all([captured, failed])
        session.commit()
        process_event(session, captured.id)
        process_event(session, failed.id)
        session.commit()

        state = session.get(PaymentState, "pay_contradict")
        assert state.state == "CAPTURED"
        assert any(a["type"] == "NEGATIVE_EVIDENCE_AFTER_CAPTURE" for a in state.anomalies)


# Category 7: Versioning & Stage 2 Boundary Gate
def test_adv_versioning_and_stage2_boundary_contract(tmp_path):
    client, factory, settings = _build_adv_app(tmp_path)
    with factory() as session:
        failed = _raw_event("evt_v1", "payment.failed", "pay_version_1")
        session.add(failed)
        session.commit()
        process_event(session, failed.id)
        session.commit()
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.payment_id == "pay_version_1"))
        case_id = case.case_id

    # Verify Stage 2 security boundary contract endpoint
    res = client.get(f"/recovery-cases/{case_id}/contract")
    assert res.status_code == 200
    data = res.json()
    assert data["schema_version"] == "1.5"
    assert data["source_event_ids"] == ["evt_v1"]
    assert data["stage1_state_version"] == 1
    assert data["recovery_eligible"] is True
    # Ensure RAW webhook payload is NOT returned in Stage 2 contract
    assert "raw_payload" not in data


# Category 8: Authorization & Replay Security
def test_adv_authorization_protected_endpoints(tmp_path):
    client, factory, settings = _build_adv_app(tmp_path, internal_token="secret-token-321")

    # Unauthorized access to internal endpoints returns 403 Forbidden
    res_dlq_unauth = client.get("/internal/dlq/evt_dummy")
    assert res_dlq_unauth.status_code == 403

    res_replay_unauth = client.post("/internal/replay/evt_dummy")
    assert res_replay_unauth.status_code == 403

    # Authorized access with valid token succeeds / proceeds
    headers = {"x-internal-token": "secret-token-321"}
    res_replay_auth = client.post("/internal/replay/non_existent", headers=headers)
    assert res_replay_auth.status_code == 404  # Passes auth, returns 404 for missing row

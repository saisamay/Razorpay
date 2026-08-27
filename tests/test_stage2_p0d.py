from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from recovery_service.database import Base, build_session_factory
from recovery_service.main import app
from recovery_service.models import RecoveryCase, utc_now
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import process_diagnosis
from recovery_service.stage2.models import Stage2Case
from recovery_service.stage2.schemas import RecoveryCaseContract


def _build_test_app(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/p0d.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        internal_api_token="test-admin-token",
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)

    app.state.settings = settings
    app.state.sessions = factory

    class DummyClient:
        def ping(self):
            return True
    app.state.queue = DummyClient()

    return TestClient(app), factory


def _sample_contract(case_id: str, merchant_id: str, state_version: int = 1) -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id="evt_fail_p0d",
        merchant_id=merchant_id,
        order_id="order_p0d",
        amount=50000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "CARD_DECLINED", "gateway": "HDFC"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail_p0d"],
        stage1_state_version=state_version,
    )


def test_tenant_isolation_forbidden_access(tmp_path):
    client, factory = _build_test_app(tmp_path)
    now = utc_now()

    # Create case belonging to Merchant A ("acc_merchant_A")
    with factory() as session:
        session.add(RecoveryCase(
            case_id="rc_merchant_A_case", payment_id="pay_A", recovery_episode_id="evt_A",
            merchant_id="acc_merchant_A", amount=10000, currency="INR", state="FAILED",
            state_confidence=1.0, failure_evidence={"reason": "CARD_DECLINED"},
            first_seen_at=now, last_seen_at=now, recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT", schema_version="1.5",
            source_event_ids=["evt_A"], stage1_state_version=1,
        ))
        session.commit()

        contract = _sample_contract("rc_merchant_A_case", "acc_merchant_A", state_version=1)
        process_diagnosis(session, contract)
        session.commit()

    # Attempt 1: Merchant B tries to access Merchant A's diagnosis -> 403 Forbidden
    res_b = client.get("/api/v2/cases/rc_merchant_A_case/diagnosis", headers={"x-merchant-id": "acc_merchant_B"})
    assert res_b.status_code == 403
    assert "denied" in res_b.json()["detail"].lower()

    # Attempt 2: Merchant B tries to access Merchant A's manifest -> 403 Forbidden
    res_manifest_b = client.get("/api/v2/cases/rc_merchant_A_case/manifest", headers={"x-merchant-id": "acc_merchant_B"})
    assert res_manifest_b.status_code == 403

    # Attempt 3: Merchant A accesses Merchant A's diagnosis -> 200 OK
    res_a = client.get("/api/v2/cases/rc_merchant_A_case/diagnosis", headers={"x-merchant-id": "acc_merchant_A"})
    assert res_a.status_code == 200
    assert res_a.json()["diagnosis_class"] == "ISSUER_DECLINE"


def test_version_history_and_stale_result_protection(tmp_path):
    client, factory = _build_test_app(tmp_path)
    now = utc_now()

    # Version 1 diagnosis
    with factory() as session:
        session.add(RecoveryCase(
            case_id="rc_versioned_1", payment_id="pay_v1", recovery_episode_id="evt_v1",
            merchant_id="acc_v", amount=10000, currency="INR", state="FAILED",
            state_confidence=1.0, failure_evidence={"reason": "GATEWAY_TIMEOUT"},
            first_seen_at=now, last_seen_at=now, recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT", schema_version="1.5",
            source_event_ids=["evt_v1"], stage1_state_version=1,
        ))
        session.commit()

        contract_v1 = _sample_contract("rc_versioned_1", "acc_v", state_version=1)
        process_diagnosis(session, contract_v1)
        session.commit()

    # Version 2 diagnosis (state version 2)
    with factory() as session:
        case = session.get(RecoveryCase, "rc_versioned_1")
        case.stage1_state_version = 2
        case.failure_evidence = {"reason": "CARD_DECLINED"}
        session.commit()

        contract_v2 = _sample_contract("rc_versioned_1", "acc_v", state_version=2)
        contract_v2.failure_evidence = {"reason": "CARD_DECLINED"}
        process_diagnosis(session, contract_v2)
        session.commit()

    # Query history
    res_hist = client.get("/api/v2/cases/rc_versioned_1/history", headers={"x-merchant-id": "acc_v"})
    assert res_hist.status_code == 200
    history = res_hist.json()
    assert len(history) >= 1
    latest = history[-1]
    assert latest["stage1_state_version"] == 2
    assert latest["diagnosis_class"] == "ISSUER_DECLINE"


def test_reprocess_endpoint_auth_and_execution(tmp_path):
    client, factory = _build_test_app(tmp_path)
    now = utc_now()

    with factory() as session:
        session.add(RecoveryCase(
            case_id="rc_reprocess_1", payment_id="pay_rep", recovery_episode_id="evt_rep",
            merchant_id="acc_rep", amount=20000, currency="INR", state="FAILED",
            state_confidence=1.0, failure_evidence={"reason": "3DS_AUTH_FAILED", "failure_step": "payment_authentication"},
            first_seen_at=now, last_seen_at=now, recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT", schema_version="1.5",
            source_event_ids=["evt_rep"], stage1_state_version=1,
        ))
        session.commit()

    # Unauthorized reprocess attempt -> 401 Unauthorized
    res_unauth = client.post("/api/v2/cases/rc_reprocess_1/reprocess")
    assert res_unauth.status_code == 401

    # Authorized reprocess attempt with token -> 200 OK
    res_auth = client.post("/api/v2/cases/rc_reprocess_1/reprocess", headers={"x-internal-token": "test-admin-token"})
    assert res_auth.status_code == 200
    assert res_auth.json()["reprocessed"] is True
    assert res_auth.json()["diagnosis_class"] == "AUTHENTICATION_FAILURE"

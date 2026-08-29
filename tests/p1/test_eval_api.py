from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from recovery_service.database import Base, build_session_factory
from recovery_service.main import app
from recovery_service.models import RecoveryCase
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import process_p1_pipeline
from recovery_service.stage2.schemas import RecoveryCaseContract


def _setup_app_and_case(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/eval_api.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)

    app.state.settings = settings
    app.state.sessions = factory

    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_eval_api_1",
        payment_id="pay_eval_1",
        recovery_episode_id="evt_fail",
        merchant_id="merchant_alpha",
        order_id="order_eval_1",
        amount=85000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "GATEWAY_TIMEOUT", "gateway": "HDFC"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail"],
        stage1_state_version=1,
    )

    with factory() as session:
        # Create RecoveryCase row
        session.add(RecoveryCase(
            case_id=contract.case_id,
            payment_id=contract.payment_id,
            recovery_episode_id=contract.recovery_episode_id,
            merchant_id=contract.merchant_id,
            order_id=contract.order_id,
            amount=contract.amount,
            currency=contract.currency,
            state=contract.state,
            state_confidence=contract.state_confidence,
            failure_evidence=contract.failure_evidence,
            first_seen_at=contract.first_seen_at,
            last_seen_at=contract.last_seen_at,
            recovery_eligible=True,
            eligibility_reason=contract.eligibility_reason,
            schema_version=contract.schema_version,
            source_event_ids=contract.source_event_ids,
            stage1_state_version=1,
        ))
        session.commit()

        # Run P1 pipeline
        process_p1_pipeline(session, contract, worker_id="eval-test-worker")
        session.commit()

    return TestClient(app)


def test_case_evaluation_api_authorized_tenant(tmp_path):
    client = _setup_app_and_case(tmp_path)

    # Merchant Alpha accesses Case rc_eval_api_1 -> 200 OK
    resp = client.get("/api/v2/evaluation/cases/rc_eval_api_1", headers={"x-merchant-id": "merchant_alpha"})
    assert resp.status_code == 200

    data = resp.json()
    assert data["case_id"] == "rc_eval_api_1"
    assert data["merchant_id"] == "merchant_alpha"
    assert data["amount"]["value"] == 85000
    assert data["amount"]["semantic_status"] == "OBSERVED"
    assert data["decision_proposal"]["selected_action"] is not None
    assert data["data_quality"]["recovery_case"] is True
    assert data["data_quality"]["proposal"] is True


def test_case_evaluation_api_cross_tenant_forbidden(tmp_path):
    client = _setup_app_and_case(tmp_path)

    # Merchant Beta attempts to access Merchant Alpha's Case rc_eval_api_1 -> 403 Forbidden
    resp = client.get("/api/v2/evaluation/cases/rc_eval_api_1", headers={"x-merchant-id": "merchant_beta"})
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]


def test_investigation_ui_endpoint_returns_html(tmp_path):
    client = _setup_app_and_case(tmp_path)

    resp = client.get("/investigation")
    assert resp.status_code == 200
    assert "Payment Recovery Investigation" in resp.text
    assert "<title>" in resp.text

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from recovery_service.database import build_session_factory, ensure_schema
from recovery_service.main import app
from recovery_service.models import RecoveryCase
from recovery_service.settings import Settings
from recovery_service.stage3.escalation import (
    EscalationError,
    TenantAccessError,
    check_and_apply_sla_timeouts,
    create_escalation,
    get_escalation,
    list_escalations,
    resolve_escalation,
)
from recovery_service.stage3.models import RecoveryEscalationRecord, RecoveryOrchestrationRecord
from recovery_service.stage3.orchestrator import create_or_get_orchestration



def _setup_db(tmp_path) -> sessionmaker[Session]:
    db_path = tmp_path / "test_esc.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test_secret",),
        environment="test",
        max_webhook_bytes=1048576,
    )
    factory = build_session_factory(settings)
    ensure_schema(factory)
    return factory



def _create_test_case(session: Session, case_id: str, merchant_id: str):
    now = datetime.now(timezone.utc)
    case = RecoveryCase(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id=f"ep_{case_id}",
        merchant_id=merchant_id,
        amount=10000,
        currency="INR",
        state="PAYMENT_FAILED",
        state_confidence=1.0,
        failure_evidence={"error": "card_decline"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="ELIGIBLE",
        schema_version="1.5",
        source_event_ids=["evt_1"],
        stage1_state_version=1,
    )
    session.add(case)
    session.commit()


def test_escalation_creation_and_retrieval(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_esc_1", "m_esc_1")
        orch = create_or_get_orchestration(session, "c_esc_1")
        session.commit()

        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_esc_1",
            merchant_id="m_esc_1",
            reason_code="MAX_ATTEMPTS_EXCEEDED",
            severity="HIGH",
        )
        session.commit()

        assert esc.status == "OPEN"
        assert esc.reason_code == "MAX_ATTEMPTS_EXCEEDED"

        # Check orchestration status locked to ESCALATED
        orch_reloaded = session.get(RecoveryOrchestrationRecord, orch.orchestration_id)
        assert orch_reloaded.episode_status == "ESCALATED"
        assert orch_reloaded.escalation_id == esc.escalation_id

        # Retrieve escalation with valid tenant
        retrieved = get_escalation(session, esc.escalation_id, merchant_id="m_esc_1")
        assert retrieved.escalation_id == esc.escalation_id


def test_escalation_tenant_isolation(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_esc_tenant", "m_owner")
        orch = create_or_get_orchestration(session, "c_esc_tenant")
        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_esc_tenant",
            merchant_id="m_owner",
            reason_code="HIGH_VALUE_UNCERTAIN_DIAGNOSIS",
        )
        session.commit()

        # Access with wrong merchant MUST raise TenantAccessError
        with pytest.raises(TenantAccessError):
            get_escalation(session, esc.escalation_id, merchant_id="m_intruder")

        # Resolve with wrong merchant MUST raise TenantAccessError
        with pytest.raises(TenantAccessError):
            resolve_escalation(
                session,
                escalation_id=esc.escalation_id,
                merchant_id="m_intruder",
                resolution_action="STOP_RECOVERY",
                operator_id="op_intruder",
            )


def test_escalation_status_transitions_and_resolution(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_esc_res", "m_res")
        orch = create_or_get_orchestration(session, "c_esc_res")
        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_esc_res",
            merchant_id="m_res",
            reason_code="COMPLIANCE_MANUAL_REVIEW",
        )
        session.commit()

        # Invalid resolution action raises EscalationError
        with pytest.raises(EscalationError):
            resolve_escalation(
                session,
                escalation_id=esc.escalation_id,
                merchant_id="m_res",
                resolution_action="INVALID_ACTION",
                operator_id="op_1",
            )

        # Valid resolution: RESUME_AUTOMATION
        resolved = resolve_escalation(
            session,
            escalation_id=esc.escalation_id,
            merchant_id="m_res",
            resolution_action="RESUME_AUTOMATION",
            operator_id="op_admin",
            notes="Approved after compliance check.",
        )
        session.commit()

        assert resolved.status == "RESOLVED"
        assert resolved.resolution_action == "RESUME_AUTOMATION"
        assert resolved.assigned_operator == "op_admin"

        # Check orchestration state reset to PENDING for next sweep
        orch_reloaded = session.get(RecoveryOrchestrationRecord, orch.orchestration_id)
        assert orch_reloaded.episode_status == "PENDING"
        assert orch_reloaded.escalation_id is None

        # Cannot resolve an already resolved escalation
        with pytest.raises(EscalationError):
            resolve_escalation(
                session,
                escalation_id=esc.escalation_id,
                merchant_id="m_res",
                resolution_action="STOP_RECOVERY",
                operator_id="op_admin",
            )


def test_escalation_sla_auto_stop(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_esc_sla", "m_sla")
        orch = create_or_get_orchestration(session, "c_esc_sla")
        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_esc_sla",
            merchant_id="m_sla",
            reason_code="F5_POLICY_REJECTION",
        )
        # Backdate triggered_at to exceed 24h SLA
        esc.triggered_at = datetime.now(timezone.utc) - timedelta(hours=25)
        session.commit()

        resolved = check_and_apply_sla_timeouts(session, sla_hours=24.0)
        session.commit()

        assert len(resolved) == 1
        assert resolved[0].escalation_id == esc.escalation_id
        assert resolved[0].status == "RESOLVED"
        assert resolved[0].resolution_action == "AUTO_STOP_SLA_EXPIRED"

        orch_reloaded = session.get(RecoveryOrchestrationRecord, orch.orchestration_id)
        assert orch_reloaded.episode_status == "STOPPED"
        assert orch_reloaded.stopping_reason == "ESCALATION_SLA_EXPIRED"


def test_escalation_api_endpoints(tmp_path):
    db_path = tmp_path / "test_api_esc.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test_secret",),
        environment="test",
        max_webhook_bytes=1048576,
    )

    factory = build_session_factory(settings)
    ensure_schema(factory)

    app.state.settings = settings
    app.state.sessions = factory
    client = TestClient(app)

    with factory() as session:
        _create_test_case(session, "c_api_esc", "m_api")
        orch = create_or_get_orchestration(session, "c_api_esc")
        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_api_esc",
            merchant_id="m_api",
            reason_code="ACTIVE_INCIDENT",
        )
        session.commit()
        esc_id = esc.escalation_id

    # 1. GET /api/v3/escalations with tenant header
    resp = client.get("/api/v3/escalations", headers={"x-merchant-id": "m_api"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["escalation_id"] == esc_id

    # 2. GET /api/v3/escalations/{id}
    resp_detail = client.get(f"/api/v3/escalations/{esc_id}", headers={"x-merchant-id": "m_api"})
    assert resp_detail.status_code == 200
    detail_data = resp_detail.json()
    assert detail_data["escalation"]["escalation_id"] == esc_id
    assert detail_data["orchestration"]["episode_status"] == "ESCALATED"

    # 3. GET /api/v3/escalations/{id} tenant forbidden
    resp_forbidden = client.get(f"/api/v3/escalations/{esc_id}", headers={"x-merchant-id": "m_wrong"})
    assert resp_forbidden.status_code == 403

    # 4. POST /api/v3/escalations/{id}/resolve
    resp_res = client.post(
        f"/api/v3/escalations/{esc_id}/resolve",
        headers={"x-merchant-id": "m_api"},
        json={
            "resolution_action": "STOP_RECOVERY",
            "operator_id": "op_api_user",
            "notes": "Stopping via API test.",
        },
    )
    assert resp_res.status_code == 200
    res_data = resp_res.json()
    assert res_data["resolution_action"] == "STOP_RECOVERY"
    assert res_data["status"] == "RESOLVED"

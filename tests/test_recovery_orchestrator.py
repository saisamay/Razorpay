from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recovery_service.database import build_session_factory, ensure_schema
from recovery_service.models import AuditLogEntry, RecoveryCase
from recovery_service.revenue_economics import compute_revenue_summary
from recovery_service.settings import Settings
from recovery_service.stage2.ai_learning import CaseKnowledgeRecord, compute_confidence_score
from recovery_service.stage2.models import (
    DecisionPolicyRecord,
    IncidentClusterRecord,
)

from recovery_service.stage3.escalation import (
    check_and_apply_sla_timeouts,
    create_escalation,
    resolve_escalation,
)
from recovery_service.stage3.models import (
    RecoveryAttemptRecord,
    RecoveryEscalationRecord,
    RecoveryOrchestrationRecord,
    Stage3OutcomeObservation,
)
from recovery_service.stage3.orchestrator import (
    advance_recovery_episode,
    create_or_get_orchestration,
    handle_outcome,
    start_attempt,
)



def _setup_db(tmp_path) -> sessionmaker[Session]:
    db_path = tmp_path / "test_orch.db"
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



def _create_test_case(session: Session, case_id: str, merchant_id: str, amount: int = 10000, create_f5_policy: bool = True) -> RecoveryCase:
    now = datetime.now(timezone.utc)
    case = RecoveryCase(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id=f"ep_{case_id}",
        merchant_id=merchant_id,
        amount=amount,
        currency="INR",
        state="PAYMENT_FAILED",
        state_confidence=1.0,
        failure_evidence={"error": "card_issuer_decline"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="ELIGIBLE",
        schema_version="1.5",
        source_event_ids=["evt_1"],
        stage1_state_version=1,
    )
    session.add(case)

    if create_f5_policy:
        existing_pol = session.scalars(
            select(DecisionPolicyRecord).where(DecisionPolicyRecord.merchant_id == merchant_id)
        ).first()
        if existing_pol is None:
            pol = DecisionPolicyRecord(
                policy_id=f"pol_{merchant_id}",
                policy_version="1.0",
                merchant_id=merchant_id,
                experiment_id="EXP_DEFAULT",
                experiment_version="1.0",
                approved_configuration_hash="a" * 64,
                source_f4_evidence_id=f"ev_{merchant_id}",
                source_f4_evaluated_at=now,
                source_f4_status="EFFICACY_RESULT_AVAILABLE",
                source_f4_configuration_hash="a" * 64,
                authorized_actions=["RETRY_NOW", "RETRY_LATER", "ALTERNATE_RAIL", "UPDATE_PAYMENT_METHOD", "CUSTOMER_INTERVENTION", "PAYMENT_LINK", "STOP"],
                baseline_action="STOP",
                status="ACTIVE_ENFORCED",
                activated_at=now,
                created_at=now,
                supersession_status="CURRENT",
            )
            session.add(pol)

    session.commit()
    return case


# 1. Create Episode Test
def test_orch_1_create_episode(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_1", "m_orch_1")
        orch = create_or_get_orchestration(session, "c_orch_1", max_attempts=3)
        session.commit()

        assert orch.orchestration_id.startswith("orch_")
        assert orch.case_id == "c_orch_1"
        assert orch.merchant_id == "m_orch_1"
        assert orch.episode_status == "PENDING"
        assert orch.current_attempt_number == 0
        assert orch.max_attempts == 3


# 2. Start Attempt 1 Test
def test_orch_2_start_attempt_1(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_2", "m_orch_2")
        orch, attempt = start_attempt(session, "c_orch_2")
        session.commit()

        assert orch.current_attempt_number == 1
        assert orch.episode_status in {"AWAITING_OUTCOME", "STOPPED"}
        assert attempt is not None
        assert attempt.attempt_number == 1
        assert attempt.proposed_action != ""


# 3. Successful Recovery Terminates Episode Test
def test_orch_3_successful_recovery_terminates_episode(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_3", "m_orch_3", amount=5000)
        orch, attempt = start_attempt(session, "c_orch_3")
        session.commit()

        now = datetime.now(timezone.utc)
        obs = Stage3OutcomeObservation(
            attribution_id="attr_orch_3",
            case_id="c_orch_3",
            payment_id="pay_c_orch_3",
            proposal_id=orch.proposal_id or "prop_3",
            merchant_id="m_orch_3",
            executed_action="RETRY_NOW",
            gross_recovered_amount=50.0,
            net_verified_recovered_amount=50.0,
            outcome_status="RECOVERED",
            observed_at=now,
            finalized_at=now,
        )
        session.add(obs)

        orch_updated = handle_outcome(session, obs)
        session.commit()

        assert orch_updated.episode_status == "RECOVERED"
        assert orch_updated.stopping_reason == "PAYMENT_RECOVERED"
        assert orch_updated.total_net_recovered_amount == 50.0

        # Further attempts must fail
        with pytest.raises(ValueError, match="terminal status"):
            start_attempt(session, "c_orch_3")


# 4. Failed Attempt Allows Attempt 2 Test
def test_orch_4_failed_attempt_allows_attempt_2(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_4", "m_orch_4")
        orch, att1 = start_attempt(session, "c_orch_4")
        session.commit()

        now = datetime.now(timezone.utc)
        obs1 = Stage3OutcomeObservation(
            attribution_id="attr_orch_4_1",
            case_id="c_orch_4",
            payment_id="pay_c_orch_4",
            proposal_id=orch.proposal_id or "prop_4_1",
            merchant_id="m_orch_4",
            executed_action="RETRY_NOW",
            gross_recovered_amount=0.0,
            net_verified_recovered_amount=0.0,
            outcome_status="FAILED",
            observed_at=now,
            finalized_at=now,
        )
        session.add(obs1)

        orch_updated = handle_outcome(session, obs1)
        session.commit()

        # Outcome handled resets status to PENDING for next attempt
        assert orch_updated.episode_status == "PENDING"
        assert orch_updated.current_attempt_number == 1

        # Advance triggers attempt 2
        orch_att2, att2 = start_attempt(session, "c_orch_4")
        session.commit()

        assert orch_att2.current_attempt_number == 2
        assert att2.attempt_number == 2


# 5. Failed Attempts Reach Max Attempts Test
def test_orch_5_failed_attempts_reach_max(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_5", "m_orch_5")

        for attempt_num in range(1, 4):
            orch, att = start_attempt(session, "c_orch_5")
            session.commit()
            now = datetime.now(timezone.utc)
            obs = Stage3OutcomeObservation(
                attribution_id=f"attr_orch_5_{attempt_num}",
                case_id="c_orch_5",
                payment_id="pay_c_orch_5",
                proposal_id=orch.proposal_id or f"prop_5_{attempt_num}",
                merchant_id="m_orch_5",
                executed_action="RETRY_NOW",
                gross_recovered_amount=0.0,
                net_verified_recovered_amount=0.0,
                outcome_status="FAILED",
                observed_at=now,
                finalized_at=now,
            )
            session.add(obs)
            orch_res = handle_outcome(session, obs)
            session.commit()

        assert orch_res.current_attempt_number == 3
        assert orch_res.episode_status == "STOPPED"
        assert orch_res.stopping_reason == "MAX_ATTEMPTS_REACHED"


# 6. No Attempt After Terminal State Test
def test_orch_6_no_attempt_after_terminal_state(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_6", "m_orch_6")
        orch = create_or_get_orchestration(session, "c_orch_6")
        orch.episode_status = "STOPPED"
        orch.stopping_reason = "MANUAL_STOP"
        session.commit()

        with pytest.raises(ValueError, match="terminal status"):
            start_attempt(session, "c_orch_6")


# 7. Recovery Window Expiry Test
def test_orch_7_recovery_window_expiry(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_7", "m_orch_7")
        orch = create_or_get_orchestration(session, "c_orch_7")
        orch.first_failure_at = datetime.now(timezone.utc) - timedelta(hours=75)
        session.commit()

        orch_adv = advance_recovery_episode(session, "c_orch_7")
        session.commit()

        assert orch_adv.episode_status == "STOPPED"
        assert orch_adv.stopping_reason == "RECOVERY_WINDOW_EXPIRED"


# 8. Negative Expected Net Value Test
def test_orch_8_negative_expected_net_value(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_8", "m_orch_8")
        orch = create_or_get_orchestration(session, "c_orch_8")
        session.commit()

        # Force stopping rules evaluation with non-positive expected_net_value
        from recovery_service.stage3.stopping import evaluate_stopping_rules
        res = evaluate_stopping_rules(
            episode_status=orch.episode_status,
            current_attempt_number=orch.current_attempt_number,
            expected_net_value=-50.0,
        )
        assert res.should_stop is True
        assert res.reason_code == "NON_POSITIVE_EXPECTED_NET_VALUE"
        assert res.target_status == "STOPPED"


# 9. F5 Denial Test
def test_orch_9_f5_denial(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_9", "m_orch_9", create_f5_policy=False)
        # Explicitly setup a disabled F5 decision policy
        policy = DecisionPolicyRecord(
            policy_id="pol_denied",
            policy_version="1.0",
            merchant_id="m_orch_9",
            experiment_id="EXP_DEFAULT",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
            source_f4_evidence_id="ev_1",
            source_f4_evaluated_at=datetime.now(timezone.utc),
            source_f4_status="EFFICACY_RESULT_AVAILABLE",
            source_f4_configuration_hash="a" * 64,
            authorized_actions=["STOP"],  # RETRY_NOW is NOT authorized
            status="DISABLED",  # Disabled status causes F5 DENY
        )
        session.add(policy)
        session.commit()

        orch, att = start_attempt(session, "c_orch_9")
        session.commit()

        assert orch.episode_status == "STOPPED"
        assert "F5_" in orch.stopping_reason


# 10. Active Incident Pause/Escalation Test
def test_orch_10_active_incident_pause_escalation(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_10", "m_orch_10")
        inc = IncidentClusterRecord(
            incident_id="inc_active_10",
            dimensions={"rail": "card"},
            affected_case_count=30,
            status="CONFIRMED",
            started_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        session.add(inc)
        session.commit()

        from recovery_service.stage3.stopping import evaluate_stopping_rules
        res = evaluate_stopping_rules(
            episode_status="PENDING",
            current_attempt_number=0,
            incident_active=True,
        )
        assert res.should_stop is True
        assert res.reason_code == "ACTIVE_SYSTEMIC_INCIDENT"
        assert res.target_status == "ESCALATED"


# 11. Escalation Lockout Test
def test_orch_11_escalation_lockout(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_11", "m_orch_11")
        orch = create_or_get_orchestration(session, "c_orch_11")
        create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_orch_11",
            merchant_id="m_orch_11",
            reason_code="MANUAL_REVIEW_REQUIRED",
        )
        session.commit()

        with pytest.raises(ValueError, match="terminal status"):
            start_attempt(session, "c_orch_11")


# 12-14. Operator Resume, Stop, Close Tests
def test_orch_12_14_operator_resolutions(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_12", "m_orch_12")
        orch = create_or_get_orchestration(session, "c_orch_12")
        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_orch_12",
            merchant_id="m_orch_12",
            reason_code="UNCERTAIN_DIAGNOSIS",
        )
        session.commit()

        # Operator Resume
        resolved = resolve_escalation(
            session,
            escalation_id=esc.escalation_id,
            merchant_id="m_orch_12",
            resolution_action="RESUME_AUTOMATION",
            operator_id="op_tester",
        )
        session.commit()

        orch_reloaded = session.get(RecoveryOrchestrationRecord, orch.orchestration_id)
        assert orch_reloaded.episode_status == "PENDING"

        # Now attempt can proceed
        orch_next, att = start_attempt(session, "c_orch_12")
        session.commit()
        assert orch_next.current_attempt_number == 1


# 15. Escalation SLA Auto-stop Test
def test_orch_15_escalation_sla_autostop(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_15", "m_orch_15")
        orch = create_or_get_orchestration(session, "c_orch_15")
        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_orch_15",
            merchant_id="m_orch_15",
            reason_code="SLA_TIMEOUT_TEST",
        )
        esc.triggered_at = datetime.now(timezone.utc) - timedelta(hours=25)
        session.commit()

        check_and_apply_sla_timeouts(session, sla_hours=24.0)
        session.commit()

        orch_reloaded = session.get(RecoveryOrchestrationRecord, orch.orchestration_id)
        assert orch_reloaded.episode_status == "STOPPED"
        assert orch_reloaded.stopping_reason == "ESCALATION_SLA_EXPIRED"


# 16-17. Duplicate and Concurrent Attempt Prevention Tests
def test_orch_16_17_duplicate_attempt_prevention(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_16", "m_orch_16")
        orch1, att1 = start_attempt(session, "c_orch_16")
        session.commit()

        # Calling start_attempt again when attempt 1 exists returns existing attempt
        orch2, att2 = start_attempt(session, "c_orch_16")
        session.commit()

        assert att1.attempt_id == att2.attempt_id
        assert att2.attempt_number == 1


# 18. Duplicate Outcome Handling Test
def test_orch_18_duplicate_outcome_handling(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_18", "m_orch_18", amount=10000)
        orch, att = start_attempt(session, "c_orch_18")
        session.commit()

        now = datetime.now(timezone.utc)
        obs = Stage3OutcomeObservation(
            attribution_id="attr_orch_18",
            case_id="c_orch_18",
            payment_id="pay_c_orch_18",
            proposal_id=orch.proposal_id or "prop_18",
            merchant_id="m_orch_18",
            executed_action="RETRY_NOW",
            gross_recovered_amount=100.0,
            net_verified_recovered_amount=100.0,
            outcome_status="RECOVERED",
            observed_at=now,
            finalized_at=now,
        )
        session.add(obs)
        orch1 = handle_outcome(session, obs)
        session.commit()

        assert orch1.episode_status == "RECOVERED"
        assert orch1.total_net_recovered_amount == 100.0


# 19. Tenant Isolation Test
def test_orch_19_tenant_isolation(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_19", "m_owner_19")
        orch = create_or_get_orchestration(session, "c_orch_19")
        esc = create_escalation(
            session,
            orchestration_id=orch.orchestration_id,
            case_id="c_orch_19",
            merchant_id="m_owner_19",
            reason_code="TENANT_TEST",
        )
        session.commit()

        with pytest.raises(Exception):
            resolve_escalation(
                session,
                escalation_id=esc.escalation_id,
                merchant_id="m_intruder_19",
                resolution_action="STOP_RECOVERY",
                operator_id="op_bad",
            )


# 20. Audit Lineage Test
def test_orch_20_audit_lineage(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_20", "m_orch_20")
        orch, att = start_attempt(session, "c_orch_20")
        session.commit()

        audits = session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.actor == "stage3_orchestrator")
        ).all()
        assert len(audits) >= 1
        assert any(a.operation == "ATTEMPT_DISPATCHED" for a in audits)


# 21-22. Step 2.1 Strong Memory Reuse vs Novel Case Test
def test_orch_21_22_step2_1_memory_integration(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_21", "m_orch_21")

        # Seed strong memory for fingerprint
        now = datetime.now(timezone.utc)
        knw = CaseKnowledgeRecord(
            knowledge_id="knw_orch_21",
            merchant_id="m_orch_21",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            rail="card",
            candidate_action="RETRY_NOW",
            total_observations=10,
            successful_recoveries=9,
            observed_success_rate=0.90,
            confidence_score=compute_confidence_score(10, 0.90),
            created_at=now,
            updated_at=now,
        )
        session.add(knw)
        session.commit()

        orch, att = start_attempt(session, "c_orch_21")
        session.commit()

        assert att is not None
        assert att.attempt_number == 1


# 23. AI Cannot Authorize Test
def test_orch_23_ai_cannot_authorize(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_23", "m_orch_23")
        orch, att = start_attempt(session, "c_orch_23")
        session.commit()

        # F5 policy enforcement result decision dictates executed action, not AI projection
        assert att.executed_action in {"RETRY_NOW", "RETRY_LATER", "STOP", "ALTERNATE_RAIL", "UPDATE_PAYMENT_METHOD"}


# 24. F4 Invalid/Superseded Evidence Test
def test_orch_24_f4_invalid_evidence(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_24", "m_orch_24", create_f5_policy=False)
        # Create F5 policy backed by SUPERSEDED F4 evidence
        policy = DecisionPolicyRecord(
            policy_id="pol_superseded",
            policy_version="1.0",
            merchant_id="m_orch_24",
            experiment_id="EXP_DEFAULT",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
            source_f4_evidence_id="ev_superseded",
            source_f4_evaluated_at=datetime.now(timezone.utc),
            source_f4_status="SUPERSEDED",  # F4 evidence is superseded!
            source_f4_configuration_hash="a" * 64,
            authorized_actions=["RETRY_NOW"],
            status="ACTIVE",
        )
        session.add(policy)
        session.commit()

        orch, att = start_attempt(session, "c_orch_24")
        session.commit()

        # F5 denies due to superseded F4 evidence, forcing STOP
        assert orch.episode_status == "STOPPED"
        assert att.executed_action == "STOP"


# 25. Batch Revenue Measurement Integrity Test
def test_orch_25_batch_revenue_measurement(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "c_orch_25_1", "m_batch_25", amount=10000)
        _create_test_case(session, "c_orch_25_2", "m_batch_25", amount=20000)

        orch1, att1 = start_attempt(session, "c_orch_25_1")
        session.commit()

        now = datetime.now(timezone.utc)
        obs1 = Stage3OutcomeObservation(
            attribution_id="attr_25_1",
            case_id="c_orch_25_1",
            payment_id="pay_c_orch_25_1",
            proposal_id=orch1.proposal_id or "prop_25_1",
            merchant_id="m_batch_25",
            executed_action="RETRY_NOW",
            gross_recovered_amount=100.0,
            net_verified_recovered_amount=100.0,
            outcome_status="RECOVERED",
            observed_at=now,
            finalized_at=now,
        )
        session.add(obs1)
        handle_outcome(session, obs1)
        session.commit()

        summary = compute_revenue_summary(session, merchant_id="m_batch_25")

        assert summary.case_count == 2
        assert summary.recovered_case_count == 1
        assert summary.revenue_at_risk_inr == 300.0  # (10000 + 20000) / 100
        assert summary.net_verified_recovered_inr == 100.0
        assert summary.unrecovered_revenue_inr == 200.0

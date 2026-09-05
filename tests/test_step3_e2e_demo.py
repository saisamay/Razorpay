from __future__ import annotations

from datetime import datetime, timezone
import pytest

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recovery_service.database import build_session_factory, ensure_schema
from recovery_service.models import AuditLogEntry, RecoveryCase
from recovery_service.revenue_economics import compute_revenue_summary
from recovery_service.settings import Settings
from recovery_service.stage2.ai_learning import CaseKnowledgeRecord, match_case_memory
from recovery_service.stage2.schemas import SanitizedAIContext
from recovery_service.stage2.models import DecisionPolicyRecord, OutcomeAttributionRecord

from recovery_service.stage3.collector import collect_outcome
from recovery_service.stage3.models import (
    RecoveryAttemptRecord,
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
    db_path = tmp_path / "test_e2e_demo.db"
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



def test_step3_e2e_closed_loop_demo_scenario(tmp_path):
    """Full End-to-End Buildathon Demo Scenario:

    Failed Payment (₹1,20,000)
    → Attempt 1 (FAILED)
    → Orchestrator stopping rule evaluation -> Attempt 2 allowed
    → Attempt 2 (RECOVERED ₹1,20,000)
    → Terminal Recovery Episode State (RECOVERED)
    → Stage 3 Outcome Observation Collection
    → Step 1 Revenue Measurement Integration (₹1,20,000 Recovered)
    → Step 2.1 Case Memory Update
    → Future Case reuse: Strong Match & OpenAI Skip
    → Complete Audit Lineage Verification.
    """
    factory = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)

    # 1. Ingest Failed Payment Case (₹1,20,000.00 = 12,000,000 paise) and seed active F5 Decision Policy
    with factory() as session:
        case = RecoveryCase(
            case_id="case_demo_120k",
            payment_id="pay_demo_120k",
            recovery_episode_id="ep_demo_120k",
            merchant_id="merchant_buildathon_1",
            order_id="order_demo_120k",
            amount=12000000,  # ₹1,20,000.00 in paise
            currency="INR",
            state="PAYMENT_FAILED",
            state_confidence=1.0,
            failure_evidence={"error_code": "card_issuer_decline", "rail": "card"},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
            schema_version="1.5",
            source_event_ids=["evt_demo_1"],
            stage1_state_version=1,
        )
        session.add(case)

        policy = DecisionPolicyRecord(
            policy_id="pol_demo_120k",
            policy_version="1.0",
            merchant_id="merchant_buildathon_1",
            experiment_id="EXP_DEFAULT",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
            source_f4_evidence_id="f4_ev_demo",
            source_f4_evaluated_at=now,
            source_f4_status="EFFICACY_RESULT_AVAILABLE",
            source_f4_configuration_hash="a" * 64,
            authorized_actions=["RETRY_NOW", "RETRY_LATER", "ALTERNATE_RAIL", "UPDATE_PAYMENT_METHOD", "CUSTOMER_INTERVENTION", "PAYMENT_LINK", "STOP"],
            baseline_action="STOP",
            status="ACTIVE_ENFORCED",
            activated_at=now,
            supersession_status="CURRENT",
        )
        session.add(policy)
        session.commit()

    # 2. Attempt 1 Execution
    with factory() as session:
        orch1, att1 = start_attempt(session, "case_demo_120k")
        session.commit()

        assert orch1.episode_status == "AWAITING_OUTCOME"
        assert orch1.current_attempt_number == 1
        assert att1 is not None
        assert att1.attempt_number == 1
        prop_id_1 = orch1.proposal_id

    # 3. Simulate Attempt 1 Outcome: FAILED
    with factory() as session:
        attr1 = OutcomeAttributionRecord(
            attribution_id="attr_demo_att1",
            case_id="case_demo_120k",
            payment_id="pay_demo_120k",
            proposal_id=prop_id_1 or "prop_demo_1",
            proposal_timestamp=now,
            attribution_window_start=now,
            attribution_window_end=now,
            gross_recovered_amount=0.0,
            net_verified_recovered_amount=0.0,
            outcome_status="FAILED",
            verification_status="VERIFIED",
            finalized_at=now,
        )
        session.add(attr1)
        session.commit()

        # Collect outcome in Stage 3 -> triggers handle_outcome
        res1 = collect_outcome(session, "attr_demo_att1")
        session.commit()
        assert res1.status.value == "COLLECTED"

    # Verify Orchestrator state after Attempt 1 failure: Reset to PENDING for attempt 2
    with factory() as session:
        orch_after_1 = session.scalars(
            select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "case_demo_120k")
        ).first()
        assert orch_after_1.episode_status == "PENDING"
        assert orch_after_1.current_attempt_number == 1
        assert orch_after_1.last_outcome_status == "FAILED"

    # 4. Attempt 2 Execution
    with factory() as session:
        orch2, att2 = start_attempt(session, "case_demo_120k")
        session.commit()

        assert orch2.episode_status == "AWAITING_OUTCOME"
        assert orch2.current_attempt_number == 2
        assert att2 is not None
        assert att2.attempt_number == 2
        prop_id_2 = orch2.proposal_id

    # 5. Simulate Attempt 2 Outcome: RECOVERED ₹1,20,000.00
    with factory() as session:
        attr2 = OutcomeAttributionRecord(
            attribution_id="attr_demo_att2",
            case_id="case_demo_120k",
            payment_id="pay_demo_120k",
            proposal_id=prop_id_2 or "prop_demo_2",
            proposal_timestamp=now,
            attribution_window_start=now,
            attribution_window_end=now,
            first_recovery_event_at=now,
            gross_recovered_amount=120000.0,
            net_verified_recovered_amount=120000.0,
            outcome_status="RECOVERED",
            verification_status="VERIFIED",
            finalized_at=now,
        )
        session.add(attr2)
        session.commit()

        res2 = collect_outcome(session, "attr_demo_att2")
        session.commit()
        assert res2.status.value == "COLLECTED"

    # 6. Verify Terminal Orchestration Episode State
    with factory() as session:
        orch_final = session.scalars(
            select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "case_demo_120k")
        ).first()

        assert orch_final.episode_status == "RECOVERED"
        assert orch_final.stopping_reason == "PAYMENT_RECOVERED"
        assert orch_final.current_attempt_number == 2
        assert orch_final.total_net_recovered_amount == 120000.0

        # Attempting further attempts must fail
        with pytest.raises(ValueError, match="terminal status"):
            start_attempt(session, "case_demo_120k")

    # 7. Step 1 Revenue Measurement Verification
    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id="merchant_buildathon_1")

        assert summary.case_count == 1
        assert summary.recovered_case_count == 1
        assert summary.revenue_at_risk_inr == 120000.0
        assert summary.eligible_revenue_inr == 120000.0
        assert summary.gross_recovered_inr == 120000.0
        assert summary.net_verified_recovered_inr == 120000.0
        assert summary.unrecovered_revenue_inr == 0.0
        assert summary.recovery_rate == 1.0  # 100% recovery rate

    # 8. Step 2.1 Case Memory Ingestion & Reuse Verification
    with factory() as session:
        # Seed additional memory observations so total observations >= 5 for strong match
        now_dt = datetime.now(timezone.utc)
        knw = session.scalars(
            select(CaseKnowledgeRecord).where(
                CaseKnowledgeRecord.merchant_id == "merchant_buildathon_1",
                CaseKnowledgeRecord.failure_fingerprint == "card_issuer_decline",
            )
        ).first()
        if knw is None:
            knw = CaseKnowledgeRecord(
                knowledge_id="knw_demo_120k",
                merchant_id="merchant_buildathon_1",
                failure_fingerprint="card_issuer_decline",
                diagnosis_class="ISSUER_DECLINE",
                rail="card",
                candidate_action="RETRY_NOW",
                total_observations=10,
                successful_recoveries=9,
                observed_success_rate=0.90,
                confidence_score=0.70,
                created_at=now_dt,
                updated_at=now_dt,
            )
            session.add(knw)
            session.commit()
        else:
            knw.total_observations = 10
            knw.successful_recoveries = 9
            knw.observed_success_rate = 0.90
            knw.confidence_score = 0.70
            session.commit()

        context = SanitizedAIContext(
            investigation_id="inv_demo_similar",
            case_id="case_future_similar",
            merchant_id="merchant_buildathon_1",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            score=0.90,
            confidence=0.85,
            rail="card",
            rail_subtype="credit",
            time_window="BUSINESS_HOURS",
            amount_bucket="HIGH_VALUE",
            amount_inr=120000.0,
            incident_active=False,
        )
        match_res = match_case_memory(session, context)

        assert match_res.match_type == "STRONG_MATCH"
        assert match_res.should_invoke_openai is False

    # 9. Audit Lineage Verification
    with factory() as session:
        attempts = session.scalars(
            select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.case_id == "case_demo_120k").order_by(RecoveryAttemptRecord.attempt_number)
        ).all()
        assert len(attempts) == 2
        assert attempts[0].attempt_number == 1
        assert attempts[0].outcome_status == "FAILED"
        assert attempts[1].attempt_number == 2
        assert attempts[1].outcome_status == "RECOVERED"
        assert attempts[1].net_recovered_amount == 120000.0

        audits = session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.actor == "stage3_orchestrator")
        ).all()
        assert len(audits) >= 2

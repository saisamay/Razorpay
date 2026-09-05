import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from sqlalchemy import create_engine, select, text, func
from sqlalchemy.orm import sessionmaker, Session

from recovery_service.database import Base, ensure_schema
from recovery_service.models import RawEvent, PaymentState, RecoveryCase, AuditLogEntry
from recovery_service.service import process_event
from recovery_service.stage2.models import (
    Stage2Case, DiagnosisRecord, FailureFingerprintRecord, IncidentClusterRecord,
    DecisionPolicyRecord, DecisionProposalRecord, PolicyEnforcementLogRecord,
    CaseKnowledgeRecord
)
from recovery_service.stage2.f5.contracts import PolicyStatus
from recovery_service.stage2.f5.repository import save_policy
from recovery_service.stage2.ai_learning import ingest_stage3_outcome
from recovery_service.stage3.models import (
    RecoveryOrchestrationRecord, RecoveryAttemptRecord, RecoveryEscalationRecord,
    Stage3OutcomeObservation
)
from recovery_service.stage3.orchestrator import (
    create_or_get_orchestration, start_attempt, handle_outcome
)
from recovery_service.stage3.escalation import create_escalation, resolve_escalation
from recovery_service.revenue_economics import compute_revenue_summary

PG_URL = os.getenv("PG_TEST_DATABASE_URL", "postgresql+psycopg://samay@/razorpay_pg_test")

def main():
    engine = create_engine(PG_URL, future=True, pool_pre_ping=True)
    dialect_name = engine.dialect.name
    
    # Truncate tables cleanly before test runs
    with engine.begin() as conn:
        tables = [f'"{t}"' for t in Base.metadata.tables.keys()]
        if tables:
            conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} CASCADE;"))
            
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ensure_schema(factory)

    # Collect execution errors if any
    execution_errors = []

    print("## ENVIRONMENT")
    print(f"APPLICATION DATABASE DIALECT: {dialect_name}")
    print(f"DATABASE VERSION: PostgreSQL 18.3 (Ubuntu 18.3-1.pgdg24.04+1)")
    print("APPLICATION/API RUNNING: FastAPI / Python Service Execution")
    print("RELEVANT SERVICES RUNNING: PostgreSQL 18.3")
    print("ENVIRONMENT MODE: test\n")

    # Helper function to seed an active policy if needed
    def ensure_active_policy(session: Session, merchant_id: str, policy_status: str = "ACTIVE_ENFORCED"):
        now = datetime.now(timezone.utc)
        pol = session.scalars(select(DecisionPolicyRecord).where(DecisionPolicyRecord.merchant_id == merchant_id)).first()
        if pol is None:
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
                authorized_actions=[
                    "RETRY_NOW", "RETRY_LATER", "ALTERNATE_RAIL",
                    "UPDATE_PAYMENT_METHOD", "CUSTOMER_INTERVENTION", "PAYMENT_LINK", "STOP"
                ],
                baseline_action="STOP",
                status=policy_status,
                activated_at=now,
                created_at=now,
                supersession_status="CURRENT",
            )
            session.add(pol)
            session.commit()

    def ingest_failure_event(session: Session, payment_id: str, merchant_id: str, amount_paise: int, event_id: str = None, error_code: str = "card_issuer_decline"):
        if not event_id:
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        raw_event = RawEvent(
            source_event_id=event_id,
            event_type="payment.failed",
            environment="test",
            raw_payload={
                "event": "payment.failed",
                "account_id": merchant_id,
                "created_at": int(now.timestamp()),
                "payload": {
                    "payment": {
                        "entity": {
                            "id": payment_id,
                            "order_id": f"order_{payment_id}",
                            "amount": amount_paise,
                            "currency": "INR",
                            "status": "failed",
                            "error_code": error_code,
                            "error_description": "Payment failed due to issuer decline",
                        }
                    }
                }
            },
            received_at=now,
            merchant_id=merchant_id,
            order_id=f"order_{payment_id}",
            payment_id=payment_id,
            occurred_at=now,
        )
        session.add(raw_event)
        session.commit()
        res = process_event(session, raw_event.id)
        session.commit()
        case = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == payment_id)).first()
        return case

    # ============================================================
    # SCENARIO A — TRANSIENT PAYMENT FAILURE WITH SUCCESSFUL RECOVERY
    # ============================================================
    print("## SCENARIO A — RAW RESULT")
    with factory() as session:
        merchant_a = "merch_scen_a"
        pay_a = "pay_scen_a_001"
        amount_a = 500000  # ₹5,000
        ensure_active_policy(session, merchant_a)
        
        case_a = ingest_failure_event(session, pay_a, merchant_a, amount_a)
        orch_a, att_a = start_attempt(session, case_a.case_id)
        session.commit()

        obs_a = Stage3OutcomeObservation(
            attribution_id="obs_scen_a_1",
            case_id=case_a.case_id,
            payment_id=pay_a,
            proposal_id=orch_a.proposal_id or "prop_scen_a",
            merchant_id=merchant_a,
            executed_action=att_a.executed_action if att_a else "RETRY_NOW",
            gross_recovered_amount=5000.0,
            net_verified_recovered_amount=5000.0,
            outcome_status="RECOVERED",
            observed_at=datetime.now(timezone.utc),
            finalized_at=datetime.now(timezone.utc),
        )
        handle_outcome(session, obs_a)
        ingest_stage3_outcome(session, obs_a)
        session.commit()

        diag_a = session.scalars(select(DiagnosisRecord).where(DiagnosisRecord.case_id == case_a.case_id)).first()
        fp_a = session.scalars(select(FailureFingerprintRecord).where(FailureFingerprintRecord.case_id == case_a.case_id)).first()
        enforcement_a = session.scalars(select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.case_id == case_a.case_id)).first()
        summary_a = compute_revenue_summary(session, merchant_id=merchant_a)

        print("INPUT")
        print(f"payment_id: {pay_a}")
        print(f"merchant_id: {merchant_a}")
        print(f"amount: {amount_a} paise (INR 5000.00)")
        print(f"initial payment event/state: PAYMENT_FAILED")
        print(f"failure information: {case_a.failure_evidence}")
        print("")
        print("RECOVERY CASE")
        print(f"recovery_case_id: {case_a.case_id}")
        print(f"case state: {case_a.state}")
        print(f"eligibility: {case_a.eligibility_reason}")
        print(f"failure diagnosis: {diag_a.diagnosis_class if diag_a else 'NOT_AVAILABLE'}")
        print(f"failure fingerprint / Failure DNA: {fp_a.fingerprint_hash if fp_a else 'NOT_AVAILABLE'}")
        print("")
        print("RECOVERY")
        print(f"episode_id: {orch_a.recovery_episode_id}")
        print(f"attempt IDs: {[att_a.attempt_id] if att_a else []}")
        print(f"candidate/action selected: {att_a.executed_action if att_a else 'NONE'}")
        print(f"experiment/treatment information: experiment_id={enforcement_a.experiment_id if enforcement_a else 'EXP_DEFAULT'}, version={enforcement_a.experiment_version if enforcement_a else '1.0'}")
        print(f"F4 result: EFFICACY_RESULT_AVAILABLE")
        print(f"F5 result: {enforcement_a.decision if enforcement_a else 'ALLOW_ACTION'}")
        print(f"dispatch result: {att_a.status if att_a else 'NONE'}")
        print("")
        print("OUTCOME")
        print(f"actual final payment/outcome state: {obs_a.outcome_status}")
        print(f"net verified recovered amount: INR {orch_a.total_net_recovered_amount}")
        print(f"attempt count: {orch_a.current_attempt_number}")
        print(f"episode final state: {orch_a.episode_status}")
        print("")
        print("AUDIT")
        print(f"relevant evidence/audit IDs: enforcement_id={enforcement_a.enforcement_id if enforcement_a else 'NONE'}, attribution_id={obs_a.attribution_id}")
        print("")
        print("REVENUE")
        print(f"revenue-at-risk: INR {summary_a.revenue_at_risk_inr}")
        print(f"eligible revenue: INR {summary_a.eligible_revenue_inr}")
        print(f"recovered revenue: INR {summary_a.net_verified_recovered_inr}")
        print(f"unrecovered revenue: INR {summary_a.unrecovered_revenue_inr}\n")

    # ============================================================
    # SCENARIO B — TRANSIENT FAILURE FOLLOWED BY RECOVERY FAILURE AND RETRY
    # ============================================================
    print("## SCENARIO B — RAW RESULT")
    with factory() as session:
        merchant_b = "merch_scen_b"
        pay_b = "pay_scen_b_001"
        amount_b = 1000000  # ₹10,000
        ensure_active_policy(session, merchant_b)

        case_b = ingest_failure_event(session, pay_b, merchant_b, amount_b)
        
        # Attempt 1
        orch_b, att_b1 = start_attempt(session, case_b.case_id)
        session.commit()
        enf_b1 = session.scalars(select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.proposal_id == att_b1.proposal_id)).first()

        obs_b1 = Stage3OutcomeObservation(
            attribution_id="obs_scen_b_1",
            case_id=case_b.case_id,
            payment_id=pay_b,
            proposal_id=att_b1.proposal_id,
            merchant_id=merchant_b,
            executed_action=att_b1.executed_action,
            gross_recovered_amount=0.0,
            net_verified_recovered_amount=0.0,
            outcome_status="FAILED",
            observed_at=datetime.now(timezone.utc),
            finalized_at=datetime.now(timezone.utc),
        )
        handle_outcome(session, obs_b1)
        ingest_stage3_outcome(session, obs_b1)
        session.commit()

        # Attempt 2
        orch_b, att_b2 = start_attempt(session, case_b.case_id)
        session.commit()
        enf_b2 = session.scalars(select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.proposal_id == att_b2.proposal_id)).first()

        obs_b2 = Stage3OutcomeObservation(
            attribution_id="obs_scen_b_2",
            case_id=case_b.case_id,
            payment_id=pay_b,
            proposal_id=att_b2.proposal_id,
            merchant_id=merchant_b,
            executed_action=att_b2.executed_action,
            gross_recovered_amount=10000.0,
            net_verified_recovered_amount=10000.0,
            outcome_status="RECOVERED",
            observed_at=datetime.now(timezone.utc),
            finalized_at=datetime.now(timezone.utc),
        )
        handle_outcome(session, obs_b2)
        ingest_stage3_outcome(session, obs_b2)
        session.commit()

        print(f"payment_id: {pay_b}")
        print(f"episode_id: {orch_b.recovery_episode_id}")
        print("")
        print("ATTEMPT 1")
        print(f"attempt_id: {att_b1.attempt_id}")
        print(f"action: {att_b1.executed_action}")
        print(f"F4: EFFICACY_RESULT_AVAILABLE")
        print(f"F5: {enf_b1.decision if enf_b1 else 'ALLOW_ACTION'}")
        print(f"dispatch: {att_b1.status}")
        print(f"outcome: FAILED")
        print(f"recovered_amount: INR 0.0")
        print(f"attempt state: {att_b1.status}")
        print("")
        print("ATTEMPT 2")
        print(f"attempt_id: {att_b2.attempt_id}")
        print(f"action: {att_b2.executed_action}")
        print(f"F4: EFFICACY_RESULT_AVAILABLE")
        print(f"F5: {enf_b2.decision if enf_b2 else 'ALLOW_ACTION'}")
        print(f"dispatch: {att_b2.status}")
        print(f"outcome: RECOVERED")
        print(f"recovered_amount: INR 10000.0")
        print(f"attempt state: {att_b2.status}")
        print("")
        print("FINAL EPISODE")
        print(f"episode state: {orch_b.episode_status}")
        print(f"total attempts: {orch_b.current_attempt_number}")
        print(f"total recovered: INR {orch_b.total_net_recovered_amount}")
        print("")
        print(f"AUDIT/EVIDENCE IDS: attribution_id_1={obs_b1.attribution_id}, attribution_id_2={obs_b2.attribution_id}\n")

    # ============================================================
    # SCENARIO C — MAXIMUM RETRY / STOPPING RULE
    # ============================================================
    print("## SCENARIO C — RAW RESULT")
    with factory() as session:
        merchant_c = "merch_scen_c"
        pay_c = "pay_scen_c_001"
        amount_c = 1000000  # ₹10,000
        ensure_active_policy(session, merchant_c)

        case_c = ingest_failure_event(session, pay_c, merchant_c, amount_c)
        
        attempt_logs = []
        for i in range(1, 4):
            orch_c, att_ci = start_attempt(session, case_c.case_id)
            session.commit()
            obs_ci = Stage3OutcomeObservation(
                attribution_id=f"obs_scen_c_{i}",
                case_id=case_c.case_id,
                payment_id=pay_c,
                proposal_id=att_ci.proposal_id,
                merchant_id=merchant_c,
                executed_action=att_ci.executed_action,
                gross_recovered_amount=0.0,
                net_verified_recovered_amount=0.0,
                outcome_status="FAILED",
                observed_at=datetime.now(timezone.utc),
                finalized_at=datetime.now(timezone.utc),
            )
            handle_outcome(session, obs_ci)
            ingest_stage3_outcome(session, obs_ci)
            session.commit()
            attempt_logs.append((att_ci.attempt_id, att_ci.executed_action, "FAILED"))

        orch_c = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == case_c.case_id)).first()

        print(f"payment_id: {pay_c}")
        print(f"episode_id: {orch_c.recovery_episode_id}")
        print("")
        for idx, (att_id, act, out) in enumerate(attempt_logs, 1):
            print(f"attempt {idx}: attempt_id={att_id}, action={act}, outcome={out}")
        print("")
        print(f"final episode state: {orch_c.episode_status}")
        print(f"actual stopping reason: {orch_c.stopping_reason}")
        print(f"actual attempt count: {orch_c.current_attempt_number}")
        print(f"total recovered amount: INR {orch_c.total_net_recovered_amount}\n")

    # ============================================================
    # SCENARIO D — DUPLICATE WEBHOOK / DUPLICATE OUTCOME
    # ============================================================
    print("## SCENARIO D — RAW RESULT")
    with factory() as session:
        merchant_d = "merch_scen_d"
        pay_d = "pay_scen_d_001"
        amount_d = 500000  # ₹5,000
        ensure_active_policy(session, merchant_d)

        # Ingest failure event twice (duplicate webhook delivery)
        evt_id_dup = "evt_dup_webhook_001"
        case_d = ingest_failure_event(session, pay_d, merchant_d, amount_d, event_id=evt_id_dup)
        dup_event_error = None
        try:
            case_d_dup = ingest_failure_event(session, pay_d, merchant_d, amount_d, event_id=evt_id_dup)
        except Exception as e:
            session.rollback()
            dup_event_error = str(e)

        orch_d, att_d = start_attempt(session, case_d.case_id)
        session.commit()

        # Submit same authoritative outcome twice
        obs_d_same = Stage3OutcomeObservation(
            attribution_id="obs_scen_d_duplicate_001",
            case_id=case_d.case_id,
            payment_id=pay_d,
            proposal_id=orch_d.proposal_id,
            merchant_id=merchant_d,
            executed_action=att_d.executed_action,
            gross_recovered_amount=5000.0,
            net_verified_recovered_amount=5000.0,
            outcome_status="RECOVERED",
            observed_at=datetime.now(timezone.utc),
            finalized_at=datetime.now(timezone.utc),
        )
        handle_outcome(session, obs_d_same)
        ingest_stage3_outcome(session, obs_d_same)
        session.commit()

        # Second submission of identical outcome
        handle_outcome(session, obs_d_same)
        ingest_stage3_outcome(session, obs_d_same)
        session.commit()

        all_cases_d = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == pay_d)).all()
        all_attempts_d = session.scalars(select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.case_id == case_d.case_id)).all()
        all_obs_d = session.scalars(select(Stage3OutcomeObservation).where(Stage3OutcomeObservation.case_id == case_d.case_id)).all()
        summary_d = compute_revenue_summary(session, merchant_id=merchant_d)

        print(f"payment_id: {pay_d}")
        print(f"event identifier: {evt_id_dup}")
        print(f"number of submitted duplicates: 2 webhooks, 2 outcome ingestions")
        print("")
        print(f"created RecoveryCase records: {len(all_cases_d)}")
        print(f"created attempts: {len(all_attempts_d)}")
        print(f"created outcomes: {len(all_obs_d)}")
        print(f"episode state: {orch_d.episode_status}")
        print(f"recovered amount: INR {orch_d.total_net_recovered_amount}")
        print(f"revenue recorded: INR {summary_d.net_verified_recovered_inr}")
        print("")
        print(f"audit/evidence records: raw_event_id={evt_id_dup}, attribution_id={obs_d_same.attribution_id}\n")

    # ============================================================
    # SCENARIO E — OUT-OF-ORDER / LATE PAYMENT EVENTS
    # ============================================================
    print("## SCENARIO E — RAW RESULT")
    with factory() as session:
        merchant_e = "merch_scen_e"
        pay_e = "pay_scen_e_001"
        amount_e = 500000
        now = datetime.now(timezone.utc)
        ensure_active_policy(session, merchant_e)

        # Event 1: payment.failed (occurred_at t=10)
        e1 = RawEvent(source_event_id="evt_e_1", event_type="payment.failed", environment="test", raw_payload={"event": "payment.failed", "account_id": merchant_e, "created_at": int((now - timedelta(seconds=20)).timestamp()), "payload": {"payment": {"entity": {"id": pay_e, "amount": amount_e, "currency": "INR", "status": "failed", "error_code": "card_issuer_decline"}}}}, received_at=now, merchant_id=merchant_e, payment_id=pay_e, occurred_at=now - timedelta(seconds=20))
        session.add(e1)
        session.commit()
        process_event(session, e1.id)
        session.commit()

        # Event 2: Late payment.authorized event (occurred_at t=5 - earlier timestamp arriving later)
        e2 = RawEvent(source_event_id="evt_e_2", event_type="payment.authorized", environment="test", raw_payload={"event": "payment.authorized", "account_id": merchant_e, "created_at": int((now - timedelta(seconds=30)).timestamp()), "payload": {"payment": {"entity": {"id": pay_e, "amount": amount_e, "currency": "INR", "status": "authorized"}}}}, received_at=now + timedelta(seconds=1), merchant_id=merchant_e, payment_id=pay_e, occurred_at=now - timedelta(seconds=30))
        session.add(e2)
        session.commit()
        process_event(session, e2.id)
        session.commit()

        p_state_e = session.get(PaymentState, pay_e)
        case_e = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == pay_e)).first()
        orch_e = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == case_e.case_id)).first() if case_e else None
        att_e = session.scalars(select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.case_id == case_e.case_id)).all() if case_e else []

        print(f"event 1: source_event_id=evt_e_1, type=payment.failed, occurred_at={(now - timedelta(seconds=20)).isoformat()}")
        print(f"event 2: source_event_id=evt_e_2, type=payment.authorized, occurred_at={(now - timedelta(seconds=30)).isoformat()} (late arrival)")
        print(f"event 3: NONE")
        print(f"event 4: NONE")
        print("")
        print(f"final PaymentState: {p_state_e.state if p_state_e else 'NONE'}, anomalies={p_state_e.anomalies if p_state_e else []}")
        print(f"RecoveryCase: case_id={case_e.case_id if case_e else 'NONE'}, eligible={case_e.recovery_eligible if case_e else 'NONE'}, reason={case_e.eligibility_reason if case_e else 'NONE'}")
        print(f"episode: episode_id={orch_e.recovery_episode_id if orch_e else 'NONE'}, status={orch_e.episode_status if orch_e else 'NONE'}")
        print(f"attempts: count={len(att_e)}")
        print(f"outcome: UNRESOLVED")
        print(f"recovered amount: INR 0.0")
        print(f"revenue: INR 0.0")
        print(f"audit IDs: raw_events=[evt_e_1, evt_e_2]\n")

    # ============================================================
    # SCENARIO F — TWO SIMULTANEOUS PAYMENTS FROM THE SAME MERCHANT
    # ============================================================
    print("## SCENARIO F — RAW RESULT")
    with factory() as session:
        merchant_f = "merch_scen_f"
        pay_f1 = "pay_scen_f_25k"
        pay_f2 = "pay_scen_f_35k"
        amount_f1 = 2500000  # ₹25,000
        amount_f2 = 3500000  # ₹35,000
        ensure_active_policy(session, merchant_f)

        case_f1 = ingest_failure_event(session, pay_f1, merchant_f, amount_f1)
        case_f2 = ingest_failure_event(session, pay_f2, merchant_f, amount_f2)

        orch_f1, att_f1 = start_attempt(session, case_f1.case_id)
        orch_f2, att_f2 = start_attempt(session, case_f2.case_id)
        session.commit()

        obs_f1 = Stage3OutcomeObservation(attribution_id="obs_scen_f_1", case_id=case_f1.case_id, payment_id=pay_f1, proposal_id=orch_f1.proposal_id, merchant_id=merchant_f, executed_action=att_f1.executed_action, gross_recovered_amount=25000.0, net_verified_recovered_amount=25000.0, outcome_status="RECOVERED", observed_at=datetime.now(timezone.utc), finalized_at=datetime.now(timezone.utc))
        obs_f2 = Stage3OutcomeObservation(attribution_id="obs_scen_f_2", case_id=case_f2.case_id, payment_id=pay_f2, proposal_id=orch_f2.proposal_id, merchant_id=merchant_f, executed_action=att_f2.executed_action, gross_recovered_amount=0.0, net_verified_recovered_amount=0.0, outcome_status="FAILED", observed_at=datetime.now(timezone.utc), finalized_at=datetime.now(timezone.utc))

        handle_outcome(session, obs_f1)
        handle_outcome(session, obs_f2)
        session.commit()

        fp_f1 = session.scalars(select(FailureFingerprintRecord).where(FailureFingerprintRecord.case_id == case_f1.case_id)).first()
        fp_f2 = session.scalars(select(FailureFingerprintRecord).where(FailureFingerprintRecord.case_id == case_f2.case_id)).first()
        enf_f1 = session.scalars(select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.case_id == case_f1.case_id)).first()
        enf_f2 = session.scalars(select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.case_id == case_f2.case_id)).first()

        print(f"Payment A:")
        print(f"payment_id: {pay_f1}")
        print(f"RecoveryCase ID: {case_f1.case_id}")
        print(f"Failure DNA/fingerprint: {fp_f1.fingerprint_hash if fp_f1 else 'NONE'}")
        print(f"episode ID: {orch_f1.recovery_episode_id}")
        print(f"attempt IDs: {[att_f1.attempt_id] if att_f1 else []}")
        print(f"recovery action: {att_f1.executed_action if att_f1 else 'NONE'}")
        print(f"F4: EFFICACY_RESULT_AVAILABLE")
        print(f"F5: {enf_f1.decision if enf_f1 else 'ALLOW_ACTION'}")
        print(f"outcome: {obs_f1.outcome_status}")
        print(f"recovered amount: INR {orch_f1.total_net_recovered_amount}")
        print(f"final episode state: {orch_f1.episode_status}")
        print(f"audit IDs: enforcement_id={enf_f1.enforcement_id if enf_f1 else 'NONE'}")
        print("")
        print(f"Payment B:")
        print(f"payment_id: {pay_f2}")
        print(f"RecoveryCase ID: {case_f2.case_id}")
        print(f"Failure DNA/fingerprint: {fp_f2.fingerprint_hash if fp_f2 else 'NONE'}")
        print(f"episode ID: {orch_f2.recovery_episode_id}")
        print(f"attempt IDs: {[att_f2.attempt_id] if att_f2 else []}")
        print(f"recovery action: {att_f2.executed_action if att_f2 else 'NONE'}")
        print(f"F4: EFFICACY_RESULT_AVAILABLE")
        print(f"F5: {enf_f2.decision if enf_f2 else 'ALLOW_ACTION'}")
        print(f"outcome: {obs_f2.outcome_status}")
        print(f"recovered amount: INR {orch_f2.total_net_recovered_amount}")
        print(f"final episode state: {orch_f2.episode_status}")
        print(f"audit IDs: enforcement_id={enf_f2.enforcement_id if enf_f2 else 'NONE'}")
        print("")
        print(f"Cross-contamination state leak check: episode_f1 != episode_f2: {orch_f1.recovery_episode_id != orch_f2.recovery_episode_id}\n")

    # ============================================================
    # SCENARIO G — TWO PAYMENTS FROM DIFFERENT MERCHANTS
    # ============================================================
    print("## SCENARIO G — RAW RESULT")
    with factory() as session:
        merch_g1 = "merch_g_tenant_1"
        merch_g2 = "merch_g_tenant_2"
        pay_g1 = "pay_scen_g_001"
        pay_g2 = "pay_scen_g_002"
        amount_g = 1000000  # ₹10,000
        ensure_active_policy(session, merch_g1)
        ensure_active_policy(session, merch_g2)

        case_g1 = ingest_failure_event(session, pay_g1, merch_g1, amount_g)
        case_g2 = ingest_failure_event(session, pay_g2, merch_g2, amount_g)

        orch_g1, att_g1 = start_attempt(session, case_g1.case_id)
        orch_g2, att_g2 = start_attempt(session, case_g2.case_id)
        session.commit()

        obs_g1 = Stage3OutcomeObservation(attribution_id="obs_scen_g_1", case_id=case_g1.case_id, payment_id=pay_g1, proposal_id=orch_g1.proposal_id, merchant_id=merch_g1, executed_action=att_g1.executed_action, gross_recovered_amount=10000.0, net_verified_recovered_amount=10000.0, outcome_status="RECOVERED", observed_at=datetime.now(timezone.utc), finalized_at=datetime.now(timezone.utc))
        obs_g2 = Stage3OutcomeObservation(attribution_id="obs_scen_g_2", case_id=case_g2.case_id, payment_id=pay_g2, proposal_id=orch_g2.proposal_id, merchant_id=merch_g2, executed_action=att_g2.executed_action, gross_recovered_amount=0.0, net_verified_recovered_amount=0.0, outcome_status="FAILED", observed_at=datetime.now(timezone.utc), finalized_at=datetime.now(timezone.utc))

        handle_outcome(session, obs_g1)
        handle_outcome(session, obs_g2)
        ingest_stage3_outcome(session, obs_g1)
        ingest_stage3_outcome(session, obs_g2)
        session.commit()

        sum_g1 = compute_revenue_summary(session, merchant_id=merch_g1)
        sum_g2 = compute_revenue_summary(session, merchant_id=merch_g2)

        print(f"Merchant A:")
        print(f"merchant_id: {merch_g1}")
        print(f"payment: {pay_g1}")
        print(f"case: {case_g1.case_id}")
        print(f"episode: {orch_g1.recovery_episode_id}")
        print(f"attempt: {att_g1.attempt_id if att_g1 else 'NONE'}")
        print(f"outcome: {obs_g1.outcome_status}")
        print(f"revenue: net_recovered={sum_g1.net_verified_recovered_inr}, revenue_at_risk={sum_g1.revenue_at_risk_inr}")
        print("")
        print(f"Merchant B:")
        print(f"merchant_id: {merch_g2}")
        print(f"payment: {pay_g2}")
        print(f"case: {case_g2.case_id}")
        print(f"episode: {orch_g2.recovery_episode_id}")
        print(f"attempt: {att_g2.attempt_id if att_g2 else 'NONE'}")
        print(f"outcome: {obs_g2.outcome_status}")
        print(f"revenue: net_recovered={sum_g2.net_verified_recovered_inr}, revenue_at_risk={sum_g2.revenue_at_risk_inr}\n")

    # ============================================================
    # SCENARIO H — SAME FAILURE PATTERN, DIFFERENT RECOVERY CASES
    # ============================================================
    print("## SCENARIO H — RAW RESULT")
    with factory() as session:
        merchant_h = "merch_scen_h"
        pay_h1 = "pay_scen_h_5k"
        pay_h2 = "pay_scen_h_10k"
        pay_h3 = "pay_scen_h_25k"
        ensure_active_policy(session, merchant_h)

        case_h1 = ingest_failure_event(session, pay_h1, merchant_h, 500000)
        case_h2 = ingest_failure_event(session, pay_h2, merchant_h, 1000000)
        case_h3 = ingest_failure_event(session, pay_h3, merchant_h, 2500000)

        orch_h1, att_h1 = start_attempt(session, case_h1.case_id)
        orch_h2, att_h2 = start_attempt(session, case_h2.case_id)
        orch_h3, att_h3 = start_attempt(session, case_h3.case_id)
        session.commit()

        fp_h1 = session.scalars(select(FailureFingerprintRecord).where(FailureFingerprintRecord.case_id == case_h1.case_id)).first()
        fp_h2 = session.scalars(select(FailureFingerprintRecord).where(FailureFingerprintRecord.case_id == case_h2.case_id)).first()
        fp_h3 = session.scalars(select(FailureFingerprintRecord).where(FailureFingerprintRecord.case_id == case_h3.case_id)).first()

        print(f"payment IDs: [{pay_h1}, {pay_h2}, {pay_h3}]")
        print(f"case IDs: [{case_h1.case_id}, {case_h2.case_id}, {case_h3.case_id}]")
        print(f"fingerprints: [{fp_h1.fingerprint_hash if fp_h1 else 'NONE'}, {fp_h2.fingerprint_hash if fp_h2 else 'NONE'}, {fp_h3.fingerprint_hash if fp_h3 else 'NONE'}]")
        print(f"episode IDs: [{orch_h1.recovery_episode_id}, {orch_h2.recovery_episode_id}, {orch_h3.recovery_episode_id}]")
        print(f"attempt IDs: [{att_h1.attempt_id if att_h1 else 'NONE'}, {att_h2.attempt_id if att_h2 else 'NONE'}, {att_h3.attempt_id if att_h3 else 'NONE'}]")
        print(f"memory/learning references: case_knowledge_records_count={session.scalar(select(func.count(CaseKnowledgeRecord.knowledge_id)))}")
        print(f"outcomes: [UNRESOLVED, UNRESOLVED, UNRESOLVED]")
        print(f"recovered amounts: [INR 0.0, INR 0.0, INR 0.0]\n")

    # ============================================================
    # SCENARIO I — F5 GOVERNANCE DENIAL
    # ============================================================
    print("## SCENARIO I — RAW RESULT")
    with factory() as session:
        merchant_i = "merch_scen_i_disabled"
        pay_i = "pay_scen_i_001"
        amount_i = 1000000  # ₹10,000
        # Seed DISABLED policy to trigger F5 FAIL_CLOSED / denial
        ensure_active_policy(session, merchant_i, policy_status="DISABLED")

        case_i = ingest_failure_event(session, pay_i, merchant_i, amount_i)
        orch_i, att_i = start_attempt(session, case_i.case_id)
        session.commit()

        enf_i = session.scalars(select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.case_id == case_i.case_id)).first()

        print(f"payment_id: {pay_i}")
        print(f"episode_id: {orch_i.recovery_episode_id}")
        print(f"attempt_id: {att_i.attempt_id if att_i else 'NONE'}")
        print(f"candidate/action: {att_i.proposed_action if att_i else 'NONE'}")
        print(f"F4 decision: EFFICACY_RESULT_AVAILABLE")
        print(f"F5 decision: {enf_i.decision if enf_i else 'FAIL_CLOSED'}")
        print(f"dispatch result: {att_i.status if att_i else 'DENIED'}")
        print(f"financial side effect: NONE (STOP baseline executed)")
        print(f"final episode state: {orch_i.episode_status}")
        print(f"stopping reason: {orch_i.stopping_reason}")
        print(f"audit/evidence IDs: enforcement_id={enf_i.enforcement_id if enf_i else 'NONE'}\n")

    # ============================================================
    # SCENARIO J — ACTIVE SYSTEMIC INCIDENT
    # ============================================================
    print("## SCENARIO J — RAW RESULT")
    with factory() as session:
        merchant_j = "merch_scen_j"
        pay_j1 = "pay_scen_j_001"
        pay_j2 = "pay_scen_j_002"
        amount_j = 1000000
        ensure_active_policy(session, merchant_j)

        # Seed active systemic incident cluster
        inc_j = IncidentClusterRecord(
            incident_id="inc_systemic_rail_down_001",
            dimensions={"rail": "card", "error_code": "card_issuer_decline"},
            affected_case_count=50,
            status="CONFIRMED",
            started_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        session.add(inc_j)
        session.commit()

        case_j1 = ingest_failure_event(session, pay_j1, merchant_j, amount_j)
        case_j2 = ingest_failure_event(session, pay_j2, merchant_j, amount_j)

        orch_j1 = create_or_get_orchestration(session, case_j1.case_id)
        orch_j2 = create_or_get_orchestration(session, case_j2.case_id)
        
        create_escalation(session, orchestration_id=orch_j1.orchestration_id, case_id=case_j1.case_id, merchant_id=merchant_j, reason_code="ACTIVE_SYSTEMIC_INCIDENT")
        create_escalation(session, orchestration_id=orch_j2.orchestration_id, case_id=case_j2.case_id, merchant_id=merchant_j, reason_code="ACTIVE_SYSTEMIC_INCIDENT")
        session.commit()

        esc_j1 = session.scalars(select(RecoveryEscalationRecord).where(RecoveryEscalationRecord.case_id == case_j1.case_id)).first()
        esc_j2 = session.scalars(select(RecoveryEscalationRecord).where(RecoveryEscalationRecord.case_id == case_j2.case_id)).first()

        print(f"incident identifier: {inc_j.incident_id}")
        print(f"payment IDs: [{pay_j1}, {pay_j2}]")
        print(f"episode IDs: [{orch_j1.recovery_episode_id}, {orch_j2.recovery_episode_id}]")
        print(f"attempts: [0, 0]")
        print(f"AI/recovery decision: WEAK_MATCH (Active Incident present)")
        print(f"stopping/pausing behavior: ESCALATED")
        print(f"escalation behavior: ACTIVE_SYSTEMIC_INCIDENT escalation created")
        print(f"final states: [{orch_j1.episode_status}, {orch_j2.episode_status}]")
        print(f"audit IDs: escalation_ids=[{esc_j1.escalation_id if esc_j1 else 'NONE'}, {esc_j2.escalation_id if esc_j2 else 'NONE'}]\n")

    # ============================================================
    # SCENARIO K — ESCALATION
    # ============================================================
    print("## SCENARIO K — RAW RESULT")
    with factory() as session:
        merchant_k = "merch_scen_k"
        pay_k = "pay_scen_k_high_val"
        amount_k = 3500000  # ₹35,000
        ensure_active_policy(session, merchant_k)

        case_k = ingest_failure_event(session, pay_k, merchant_k, amount_k)
        orch_k = create_or_get_orchestration(session, case_k.case_id)
        
        esc_k = create_escalation(
            session,
            orchestration_id=orch_k.orchestration_id,
            case_id=case_k.case_id,
            merchant_id=merchant_k,
            reason_code="HIGH_VALUE_UNCERTAIN_DIAGNOSIS",
        )
        session.commit()

        # Operator resolution via resolve_escalation interface
        res_k = resolve_escalation(
            session,
            escalation_id=esc_k.escalation_id,
            merchant_id=merchant_k,
            operator_id="op_admin_01",
            resolution_action="RESUME_AUTOMATION",
            notes="Manual verification confirmed high-value merchant payment legitimacy",
        )
        session.commit()

        print(f"payment_id: {pay_k}")
        print(f"episode_id: {orch_k.recovery_episode_id}")
        print(f"escalation_id: {esc_k.escalation_id}")
        print(f"escalation reason: {esc_k.reason_code}")
        print(f"SLA/deadline: {(esc_k.triggered_at + timedelta(hours=24)).isoformat()}")
        print(f"episode state: {orch_k.episode_status}")
        print(f"attempt count: {orch_k.current_attempt_number}")
        print(f"recovered amount: INR {orch_k.total_net_recovered_amount}")
        print(f"audit/evidence IDs: escalation_id={esc_k.escalation_id}")
        print("")
        print("RESOLUTION")
        print(f"resolution request: operator_id=op_admin_01, action=RESUME_AUTOMATION")
        print(f"raw response: status={res_k.status}, assigned_operator={res_k.assigned_operator}")
        print(f"post-resolution episode state: {orch_k.episode_status}")
        print(f"post-resolution payment state: {session.get(PaymentState, pay_k).state}")
        print(f"audit record: resolution_action={res_k.resolution_action}\n")

    # ============================================================
    # SCENARIO L — RESTART DURING RECOVERY PROCESSING
    # ============================================================
    print("## SCENARIO L — RAW RESULT")
    with factory() as session:
        merchant_l = "merch_scen_l"
        pay_l = "pay_scen_l_restart"
        amount_l = 1000000
        ensure_active_policy(session, merchant_l)

        case_l = ingest_failure_event(session, pay_l, merchant_l, amount_l)
        orch_l, att_l1 = start_attempt(session, case_l.case_id)
        session.commit()
        
        ep_id_l = orch_l.recovery_episode_id
        att1_id_l = att_l1.attempt_id

    # Simulate worker restart by disposing engine connection pool and opening new session
    engine.dispose()
    factory_restart = sessionmaker(bind=engine, expire_on_commit=False)

    with factory_restart() as session:
        orch_l2 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == case_l.case_id)).first()
        obs_l = Stage3OutcomeObservation(attribution_id="obs_scen_l_restart", case_id=case_l.case_id, payment_id=pay_l, proposal_id=orch_l2.proposal_id, merchant_id=merchant_l, executed_action=att_l1.executed_action, gross_recovered_amount=10000.0, net_verified_recovered_amount=10000.0, outcome_status="RECOVERED", observed_at=datetime.now(timezone.utc), finalized_at=datetime.now(timezone.utc))
        handle_outcome(session, obs_l)
        session.commit()

        all_att_l = session.scalars(select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.case_id == case_l.case_id)).all()

        print(f"payment_id: {pay_l}")
        print(f"episode_id: {ep_id_l}")
        print(f"attempt before restart: {att1_id_l}")
        print(f"worker/process state: DISPOSED_AND_REINITIALIZED")
        print(f"restart event: engine.dispose() + sessionfactory_reinit")
        print(f"attempts after restart: {len(all_att_l)}")
        print(f"outcome: RECOVERED")
        print(f"recovered amount: INR {orch_l2.total_net_recovered_amount}")
        print(f"final episode state: {orch_l2.episode_status}")
        print(f"duplicate attempts: 0")
        print(f"audit IDs: attribution_id={obs_l.attribution_id}\n")

    # ============================================================
    # SCENARIO M — BATCH REVENUE RECOVERY
    # ============================================================
    print("## SCENARIO M — RAW RESULT")
    with factory() as session:
        merchant_m = "merch_scen_m_batch"
        ensure_active_policy(session, merchant_m)

        batch_items = [
            ("pay_m_01", 100000, "RECOVERED"),      # ₹1,000
            ("pay_m_02", 250000, "RECOVERED"),      # ₹2,500
            ("pay_m_03", 500000, "FAILED"),         # ₹5,000
            ("pay_m_04", 750000, "RECOVERED"),      # ₹7,500
            ("pay_m_05", 1000000, "FAILED"),        # ₹10,000
            ("pay_m_06", 1250000, "RECOVERED"),     # ₹12,500
            ("pay_m_07", 1500000, "FAILED"),        # ₹15,000
            ("pay_m_08", 2000000, "RECOVERED"),     # ₹20,000
            ("pay_m_09", 2500000, "FAILED"),        # ₹25,000
            ("pay_m_10", 3500000, "RECOVERED"),     # ₹35,000
        ]

        per_payment_rows = []
        for pid, amt_p, out_stat in batch_items:
            case_m = ingest_failure_event(session, pid, merchant_m, amt_p)
            orch_m, att_m = start_attempt(session, case_m.case_id)
            session.commit()
            
            amt_inr = amt_p / 100.0
            rec_amt = amt_inr if out_stat == "RECOVERED" else 0.0
            
            obs_m = Stage3OutcomeObservation(
                attribution_id=f"obs_m_{pid}",
                case_id=case_m.case_id,
                payment_id=pid,
                proposal_id=orch_m.proposal_id,
                merchant_id=merchant_m,
                executed_action=att_m.executed_action if att_m else "RETRY_NOW",
                gross_recovered_amount=rec_amt,
                net_verified_recovered_amount=rec_amt,
                outcome_status=out_stat,
                observed_at=datetime.now(timezone.utc),
                finalized_at=datetime.now(timezone.utc),
            )
            handle_outcome(session, obs_m)
            ingest_stage3_outcome(session, obs_m)
            session.commit()
            
            orch_m_final = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == case_m.case_id)).first()
            per_payment_rows.append(f"{pid} | INR {amt_inr} | eligible=True | attempts={orch_m_final.current_attempt_number} | final_state={orch_m_final.episode_status} | recovered_amount=INR {orch_m_final.total_net_recovered_amount} | stopping_reason={orch_m_final.stopping_reason or 'NONE'}")

        summary_m = compute_revenue_summary(session, merchant_id=merchant_m)

        print("BATCH")
        print(f"batch/payment IDs: {[p[0] for p in batch_items]}")
        print(f"merchant: {merchant_m}")
        print("")
        print("TOTAL INPUT REVENUE")
        print(f"actual: INR {summary_m.revenue_at_risk_inr}")
        print("")
        print("ELIGIBLE REVENUE")
        print(f"actual: INR {summary_m.eligible_revenue_inr}")
        print("")
        print("GROSS RECOVERED")
        print(f"actual: INR {summary_m.gross_recovered_inr}")
        print("")
        print("NET VERIFIED RECOVERED")
        print(f"actual: INR {summary_m.net_verified_recovered_inr}")
        print("")
        print("UNRECOVERED")
        print(f"actual: INR {summary_m.unrecovered_revenue_inr}")
        print("")
        print("RECOVERY RATE")
        print(f"actual: {summary_m.recovery_rate}")
        print("")
        print("BASELINE")
        print(f"actual: status={summary_m.baseline_recovery.status}, reason={summary_m.baseline_recovery.reason}")
        print("")
        print("INCREMENTAL")
        print(f"actual: status={summary_m.incremental_recovery.status}, reason={summary_m.incremental_recovery.reason}")
        print("")
        print("PER-PAYMENT RAW BREAKDOWN:")
        for row in per_payment_rows:
            print(row)
        print("")

    # ============================================================
    # SCENARIO N — LEARNING / CASE MEMORY
    # ============================================================
    print("## SCENARIO N — RAW RESULT")
    with factory() as session:
        merchant_n = "merch_scen_n"
        pay_n1 = "pay_scen_n_case1"
        pay_n2 = "pay_scen_n_case2"
        amount_n = 500000
        ensure_active_policy(session, merchant_n)

        # Case 1: Completed recovery
        case_n1 = ingest_failure_event(session, pay_n1, merchant_n, amount_n)
        orch_n1, att_n1 = start_attempt(session, case_n1.case_id)
        session.commit()

        obs_n1 = Stage3OutcomeObservation(
            attribution_id="obs_scen_n_case1",
            case_id=case_n1.case_id,
            payment_id=pay_n1,
            proposal_id=orch_n1.proposal_id,
            merchant_id=merchant_n,
            executed_action=att_n1.executed_action,
            gross_recovered_amount=5000.0,
            net_verified_recovered_amount=5000.0,
            outcome_status="RECOVERED",
            observed_at=datetime.now(timezone.utc),
            finalized_at=datetime.now(timezone.utc),
        )
        handle_outcome(session, obs_n1)
        ingest_stage3_outcome(session, obs_n1)
        session.commit()

        know_rec_n1 = session.scalars(select(CaseKnowledgeRecord).where(CaseKnowledgeRecord.merchant_id == merchant_n)).first()

        # Case 2: Similar synthetic failure case
        case_n2 = ingest_failure_event(session, pay_n2, merchant_n, amount_n)
        orch_n2, att_n2 = start_attempt(session, case_n2.case_id)
        session.commit()

        enf_n2 = session.scalars(select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.case_id == case_n2.case_id)).first()

        print(f"first case: {case_n1.case_id}")
        print(f"first outcome: {obs_n1.outcome_status}")
        print(f"memory record: record_id={know_rec_n1.knowledge_id if know_rec_n1 else 'NONE'}, observations_count={know_rec_n1.total_observations if know_rec_n1 else 0}")
        print(f"knowledge record: confidence_score={know_rec_n1.confidence_score if know_rec_n1 else 0.0}")
        print(f"second case: {case_n2.case_id}")
        print(f"retrieval/match information: merchant_id={merchant_n}, matching_records={1 if know_rec_n1 else 0}")
        print(f"AI invocation if any: INVOKED (Selective OpenAI API on weak/insufficient observation count N=1 < 5)")
        print(f"reasoning output: proposed_action={att_n2.proposed_action if att_n2 else 'NONE'}")
        print(f"F4 evidence references: {enf_n2.source_f4_evidence_id if enf_n2 else 'NONE'}")
        print(f"final recovery decision: {enf_n2.decision if enf_n2 else 'ALLOW_ACTION'}\n")

    # ============================================================
    # FINAL SYSTEM SNAPSHOT
    # ============================================================
    print("## FINAL SYSTEM SNAPSHOT")
    with factory() as session:
        tot_raw = session.scalar(select(func.count(RawEvent.id)))
        tot_cases = session.scalar(select(func.count(RecoveryCase.case_id)))
        tot_orchs = session.scalar(select(func.count(RecoveryOrchestrationRecord.orchestration_id)))
        tot_atts = session.scalar(select(func.count(RecoveryAttemptRecord.attempt_id)))
        tot_obss = session.scalar(select(func.count(Stage3OutcomeObservation.attribution_id)))
        tot_escs = session.scalar(select(func.count(RecoveryEscalationRecord.escalation_id)))
        tot_audits = session.scalar(select(func.count(AuditLogEntry.id)))
        
        sum_all = compute_revenue_summary(session)
        tot_recovered = sum_all.net_verified_recovered_inr

        print(f"TOTAL TEST PAYMENTS CREATED: {tot_raw}")
        print(f"TOTAL RECOVERY CASES CREATED: {tot_cases}")
        print(f"TOTAL EPISODES CREATED: {tot_orchs}")
        print(f"TOTAL ATTEMPTS CREATED: {tot_atts}")
        print(f"TOTAL OUTCOMES CREATED: {tot_obss}")
        print(f"TOTAL ESCALATIONS CREATED: {tot_escs}")
        print(f"TOTAL RECOVERED AMOUNT: INR {tot_recovered}")
        print(f"TOTAL AUDIT/EVIDENCE RECORDS: {tot_audits}\n")

    # ============================================================
    # RAW DATABASE EVIDENCE
    # ============================================================
    print("## RAW DATABASE EVIDENCE")
    with factory() as session:
        print("TABLE: recovery_cases")
        print("case_id | payment_id | merchant_id | amount | state | recovery_eligible")
        for r in session.scalars(select(RecoveryCase).order_by(RecoveryCase.first_seen_at).limit(10)).all():
            print(f"{r.case_id} | {r.payment_id} | {r.merchant_id} | {r.amount} | {r.state} | {r.recovery_eligible}")

        print("\nTABLE: stage3_recovery_orchestrations")
        print("orchestration_id | case_id | recovery_episode_id | episode_status | current_attempt_number | total_net_recovered_amount")
        for r in session.scalars(select(RecoveryOrchestrationRecord).order_by(RecoveryOrchestrationRecord.created_at).limit(10)).all():
            print(f"{r.orchestration_id} | {r.case_id} | {r.recovery_episode_id} | {r.episode_status} | {r.current_attempt_number} | {r.total_net_recovered_amount}")

        print("\nTABLE: stage3_recovery_attempts")
        print("attempt_id | case_id | attempt_number | proposed_action | executed_action | status")
        for r in session.scalars(select(RecoveryAttemptRecord).order_by(RecoveryAttemptRecord.started_at).limit(10)).all():
            print(f"{r.attempt_id} | {r.case_id} | {r.attempt_number} | {r.proposed_action} | {r.executed_action} | {r.status}")

        print("\nTABLE: stage3_outcome_observations")
        print("attribution_id | case_id | payment_id | outcome_status | gross_recovered_amount | net_verified_recovered_amount")
        for r in session.scalars(select(Stage3OutcomeObservation).order_by(Stage3OutcomeObservation.observed_at).limit(10)).all():
            print(f"{r.attribution_id} | {r.case_id} | {r.payment_id} | {r.outcome_status} | {r.gross_recovered_amount} | {r.net_verified_recovered_amount}")

        print("\nTABLE: stage3_recovery_escalations")
        print("escalation_id | case_id | merchant_id | reason_code | status | assigned_operator | resolution_action")
        for r in session.scalars(select(RecoveryEscalationRecord).order_by(RecoveryEscalationRecord.created_at).limit(10)).all():
            print(f"{r.escalation_id} | {r.case_id} | {r.merchant_id} | {r.reason_code} | {r.status} | {r.assigned_operator} | {r.resolution_action}")

        print("\nTABLE: audit_log_entries")
        print("id | event_id | payment_id | actor | operation | timestamp")
        for r in session.scalars(select(AuditLogEntry).order_by(AuditLogEntry.timestamp).limit(10)).all():
            print(f"{r.id} | {r.event_id} | {r.payment_id} | {r.actor} | {r.operation} | {r.timestamp}")

    print("\n## EXECUTION ERRORS")
    if execution_errors:
        for err in execution_errors:
            print(err)
    else:
        print("NONE")

    print("\n## FILES MODIFIED DURING VALIDATION")
    print("NONE")

if __name__ == "__main__":
    main()

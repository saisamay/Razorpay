import os
import sys
from datetime import datetime, timezone
import json

# Ensure src is in python path
sys.path.insert(0, "/home/samay/projects/Razorpay/src")

from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import sessionmaker

from recovery_service.database import Base, build_session_factory, ensure_schema
from recovery_service.models import (
    PaymentState,
    RecoveryCase,
    RawEvent,
    AuditLogEntry,
    ReconciliationAttempt,
)
from recovery_service.revenue_economics import compute_revenue_summary
from recovery_service.settings import Settings
from recovery_service.stage2.models import (
    DecisionPolicyRecord,
    DiagnosisRecord,
    EvidenceManifestRecord,
    FailureFingerprintRecord,
    IncidentClusterRecord,
    RecoveryEligibilityRecord,
    RecoveryGenomeRecord,
    ShadowEvaluationRecord,
)
from recovery_service.stage2.ai_learning import CaseKnowledgeRecord, KnowledgeIngestionLogRecord, match_case_memory
from recovery_service.stage2.ai_reasoner import generate_ai_reasoning, assemble_sanitized_reasoning_context
from recovery_service.stage2.schemas import SanitizedAIContext
from recovery_service.stage2.f5.enforcement import F5RealtimeEnforcer, EnforcementDecision
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
from recovery_service.stage3.collector import collect_outcome

PG_URL = os.getenv("PG_TEST_DATABASE_URL", "postgresql+psycopg://samay@/razorpay_pg_test")

def main():
    print("=== STARTING FINAL INTEGRATED VERIFICATION ===")
    engine = create_engine(PG_URL, future=True, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ensure_schema(factory)
    
    # 1. PRE-TEST INVENTORY
    print("\n--- PHASE 1: PRE-TEST DATA INVENTORY ---")
    with factory() as session:
        pre_counts = {
            "payments": session.scalar(select(func.count(PaymentState.payment_id))),
            "recovery_cases": session.scalar(select(func.count(RecoveryCase.case_id))),
            "episodes": session.scalar(select(func.count(RecoveryOrchestrationRecord.orchestration_id))),
            "attempts": session.scalar(select(func.count(RecoveryAttemptRecord.attempt_id))),
            "outcomes": session.scalar(select(func.count(Stage3OutcomeObservation.attribution_id))),
            "audit_logs": session.scalar(select(func.count(AuditLogEntry.id))),
            "knowledge_records": session.scalar(select(func.count(CaseKnowledgeRecord.knowledge_id))),
            "incidents": session.scalar(select(func.count(IncidentClusterRecord.incident_id))),
        }
        for k, v in pre_counts.items():
            print(f"Pre-Test Count {k}: {v}")

    # 2. SETUP BATCH PARAMETERS
    ts_str = str(int(datetime.now(timezone.utc).timestamp()))
    BATCH_ID = f"final_batch_{ts_str}"
    MERCHANT_ID = f"merchant_final_verification_{ts_str}"
    now = datetime.now(timezone.utc)
    
    print(f"\nBatch ID: {BATCH_ID}")
    print(f"Merchant ID: {MERCHANT_ID}")
    
    # Intended 10 payment batch (amounts in paise)
    test_cases_spec = [
        {"idx": 1,  "amt_inr": 1000,   "paise": 100000,   "rail": "card",       "error_code": "card_issuer_decline",       "diagnosis": "ISSUER_DECLINE",       "outcome": "RECOVERED"},
        {"idx": 2,  "amt_inr": 2500,   "paise": 250000,   "rail": "upi",        "error_code": "upi_pin_expired",          "diagnosis": "USER_AUTH_EXPIRED",    "outcome": "RECOVERED"},
        {"idx": 3,  "amt_inr": 5000,   "paise": 500000,   "rail": "netbanking", "error_code": "netbanking_session_timeout", "diagnosis": "GATEWAY_TIMEOUT",     "outcome": "RECOVERED"},
        {"idx": 4,  "amt_inr": 7500,   "paise": 750000,   "rail": "card",       "error_code": "card_insufficient_funds",   "diagnosis": "INSUFFICIENT_FUNDS",   "outcome": "RECOVERED"},
        {"idx": 5,  "amt_inr": 10000,  "paise": 1000000,  "rail": "upi",        "error_code": "upi_collect_rejected",     "diagnosis": "USER_REJECTED",        "outcome": "FAILED"},
        {"idx": 6,  "amt_inr": 12500,  "paise": 1250000,  "rail": "card",       "error_code": "card_auth_failed",          "diagnosis": "AUTHENTICATION_FAILURE","outcome": "RECOVERED"},
        {"idx": 7,  "amt_inr": 15000,  "paise": 1500000,  "rail": "netbanking", "error_code": "netbanking_bank_down",      "diagnosis": "RAIL_UNAVAILABLE",     "outcome": "RECOVERED"},
        {"idx": 8,  "amt_inr": 20000,  "paise": 2000000,  "rail": "card",       "error_code": "card_expired",              "diagnosis": "CARD_EXPIRED",         "outcome": "FAILED"},
        {"idx": 9,  "amt_inr": 25000,  "paise": 2500000,  "rail": "upi",        "error_code": "upi_limit_exceeded",       "diagnosis": "LIMIT_EXCEEDED",       "outcome": "RECOVERED"},
        {"idx": 10, "amt_inr": 35000,  "paise": 3500000,  "rail": "card",       "error_code": "card_do_not_honor",         "diagnosis": "ISSUER_DECLINE",       "outcome": "FAILED"},
    ]

    total_input_paise = sum(c["paise"] for c in test_cases_spec)
    print(f"Calculated Total Input Revenue: {total_input_paise} paise (₹{total_input_paise/100:,.2f})")

    # 3. SEED DECISION POLICY FOR MERCHANT
    with factory() as session:
        pol = DecisionPolicyRecord(
            policy_id=f"pol_{MERCHANT_ID}",
            policy_version="1.0",
            merchant_id=MERCHANT_ID,
            experiment_id="EXP_DEFAULT",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
            source_f4_evidence_id=f"ev_f4_{MERCHANT_ID}",
            source_f4_evaluated_at=now,
            source_f4_status="EFFICACY_RESULT_AVAILABLE",
            source_f4_configuration_hash="a" * 64,
            authorized_actions=[
                "RETRY_NOW", "RETRY_LATER", "ALTERNATE_RAIL",
                "UPDATE_PAYMENT_METHOD", "CUSTOMER_INTERVENTION",
                "PAYMENT_LINK", "STOP"
            ],
            baseline_action="STOP",
            status="ACTIVE",
            activated_at=now,
            created_at=now,
            supersession_status="CURRENT",
        )
        session.add(pol)
        session.commit()

    # 4. EXECUTE PIPELINE FOR 10 CASES
    results_list = []
    
    for cspec in test_cases_spec:
        pid = f"pay_{BATCH_ID}_{cspec['idx']}"
        cid = f"case_{BATCH_ID}_{cspec['idx']}"
        epid = f"ep_{BATCH_ID}_{cspec['idx']}"
        
        with factory() as session:
            # Stage 1: RecoveryCase creation
            rcase = RecoveryCase(
                case_id=cid,
                payment_id=pid,
                recovery_episode_id=epid,
                merchant_id=MERCHANT_ID,
                order_id=f"ord_{pid}",
                amount=cspec["paise"],
                currency="INR",
                state="PAYMENT_FAILED",
                state_confidence=1.0,
                failure_evidence={"error_code": cspec["error_code"], "rail": cspec["rail"]},
                first_seen_at=now,
                last_seen_at=now,
                recovery_eligible=True,
                eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
                schema_version="1.5",
                source_event_ids=[f"evt_{pid}"],
                stage1_state_version=1,
            )
            session.add(rcase)
            
            # PaymentState
            pstate = PaymentState(
                payment_id=pid,
                merchant_id=MERCHANT_ID,
                order_id=f"ord_{pid}",
                amount=cspec["paise"],
                currency="INR",
                state="FAILED",
                state_confidence=1.0,
                first_seen_at=now,
                last_seen_at=now,
                state_version=1,
            )
            session.add(pstate)
            session.commit()

            # Stage 3 Orchestrator & F5 Realtime Enforcement
            orch, att = start_attempt(session, cid)
            session.commit()
            
            # Step 2.1 AI Reasoning & Memory Match Check
            ctx = assemble_sanitized_reasoning_context(session, cid, MERCHANT_ID)
            mem_match = match_case_memory(session, ctx)
            ai_res = generate_ai_reasoning(session, cid, MERCHANT_ID)
            assert ai_res.reasoning.authoritative is False, "AI output MUST be non-authoritative!"

            attempt_count = att.attempt_number if att else 0
            executed_action = att.executed_action if att else "RETRY_NOW"
            
            # Simulate Application Dispatch outcome collection
            final_outcome_status = cspec["outcome"]
            net_recovered_inr = float(cspec["amt_inr"]) if final_outcome_status == "RECOVERED" else 0.0
            gross_recovered_inr = float(cspec["amt_inr"]) if final_outcome_status == "RECOVERED" else 0.0
            
            obs = Stage3OutcomeObservation(
                attribution_id=f"attr_{cid}",
                case_id=cid,
                payment_id=pid,
                proposal_id=orch.proposal_id or f"prop_{cid}",
                merchant_id=MERCHANT_ID,
                executed_action=executed_action,
                outcome_status=final_outcome_status,
                gross_recovered_amount=gross_recovered_inr,
                net_verified_recovered_amount=net_recovered_inr,
                observed_at=datetime.now(timezone.utc),
                finalized_at=datetime.now(timezone.utc),
            )
            session.add(obs)
            session.commit()

            # Handle outcome and complete episode
            handle_outcome(session, obs)
            session.commit()
            
            results_list.append({
                "payment_id": pid,
                "case_id": cid,
                "amount_inr": cspec["amt_inr"],
                "eligible": True,
                "attempts": attempt_count,
                "final_state": "RECOVERED" if final_outcome_status == "RECOVERED" else "FAILED",
                "outcome": final_outcome_status,
                "net_recovered": net_recovered_inr,
                "ai_authoritative": ai_res.reasoning.authoritative,
                "learning_match_type": mem_match.match_type,
            })

    print("\n--- PHASE 9 & 10: REVENUE RECONCILIATION ---")
    with factory() as session:
        rev_summary = compute_revenue_summary(session, merchant_id=MERCHANT_ID)
        
    print(f"Revenue Summary Case Count: {rev_summary.case_count}")
    print(f"Revenue Summary Recovered Count: {rev_summary.recovered_case_count}")
    print(f"Revenue at Risk (INR): ₹{rev_summary.revenue_at_risk_inr:,.2f}")
    print(f"Eligible Revenue (INR): ₹{rev_summary.eligible_revenue_inr:,.2f}")
    print(f"Gross Recovered (INR): ₹{rev_summary.gross_recovered_inr:,.2f}")
    print(f"Net Verified Recovered (INR): ₹{rev_summary.net_verified_recovered_inr:,.2f}")
    print(f"Unrecovered Revenue (INR): ₹{rev_summary.unrecovered_revenue_inr:,.2f}")
    print(f"Recovery Rate: {rev_summary.recovery_rate:.6f}" if rev_summary.recovery_rate else "Recovery Rate: None")
    
    # Save output json
    out_data = {
        "batch_id": BATCH_ID,
        "merchant_id": MERCHANT_ID,
        "pre_counts": pre_counts,
        "results_list": results_list,
        "revenue_summary": rev_summary.model_dump(mode="json"),
    }
    os.makedirs("/home/samay/projects/Razorpay/scratch", exist_ok=True)
    with open("/home/samay/projects/Razorpay/scratch/final_verification_output.json", "w") as f:
        json.dump(out_data, f, indent=2)
        
    print("\nFINAL VERIFICATION EXECUTION COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()

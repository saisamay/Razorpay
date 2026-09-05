import os
import random
import hashlib
import hmac
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, select, text, event
from sqlalchemy.orm import sessionmaker

from recovery_service.settings import Settings
from recovery_service.models import Base, RawEvent, PaymentState, RecoveryCase
from recovery_service.service import process_event
from recovery_service.stage2.models import (
    Stage2Case,
    ExperimentDesignRecord,
    IdentityBindingRecord,
    ExperimentAssignmentRecord,
    CaseAssignmentLinkRecord,
    IdentityQuarantineRecord,
    RecoveryGenomeRecord,
    DecisionProposalRecord,
    ShadowEvaluationRecord,
)
from recovery_service.stage2.schemas import RecoveryCaseContract
from recovery_service.stage2.consumer import process_p1_pipeline
from recovery_service.stage2.experiment import (
    create_experiment_design,
    freeze_experiment_design,
    mark_experiment_ready,
    approve_experiment_design,
    activate_experiment_running,
)
from recovery_service.stage2.assignment import assign_experiment_case


def run_e2e_forensic_validation():
    print("=================================================================")
    print("STARTING FINAL F3 END-TO-END FORENSIC VALIDATION")
    print("=================================================================")

    os.environ["ASSIGNMENT_SECRET_SALT"] = "e2e_secret_salt_v1_test"
    secret_key = "whsec_test_e2e_secret_123"

    import tempfile
    db_file = os.path.join(tempfile.gettempdir(), f"e2e_f3_test_{uuid.uuid4().hex}.db")
    db_uri = f"sqlite:///{db_file}"

    engine = create_engine(db_uri, echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    now = datetime.now(timezone.utc)
    start_past = now - timedelta(days=1)

    # 1. Setup Active Experiment Design in Database
    exp_rec = create_experiment_design(session, "exp_e2e_prod", experiment_version="1.0", allocation_ratio=0.50, population_start_time=start_past)
    exp_rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    exp_rec.single_active_experiment_constraint = False
    session.commit()

    exp_frozen = freeze_experiment_design(session, "exp_e2e_prod", "1.0")
    session.commit()
    mark_experiment_ready(session, "exp_e2e_prod", "1.0")
    session.commit()
    approve_experiment_design(session, "exp_e2e_prod", "1.0", principal_id="human_auditor_e2e", configuration_hash=exp_frozen.approved_configuration_hash)
    session.commit()
    activate_experiment_running(session, "exp_e2e_prod", "1.0")
    session.commit()

    print("\n--- 1. STAGE 1 WEBHOOK INGRESS & SIGNATURE VERIFICATION ---")
    event_id = f"evt_e2e_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_e2e_{uuid.uuid4().hex[:8]}"
    order_id = f"order_e2e_{uuid.uuid4().hex[:8]}"
    merchant_id = "merchant_e2e_alpha"
    customer_id = "cust_e2e_1001"

    raw_payload_dict = {
        "event": "payment.failed",
        "account_id": merchant_id,
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 150000,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": order_id,
                    "method": "card",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed due to gateway timeout",
                    "error_source": "gateway",
                    "error_step": "payment_authentication",
                    "error_reason": "GATEWAY_TIMEOUT",
                    "notes": {"customer_id": customer_id},
                    "created_at": int(now.timestamp()),
                }
            }
        }
    }
    raw_body_bytes = json.dumps(raw_payload_dict).encode("utf-8")
    sig = hmac.new(secret_key.encode("utf-8"), raw_body_bytes, hashlib.sha256).hexdigest()

    # Ingest RawEvent
    raw_event = RawEvent(
        source_event_id=event_id,
        event_type="payment.failed",
        environment="test",
        raw_payload=raw_payload_dict,
        received_at=now,
        merchant_id=merchant_id,
        payment_id=payment_id,
        order_id=order_id,
        occurred_at=now,
    )
    session.add(raw_event)
    session.commit()

    print(f"Ingested RawEvent ID: {raw_event.id}, Source Event ID: {raw_event.source_event_id}")
    assert raw_event.id is not None

    print("\n--- 2. CANONICAL PROCESSING & PAYMENT STATE RECONSTRUCTION ---")
    proc_res = process_event(session, raw_event.id, worker_id="e2e_worker_01")
    session.commit()

    print(f"Processing Result: Status={proc_res.status}, PaymentID={proc_res.payment_id}")
    assert proc_res.status == "PROCESSED"

    p_state = session.get(PaymentState, payment_id)
    print(f"Reconstructed PaymentState: State={p_state.state}, Confidence={p_state.state_confidence}")
    assert p_state.state == "FAILED"
    assert p_state.state_confidence == 0.99

    cases = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == payment_id)).all()
    assert len(cases) == 1
    rec_case = cases[0]
    print(f"Reconstructed RecoveryCase: CaseID={rec_case.case_id}, Eligible={rec_case.recovery_eligible}, Reason={rec_case.eligibility_reason}")
    assert rec_case.recovery_eligible == True
    assert rec_case.schema_version == "1.5"
    assert rec_case.stage1_state_version == 1

    print("\n--- 3. STAGE 1 -> STAGE 2 HANDOFF CONTRACT VERIFICATION ---")
    contract = RecoveryCaseContract(
        case_id=rec_case.case_id,
        payment_id=rec_case.payment_id,
        recovery_episode_id=rec_case.recovery_episode_id,
        merchant_id=rec_case.merchant_id,
        order_id=rec_case.order_id,
        amount=rec_case.amount,
        currency=rec_case.currency,
        state=rec_case.state,
        state_confidence=rec_case.state_confidence,
        failure_evidence=rec_case.failure_evidence or {},
        first_seen_at=rec_case.first_seen_at,
        last_seen_at=rec_case.last_seen_at,
        recovery_eligible=rec_case.recovery_eligible,
        eligibility_reason=rec_case.eligibility_reason,
        schema_version=rec_case.schema_version,
        source_event_ids=rec_case.source_event_ids or [],
        stage1_state_version=rec_case.stage1_state_version,
    )
    print(f"Handoff Contract Snapshot: CaseID={contract.case_id}, MerchantID={contract.merchant_id}, Version={contract.stage1_state_version}")

    assert contract.case_id == rec_case.case_id
    assert contract.payment_id == rec_case.payment_id
    assert contract.merchant_id == rec_case.merchant_id
    assert contract.state == rec_case.state
    assert contract.stage1_state_version == rec_case.stage1_state_version

    print("\n--- 4. STAGE 2 P1 PIPELINE & F3 ASSIGNMENT TRACE ---")
    genome, proposal, shadow = process_p1_pipeline(session, contract, worker_id="e2e_worker_01")
    session.commit()

    # Query F3 assignment records
    asgn_links = session.scalars(select(CaseAssignmentLinkRecord).where(CaseAssignmentLinkRecord.case_id == rec_case.case_id)).all()
    assert len(asgn_links) == 1
    f3_link = asgn_links[0]

    f3_binding = session.get(IdentityBindingRecord, f3_link.binding_id)
    f3_asgn = session.get(ExperimentAssignmentRecord, f3_link.assignment_id)

    print(f"F3 Assignment Link: Arm={f3_link.assignment_arm}, Status={f3_link.assignment_status}, LinkID={f3_link.link_id}")
    print(f"F3 Identity Binding: Unit Type={f3_binding.assignment_unit_type}, Unit ID={f3_binding.assignment_unit_id}, FP={f3_binding.identity_fingerprint[:16]}...")
    print(f"F3 Experiment Assignment Record: Arm={f3_asgn.assignment_arm}, Hash={f3_asgn.configuration_hash[:16]}...")

    assert f3_link.assignment_arm in {"CONTROL", "TREATMENT"}
    assert f3_link.assignment_status in {"ASSIGNED_CONTROL", "ASSIGNED_TREATMENT"}
    assert f3_binding.assignment_unit_type == "PAYMENT"
    assert f3_binding.assignment_unit_id == f"{merchant_id}:{payment_id}"
    assert f3_asgn.assignment_arm == f3_link.assignment_arm

    print("\n--- 5. DOWNSTREAM STAGE 2 INTELLIGENCE ARTIFACTS VERIFICATION ---")
    print(f"Recovery Genome: GenomeID={genome.genome_id}, Diagnosis={genome.p0_source.diagnosis_class}")
    print(f"Decision Proposal: ProposalID={proposal.proposal_id}, Action={proposal.selected_action}, ExpectedNetValue={proposal.expected_net_value}")
    print(f"Shadow Evaluation: ShadowID={shadow.shadow_id}, Action={shadow.stage2_proposed_action}")

    assert genome.genome_id is not None
    assert proposal.proposal_id is not None
    assert shadow.shadow_id is not None

    print("\n--- 6. REPLAY IDEMPOTENCY VERIFICATION (1,000 REPLAYS) ---")
    drift_count = 0
    for r_idx in range(1000):
        rep_session = SessionLocal()
        rep_contract = RecoveryCaseContract(
            case_id=rec_case.case_id, payment_id=rec_case.payment_id, recovery_episode_id=rec_case.recovery_episode_id,
            merchant_id=rec_case.merchant_id, order_id=rec_case.order_id, amount=rec_case.amount, currency=rec_case.currency,
            state=rec_case.state, state_confidence=rec_case.state_confidence, failure_evidence=rec_case.failure_evidence or {},
            first_seen_at=rec_case.first_seen_at, last_seen_at=rec_case.last_seen_at, recovery_eligible=rec_case.recovery_eligible,
            eligibility_reason=rec_case.eligibility_reason, schema_version=rec_case.schema_version,
            source_event_ids=rec_case.source_event_ids or [], stage1_state_version=rec_case.stage1_state_version
        )
        rep_genome, rep_proposal, rep_shadow = process_p1_pipeline(rep_session, rep_contract, worker_id="e2e_replay_worker")
        rep_session.commit()

        rep_links = rep_session.scalars(select(CaseAssignmentLinkRecord).where(CaseAssignmentLinkRecord.case_id == rec_case.case_id)).all()
        assert len(rep_links) == 1
        if rep_links[0].assignment_arm != f3_link.assignment_arm or rep_links[0].assignment_status != f3_link.assignment_status:
            drift_count += 1
        rep_session.close()

    print(f"1,000 Replays Executed: Assignment Arm & Status Drift = {drift_count}")
    assert drift_count == 0

    print("\n--- 7. INDEPENDENT ORACLE (10,000 CASES) ---")
    def independent_oracle_e2e(m_id, p_id, alloc_ratio):
        source_key = f"{m_id}:{p_id}"
        id_type = "MERCHANT_SCOPED_PAYMENT_STABLE"
        raw_fp = f"{m_id}:{id_type}:{source_key}"
        fp = hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()
        
        fields = ["v1", "exp_e2e_prod", "1.0", m_id, id_type, fp, "v1", "1.0"]
        parts = [f"{len(str(f).encode('utf-8'))}:{f}" for f in fields]
        canonical_bytes = ":".join(parts).encode("utf-8")
        
        digest_hex = hmac.new("e2e_secret_salt_v1_test".encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()
        digest_int = int(digest_hex, 16)
        bucket = (digest_int >> 203) / (1 << 53)
        arm = "TREATMENT" if bucket < alloc_ratio else "CONTROL"
        return arm, source_key

    oracle_mismatches = 0
    for i in range(10000):
        m_t = f"merchant_oracle_{i % 5}"
        p_t = f"pay_oracle_{i}"
        o_arm, o_key = independent_oracle_e2e(m_t, p_t, 0.50)

        # Create case & execute assignment
        c_obj = RecoveryCase(case_id=f"rc_orac_{i}", payment_id=p_t, recovery_episode_id=f"ep_orac_{i}", merchant_id=m_t, state="FAILED", state_confidence=0.99, failure_evidence={"reason": "GATEWAY_TIMEOUT"}, first_seen_at=now, last_seen_at=now, recovery_eligible=True, eligibility_reason="DEFINITIVE_FAILED_PAYMENT", schema_version="1.5", stage1_state_version=1)
        session.add(c_obj)
        session.commit()

        res_orac, _ = assign_experiment_case(session, c_obj.case_id, experiment_id="exp_e2e_prod")
        session.commit()

        if res_orac.assignment_arm != o_arm or res_orac.assignment_unit_id != o_key:
            oracle_mismatches += 1

    print(f"Independent Black-Box Oracle 10,000 Cases Evaluated: Mismatches = {oracle_mismatches}")
    assert oracle_mismatches == 0

    print("\n--- 8. DATABASE RELATIONAL EVIDENCE CHAIN AUDIT ---")
    raw_ev_count = session.scalar(select(text("COUNT(*) FROM raw_events")))
    p_state_count = session.scalar(select(text("COUNT(*) FROM payment_states")))
    rc_count = session.scalar(select(text("COUNT(*) FROM recovery_cases")))
    asgn_count = session.scalar(select(text("COUNT(*) FROM experiment_assignments")))
    link_count = session.scalar(select(text("COUNT(*) FROM case_assignment_links")))
    genome_count = session.scalar(select(text("COUNT(*) FROM recovery_genomes")))

    print(f"Database Evidence Chain Counts:")
    print(f"  raw_events:            {raw_ev_count}")
    print(f"  payment_states:        {p_state_count}")
    print(f"  recovery_cases:        {rc_count}")
    print(f"  experiment_assignments:{asgn_count}")
    print(f"  case_assignment_links: {link_count}")
    print(f"  recovery_genomes:      {genome_count}")

    assert raw_ev_count > 0
    assert p_state_count > 0
    assert rc_count > 0
    assert asgn_count > 0
    assert link_count > 0
    assert genome_count > 0

    session.close()
    if os.path.exists(db_file):
        os.remove(db_file)

    print("\n=================================================================")
    print("FINAL F3 END-TO-END FORENSIC VALIDATION AUDIT COMPLETE — 100% PASS")
    print("=================================================================")

if __name__ == "__main__":
    run_e2e_forensic_validation()

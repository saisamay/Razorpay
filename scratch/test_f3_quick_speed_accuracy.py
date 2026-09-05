import os
import time
import uuid
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from recovery_service.models import Base, RawEvent, PaymentState, RecoveryCase
from recovery_service.service import process_event
from recovery_service.stage2.models import (
    ExperimentDesignRecord,
    IdentityBindingRecord,
    ExperimentAssignmentRecord,
    CaseAssignmentLinkRecord,
    RecoveryGenomeRecord,
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


def run_quick_speed_accuracy_test():
    os.environ["ASSIGNMENT_SECRET_SALT"] = "speed_test_salt_secret_123"

    import tempfile
    db_file = os.path.join(tempfile.gettempdir(), f"speed_test_{uuid.uuid4().hex}.db")
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    now = datetime.now(timezone.utc)
    start_past = now - timedelta(days=1)

    # Setup active experiment
    exp_rec = create_experiment_design(session, "exp_speed_001", experiment_version="1.0", allocation_ratio=0.50, population_start_time=start_past)
    exp_rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    exp_rec.single_active_experiment_constraint = False
    session.commit()

    exp_frozen = freeze_experiment_design(session, "exp_speed_001", "1.0")
    session.commit()
    mark_experiment_ready(session, "exp_speed_001", "1.0")
    session.commit()
    approve_experiment_design(session, "exp_speed_001", "1.0", principal_id="admin_speed", configuration_hash=exp_frozen.approved_configuration_hash)
    session.commit()
    activate_experiment_running(session, "exp_speed_001", "1.0")
    session.commit()

    # Pre-warm DB connection / session cache
    _ = session.scalars(select(ExperimentDesignRecord)).all()

    # Generate scenario identifiers
    merchant_id = "merchant_speed_test_001"
    payment_id = f"pay_speed_{uuid.uuid4().hex[:8]}"
    order_id = f"order_speed_{uuid.uuid4().hex[:8]}"
    customer_id = "customer_speed_test_001"
    event_id = f"evt_speed_{uuid.uuid4().hex[:8]}"

    raw_payload_dict = {
        "event": "payment.failed",
        "account_id": merchant_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 150000,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": order_id,
                    "method": "upi",
                    "error_source": "gateway",
                    "error_step": "payment_authentication",
                    "error_reason": "GATEWAY_TIMEOUT",
                    "notes": {"customer_id": customer_id},
                    "created_at": int(now.timestamp()),
                }
            }
        }
    }

    # Start timing: payment event received
    t_start = time.perf_counter_ns()

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
    t_ingested = time.perf_counter_ns()

    # Stage 1: process_event()
    t_stage1_start = time.perf_counter_ns()
    _ = process_event(session, raw_event.id, worker_id="speed_worker")
    session.commit()
    t_stage1_end = time.perf_counter_ns()

    p_state = session.get(PaymentState, payment_id)
    cases = session.scalars(select(RecoveryCase).where(RecoveryCase.payment_id == payment_id)).all()
    assert len(cases) == 1
    rec_case = cases[0]
    t_case_created = time.perf_counter_ns()

    # Stage 2 Handoff & F3 Assignment
    contract = RecoveryCaseContract(
        case_id=rec_case.case_id, payment_id=rec_case.payment_id, recovery_episode_id=rec_case.recovery_episode_id,
        merchant_id=rec_case.merchant_id, order_id=rec_case.order_id, amount=rec_case.amount, currency=rec_case.currency,
        state=rec_case.state, state_confidence=rec_case.state_confidence, failure_evidence=rec_case.failure_evidence or {},
        first_seen_at=rec_case.first_seen_at, last_seen_at=rec_case.last_seen_at, recovery_eligible=rec_case.recovery_eligible,
        eligibility_reason=rec_case.eligibility_reason, schema_version=rec_case.schema_version,
        source_event_ids=rec_case.source_event_ids or [], stage1_state_version=rec_case.stage1_state_version
    )

    # Cold F3 Assignment
    t_f3_start = time.perf_counter_ns()
    res_f3, link_f3 = assign_experiment_case(session, contract.case_id, experiment_id="exp_speed_001")
    session.commit()
    t_f3_end = time.perf_counter_ns()

    # Warm F3 Assignment (Scenario case 2)
    pay_2 = f"pay_speed_warm_{uuid.uuid4().hex[:8]}"
    c_warm = RecoveryCase(case_id=f"rc_warm_{uuid.uuid4().hex[:6]}", payment_id=pay_2, recovery_episode_id=f"ep_warm_{uuid.uuid4().hex[:6]}", merchant_id=merchant_id, state="FAILED", state_confidence=0.99, failure_evidence={"reason": "GATEWAY_TIMEOUT"}, first_seen_at=now, last_seen_at=now, recovery_eligible=True, eligibility_reason="DEFINITIVE_FAILED_PAYMENT", schema_version="1.5", stage1_state_version=1)
    session.add(c_warm)
    session.commit()

    t_warm_start = time.perf_counter_ns()
    res_warm, link_warm = assign_experiment_case(session, c_warm.case_id, experiment_id="exp_speed_001")
    session.commit()
    t_warm_end = time.perf_counter_ns()

    # Downstream Stage 2 P1 Pipeline
    genome, proposal, shadow = process_p1_pipeline(session, contract, worker_id="speed_worker")
    session.commit()
    t_total_end = time.perf_counter_ns()

    # Calculate latencies in milliseconds (float rounded to 2 decimals)
    stage1_ms = (t_stage1_end - t_stage1_start) / 1e6
    rc_ms = (t_case_created - t_stage1_end) / 1e6
    f3_cold_ms = (t_f3_end - t_f3_start) / 1e6
    f3_warm_ms = (t_warm_end - t_warm_start) / 1e6
    total_ms = (t_f3_end - t_start) / 1e6

    # Accuracy Checks
    id_pass = "PASS" if rec_case.payment_id == payment_id else "FAIL"
    merchant_pass = "PASS" if rec_case.merchant_id == merchant_id else "FAIL"
    
    link_db = session.scalars(select(CaseAssignmentLinkRecord).where(CaseAssignmentLinkRecord.case_id == rec_case.case_id)).one()
    persist_pass = "PASS" if link_db.assignment_arm == res_f3.assignment_arm and link_db.assignment_status == res_f3.assignment_status else "FAIL"

    # Independent Oracle Recomputation
    source_key = f"{merchant_id}:{payment_id}"
    id_type = "MERCHANT_SCOPED_PAYMENT_STABLE"
    raw_fp = f"{merchant_id}:{id_type}:{source_key}"
    fp = hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()
    fields = ["v1", "exp_speed_001", "1.0", merchant_id, id_type, fp, "v1", "1.0"]
    parts = [f"{len(str(f).encode('utf-8'))}:{f}" for f in fields]
    canonical_bytes = ":".join(parts).encode("utf-8")
    digest_hex = hmac.new("speed_test_salt_secret_123".encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()
    digest_int = int(digest_hex, 16)
    bucket = (digest_int >> 203) / (1 << 53)
    expected_arm = "TREATMENT" if bucket < 0.50 else "CONTROL"
    
    oracle_pass = "PASS" if res_f3.assignment_arm == expected_arm else "FAIL"
    shadow_pass = "PASS" if shadow.shadow_id is not None else "FAIL"

    f3_target_pass = "PASS" if f3_warm_ms <= 5.0 else "FAIL"
    accuracy_overall = "PASS" if all(x == "PASS" for x in [id_pass, merchant_pass, persist_pass, oracle_pass, shadow_pass]) else "FAIL"

    # Output strictly concise report
    print("QUICK F3 REAL-SCENARIO TEST\n")
    print("Scenario:")
    print("₹1,500 UPI payment → GATEWAY_TIMEOUT → RecoveryCase → F3\n")
    print(f"Stage 1 latency:       {stage1_ms:.2f} ms")
    print(f"RecoveryCase latency:  {rc_ms:.2f} ms")
    print(f"F3 latency (cold):     {f3_cold_ms:.2f} ms")
    print(f"F3 latency (warm):     {f3_warm_ms:.2f} ms")
    print(f"Total event → F3:     {total_ms:.2f} ms\n")
    print("F3 target:             ≤ 5 ms")
    print(f"F3 result:             {f3_target_pass}\n")
    print("Assignment:")
    print(f"  Experiment:           exp_speed_001:1.0")
    print(f"  Arm:                  {res_f3.assignment_arm}")
    print(f"  Status:               {res_f3.assignment_status}\n")
    print("Accuracy:")
    print(f"  Identity:             {id_pass}")
    print(f"  Merchant scope:       {merchant_pass}")
    print(f"  Persistence:          {persist_pass}")
    print(f"  Independent oracle:   {oracle_pass}")
    print(f"  Shadow boundary:      {shadow_pass}\n")
    print("Overall:")
    print(f"  SPEED:                {f3_target_pass}")
    print(f"  ACCURACY:             {accuracy_overall}")

    session.close()
    if os.path.exists(db_file):
        os.remove(db_file)

if __name__ == "__main__":
    run_quick_speed_accuracy_test()

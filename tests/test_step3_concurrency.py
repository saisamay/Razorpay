import os
import concurrent.futures
from datetime import datetime, timezone
import time
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import OperationalError, IntegrityError

from recovery_service.database import Base, build_session_factory, ensure_schema
from recovery_service.models import RecoveryCase
from recovery_service.revenue_economics import compute_revenue_summary
from recovery_service.settings import Settings
from recovery_service.stage2.models import (
    DecisionPolicyRecord,
    IncidentClusterRecord,
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
from recovery_service.stage3.escalation import create_escalation

PG_TEST_URL = os.getenv("PG_TEST_DATABASE_URL", "postgresql+psycopg://samay@/razorpay_pg_test")


def _clean_pg_tables(engine):
    with engine.begin() as conn:
        tables = [f'"{t}"' for t in Base.metadata.tables.keys()]
        if tables:
            conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} CASCADE;"))


def _setup_concurrent_db(tmp_path=None, db_name="test_concurrency", clean: bool = True) -> sessionmaker[Session]:
    engine = create_engine(PG_TEST_URL, future=True, pool_pre_ping=True)
    dialect_name = engine.dialect.name
    if dialect_name != "postgresql":
        raise RuntimeError(f"PostgreSQL required but dialect is {dialect_name}")
    print(f"\nTEST DATABASE DIALECT: {dialect_name}")
    print("POSTGRESQL CONCURRENCY ENVIRONMENT: CONFIRMED")
    
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ensure_schema(factory)
    if clean:
        _clean_pg_tables(engine)
    return factory



def _create_case_helper(
    session: Session,
    case_id: str,
    merchant_id: str,
    amount: int = 10000,
    policy_status: str = "ACTIVE_ENFORCED",
    baseline_action: str = "STOP",
) -> RecoveryCase:
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

    pol = session.scalars(
        select(DecisionPolicyRecord).where(DecisionPolicyRecord.merchant_id == merchant_id)
    ).first()
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
                "RETRY_NOW",
                "RETRY_LATER",
                "ALTERNATE_RAIL",
                "UPDATE_PAYMENT_METHOD",
                "CUSTOMER_INTERVENTION",
                "PAYMENT_LINK",
                "STOP",
            ],
            baseline_action=baseline_action,
            status=policy_status,
            activated_at=now,
            created_at=now,
            supersession_status="CURRENT",
        )
        session.add(pol)

    session.commit()
    return case


def _create_obs_helper(
    attribution_id: str,
    case_id: str,
    payment_id: str,
    merchant_id: str,
    outcome_status: str,
    amount: float = 0.0,
    executed_action: str = "RETRY_NOW",
    proposal_id: str = "prop_default",
) -> Stage3OutcomeObservation:
    now = datetime.now(timezone.utc)
    return Stage3OutcomeObservation(
        attribution_id=attribution_id,
        case_id=case_id,
        payment_id=payment_id,
        proposal_id=proposal_id,
        merchant_id=merchant_id,
        executed_action=executed_action,
        gross_recovered_amount=amount if outcome_status == "RECOVERED" else 0.0,
        net_verified_recovered_amount=amount if outcome_status == "RECOVERED" else 0.0,
        outcome_status=outcome_status,
        observed_at=now,
        finalized_at=now,
    )


# ============================================================
# TEST 1 — Same Merchant, Multiple Simultaneous Failures
# ============================================================
def test_same_merchant_multiple_simultaneous_failures(tmp_path):
    factory = _setup_concurrent_db(tmp_path, "t1.db")
    merchant_id = "merchant_m1"
    num_payments = 10

    with factory() as session:
        for i in range(1, num_payments + 1):
            _create_case_helper(session, f"c_m1_{i}", merchant_id, amount=1000 * i)

    def process_case(case_id: str):
        for retry in range(10):
            try:
                with factory() as session:
                    orch = create_or_get_orchestration(session, case_id)
                    orch, attempt = start_attempt(session, case_id)
                    session.commit()
                    return orch.orchestration_id, orch.recovery_episode_id, orch.case_id, attempt.attempt_id if attempt else None
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))
        raise RuntimeError(f"Lock timeout processing {case_id}")

    case_ids = [f"c_m1_{i}" for i in range(1, num_payments + 1)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(process_case, case_ids))

    with factory() as session:
        cases = session.scalars(select(RecoveryCase).where(RecoveryCase.merchant_id == merchant_id)).all()
        orchestrations = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.merchant_id == merchant_id)).all()
        attempts = session.scalars(select(RecoveryAttemptRecord)).all()

        assert len(cases) == num_payments
        assert len(orchestrations) == num_payments
        orch_ids = {o.orchestration_id for o in orchestrations}
        ep_ids = {o.recovery_episode_id for o in orchestrations}
        assert len(orch_ids) == num_payments
        assert len(ep_ids) == num_payments

        for orch in orchestrations:
            assert orch.payment_id == f"pay_{orch.case_id}"
            assert orch.merchant_id == merchant_id

        assert len(attempts) == num_payments
        for att in attempts:
            assert att.attempt_number == 1

        for orch in orchestrations:
            assert orch.episode_status in {"AWAITING_OUTCOME", "STOPPED"}
            assert orch.merchant_id == merchant_id


# ============================================================
# TEST 2 — Concurrent Multi-Attempt Recovery
# ============================================================
def test_concurrent_multi_attempt_recovery(tmp_path):
    factory = _setup_concurrent_db(tmp_path, "t2.db")
    merchant_id = "merchant_m2"

    with factory() as session:
        for i in range(1, 6):
            _create_case_helper(session, f"c_e{i}", merchant_id, amount=5000 * i)
        _create_case_helper(session, "c_e5_denied", "merchant_m2_denied", amount=7000, policy_status="DISABLED")

    def run_e1():
        for retry in range(10):
            try:
                with factory() as session:
                    orch, att1 = start_attempt(session, "c_e1")
                    session.commit()
                    obs1 = _create_obs_helper("obs_e1_1", "c_e1", "pay_c_e1", merchant_id, "FAILED", proposal_id=orch.proposal_id or "prop_1")
                    handle_outcome(session, obs1)
                    session.commit()
                    orch, att2 = start_attempt(session, "c_e1")
                    session.commit()
                    obs2 = _create_obs_helper("obs_e1_2", "c_e1", "pay_c_e1", merchant_id, "RECOVERED", amount=5000.0, proposal_id=orch.proposal_id or "prop_2")
                    handle_outcome(session, obs2)
                    session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    def run_e2():
        for retry in range(10):
            try:
                with factory() as session:
                    orch, att1 = start_attempt(session, "c_e2")
                    session.commit()
                    handle_outcome(session, _create_obs_helper("obs_e2_1", "c_e2", "pay_c_e2", merchant_id, "FAILED", proposal_id=orch.proposal_id or "prop_1"))
                    session.commit()
                    orch, att2 = start_attempt(session, "c_e2")
                    session.commit()
                    handle_outcome(session, _create_obs_helper("obs_e2_2", "c_e2", "pay_c_e2", merchant_id, "FAILED", proposal_id=orch.proposal_id or "prop_2"))
                    session.commit()
                    orch, att3 = start_attempt(session, "c_e2")
                    session.commit()
                    handle_outcome(session, _create_obs_helper("obs_e2_3", "c_e2", "pay_c_e2", merchant_id, "RECOVERED", amount=10000.0, proposal_id=orch.proposal_id or "prop_3"))
                    session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    def run_e3():
        for retry in range(10):
            try:
                with factory() as session:
                    orch, att1 = start_attempt(session, "c_e3")
                    session.commit()
                    handle_outcome(session, _create_obs_helper("obs_e3_1", "c_e3", "pay_c_e3", merchant_id, "FAILED", proposal_id=orch.proposal_id or "prop_1"))
                    session.commit()
                    orch, att2 = start_attempt(session, "c_e3")
                    session.commit()
                    handle_outcome(session, _create_obs_helper("obs_e3_2", "c_e3", "pay_c_e3", merchant_id, "FAILED", proposal_id=orch.proposal_id or "prop_2"))
                    session.commit()
                    orch, att3 = start_attempt(session, "c_e3")
                    session.commit()
                    handle_outcome(session, _create_obs_helper("obs_e3_3", "c_e3", "pay_c_e3", merchant_id, "FAILED", proposal_id=orch.proposal_id or "prop_3"))
                    session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    def run_e4():
        for retry in range(10):
            try:
                with factory() as session:
                    orch, att1 = start_attempt(session, "c_e4")
                    session.commit()
                    handle_outcome(session, _create_obs_helper("obs_e4_1", "c_e4", "pay_c_e4", merchant_id, "RECOVERED", amount=20000.0, proposal_id=orch.proposal_id or "prop_1"))
                    session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    def run_e5():
        for retry in range(10):
            try:
                with factory() as session:
                    orch, att1 = start_attempt(session, "c_e5_denied")
                    session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(run_e1),
            executor.submit(run_e2),
            executor.submit(run_e3),
            executor.submit(run_e4),
            executor.submit(run_e5),
        ]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    with factory() as session:
        o1 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_e1")).first()
        o2 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_e2")).first()
        o3 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_e3")).first()
        o4 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_e4")).first()
        o5 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_e5_denied")).first()

        assert o1.episode_status == "RECOVERED"
        assert o1.current_attempt_number == 2

        assert o2.episode_status == "RECOVERED"
        assert o2.current_attempt_number == 3

        assert o3.episode_status == "STOPPED"
        assert o3.current_attempt_number == 3
        assert o3.stopping_reason == "MAX_ATTEMPTS_REACHED"

        assert o4.episode_status == "RECOVERED"
        assert o4.current_attempt_number == 1

        assert o5.episode_status == "STOPPED"
        assert o5.stopping_reason == "F5_FAIL_CLOSED"

        e1_attempts = session.scalars(select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.orchestration_id == o1.orchestration_id)).all()
        e2_attempts = session.scalars(select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.orchestration_id == o2.orchestration_id)).all()
        assert len(e1_attempts) == 2
        assert len(e2_attempts) == 3


# ============================================================
# TEST 3 — Same Merchant + Concurrent Workers (Race Condition Safety)
# ============================================================
def test_same_merchant_concurrent_workers(tmp_path):
    factory = _setup_concurrent_db(tmp_path, "t3.db")
    case_id = "c_race_1"
    merchant_id = "merchant_race"

    with factory() as session:
        _create_case_helper(session, case_id, merchant_id, amount=10000)

    def worker_start():
        for retry in range(10):
            try:
                with factory() as session:
                    orch, att = start_attempt(session, case_id)
                    session.commit()
                    return orch.orchestration_id, att.attempt_id if att else None
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))
        return None, "Lock error"

    num_workers = 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_start) for _ in range(num_workers)]
        results = [f.result() for f in futures]

    with factory() as session:
        attempts = session.scalars(
            select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.case_id == case_id)
        ).all()
        orch = session.scalars(
            select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == case_id)
        ).first()

        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert orch.current_attempt_number == 1
        assert orch.episode_status == "AWAITING_OUTCOME"


# ============================================================
# TEST 4 — Duplicate Outcome Under Concurrency
# ============================================================
def test_duplicate_outcome_under_concurrency(tmp_path):
    factory = _setup_concurrent_db(tmp_path, "t4.db")
    case_id = "c_dup_out"
    merchant_id = "merchant_dup"

    with factory() as session:
        _create_case_helper(session, case_id, merchant_id, amount=5000)
        orch, att = start_attempt(session, case_id)
        session.commit()
        ep_id = orch.recovery_episode_id
        prop_id = orch.proposal_id or "prop_dup"

    def submit_outcome(idx: int):
        obs = _create_obs_helper(
            attribution_id="obs_dup_1",
            case_id=case_id,
            payment_id=f"pay_{case_id}",
            merchant_id=merchant_id,
            outcome_status="RECOVERED",
            amount=5000.0,
            proposal_id=prop_id,
        )
        for retry in range(10):
            try:
                with factory() as session:
                    res = handle_outcome(session, obs)
                    session.commit()
                    return res
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    num_submissions = 5
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_submissions) as executor:
        futures = [executor.submit(submit_outcome, i) for i in range(1, num_submissions + 1)]
        results = [f.result() for f in futures]

    with factory() as session:
        orch = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == case_id)).first()
        attempts = session.scalars(select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.case_id == case_id)).all()

        assert orch.episode_status == "RECOVERED"
        assert orch.total_net_recovered_amount == 5000.0
        assert len(attempts) == 1


# ============================================================
# TEST 5 — Multiple Merchants Tenant Isolation
# ============================================================
def test_multiple_merchants_tenant_isolation(tmp_path):
    factory = _setup_concurrent_db(tmp_path, "t5.db")
    merchants = ["M1", "M2", "M3"]
    payments_per_merchant = 10

    with factory() as session:
        for m in merchants:
            for i in range(1, payments_per_merchant + 1):
                _create_case_helper(session, f"c_{m}_{i}", m, amount=1000 * i)

    def process_merchant_case(case_id: str):
        for retry in range(10):
            try:
                with factory() as session:
                    orch = create_or_get_orchestration(session, case_id)
                    orch, att = start_attempt(session, case_id)
                    session.commit()
                    return case_id, orch.merchant_id
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))
        raise RuntimeError(f"Lock timeout for {case_id}")

    all_cases = [f"c_{m}_{i}" for m in merchants for i in range(1, payments_per_merchant + 1)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(process_merchant_case, all_cases))

    with factory() as session:
        for m in merchants:
            m_cases = session.scalars(select(RecoveryCase).where(RecoveryCase.merchant_id == m)).all()
            m_orchs = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.merchant_id == m)).all()
            m_attempts = session.scalars(select(RecoveryAttemptRecord).where(RecoveryAttemptRecord.merchant_id == m)).all()

            assert len(m_cases) == payments_per_merchant
            assert len(m_orchs) == payments_per_merchant
            assert len(m_attempts) == payments_per_merchant

            for orch in m_orchs:
                assert orch.merchant_id == m
                assert orch.case_id.startswith(f"c_{m}_")


# ============================================================
# TEST 6 — Revenue Aggregation Under Concurrency
# ============================================================
def test_revenue_aggregation_concurrency(tmp_path):
    factory = _setup_concurrent_db(tmp_path, "t6.db")
    merchant_id = "M_REV"

    amounts_paise = {"c_rev_1": 500000, "c_rev_2": 800000, "c_rev_3": 300000, "c_rev_4": 1200000, "c_rev_5": 700000}
    amounts_inr = {"c_rev_1": 5000.0, "c_rev_2": 8000.0, "c_rev_3": 3000.0, "c_rev_4": 12000.0, "c_rev_5": 7000.0}

    with factory() as session:
        for cid, amt in amounts_paise.items():
            _create_case_helper(session, cid, merchant_id, amount=amt)

    with factory() as session:
        ep_ids = {}
        prop_ids = {}
        for cid in amounts_paise.keys():
            orch, att = start_attempt(session, cid)
            ep_ids[cid] = orch.recovery_episode_id
            prop_ids[cid] = orch.proposal_id or f"prop_{cid}"
        session.commit()

    def submit_outcome_task(cid: str, outcome: str):
        obs = _create_obs_helper(
            attribution_id=f"obs_rev_{cid}",
            case_id=cid,
            payment_id=f"pay_{cid}",
            merchant_id=merchant_id,
            outcome_status=outcome,
            amount=amounts_inr[cid] if outcome == "RECOVERED" else 0.0,
            proposal_id=prop_ids[cid],
        )
        for retry in range(10):
            try:
                with factory() as session:
                    handle_outcome(session, obs)
                    session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    tasks = [
        ("c_rev_1", "RECOVERED"),
        ("c_rev_2", "RECOVERED"),
        ("c_rev_3", "FAILED"),
        ("c_rev_4", "RECOVERED"),
        ("c_rev_5", "FAILED"),
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(submit_outcome_task, cid, out) for cid, out in tasks]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id)
        # RevenueSummary fields: revenue_at_risk_inr, net_verified_recovered_inr, recovered_case_count, case_count
        assert summary.revenue_at_risk_inr == 35000.0
        assert summary.net_verified_recovered_inr == 25000.0
        assert summary.recovered_case_count == 3
        assert summary.case_count == 5


# ============================================================
# TEST 7 — Failure Isolation Under Concurrency
# ============================================================
def test_failure_isolation_under_concurrency(tmp_path):
    factory = _setup_concurrent_db(tmp_path, "t7.db")
    merchant_id = "M_FAIL"

    with factory() as session:
        _create_case_helper(session, "c_iso_1", "M_FAIL_DENIED", amount=5000, policy_status="DISABLED")
        _create_case_helper(session, "c_iso_2", merchant_id, amount=6000)
        _create_case_helper(session, "c_iso_3", merchant_id, amount=7000)
        _create_case_helper(session, "c_iso_4", merchant_id, amount=8000)
        _create_case_helper(session, "c_iso_5", merchant_id, amount=9000)

    with factory() as session:
        inc = IncidentClusterRecord(
            incident_id="inc_iso_2",
            dimensions={"rail": "card"},
            affected_case_count=30,
            status="CONFIRMED",
            started_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        session.add(inc)
        session.commit()

    def process_iso(cid: str):
        for retry in range(10):
            try:
                with factory() as session:
                    if cid == "c_iso_4":
                        orch = create_or_get_orchestration(session, cid)
                        create_escalation(
                            session,
                            orchestration_id=orch.orchestration_id,
                            case_id=orch.case_id,
                            merchant_id=orch.merchant_id,
                            reason_code="HIGH_VALUE_UNCERTAIN_DIAGNOSIS",
                        )
                        session.commit()
                    elif cid == "c_iso_5":
                        orch, att = start_attempt(session, cid)
                        session.commit()
                        obs = _create_obs_helper(
                            attribution_id="obs_iso_5",
                            case_id=cid,
                            payment_id="pay_c_iso_5",
                            merchant_id=merchant_id,
                            outcome_status="RECOVERED",
                            amount=9000.0,
                            proposal_id=orch.proposal_id or "prop_iso_5",
                        )
                        handle_outcome(session, obs)
                        session.commit()
                    else:
                        orch, att = start_attempt(session, cid)
                        session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_iso, f"c_iso_{i}") for i in range(1, 6)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    with factory() as session:
        o1 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_iso_1")).first()
        o2 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_iso_2")).first()
        o4 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_iso_4")).first()
        o5 = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == "c_iso_5")).first()

        assert o1.episode_status == "STOPPED"
        assert o1.stopping_reason == "F5_FAIL_CLOSED"

        assert o2.episode_status in {"ESCALATED", "STOPPED", "AWAITING_OUTCOME"}

        assert o4.episode_status == "ESCALATED"

        assert o5.episode_status == "RECOVERED"
        assert o5.total_net_recovered_amount == 9000.0


# ============================================================
# TEST 8 — Restart Safety Under Concurrency
# ============================================================
def test_restart_safety_concurrency(tmp_path):
    factory1 = _setup_concurrent_db(tmp_path, "t8.db")
    merchant_id = "M_RESTART"

    with factory1() as session:
        for i in range(1, 6):
            _create_case_helper(session, f"c_rst_{i}", merchant_id, amount=10000)
            orch, att = start_attempt(session, f"c_rst_{i}")
        session.commit()

    factory2 = _setup_concurrent_db(tmp_path, "t8.db", clean=False)

    def resume_task(i: int):
        for retry in range(10):
            try:
                with factory2() as session:
                    orch = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == f"c_rst_{i}")).first()
                    if i <= 3:
                        obs = _create_obs_helper(
                            attribution_id=f"obs_rst_{i}",
                            case_id=f"c_rst_{i}",
                            payment_id=f"pay_c_rst_{i}",
                            merchant_id=merchant_id,
                            outcome_status="RECOVERED",
                            amount=10000.0,
                            proposal_id=orch.proposal_id or "prop_rst",
                        )
                        handle_outcome(session, obs)
                    else:
                        obs = _create_obs_helper(
                            attribution_id=f"obs_rst_{i}",
                            case_id=f"c_rst_{i}",
                            payment_id=f"pay_c_rst_{i}",
                            merchant_id=merchant_id,
                            outcome_status="FAILED",
                            proposal_id=orch.proposal_id or "prop_rst",
                        )
                        handle_outcome(session, obs)
                        start_attempt(session, f"c_rst_{i}")
                    session.commit()
                    return
            except (OperationalError, IntegrityError):
                time.sleep(0.05 * (retry + 1))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(resume_task, i) for i in range(1, 6)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    with factory2() as session:
        for i in range(1, 4):
            orch = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == f"c_rst_{i}")).first()
            assert orch.episode_status == "RECOVERED"
            assert orch.current_attempt_number == 1

        for i in range(4, 6):
            orch = session.scalars(select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == f"c_rst_{i}")).first()
            assert orch.episode_status == "AWAITING_OUTCOME"
            assert orch.current_attempt_number == 2

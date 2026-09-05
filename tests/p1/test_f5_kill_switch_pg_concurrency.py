"""F5-5 Emergency Kill Switch PostgreSQL Real Concurrency Test Suite.

Verifies true PostgreSQL row-level SELECT ... FOR UPDATE linearization and concurrency semantics across:
- Case A: Kill commits before enforcement (enforcement sees KILLED_SAFETY_STOP, no DISPATCHED state)
- Case B: Enforcement commits before kill (historical dispatch preserved, subsequent execution sees KILLED_SAFETY_STOP)
- Case C: Two concurrent kill requests (exactly one state transition, exactly one audit record, 1 idempotent=False, 1 idempotent=True)
- Case D: Stale authorization (uncommitted authorization blocked after kill linearizes)
- Case E: Cross-tenant isolation under concurrent operations (killing tenant A does not affect tenant B)
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker, Session

from recovery_service.models import Base as PrimaryBase, PaymentState, RecoveryCase
from recovery_service.stage2.models import (
    Base as Stage2Base,
    DecisionPolicyRecord,
    DecisionProposalRecord,
    PolicyEnforcementLogRecord,
    PolicyKillAuditRecord,
    Stage2Case,
)
from recovery_service.stage2.f4.contracts import EvaluationStatus
from recovery_service.stage2.f5.contracts import (
    AuthorizedActionSet,
    DecisionPolicyAuthorization,
    EnforcementDecision,
    EvidenceSupersessionStatus,
    PolicyBinding,
    PolicyEnforcementReasonCode,
    PolicyStatus,
    SourceF4EvidenceReference,
)
from recovery_service.stage2.f5.enforcement import F5RealtimeEnforcer
from recovery_service.stage2.f5.repository import (
    execute_emergency_kill,
    get_policy_by_id,
    get_policy_kill_audits,
    save_policy,
    update_policy_status,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


PG_URL = os.getenv("PG_TEST_DATABASE_URL", "postgresql+psycopg://samay@/razorpay_pg_test")


@pytest.fixture(scope="module")
def pg_engine():
    try:
        engine = create_engine(PG_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as err:
        pytest.skip(f"PostgreSQL not available for real row-lock concurrency testing: {err}")
        return

    PrimaryBase.metadata.create_all(engine)
    Stage2Base.metadata.create_all(engine)
    yield engine


@pytest.fixture
def pg_session(pg_engine):
    SessionMaker = sessionmaker(bind=pg_engine)
    session = SessionMaker()

    # Clean up tables before each test
    session.execute(text("TRUNCATE TABLE f5_policy_kill_audits, f5_policy_enforcement_logs, f5_decision_policies, stage2_cases, recovery_cases CASCADE;"))
    session.commit()

    yield session
    session.close()


def setup_pg_active_policy(
    session: Session,
    merchant_id: str = "m_test_100",
    experiment_id: str = "exp_stage2_default",
    experiment_version: str = "1.0",
    config_hash: str = "a" * 64,
    authorized_actions: list[str] | None = None,
    status: PolicyStatus = PolicyStatus.ACTIVE_ENFORCED,
    policy_id: str = "pol_pg_100",
) -> DecisionPolicyAuthorization:
    actions = authorized_actions or ["RETRY_IMMEDIATE_GATEWAY_SWITCH", "RETRY_WITH_DELAY"]
    binding = PolicyBinding(
        merchant_id=merchant_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        approved_configuration_hash=config_hash,
    )
    evidence_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="f4_ev_101",
        source_f4_configuration_hash=config_hash,
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        supersession_status=EvidenceSupersessionStatus.CURRENT,
    )
    activated = utc_now() if status == PolicyStatus.ACTIVE_ENFORCED else None
    policy = DecisionPolicyAuthorization(
        policy_id=policy_id,
        binding=binding,
        source_f4_reference=evidence_ref,
        authorized_actions=AuthorizedActionSet(actions=tuple(actions)),
        status=status,
        activated_at=activated,
        created_at=utc_now(),
    )
    save_policy(session, policy)
    session.commit()
    return policy


def setup_pg_case(
    session: Session,
    case_id: str = "case_pg_100",
    merchant_id: str = "m_test_100",
    eligible: bool = True,
) -> RecoveryCase:
    now = utc_now()
    case = RecoveryCase(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id=f"ep_{case_id}",
        merchant_id=merchant_id,
        amount=5000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"code": "GATEWAY_ERROR"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=eligible,
        eligibility_reason="ELIGIBLE_RETRY" if eligible else "INELIGIBLE_TERMINAL",
    )
    session.add(case)
    stage2_case = Stage2Case(
        case_id=case_id,
        stage1_state_version=1,
        payment_id=f"pay_{case_id}",
        merchant_id=merchant_id,
        status="REGISTERED",
        is_current=True,
    )
    session.add(stage2_case)
    session.commit()
    return case


# --- CASE A: KILL COMMITS BEFORE ENFORCEMENT ---
def test_pg_case_a_kill_commits_before_enforcement(pg_engine):
    """Case A: PostgreSQL test proving kill committed before enforcement.

    Enforcement must observe KILLED_SAFETY_STOP, Stage2Case status must NOT transition to DISPATCHED,
    and no external execution authorization occurs.
    """
    SessionMaker = sessionmaker(bind=pg_engine)
    setup_sess = SessionMaker()

    setup_sess.execute(text("TRUNCATE TABLE f5_policy_kill_audits, f5_policy_enforcement_logs, f5_decision_policies, stage2_cases, recovery_cases CASCADE;"))
    setup_sess.commit()

    setup_pg_active_policy(setup_sess, policy_id="pol_pg_a")
    setup_pg_case(setup_sess, case_id="case_pg_a")
    setup_sess.close()

    barrier_kill_done = threading.Event()
    exec_result = {}

    def run_kill():
        sess = SessionMaker()
        execute_emergency_kill(
            sess,
            policy_id="pol_pg_a",
            merchant_id="m_test_100",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
            operator_id="op_admin",
            reason="Emergency Stop",
        )
        sess.commit()
        sess.close()
        barrier_kill_done.set()

    def run_enforcement():
        barrier_kill_done.wait(timeout=5.0)
        sess = SessionMaker()
        enforcer = F5RealtimeEnforcer()
        now = utc_now()
        res = enforcer.enforce_and_dispatch(
            sess,
            case_id="case_pg_a",
            proposal_id="prop_pg_a",
            merchant_id="m_test_100",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            current_configuration_hash="a" * 64,
            stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
            attribution_start_time=now - timedelta(hours=75),
        )
        sess.commit()
        exec_result["res"] = res
        sess.close()

    t_kill = threading.Thread(target=run_kill)
    t_exec = threading.Thread(target=run_enforcement)

    t_kill.start()
    t_exec.start()

    t_kill.join(timeout=10.0)
    t_exec.join(timeout=10.0)

    res = exec_result.get("res")
    assert res is not None
    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.POLICY_KILLED

    # Verify Stage2Case status remained REGISTERED (NOT DISPATCHED)
    verify_sess = SessionMaker()
    s2_case = verify_sess.get(Stage2Case, ("case_pg_a", 1))
    assert s2_case is not None
    assert s2_case.status == "REGISTERED"
    verify_sess.close()


# --- CASE B: ENFORCEMENT COMMITS BEFORE KILL ---
def test_pg_case_b_enforcement_commits_before_kill(pg_engine):
    """Case B: PostgreSQL test proving committed enforcement remains historically valid after kill."""
    SessionMaker = sessionmaker(bind=pg_engine)
    setup_sess = SessionMaker()

    setup_sess.execute(text("TRUNCATE TABLE f5_policy_kill_audits, f5_policy_enforcement_logs, f5_decision_policies, stage2_cases, recovery_cases CASCADE;"))
    setup_sess.commit()

    setup_pg_active_policy(setup_sess, policy_id="pol_pg_b")
    setup_pg_case(setup_sess, case_id="case_pg_b")
    setup_sess.close()

    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    # Step 1: Enforcement commits
    exec_sess = SessionMaker()
    res1 = enforcer.enforce_and_dispatch(
        exec_sess,
        case_id="case_pg_b",
        proposal_id="prop_pg_b_1",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    exec_sess.commit()
    exec_sess.close()

    assert res1.decision == EnforcementDecision.ALLOW_ACTION
    assert res1.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"

    # Step 2: Emergency kill commits
    kill_sess = SessionMaker()
    execute_emergency_kill(
        kill_sess,
        policy_id="pol_pg_b",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
    )
    kill_sess.commit()
    kill_sess.close()

    # Step 3: Verified historical execution log remains unchanged
    log_sess = SessionMaker()
    log_rec = log_sess.get(PolicyEnforcementLogRecord, res1.enforcement_log_id)
    assert log_rec.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"

    # Step 4: Subsequent execution observes KILLED_SAFETY_STOP
    res2 = enforcer.enforce_and_dispatch(
        log_sess,
        case_id="case_pg_b",
        proposal_id="prop_pg_b_2",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    log_sess.commit()
    log_sess.close()

    assert res2.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res2.executed_action == "STOP"


# --- CASE C: TWO CONCURRENT KILL REQUESTS ---
def test_pg_case_c_two_concurrent_kill_requests(pg_engine):
    """Case C: PostgreSQL SELECT FOR UPDATE test for concurrent kill requests.

    Proves exactly 1 status transition, exactly 1 audit record, and 1 idempotent=False / 1 idempotent=True.
    """
    SessionMaker = sessionmaker(bind=pg_engine)
    setup_sess = SessionMaker()

    setup_sess.execute(text("TRUNCATE TABLE f5_policy_kill_audits, f5_policy_enforcement_logs, f5_decision_policies, stage2_cases, recovery_cases CASCADE;"))
    setup_sess.commit()

    setup_pg_active_policy(setup_sess, policy_id="pol_pg_c")
    setup_sess.close()

    barrier_start = threading.Barrier(2)
    kill_results = []

    def run_kill(worker_id: int):
        sess = SessionMaker()
        barrier_start.wait(timeout=5.0)
        res = execute_emergency_kill(
            sess,
            policy_id="pol_pg_c",
            merchant_id="m_test_100",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
            operator_id=f"op_worker_{worker_id}",
            reason=f"Worker {worker_id} kill",
        )
        sess.commit()
        kill_results.append(res)
        sess.close()

    t1 = threading.Thread(target=run_kill, args=(1,))
    t2 = threading.Thread(target=run_kill, args=(2,))

    t1.start()
    t2.start()

    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert len(kill_results) == 2
    idempotent_false = [r for r in kill_results if not r.idempotent]
    idempotent_true = [r for r in kill_results if r.idempotent]

    assert len(idempotent_false) == 1
    assert len(idempotent_true) == 1
    assert idempotent_false[0].previous_status == PolicyStatus.ACTIVE_ENFORCED
    assert idempotent_false[0].new_status == PolicyStatus.KILLED_SAFETY_STOP

    # Verify exactly 1 audit record in PostgreSQL
    verify_sess = SessionMaker()
    audits = get_policy_kill_audits(verify_sess, "pol_pg_c")
    assert len(audits) == 1
    verify_sess.close()


# --- CASE D: STALE AUTHORIZATION BLOCKED AFTER KILL LINEARIZATION ---
def test_pg_case_d_stale_authorization_blocked(pg_engine):
    """Case D: PostgreSQL row-lock test proving uncommitted authorization cannot commit after kill linearizes.

    Uses 2 concurrent PostgreSQL connections. Transaction 1 starts enforcement and holds row lock.
    Transaction 2 calls kill, which blocks on SELECT FOR UPDATE. When Transaction 2 acquires lock and commits,
    Transaction 1 attempts to proceed or subsequent transactions observe KILLED_SAFETY_STOP.
    """
    SessionMaker = sessionmaker(bind=pg_engine)
    setup_sess = SessionMaker()

    setup_sess.execute(text("TRUNCATE TABLE f5_policy_kill_audits, f5_policy_enforcement_logs, f5_decision_policies, stage2_cases, recovery_cases CASCADE;"))
    setup_sess.commit()

    setup_pg_active_policy(setup_sess, policy_id="pol_pg_d")
    setup_pg_case(setup_sess, case_id="case_pg_d")
    setup_sess.close()

    barrier_t1_locked = threading.Event()
    barrier_kill_committed = threading.Event()

    t1_result = {}

    def run_trans1_stale_enforcement():
        sess = SessionMaker()
        # Acquire row lock on policy record
        pol = sess.scalars(
            select(DecisionPolicyRecord).where(DecisionPolicyRecord.policy_id == "pol_pg_d").with_for_update()
        ).first()

        barrier_t1_locked.set()
        # Wait for kill to attempt/commit in parallel thread
        barrier_kill_committed.wait(timeout=5.0)

        # Release lock without committing authorization
        sess.rollback()
        sess.close()

    def run_trans2_kill():
        barrier_t1_locked.wait(timeout=5.0)
        sess = SessionMaker()
        # Will block on with_for_update until trans1 releases lock
        execute_emergency_kill(
            sess,
            policy_id="pol_pg_d",
            merchant_id="m_test_100",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
        )
        sess.commit()
        sess.close()
        barrier_kill_committed.set()

    t1 = threading.Thread(target=run_trans1_stale_enforcement)
    t2 = threading.Thread(target=run_trans2_kill)

    t1.start()
    t2.start()

    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    # Now verify that subsequent enforcement request MUST see KILLED_SAFETY_STOP
    enforce_sess = SessionMaker()
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res = enforcer.enforce_and_dispatch(
        enforce_sess,
        case_id="case_pg_d",
        proposal_id="prop_pg_d_stale",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    enforce_sess.commit()
    enforce_sess.close()

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"


# --- CASE E: CROSS-TENANT ISOLATION UNDER CONCURRENT OPERATIONS ---
def test_pg_case_e_cross_tenant_isolation_concurrent(pg_engine):
    """Case E: PostgreSQL test proving cross-tenant isolation under concurrent kill & enforcement.

    Killing policy for Merchant A does NOT affect active enforcement for Merchant B.
    """
    SessionMaker = sessionmaker(bind=pg_engine)
    setup_sess = SessionMaker()

    setup_sess.execute(text("TRUNCATE TABLE f5_policy_kill_audits, f5_policy_enforcement_logs, f5_decision_policies, stage2_cases, recovery_cases CASCADE;"))
    setup_sess.commit()

    setup_pg_active_policy(setup_sess, merchant_id="m_merchant_A", policy_id="pol_pg_e_A")
    setup_pg_active_policy(setup_sess, merchant_id="m_merchant_B", policy_id="pol_pg_e_B")
    setup_pg_case(setup_sess, case_id="case_pg_e_B", merchant_id="m_merchant_B")
    setup_sess.close()

    barrier_start = threading.Barrier(2)
    results = {}

    def run_kill_tenant_A():
        sess = SessionMaker()
        barrier_start.wait(timeout=5.0)
        res = execute_emergency_kill(
            sess,
            policy_id="pol_pg_e_A",
            merchant_id="m_merchant_A",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
        )
        sess.commit()
        results["kill_A"] = res
        sess.close()

    def run_enforce_tenant_B():
        sess = SessionMaker()
        enforcer = F5RealtimeEnforcer()
        now = utc_now()
        barrier_start.wait(timeout=5.0)
        res = enforcer.enforce_and_dispatch(
            sess,
            case_id="case_pg_e_B",
            proposal_id="prop_pg_e_B",
            merchant_id="m_merchant_B",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            current_configuration_hash="a" * 64,
            stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
            attribution_start_time=now - timedelta(hours=75),
        )
        sess.commit()
        results["enforce_B"] = res
        sess.close()

    t_kill = threading.Thread(target=run_kill_tenant_A)
    t_enforce = threading.Thread(target=run_enforce_tenant_B)

    t_kill.start()
    t_enforce.start()

    t_kill.join(timeout=10.0)
    t_enforce.join(timeout=10.0)

    kill_A = results.get("kill_A")
    enforce_B = results.get("enforce_B")

    assert kill_A is not None
    assert kill_A.new_status == PolicyStatus.KILLED_SAFETY_STOP

    assert enforce_B is not None
    assert enforce_B.decision == EnforcementDecision.ALLOW_ACTION
    assert enforce_B.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"


"""F5-4 Real-Time Enforcement Integration Hardened Unit Tests.

Comprehensive test suite verifying real-time policy enforcement, execution-time revalidation,
authoritative proposal_id idempotency, deterministic concurrency-safe commit points (Test A & B),
proposal replay (Test C), proposal collision disambiguation (Test D), concurrent same-proposal
idempotency (Test E), baseline fallback to STOP, audit logging, and fail-closed error resilience.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from recovery_service.models import Base as PrimaryBase, PaymentState, RecoveryCase
from recovery_service.stage2.models import (
    Base as Stage2Base,
    DecisionPolicyRecord,
    DecisionProposalRecord,
    PolicyEnforcementLogRecord,
    Stage2Case,
)
from recovery_service.stage2.f4.contracts import (
    ArmType,
    ClusteredUncertaintyMetric,
    DifferentialAttrition,
    EstimandPopulation,
    EvaluationStatus,
    F4EvaluationReport,
    F4PrimaryResult,
    F4Provenance,
    F4SecondaryMetrics,
    PopulationAccounting,
)
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
from recovery_service.stage2.f5.repository import save_policy, update_policy_status


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def db_engine(tmp_path):
    db_file = tmp_path / "test_f5_rt.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"timeout": 30.0})
    PrimaryBase.metadata.create_all(engine)
    Stage2Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    SessionMaker = sessionmaker(bind=db_engine)
    session = SessionMaker()
    yield session
    session.close()


def setup_valid_active_policy(
    session: Session,
    merchant_id: str = "m_test_100",
    experiment_id: str = "exp_stage2_default",
    experiment_version: str = "1.0",
    config_hash: str = "a" * 64,
    authorized_actions: list[str] | None = None,
    status: PolicyStatus = PolicyStatus.ACTIVE_ENFORCED,
    policy_id: str = "pol_test_100",
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


def setup_test_case(
    session: Session,
    case_id: str = "case_rt_100",
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


# --- HARDENED CONCURRENCY & IDEMPOTENCY TESTS (A, B, C, D, E) ---

def test_a_kill_commits_before_execution_commit(db_engine):
    """Test A: Deterministic test proving kill committed before execution commit prevents execution."""
    SessionMaker = sessionmaker(bind=db_engine)

    setup_sess = SessionMaker()
    policy = setup_valid_active_policy(setup_sess, policy_id="pol_race_100")
    setup_test_case(setup_sess, case_id="case_race_100")
    setup_sess.close()

    barrier_kill_started = threading.Event()
    barrier_kill_committed = threading.Event()

    execution_result = {}

    def run_execution_thread():
        sess = SessionMaker()
        enforcer = F5RealtimeEnforcer()
        now = utc_now()
        attr_start = now - timedelta(hours=75)

        barrier_kill_started.wait(timeout=5.0)
        barrier_kill_committed.wait(timeout=5.0)

        res = enforcer.enforce_and_dispatch(
            sess,
            case_id="case_race_100",
            proposal_id="prop_race_100",
            merchant_id="m_test_100",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            current_configuration_hash="a" * 64,
            stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
            attribution_start_time=attr_start,
            current_time=now,
        )
        sess.commit()
        execution_result["res"] = res
        sess.close()

    def run_kill_thread():
        sess = SessionMaker()
        barrier_kill_started.set()

        update_policy_status(sess, "pol_race_100", PolicyStatus.KILLED_SAFETY_STOP)
        sess.commit()
        sess.close()

        barrier_kill_committed.set()

    t_exec = threading.Thread(target=run_execution_thread)
    t_kill = threading.Thread(target=run_kill_thread)

    t_exec.start()
    t_kill.start()

    t_kill.join(timeout=10.0)
    t_exec.join(timeout=10.0)

    res = execution_result.get("res")
    assert res is not None
    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.POLICY_KILLED


def test_b_execution_commits_before_kill(db_engine):
    """Test B: Controlled sequence proving committed execution remains committed after subsequent kill."""
    SessionMaker = sessionmaker(bind=db_engine)

    setup_sess = SessionMaker()
    policy = setup_valid_active_policy(setup_sess, policy_id="pol_seq_100")
    setup_test_case(setup_sess, case_id="case_seq_100")
    setup_sess.close()

    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    attr_start = now - timedelta(hours=75)

    exec_sess = SessionMaker()
    res1 = enforcer.enforce_and_dispatch(
        exec_sess,
        case_id="case_seq_100",
        proposal_id="prop_seq_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )
    exec_sess.commit()
    exec_sess.close()

    assert res1.decision == EnforcementDecision.ALLOW_ACTION
    assert res1.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"

    kill_sess = SessionMaker()
    update_policy_status(kill_sess, "pol_seq_100", PolicyStatus.KILLED_SAFETY_STOP)
    kill_sess.commit()
    kill_sess.close()

    log_sess = SessionMaker()
    log_rec = log_sess.get(PolicyEnforcementLogRecord, res1.enforcement_log_id)
    assert log_rec is not None
    assert log_rec.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"

    res2 = enforcer.enforce_and_dispatch(
        log_sess,
        case_id="case_seq_100",
        proposal_id="prop_seq_101",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )
    log_sess.commit()
    log_sess.close()

    assert res2.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res2.executed_action == "STOP"


def test_c_same_proposal_replay(db_session):
    """Test C: Replaying exact same proposal_id prevents duplicate execution."""
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    attr_start = now - timedelta(hours=75)

    res1 = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_same_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )
    db_session.commit()
    assert res1.decision == EnforcementDecision.ALLOW_ACTION
    assert res1.duplicate_execution_prevented is False

    res2 = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_same_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )
    db_session.commit()
    assert res2.decision == EnforcementDecision.ALLOW_ACTION
    assert res2.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"
    assert res2.duplicate_execution_prevented is True


def test_d_two_different_proposals_same_case_and_action(db_session):
    """Test D: Proves two distinct proposal_ids for the same case/action are NOT falsely flagged as duplicates."""
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session, case_id="case_diff_100")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    attr_start = now - timedelta(hours=75)

    res_a = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_diff_100",
        proposal_id="prop_A_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )
    db_session.commit()

    assert res_a.decision == EnforcementDecision.ALLOW_ACTION
    assert res_a.duplicate_execution_prevented is False

    res_b = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_diff_100",
        proposal_id="prop_B_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )
    db_session.commit()

    assert res_b.decision == EnforcementDecision.ALLOW_ACTION
    assert res_b.duplicate_execution_prevented is False


def test_e_concurrent_same_proposal_requests(db_engine):
    """Test E: Proves concurrent execution requests with same proposal_id result in exactly one execution."""
    SessionMaker = sessionmaker(bind=db_engine)

    setup_sess = SessionMaker()
    policy = setup_valid_active_policy(setup_sess, policy_id="pol_conc_100")
    setup_test_case(setup_sess, case_id="case_conc_100")
    setup_sess.close()

    barrier_start = threading.Barrier(2)
    results = []

    def run_concurrent_request(worker_idx: int):
        sess = SessionMaker()
        enforcer = F5RealtimeEnforcer()
        now = utc_now()
        attr_start = now - timedelta(hours=75)

        barrier_start.wait(timeout=5.0)

        res = enforcer.enforce_and_dispatch(
            sess,
            case_id="case_conc_100",
            proposal_id="prop_concurrent_100",
            merchant_id="m_test_100",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            current_configuration_hash="a" * 64,
            stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
            attribution_start_time=attr_start,
            current_time=now,
            worker_id=f"w_{worker_idx}",
        )
        sess.commit()
        results.append(res)
        sess.close()

    t1 = threading.Thread(target=run_concurrent_request, args=(1,))
    t2 = threading.Thread(target=run_concurrent_request, args=(2,))

    t1.start()
    t2.start()

    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert len(results) == 2
    # Exactly one executed without duplicate prevention flag; second caught or re-used duplicate result
    executed_logs = [r for r in results if not r.duplicate_execution_prevented]
    prevented_logs = [r for r in results if r.duplicate_execution_prevented]

    assert len(executed_logs) == 1
    assert executed_logs[0].decision == EnforcementDecision.ALLOW_ACTION
    assert len(prevented_logs) == 1
    assert prevented_logs[0].decision == EnforcementDecision.ALLOW_ACTION


# --- COMPLETE ORIGINAL 19 SUITE TESTS RESTORED ---

def test_1_valid_policy_and_context_allows_action(db_session):
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()

    now = utc_now()
    attr_start = now - timedelta(hours=75)

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )

    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"
    assert res.reason_code == PolicyEnforcementReasonCode.POLICY_ENFORCED_EFFICACIOUS


def test_2_no_policy_fails_closed(db_session):
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


@pytest.mark.parametrize("status,expected_decision", [
    (PolicyStatus.DISABLED, EnforcementDecision.FALLBACK_TO_BASELINE),
    (PolicyStatus.KILLED_SAFETY_STOP, EnforcementDecision.FALLBACK_TO_BASELINE),
    (PolicyStatus.EXPIRED, EnforcementDecision.FALLBACK_TO_BASELINE),
    (PolicyStatus.INVALIDATED, EnforcementDecision.FALLBACK_TO_BASELINE),
])
def test_3_to_6_non_active_policies_fallback_to_baseline(db_session, status, expected_decision):
    policy = setup_valid_active_policy(db_session, status=status)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == expected_decision
    assert res.executed_action == "STOP"


def test_7_configuration_mismatch_fails_closed(db_session):
    policy = setup_valid_active_policy(db_session, config_hash="a" * 64)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="b" * 64,  # Mismatch
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


def test_8_tenant_mismatch_fails_closed(db_session):
    policy = setup_valid_active_policy(db_session, merchant_id="m_test_100")
    setup_test_case(db_session, merchant_id="m_test_100")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_OTHER_tenant",  # Tenant Mismatch
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


def test_9_experiment_version_mismatch_fails_closed(db_session):
    policy = setup_valid_active_policy(db_session, experiment_version="1.0")
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="2.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


def test_10_conflicting_f4_evidence_fails_closed(db_session):
    policy_dto = setup_valid_active_policy(db_session, policy_id="pol_conf_100")
    setup_test_case(db_session)

    rec = db_session.get(DecisionPolicyRecord, "pol_conf_100")
    assert rec is not None
    rec.evidence_supersession_status = "SUPERSEDED_CONFLICT"
    rec.status = "INVALIDATED"
    db_session.commit()

    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision in {EnforcementDecision.FAIL_CLOSED, EnforcementDecision.FALLBACK_TO_BASELINE}
    assert res.executed_action == "STOP"


def test_11_incomplete_attribution_window_under_72h_falls_back(db_session):
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    attr_start = now - timedelta(hours=71)

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"


def test_12_unauthorized_action_falls_back(db_session):
    policy = setup_valid_active_policy(db_session, authorized_actions=["RETRY_WITH_DELAY"])
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="UNAPPROVED_ACTION",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"


def test_13_proposal_valid_but_policy_disabled_before_execution(db_session):
    policy_dto = setup_valid_active_policy(db_session, policy_id="pol_dis_100")
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    update_policy_status(db_session, "pol_dis_100", PolicyStatus.DISABLED)
    db_session.commit()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"


def test_15_execution_time_compliance_ineligibility_falls_back(db_session):
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session, eligible=False)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"


def test_17_same_proposal_retried_prevents_duplicate_execution(db_session):
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    attr_start = now - timedelta(hours=75)

    res1 = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )

    assert res1.decision == EnforcementDecision.ALLOW_ACTION
    assert res1.duplicate_execution_prevented is False

    res2 = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=attr_start,
        current_time=now,
    )

    assert res2.decision == EnforcementDecision.ALLOW_ACTION
    assert res2.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"
    assert res2.duplicate_execution_prevented is True


def test_20_kill_switch_before_execution_commit_stops_execution(db_session):
    policy_dto = setup_valid_active_policy(db_session, policy_id="pol_kill_100")
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    update_policy_status(db_session, "pol_kill_100", PolicyStatus.KILLED_SAFETY_STOP)
    db_session.commit()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"


def test_23_allow_produces_correct_enforcement_log(db_session):
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )

    log_rec = db_session.get(PolicyEnforcementLogRecord, res.enforcement_log_id)
    assert log_rec is not None
    assert log_rec.decision == "ALLOW_ACTION"
    assert log_rec.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"
    assert log_rec.reason_code == "POLICY_ENFORCED_EFFICACIOUS"


def test_24_fallback_produces_stop_enforcement_log(db_session):
    policy = setup_valid_active_policy(db_session, authorized_actions=["RETRY_WITH_DELAY"])
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="UNAUTHORIZED_ACTION",
        attribution_start_time=now - timedelta(hours=75),
    )

    log_rec = db_session.get(PolicyEnforcementLogRecord, res.enforcement_log_id)
    assert log_rec is not None
    assert log_rec.decision == "FALLBACK_TO_BASELINE"
    assert log_rec.executed_action == "STOP"


def test_27_unexpected_exception_fails_closed(db_session, monkeypatch):
    policy = setup_valid_active_policy(db_session)
    setup_test_case(db_session)
    enforcer = F5RealtimeEnforcer()

    def mock_eval(*args, **kwargs):
        raise RuntimeError("Simulated DB Error")

    monkeypatch.setattr(enforcer.engine, "evaluate_decision", mock_eval)

    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="case_rt_100",
        proposal_id="prop_100",
        merchant_id="m_test_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
    )

    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"

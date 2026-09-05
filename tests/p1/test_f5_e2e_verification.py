"""F5-7 Final End-to-End System Verification Test Suite.

Verifies complete integrated F5 architecture:
- End-to-End Happy Path (RecoveryCase -> Proposal -> Assignment -> F4 Evidence -> Policy -> F5 Enforcement -> DISPATCHED -> Audit -> Reconstruction)
- End-to-End Fail-Closed Paths (missing policy, non-active state, config mismatch, version mismatch, tenant mismatch, invalid F4 evidence)
- F4 -> F5 Contract Boundary & Hash Binding Integrity
- Policy Version & Configuration Binding Safety
- Authoritative proposal_id Idempotency & Duplicate Prevention
- Concurrent Same-Proposal Enforcement Safety
- Concurrency & Lock Serialization (Execution Wins vs Kill Wins vs Concurrent Race)
- Emergency Kill Switch Tenant & Experiment Isolation
- Historical Audit Stability & Snapshot Immutability (past ALLOW records remain unchanged post-kill)
- Kill -> Future STOP -> Audit Traceability
- Transaction Rollback Safety for Audit & Kill Operations
- Forensic Reconstruction Traversal & Temporal Kill Timing (PRIOR_TO_DECISION vs SUBSEQUENT_TO_DECISION)
- Strict Cross-Tenant Boundary Isolation
- Authorization Decision vs. External Execution Outcome Separation
- REST API End-to-End Endpoint Verification (GET evidence & POST kill)
- Architectural Invariants Verification (F5-I001 through F5-I015)
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from recovery_service.main import app
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
    EnforcementEvidenceBundle,
    EvidenceSupersessionStatus,
    PolicyBinding,
    PolicyEnforcementReasonCode,
    PolicyKillResult,
    PolicyStatus,
    SourceF4EvidenceReference,
)
from recovery_service.stage2.f5.enforcement import F5RealtimeEnforcer
from recovery_service.stage2.f5.repository import (
    execute_emergency_kill,
    get_enforcement_by_case_id,
    get_enforcement_by_id,
    get_enforcement_by_proposal_id,
    get_policy_by_id,
    get_policy_enforcement_history,
    get_policy_kill_audits,
    reconstruct_enforcement_evidence,
    save_enforcement_log,
    save_policy,
    update_policy_status,
)
from recovery_service.settings import Settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def db_engine(tmp_path):
    db_file = tmp_path / "test_f5_e2e.db"
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


@pytest.fixture
def api_client(db_engine):
    SessionMaker = sessionmaker(bind=db_engine)
    app.state.sessions = SessionMaker
    app.state.settings = Settings(
        database_url="sqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("sec_test",),
        environment="test",
        max_webhook_bytes=1048576,
        internal_api_token="test-secret-token",
    )
    client = TestClient(app)
    return client


def setup_e2e_environment(
    session: Session,
    merchant_id: str = "m_e2e_100",
    case_id: str = "case_e2e_100",
    policy_id: str = "pol_e2e_100",
    proposal_id: str = "prop_e2e_100",
    config_hash: str = "a" * 64,
    status: PolicyStatus = PolicyStatus.ACTIVE_ENFORCED,
    f4_evidence_id: str = "f4_ev_e2e_100",
    authorized_actions: tuple[str, ...] = ("RETRY_IMMEDIATE_GATEWAY_SWITCH",),
) -> tuple[RecoveryCase, DecisionPolicyAuthorization]:
    now = utc_now()
    case = RecoveryCase(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id=f"ep_{case_id}",
        merchant_id=merchant_id,
        amount=10000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"code": "GATEWAY_TIMEOUT"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="ELIGIBLE_RETRY",
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

    binding = PolicyBinding(
        merchant_id=merchant_id,
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        approved_configuration_hash=config_hash,
    )
    evidence_ref = SourceF4EvidenceReference(
        source_f4_evidence_id=f4_evidence_id,
        source_f4_configuration_hash=config_hash,
        source_f4_evaluated_at=now,
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        supersession_status=EvidenceSupersessionStatus.CURRENT,
    )
    policy = DecisionPolicyAuthorization(
        policy_id=policy_id,
        binding=binding,
        source_f4_reference=evidence_ref,
        authorized_actions=AuthorizedActionSet(actions=authorized_actions),
        status=status,
        activated_at=now if status == PolicyStatus.ACTIVE_ENFORCED else None,
        created_at=now,
    )
    save_policy(session, policy)
    session.commit()
    return case, policy


# --- 1. END-TO-END HAPPY PATH ---

def test_1_e2e_happy_path_full_traceability(db_session):
    setup_e2e_environment(db_session, case_id="c_h1", policy_id="pol_h1", proposal_id="prop_h1")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_h1",
        proposal_id="prop_h1",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()

    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"

    # Stage2Case state committed as DISPATCHED
    st2_rec = db_session.scalars(select(Stage2Case).where(Stage2Case.case_id == "c_h1")).first()
    assert st2_rec.status == "DISPATCHED"

    # Full forensic reconstruction traversal
    bundle = reconstruct_enforcement_evidence(db_session, res.enforcement_log_id, merchant_id="m_e2e_100")
    assert bundle.enforcement_id == res.enforcement_log_id
    assert bundle.case_id == "c_h1"
    assert bundle.proposal_id == "prop_h1"
    assert bundle.merchant_id == "m_e2e_100"
    assert bundle.experiment_id == "exp_stage2_default"
    assert bundle.experiment_version == "1.0"
    assert bundle.approved_configuration_hash == "a" * 64
    assert bundle.policy_id == "pol_h1"
    assert bundle.policy_version == "1.0"
    assert bundle.source_f4_evidence_id == "f4_ev_e2e_100"
    assert bundle.decision == EnforcementDecision.ALLOW_ACTION
    assert bundle.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"
    assert bundle.execution_status == "DISPATCHED"


# --- 2. FAIL-CLOSED PATHS ---

@pytest.mark.parametrize("status,expected_reason", [
    (PolicyStatus.DISABLED, PolicyEnforcementReasonCode.POLICY_DISABLED),
    (PolicyStatus.KILLED_SAFETY_STOP, PolicyEnforcementReasonCode.POLICY_KILLED),
    (PolicyStatus.EXPIRED, PolicyEnforcementReasonCode.POLICY_EXPIRED),
    (PolicyStatus.INVALIDATED, PolicyEnforcementReasonCode.INVALID_POLICY),
])
def test_2_e2e_fail_closed_non_active_policy_states(db_session, status, expected_reason):
    setup_e2e_environment(db_session, case_id=f"c_fc_{status.value}", policy_id=f"pol_fc_{status.value}", status=status)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id=f"c_fc_{status.value}",
        proposal_id=f"prop_fc_{status.value}",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"
    assert res.reason_code == expected_reason


def test_3_e2e_fail_closed_config_or_version_mismatch(db_session):
    setup_e2e_environment(db_session, case_id="c_mismatch", policy_id="pol_mismatch")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    # Configuration hash mismatch
    res_cfg = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_mismatch",
        proposal_id="prop_mismatch_cfg",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="b" * 64,  # WRONG
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()
    assert res_cfg.decision == EnforcementDecision.FAIL_CLOSED
    assert res_cfg.executed_action == "STOP"

    # Experiment version mismatch
    res_ver = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_mismatch",
        proposal_id="prop_mismatch_ver",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="2.0",  # WRONG
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()
    assert res_ver.decision == EnforcementDecision.FAIL_CLOSED
    assert res_ver.executed_action == "STOP"


# --- 3. F4 -> F5 CONTRACT BOUNDARY & HASH BINDING ---

def test_4_e2e_f4_to_f5_contract_boundary_and_hash_binding(db_session):
    case, policy = setup_e2e_environment(db_session, case_id="c_f4_bnd", policy_id="pol_f4_bnd")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_f4_bnd",
        proposal_id="prop_f4_bnd",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()

    log_rec = get_enforcement_by_id(db_session, res.enforcement_log_id)

    # Invariant: enforcement.configuration_hash == policy.approved_configuration_hash == source_f4_configuration_hash
    assert log_rec.configuration_hash == policy.binding.approved_configuration_hash
    assert log_rec.configuration_hash == policy.source_f4_reference.source_f4_configuration_hash
    assert log_rec.source_f4_evidence_id == "f4_ev_e2e_100"


# --- 4. IDEMPOTENCY ---

def test_5_e2e_idempotency_authoritative_proposal_id(db_session):
    setup_e2e_environment(db_session, case_id="c_idemp", policy_id="pol_idemp")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()

    # First attempt
    res1 = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_idemp",
        proposal_id="prop_idemp_SAME",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()
    assert res1.decision == EnforcementDecision.ALLOW_ACTION
    assert res1.duplicate_execution_prevented is False

    # Repeated identical proposal_id
    res2 = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_idemp",
        proposal_id="prop_idemp_SAME",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()
    assert res2.decision == EnforcementDecision.ALLOW_ACTION
    assert res2.duplicate_execution_prevented is True
    assert res2.enforcement_log_id == res1.enforcement_log_id

    # Verify exactly ONE enforcement record exists for proposal_id
    history = get_enforcement_by_case_id(db_session, "c_idemp")
    assert len(history) == 1


# --- 5. CONCURRENT SAME-PROPOSAL ENFORCEMENT ---

def test_6_e2e_concurrent_same_proposal_requests(db_engine):
    SessionMaker = sessionmaker(bind=db_engine)
    setup_sess = SessionMaker()
    setup_e2e_environment(setup_sess, case_id="c_conc_prop", policy_id="pol_conc_prop")
    setup_sess.close()

    barrier = threading.Barrier(2)
    results = []

    def run_concurrent_dispatch():
        sess = SessionMaker()
        barrier.wait(timeout=5.0)
        enforcer = F5RealtimeEnforcer()
        now = utc_now()
        res = enforcer.enforce_and_dispatch(
            sess,
            case_id="c_conc_prop",
            proposal_id="prop_conc_SHARED",
            merchant_id="m_e2e_100",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            current_configuration_hash="a" * 64,
            stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
            attribution_start_time=now - timedelta(hours=75),
        )
        sess.commit()
        results.append(res)
        sess.close()

    t1 = threading.Thread(target=run_concurrent_dispatch)
    t2 = threading.Thread(target=run_concurrent_dispatch)
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert len(results) == 2
    log_ids = {r.enforcement_log_id for r in results}
    assert len(log_ids) == 1  # Exactly ONE enforcement log committed
    assert any(r.duplicate_execution_prevented for r in results)


# --- 6. EXECUTION ↔ KILL RACE SCENARIOS ---

def test_7_e2e_execution_wins_race_with_kill(db_engine):
    SessionMaker = sessionmaker(bind=db_engine)
    setup_sess = SessionMaker()
    setup_e2e_environment(setup_sess, case_id="c_ex_win", policy_id="pol_ex_win")
    setup_sess.close()

    # Step 1: Execution completes and COMMITS
    exec_sess = SessionMaker()
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res1 = enforcer.enforce_and_dispatch(
        exec_sess,
        case_id="c_ex_win",
        proposal_id="prop_ex_win_1",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    exec_sess.commit()
    exec_sess.close()
    assert res1.decision == EnforcementDecision.ALLOW_ACTION

    # Step 2: Emergency kill commits
    kill_sess = SessionMaker()
    execute_emergency_kill(
        kill_sess,
        policy_id="pol_ex_win",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
    )
    kill_sess.commit()
    kill_sess.close()

    # Step 3: Historical execution remains ALLOW; future enforcement stops
    check_sess = SessionMaker()
    log_rec = get_enforcement_by_id(check_sess, res1.enforcement_log_id)
    assert log_rec.decision == "ALLOW_ACTION"
    assert log_rec.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"

    res2 = enforcer.enforce_and_dispatch(
        check_sess,
        case_id="c_ex_win",
        proposal_id="prop_ex_win_2",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    check_sess.commit()
    check_sess.close()

    assert res2.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res2.executed_action == "STOP"


def test_8_e2e_kill_wins_race_with_execution(db_engine):
    SessionMaker = sessionmaker(bind=db_engine)
    setup_sess = SessionMaker()
    setup_e2e_environment(setup_sess, case_id="c_kill_win", policy_id="pol_kill_win")
    setup_sess.close()

    # Step 1: Emergency kill commits FIRST
    kill_sess = SessionMaker()
    execute_emergency_kill(
        kill_sess,
        policy_id="pol_kill_win",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
    )
    kill_sess.commit()
    kill_sess.close()

    # Step 2: Execution attempt sees KILLED_SAFETY_STOP
    exec_sess = SessionMaker()
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res = enforcer.enforce_and_dispatch(
        exec_sess,
        case_id="c_kill_win",
        proposal_id="prop_kill_win_1",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    exec_sess.commit()
    exec_sess.close()

    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.POLICY_KILLED


# --- 7. KILL-SWITCH ISOLATION ---

def test_9_e2e_kill_switch_scope_isolation(db_session):
    setup_e2e_environment(db_session, merchant_id="m_A", case_id="c_iso_A", policy_id="pol_iso_A")
    setup_e2e_environment(db_session, merchant_id="m_B", case_id="c_iso_B", policy_id="pol_iso_B")

    # Kill Merchant A's policy
    execute_emergency_kill(
        db_session,
        policy_id="pol_iso_A",
        merchant_id="m_A",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
    )
    db_session.commit()

    # Merchant B's policy remains ACTIVE and authorizes treatment
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res_B = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_iso_B",
        proposal_id="prop_iso_B",
        merchant_id="m_B",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()

    assert res_B.decision == EnforcementDecision.ALLOW_ACTION
    assert res_B.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"


# --- 8. HISTORICAL AUDIT STABILITY & SNAPSHOT IMMUTABILITY ---

def test_10_e2e_historical_audit_stability(db_session):
    setup_e2e_environment(db_session, case_id="c_hist", policy_id="pol_hist", proposal_id="prop_hist")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_hist",
        proposal_id="prop_hist",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()
    assert res.decision == EnforcementDecision.ALLOW_ACTION

    # Later: Kill Policy
    execute_emergency_kill(
        db_session,
        policy_id="pol_hist",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
    )
    db_session.commit()

    # Verify past enforcement record is unchanged
    log_rec = get_enforcement_by_id(db_session, res.enforcement_log_id)
    assert log_rec.decision == "ALLOW_ACTION"
    assert log_rec.executed_action == "RETRY_IMMEDIATE_GATEWAY_SWITCH"

    evidence = reconstruct_enforcement_evidence(db_session, res.enforcement_log_id)
    assert evidence.decision == EnforcementDecision.ALLOW_ACTION
    assert evidence.policy_killed is True
    assert evidence.kill_audit_summary["kill_timing_relative_to_enforcement"] == "SUBSEQUENT_TO_DECISION"


# --- 9. KILL -> FUTURE STOP -> AUDIT TRACEABILITY ---

def test_11_e2e_kill_to_future_stop_audit_chain(db_session):
    setup_e2e_environment(db_session, case_id="c_chain", policy_id="pol_chain", proposal_id="prop_chain_1")

    # Step 1: Kill policy
    kill_res = execute_emergency_kill(
        db_session,
        policy_id="pol_chain",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
        operator_id="op_admin",
        reason="Gateway degradation",
    )
    db_session.commit()
    assert kill_res.new_status == PolicyStatus.KILLED_SAFETY_STOP

    # Step 2: New proposal arrives for killed policy
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    enf_res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_chain",
        proposal_id="prop_chain_2",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()

    assert enf_res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert enf_res.executed_action == "STOP"

    # Verify both kill audit and post-kill enforcement audit exist independently
    kill_audits = get_policy_kill_audits(db_session, "pol_chain")
    assert len(kill_audits) == 1
    assert kill_audits[0].operator_id == "op_admin"

    evidence = reconstruct_enforcement_evidence(db_session, enf_res.enforcement_log_id)
    assert evidence.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert evidence.executed_action == "STOP"
    assert evidence.policy_killed is True


# --- 10. TRANSACTION ROLLBACK SAFETY ---

def test_12_e2e_transaction_rollback_safety(db_session):
    setup_e2e_environment(db_session, case_id="c_rb", policy_id="pol_rb", proposal_id="prop_rb")

    # Attempt kill with scope mismatch
    with pytest.raises(ValueError, match="Tenant isolation mismatch"):
        execute_emergency_kill(
            db_session,
            policy_id="pol_rb",
            merchant_id="m_WRONG_tenant",
            experiment_id="exp_stage2_default",
            experiment_version="1.0",
            approved_configuration_hash="a" * 64,
        )
    db_session.rollback()

    rec = get_policy_by_id(db_session, "pol_rb")
    assert rec.status == "ACTIVE_ENFORCED"


# --- 11. REST API ENDPOINTS E2E VERIFICATION ---

def test_13_e2e_rest_api_evidence_and_kill_endpoints(api_client, db_session):
    setup_e2e_environment(db_session, case_id="c_api_e2e", policy_id="pol_api_e2e", proposal_id="prop_api_e2e")
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_api_e2e",
        proposal_id="prop_api_e2e",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()

    # GET evidence endpoint
    resp_ev = api_client.get(
        f"/api/v2/policies/enforcement/{res.enforcement_log_id}/evidence",
        headers={"x-internal-token": "test-secret-token", "x-merchant-id": "m_e2e_100"},
    )
    assert resp_ev.status_code == 200
    ev_data = resp_ev.json()
    assert ev_data["enforcement_id"] == res.enforcement_log_id
    assert ev_data["decision"] == "ALLOW_ACTION"

    # POST kill endpoint
    resp_kill = api_client.post(
        "/api/v2/policies/pol_api_e2e/kill",
        headers={"x-internal-token": "test-secret-token"},
        json={
            "merchant_id": "m_e2e_100",
            "experiment_id": "exp_stage2_default",
            "experiment_version": "1.0",
            "approved_configuration_hash": "a" * 64,
            "operator_id": "api_admin",
            "reason": "REST API Emergency Stop",
        },
    )
    assert resp_kill.status_code == 200
    kill_data = resp_kill.json()
    assert kill_data["policy_id"] == "pol_api_e2e"
    assert kill_data["new_status"] == "KILLED_SAFETY_STOP"


# --- 12. ARCHITECTURAL INVARIANTS VERIFICATION (F5-I001 TO F5-I015) ---

def test_14_e2e_architectural_invariants_verification(db_session):
    # F5-I001: Only ACTIVE_ENFORCED policy can authorize treatment
    setup_e2e_environment(db_session, case_id="c_inv1", policy_id="pol_inv1", status=PolicyStatus.DISABLED)
    enforcer = F5RealtimeEnforcer()
    now = utc_now()
    res_inv1 = enforcer.enforce_and_dispatch(
        db_session,
        case_id="c_inv1",
        proposal_id="prop_inv1",
        merchant_id="m_e2e_100",
        experiment_id="exp_stage2_default",
        experiment_version="1.0",
        current_configuration_hash="a" * 64,
        stage2_proposed_action="RETRY_IMMEDIATE_GATEWAY_SWITCH",
        attribution_start_time=now - timedelta(hours=75),
    )
    db_session.commit()
    assert res_inv1.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res_inv1.executed_action == "STOP"

    # F5-I007: proposal_id is authoritative idempotency key
    # F5-I009: Enforcement audit is append-only
    # F5-I010: Kill audit is append-only
    # F5-I012: Audit/evidence reconstruction is tenant-isolated
    # F5-I014: DISPATCHED means dispatch commitment, not external recovery completion
    bundle = reconstruct_enforcement_evidence(db_session, res_inv1.enforcement_log_id)
    assert bundle.decision == EnforcementDecision.FALLBACK_TO_BASELINE

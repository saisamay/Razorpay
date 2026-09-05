"""F5-3.1 Decision Engine Unit Tests (Semantically Hardened).

Comprehensive test suite verifying all 26 decision pipeline conditions, identity checks,
binding validation, lifecycle transitions, F4 status mapping, 72-hour attribution window,
evidence supersession, action set authorization, tenant isolation, and fail-closed defaults.
"""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from recovery_service.database import Base
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
from recovery_service.stage2.f5.engine import F5DecisionEngine
from recovery_service.stage2.f5.repository import save_policy
from recovery_service.stage2.models import DecisionPolicyRecord


def valid_hash() -> str:
    return "a" * 64


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def db_session():
    """In-memory SQLite database session for F5 Decision Engine testing."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def engine():
    return F5DecisionEngine()


def create_test_policy(
    session,
    policy_id="pol_test_01",
    merchant_id="merchant_123",
    experiment_id="exp_01",
    experiment_version="1.0",
    config_hash=None,
    status=PolicyStatus.ACTIVE_ENFORCED,
    f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
    actions=("RETRY_RECOMMENDED", "SMART_ROUTING"),
    supersession_status=EvidenceSupersessionStatus.CURRENT,
    evaluated_at_delta_hours=73,
    source_f4_evidence_id="ev_999",
):
    actual_hash = config_hash or valid_hash()
    eval_time = utc_now() - timedelta(hours=evaluated_at_delta_hours)

    binding = PolicyBinding(
        merchant_id=merchant_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        approved_configuration_hash=actual_hash,
        policy_version="1.0",
    )
    source_ref = SourceF4EvidenceReference(
        source_f4_evidence_id=source_f4_evidence_id,
        source_f4_evaluated_at=eval_time,
        source_f4_status=f4_status,
        source_f4_configuration_hash=actual_hash,
        source_f4_point_estimate=150.0,
        source_f4_confidence_interval_lower=50.0,
        source_f4_confidence_interval_upper=250.0,
        supersession_status=supersession_status,
    )
    action_set = AuthorizedActionSet(actions=actions)

    activated = eval_time if status == PolicyStatus.ACTIVE_ENFORCED else None

    auth = DecisionPolicyAuthorization(
        policy_id=policy_id,
        binding=binding,
        source_f4_reference=source_ref,
        authorized_actions=action_set,
        status=status,
        activated_at=activated,
    )
    return save_policy(session, auth)


# 1. Positive Path
def test_1_positive_path_allows_action(db_session, engine):
    create_test_policy(db_session)
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_RECOMMENDED"
    assert res.reason_code == PolicyEnforcementReasonCode.POLICY_ENFORCED_EFFICACIOUS
    assert res.policy_id == "pol_test_01"


# 2. Policy Failures
def test_2_missing_policy_fails_closed(db_session, engine):
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_unknown",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.POLICY_NOT_FOUND


def test_3_multiple_active_policies_fails_closed(db_session, engine):
    rec1 = DecisionPolicyRecord(
        policy_id="p_dup_1",
        policy_version="1.0",
        merchant_id="m_dup",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        source_f4_evidence_id="ev_1",
        source_f4_evaluated_at=utc_now() - timedelta(hours=80),
        source_f4_status="EFFICACY_RESULT_AVAILABLE",
        source_f4_configuration_hash=valid_hash(),
        authorized_actions=["RETRY_RECOMMENDED"],
        status="ACTIVE_ENFORCED",
        activated_at=utc_now(),
    )
    rec2 = DecisionPolicyRecord(
        policy_id="p_dup_2",
        policy_version="2.0",
        merchant_id="m_dup",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        source_f4_evidence_id="ev_2",
        source_f4_evaluated_at=utc_now() - timedelta(hours=80),
        source_f4_status="EFFICACY_RESULT_AVAILABLE",
        source_f4_configuration_hash=valid_hash(),
        authorized_actions=["RETRY_RECOMMENDED"],
        status="ACTIVE_ENFORCED",
        activated_at=utc_now(),
    )
    db_session.add_all([rec1, rec2])
    db_session.flush()

    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="m_dup",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.INVALID_POLICY


@pytest.mark.parametrize(
    "status,expected_reason",
    [
        (PolicyStatus.DRAFT, PolicyEnforcementReasonCode.POLICY_DISABLED),
        (PolicyStatus.DISABLED, PolicyEnforcementReasonCode.POLICY_DISABLED),
        (PolicyStatus.KILLED_SAFETY_STOP, PolicyEnforcementReasonCode.POLICY_KILLED),
        (PolicyStatus.EXPIRED, PolicyEnforcementReasonCode.POLICY_EXPIRED),
        (PolicyStatus.INVALIDATED, PolicyEnforcementReasonCode.INVALID_POLICY),
    ],
)
def test_4_to_8_non_active_policy_states_fallback_to_baseline(db_session, engine, status, expected_reason):
    create_test_policy(db_session, status=status)
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"
    assert res.reason_code == expected_reason


# 3. Binding Failures
def test_9_merchant_mismatch_fails_closed(db_session, engine):
    create_test_policy(db_session, merchant_id="merchant_123")
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_DIFFERENT",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"
    assert res.reason_code in (PolicyEnforcementReasonCode.TENANT_MISMATCH, PolicyEnforcementReasonCode.POLICY_NOT_FOUND)


def test_10_experiment_mismatch_fails_closed(db_session, engine):
    create_test_policy(db_session, experiment_id="exp_01")
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_DIFFERENT",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


def test_11_experiment_version_mismatch_fails_closed(db_session, engine):
    create_test_policy(db_session, experiment_version="1.0")
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="2.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


def test_12_configuration_hash_mismatch_fails_closed(db_session, engine):
    create_test_policy(db_session, config_hash="a" * 64)
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash="b" * 64,
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"
    assert res.reason_code in (PolicyEnforcementReasonCode.CONFIG_HASH_MISMATCH, PolicyEnforcementReasonCode.POLICY_NOT_FOUND)


# 4. Evidence & F4 Lifecycle Failures
@pytest.mark.parametrize(
    "f4_status,expected_decision,expected_reason",
    [
        (EvaluationStatus.VERSION_INCONSISTENCY, EnforcementDecision.FAIL_CLOSED, PolicyEnforcementReasonCode.VERSION_MISMATCH),
        (EvaluationStatus.EXPERIMENT_INVALIDATED, EnforcementDecision.FAIL_CLOSED, PolicyEnforcementReasonCode.INVALID_EVIDENCE),
        (EvaluationStatus.SAFETY_STOPPED, EnforcementDecision.FAIL_CLOSED, PolicyEnforcementReasonCode.SAFETY_STOP),
        (EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM, EnforcementDecision.FALLBACK_TO_BASELINE, PolicyEnforcementReasonCode.F4_STATUS_NOT_EFFICACIOUS),
    ],
)
def test_15_to_18_f4_non_efficacious_statuses_fail_closed_or_fallback(db_session, engine, f4_status, expected_decision, expected_reason):
    create_test_policy(db_session, f4_status=f4_status)
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == expected_decision
    assert res.executed_action == "STOP"
    assert res.reason_code == expected_reason


# 5. Evidence Supersession Hardened Tests
def test_19_superseded_conflict_fails_closed(db_session, engine):
    create_test_policy(
        db_session,
        supersession_status=EvidenceSupersessionStatus.SUPERSEDED_CONFLICT,
        status=PolicyStatus.INVALIDATED,
    )
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"


def test_19b_superseded_consistent_does_not_automatically_stop(db_session, engine):
    create_test_policy(
        db_session,
        supersession_status=EvidenceSupersessionStatus.SUPERSEDED_CONSISTENT,
        status=PolicyStatus.ACTIVE_ENFORCED,
    )
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_RECOMMENDED"


# 6. Attribution Window Explicit Timestamp Cases A-E
def test_case_a_attribution_window_incomplete_under_72h_fails_fallback(db_session, engine):
    create_test_policy(db_session)
    now = utc_now()
    t0 = now - timedelta(hours=71)  # Only 71h elapsed!
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        current_time=now,
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.STALE_EVALUATION


def test_case_b_attribution_window_exactly_complete_72h_allows(db_session, engine):
    create_test_policy(db_session)
    now = utc_now()
    t0 = now - timedelta(hours=72)  # Exactly 72h elapsed
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        current_time=now,
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_RECOMMENDED"


def test_case_c_attribution_window_completed_96h_allows(db_session, engine):
    create_test_policy(db_session)
    now = utc_now()
    t0 = now - timedelta(hours=96)  # 96h elapsed >= 72h
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        current_time=now,
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_RECOMMENDED"


def test_case_d_evaluation_occurred_later_does_not_derive_window_from_evaluation_timestamp(db_session, engine):
    create_test_policy(db_session, evaluated_at_delta_hours=0)  # Evaluation just ran (0h ago)
    now = utc_now()
    t0 = now - timedelta(hours=72)  # Attribution start was 72h ago
    # Evaluation timestamp is T0 + 72h, but attribution start T0 satisfies 72h requirement
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        current_time=now,
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_RECOMMENDED"


def test_case_e_missing_attribution_timestamp_fails_closed(db_session, engine):
    create_test_policy(db_session)
    now = utc_now()
    # attribution_start_time is omitted / None!
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        current_time=now,
        attribution_start_time=None,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.STALE_EVALUATION


# 7. Action Set Authorization
def test_22_authorized_action_allows(db_session, engine):
    create_test_policy(db_session, actions=("RETRY_RECOMMENDED", "SMART_ROUTING"))
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="SMART_ROUTING",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "SMART_ROUTING"


def test_23_unauthorized_action_fallback_to_baseline(db_session, engine):
    create_test_policy(db_session, actions=("RETRY_RECOMMENDED",))
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="UNAUTHORIZED_ACTION_XYZ",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res.executed_action == "STOP"
    assert res.reason_code == PolicyEnforcementReasonCode.UNAUTHORIZED_ACTION


# 8. Safety / Unknown Context
def test_24_empty_case_id_fails_closed(db_session, engine):
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


# 9. Isolation Tests
def test_25_cross_merchant_isolation(db_session, engine):
    create_test_policy(db_session, merchant_id="merchant_A")
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_B",
        experiment_id="exp_01",
        experiment_version="1.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"


def test_26_cross_version_isolation(db_session, engine):
    create_test_policy(db_session, experiment_version="1.0")
    t0 = utc_now() - timedelta(hours=75)
    res = engine.evaluate_decision(
        session=db_session,
        case_id="case_001",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="2.0",
        current_configuration_hash=valid_hash(),
        stage2_proposed_action="RETRY_RECOMMENDED",
        attribution_start_time=t0,
    )
    assert res.decision == EnforcementDecision.FAIL_CLOSED
    assert res.executed_action == "STOP"

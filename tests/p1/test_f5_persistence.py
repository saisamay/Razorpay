"""F5-2.1 Hardened Policy Persistence & Repository Unit Tests.

Verifies DB persistence of DecisionPolicyRecord and PolicyEnforcementLogRecord,
binding integrity, F4 provenance validation, AuthorizedActionSet round-tripping,
single active policy invariant, terminal state transition safety, evidence supersession tracking,
and append-only enforcement log auditing.
"""

from datetime import datetime, timezone
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
    PolicyEnforcementResult,
    PolicyStatus,
    SourceF4EvidenceReference,
)
from recovery_service.stage2.f5.repository import (
    enforcement_log_record_to_contract,
    get_active_policy_for_binding,
    get_enforcement_logs_by_case,
    get_policy_by_id,
    policy_record_to_contract,
    save_enforcement_log,
    save_policy,
    update_policy_status,
)
from recovery_service.stage2.models import DecisionPolicyRecord


def valid_hash() -> str:
    return "a" * 64


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def db_session():
    """Creates an in-memory SQLite database session with Base metadata created."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


def test_save_and_reload_valid_policy(db_session):
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    source_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
        source_f4_point_estimate=125.5,
        source_f4_confidence_interval_lower=25.0,
        source_f4_confidence_interval_upper=225.0,
        statistical_limitations=["MAR assumption"],
    )
    action_set = AuthorizedActionSet(actions=("SMART_ROUTING", "RETRY_RECOMMENDED"))

    auth = DecisionPolicyAuthorization(
        policy_id="pol_100",
        binding=binding,
        source_f4_reference=source_ref,
        authorized_actions=action_set,
        status=PolicyStatus.ACTIVE_ENFORCED,
        activated_at=utc_now(),
    )

    record = save_policy(db_session, auth)
    assert record.policy_id == "pol_100"

    reloaded_contract = policy_record_to_contract(record)
    assert reloaded_contract.policy_id == "pol_100"
    assert reloaded_contract.binding.merchant_id == "merchant_123"
    assert reloaded_contract.binding.approved_configuration_hash == valid_hash()
    assert reloaded_contract.authorized_actions.actions == ("RETRY_RECOMMENDED", "SMART_ROUTING")
    assert reloaded_contract.status == PolicyStatus.ACTIVE_ENFORCED


def test_save_policy_rejects_hash_mismatch(db_session):
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
        policy_version="1.0",
    )
    source_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash="b" * 64,  # Mismatch!
    )
    action_set = AuthorizedActionSet(actions=("RETRY_RECOMMENDED",))

    with pytest.raises(Exception, match="approved_configuration_hash must match source F4 evidence configuration hash"):
        DecisionPolicyAuthorization(
            policy_id="pol_100",
            binding=binding,
            source_f4_reference=source_ref,
            authorized_actions=action_set,
            status=PolicyStatus.DRAFT,
        )


def test_single_active_policy_per_binding_enforced(db_session):
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    source_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
    )
    action_set = AuthorizedActionSet(actions=("RETRY_RECOMMENDED",))

    # P1 saved as ACTIVE_ENFORCED
    auth1 = DecisionPolicyAuthorization(
        policy_id="pol_01",
        binding=binding,
        source_f4_reference=source_ref,
        authorized_actions=action_set,
        status=PolicyStatus.ACTIVE_ENFORCED,
        activated_at=utc_now(),
    )
    save_policy(db_session, auth1)

    # Attempting to save P2 as ACTIVE_ENFORCED for exact same binding must fail
    binding_v2 = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="2.0",  # Different policy_version!
    )
    auth2 = DecisionPolicyAuthorization(
        policy_id="pol_02",
        binding=binding_v2,
        source_f4_reference=source_ref,
        authorized_actions=action_set,
        status=PolicyStatus.ACTIVE_ENFORCED,
        activated_at=utc_now(),
    )

    with pytest.raises(ValueError, match="Single active policy invariant breach"):
        save_policy(db_session, auth2)


def test_get_active_policy_multiple_records_fails_closed(db_session):
    """Directly insert two ACTIVE_ENFORCED rows to test fail-closed detection."""
    rec1 = DecisionPolicyRecord(
        policy_id="pol_dup_1",
        policy_version="1.0",
        merchant_id="m_dup",
        experiment_id="exp_dup",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        treatment_arm_definition="STAGE2_DECISION_PROPOSAL",
        source_f4_evidence_id="ev_dup_1",
        source_f4_evaluated_at=utc_now(),
        source_f4_status="EFFICACY_RESULT_AVAILABLE",
        source_f4_configuration_hash=valid_hash(),
        authorized_actions=["RETRY_RECOMMENDED"],
        baseline_action="STOP",
        status="ACTIVE_ENFORCED",
        activated_at=utc_now(),
    )
    rec2 = DecisionPolicyRecord(
        policy_id="pol_dup_2",
        policy_version="2.0",
        merchant_id="m_dup",
        experiment_id="exp_dup",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        treatment_arm_definition="STAGE2_DECISION_PROPOSAL",
        source_f4_evidence_id="ev_dup_2",
        source_f4_evaluated_at=utc_now(),
        source_f4_status="EFFICACY_RESULT_AVAILABLE",
        source_f4_configuration_hash=valid_hash(),
        authorized_actions=["RETRY_RECOMMENDED"],
        baseline_action="STOP",
        status="ACTIVE_ENFORCED",
        activated_at=utc_now(),
    )
    db_session.add_all([rec1, rec2])
    db_session.flush()

    with pytest.raises(ValueError, match="Integrity failure: multiple \\(2\\) ACTIVE_ENFORCED policies found"):
        get_active_policy_for_binding(db_session, "m_dup", "exp_dup", "1.0", valid_hash())


def test_terminal_lifecycle_states_cannot_reactivate(db_session):
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    source_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
    )
    action_set = AuthorizedActionSet(actions=("RETRY_RECOMMENDED",))

    auth = DecisionPolicyAuthorization(
        policy_id="pol_terminal",
        binding=binding,
        source_f4_reference=source_ref,
        authorized_actions=action_set,
        status=PolicyStatus.DRAFT,
    )
    save_policy(db_session, auth)

    # Disable it via KILLED_SAFETY_STOP
    update_policy_status(db_session, "pol_terminal", PolicyStatus.KILLED_SAFETY_STOP)

    # Attempting to reactivate to ACTIVE_ENFORCED must fail
    with pytest.raises(ValueError, match="cannot transition to ACTIVE_ENFORCED"):
        update_policy_status(db_session, "pol_terminal", PolicyStatus.ACTIVE_ENFORCED, activated_at=utc_now())


def test_action_set_canonical_sorting_persisted(db_session):
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    source_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
    )
    action_set = AuthorizedActionSet(actions=("SMART_ROUTING", "ALTERNATIVE_PAYMENT", "SMART_ROUTING", "RETRY_RECOMMENDED"))

    auth = DecisionPolicyAuthorization(
        policy_id="pol_action_sort",
        binding=binding,
        source_f4_reference=source_ref,
        authorized_actions=action_set,
        status=PolicyStatus.DRAFT,
    )

    record = save_policy(db_session, auth)
    reloaded = policy_record_to_contract(record)
    assert reloaded.authorized_actions.actions == ("ALTERNATIVE_PAYMENT", "RETRY_RECOMMENDED", "SMART_ROUTING")
    assert reloaded.authorized_actions.contains("RETRY_RECOMMENDED")


def test_get_active_policy_for_binding_isolation(db_session):
    binding1 = PolicyBinding(
        merchant_id="merchant_A",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    source_ref1 = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_A",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
    )
    auth1 = DecisionPolicyAuthorization(
        policy_id="pol_A",
        binding=binding1,
        source_f4_reference=source_ref1,
        authorized_actions=AuthorizedActionSet(actions=("RETRY_RECOMMENDED",)),
        status=PolicyStatus.ACTIVE_ENFORCED,
        activated_at=utc_now(),
    )
    save_policy(db_session, auth1)

    # Query for merchant_A -> returns pol_A
    rec = get_active_policy_for_binding(db_session, "merchant_A", "exp_01", "1.0", valid_hash())
    assert rec is not None
    assert rec.policy_id == "pol_A"

    # Query for merchant_B -> returns None
    rec_b = get_active_policy_for_binding(db_session, "merchant_B", "exp_01", "1.0", valid_hash())
    assert rec_b is None


def test_save_and_retrieve_enforcement_log(db_session):
    res_allow = PolicyEnforcementResult(
        decision=EnforcementDecision.ALLOW_ACTION,
        reason_code=PolicyEnforcementReasonCode.POLICY_ENFORCED_EFFICACIOUS,
        policy_id="pol_100",
        policy_version="1.0",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        case_id="case_log_101",
        stage2_proposed_action="RETRY_RECOMMENDED",
        executed_action="RETRY_RECOMMENDED",
        source_f4_evidence_id="ev_99",
    )
    save_enforcement_log(db_session, res_allow, configuration_hash=valid_hash(), enforcement_id="enf_01")

    res_fallback = PolicyEnforcementResult(
        decision=EnforcementDecision.FALLBACK_TO_BASELINE,
        reason_code=PolicyEnforcementReasonCode.POLICY_DISABLED,
        policy_id="pol_100",
        policy_version="1.0",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        case_id="case_log_101",
        stage2_proposed_action="RETRY_RECOMMENDED",
        executed_action="STOP",
        source_f4_evidence_id="ev_99",
    )
    save_enforcement_log(db_session, res_fallback, configuration_hash=valid_hash(), enforcement_id="enf_02")

    logs = get_enforcement_logs_by_case(db_session, "case_log_101")
    assert len(logs) == 2
    assert logs[0].enforcement_id == "enf_01"
    assert logs[0].decision == EnforcementDecision.ALLOW_ACTION.value
    assert logs[0].executed_action == "RETRY_RECOMMENDED"

    assert logs[1].enforcement_id == "enf_02"
    assert logs[1].decision == EnforcementDecision.FALLBACK_TO_BASELINE.value
    assert logs[1].executed_action == "STOP"

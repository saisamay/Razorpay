"""F5-1.3 Contract & Policy Schema Unit & Invariant Tests.

Verifies F5 contract validation rules, enums, decision-reason consistency matrix,
fail-closed properties, F4 evidence reference integrity, evidence supersession semantics & ordering,
AuthorizedActionSet cardinality & canonical sorting, and contract invariants F5-I001 through F5-I013.
"""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from recovery_service.stage2.f4.contracts import EvaluationStatus
from recovery_service.stage2.f5.contracts import (
    AuthorizedActionSet,
    DecisionPolicyAuthorization,
    EnforcementDecision,
    EvidenceSupersessionStatus,
    F5_CONTRACT_INVARIANTS,
    PolicyBinding,
    PolicyEnforcementReasonCode,
    PolicyEnforcementResult,
    PolicyStatus,
    SourceF4EvidenceReference,
)


def valid_hash() -> str:
    return "a" * 64


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_valid_policy_binding():
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    assert binding.merchant_id == "merchant_123"
    assert binding.experiment_id == "exp_01"
    assert binding.experiment_version == "1.0"
    assert binding.approved_configuration_hash == valid_hash()
    assert binding.policy_version == "1.0"


def test_binding_provenance_exactness_no_normalization():
    binding = PolicyBinding(
        merchant_id="Merchant_CaseSensitive_123",
        experiment_id="Exp_CaseSensitive_01",
        experiment_version="1.0-beta",
        approved_configuration_hash=valid_hash(),
        policy_version="2.0-rc1",
    )
    assert binding.merchant_id == "Merchant_CaseSensitive_123"
    assert binding.experiment_id == "Exp_CaseSensitive_01"
    assert binding.experiment_version == "1.0-beta"
    assert binding.policy_version == "2.0-rc1"


def test_authorized_action_set_canonical_sorting_and_uniqueness():
    act_set = AuthorizedActionSet(actions=("SMART_ROUTING", "RETRY_RECOMMENDED", "SMART_ROUTING", "ALTERNATIVE_PAYMENT"))
    # Must deduplicate and canonically sort tuple
    assert act_set.actions == ("ALTERNATIVE_PAYMENT", "RETRY_RECOMMENDED", "SMART_ROUTING")
    assert act_set.contains("RETRY_RECOMMENDED")
    assert act_set.contains("SMART_ROUTING")
    assert not act_set.contains("UNAUTHORIZED_ACTION_XYZ")


def test_authorized_action_set_rejects_empty():
    with pytest.raises(ValidationError, match="AuthorizedActionSet actions cannot be empty"):
        AuthorizedActionSet(actions=())


def test_authorized_action_set_rejects_whitespace_element():
    with pytest.raises(ValidationError, match="action elements must be non-empty strings"):
        AuthorizedActionSet(actions=("RETRY_RECOMMENDED", "   "))


def test_valid_source_f4_evidence_reference_preserves_f4_enum():
    ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
        source_f4_point_estimate=150.0,
        source_f4_confidence_interval_lower=50.0,
        source_f4_confidence_interval_upper=250.0,
        statistical_limitations=["MAR assumption", "Propensity parameter uncertainty"],
    )
    assert ref.source_f4_evidence_id == "ev_99"
    assert isinstance(ref.source_f4_status, EvaluationStatus)
    assert ref.source_f4_status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE
    assert ref.supersession_status == EvidenceSupersessionStatus.CURRENT


def test_evidence_supersession_metadata_validation():
    with pytest.raises(ValidationError, match="Superseded F4 evidence reference must specify superseded_at timestamp"):
        SourceF4EvidenceReference(
            source_f4_evidence_id="ev_99",
            source_f4_evaluated_at=utc_now(),
            source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
            source_f4_configuration_hash=valid_hash(),
            superseding_f4_evidence_id="ev_100",
            superseded_at=None,  # Missing timestamp!
        )


def test_policy_authorization_rejects_active_status_on_conflicting_superseded_evidence():
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
        superseding_f4_evidence_id="ev_100",
        superseded_at=utc_now(),
        supersession_status=EvidenceSupersessionStatus.SUPERSEDED_CONFLICT,
    )
    act_set = AuthorizedActionSet(actions=("RETRY_RECOMMENDED",))

    with pytest.raises(ValidationError, match="Policy with conflicting superseding evidence cannot remain ACTIVE_ENFORCED"):
        DecisionPolicyAuthorization(
            policy_id="pol_100",
            binding=binding,
            source_f4_reference=ref,
            authorized_actions=act_set,
            status=PolicyStatus.ACTIVE_ENFORCED,  # Invalid when conflicting evidence exists!
            activated_at=utc_now(),
        )


def test_decision_policy_authorization_valid():
    binding = PolicyBinding(
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        approved_configuration_hash=valid_hash(),
        policy_version="1.0",
    )
    ref = SourceF4EvidenceReference(
        source_f4_evidence_id="ev_99",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash=valid_hash(),
    )
    act_set = AuthorizedActionSet(actions=("RETRY_RECOMMENDED",))

    auth = DecisionPolicyAuthorization(
        policy_id="pol_100",
        binding=binding,
        source_f4_reference=ref,
        authorized_actions=act_set,
        status=PolicyStatus.ACTIVE_ENFORCED,
        activated_at=utc_now(),
    )
    assert auth.policy_id == "pol_100"
    assert auth.status == PolicyStatus.ACTIVE_ENFORCED


def test_decision_reason_contradictions_allow_action_with_invalid_reasons():
    invalid_reasons_for_allow = [
        PolicyEnforcementReasonCode.CONFIG_HASH_MISMATCH,
        PolicyEnforcementReasonCode.POLICY_KILLED,
        PolicyEnforcementReasonCode.TENANT_MISMATCH,
        PolicyEnforcementReasonCode.VERSION_MISMATCH,
        PolicyEnforcementReasonCode.F4_STATUS_NOT_EFFICACIOUS,
        PolicyEnforcementReasonCode.STALE_EVALUATION,
        PolicyEnforcementReasonCode.MISSING_EVIDENCE,
        PolicyEnforcementReasonCode.INVALID_EVIDENCE,
        PolicyEnforcementReasonCode.POLICY_NOT_FOUND,
        PolicyEnforcementReasonCode.POLICY_DISABLED,
        PolicyEnforcementReasonCode.POLICY_EXPIRED,
        PolicyEnforcementReasonCode.SAFETY_STOP,
        PolicyEnforcementReasonCode.INVALID_POLICY,
        PolicyEnforcementReasonCode.UNAUTHORIZED_ACTION,
        PolicyEnforcementReasonCode.SUPERSEDED_BY_NEWER_EVIDENCE,
        PolicyEnforcementReasonCode.SUPERSEDING_EVIDENCE_CONFLICT,
    ]

    for rc in invalid_reasons_for_allow:
        with pytest.raises(ValidationError, match="Contradictory decision combination: ALLOW_ACTION cannot be paired with reason code"):
            PolicyEnforcementResult(
                decision=EnforcementDecision.ALLOW_ACTION,
                reason_code=rc,
                policy_id="pol_100",
                policy_version="1.0",
                merchant_id="merchant_123",
                experiment_id="exp_01",
                experiment_version="1.0",
                case_id="case_101",
                stage2_proposed_action="RETRY_RECOMMENDED",
                executed_action="RETRY_RECOMMENDED",
            )


def test_valid_allow_action_combination():
    res = PolicyEnforcementResult(
        decision=EnforcementDecision.ALLOW_ACTION,
        reason_code=PolicyEnforcementReasonCode.POLICY_ENFORCED_EFFICACIOUS,
        policy_id="pol_100",
        policy_version="1.0",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        case_id="case_101",
        stage2_proposed_action="RETRY_RECOMMENDED",
        executed_action="RETRY_RECOMMENDED",
        source_f4_evidence_id="ev_99",
    )
    assert res.decision == EnforcementDecision.ALLOW_ACTION
    assert res.executed_action == "RETRY_RECOMMENDED"
    assert res.reason_code == PolicyEnforcementReasonCode.POLICY_ENFORCED_EFFICACIOUS


def test_valid_fallback_and_fail_closed_combinations():
    res_fallback = PolicyEnforcementResult(
        decision=EnforcementDecision.FALLBACK_TO_BASELINE,
        reason_code=PolicyEnforcementReasonCode.POLICY_KILLED,
        policy_id="pol_100",
        policy_version="1.0",
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        case_id="case_101",
        stage2_proposed_action="RETRY_RECOMMENDED",
        executed_action="STOP",
    )
    assert res_fallback.decision == EnforcementDecision.FALLBACK_TO_BASELINE
    assert res_fallback.executed_action == "STOP"

    res_fail_closed = PolicyEnforcementResult(
        decision=EnforcementDecision.FAIL_CLOSED,
        reason_code=PolicyEnforcementReasonCode.CONFIG_HASH_MISMATCH,
        policy_id=None,
        policy_version=None,
        merchant_id="merchant_123",
        experiment_id="exp_01",
        experiment_version="1.0",
        case_id="case_101",
        stage2_proposed_action="RETRY_RECOMMENDED",
        executed_action="STOP",
    )
    assert res_fail_closed.decision == EnforcementDecision.FAIL_CLOSED
    assert res_fail_closed.executed_action == "STOP"


def test_f5_contract_invariants_registry():
    assert len(F5_CONTRACT_INVARIANTS) == 13
    ids = [inv.invariant_id for inv in F5_CONTRACT_INVARIANTS]
    for inv_num in range(1, 14):
        assert f"F5-I{inv_num:03d}" in ids

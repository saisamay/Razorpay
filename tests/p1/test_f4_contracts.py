from __future__ import annotations

import pytest
from pydantic import ValidationError

from recovery_service.stage2.f4 import (
    ArmType,
    ClusteredUncertaintyMetric,
    DifferentialAttrition,
    EstimandPopulation,
    EvaluationStatus,
    F4EvaluationReport,
    F4Observation,
    F4PrimaryResult,
    F4Provenance,
    F4SecondaryMetrics,
    MetricSemanticStatus,
    OutcomeState,
    PopulationAccounting,
    F4_INVARIANTS_REGISTRY,
    get_invariant,
    list_invariants,
)
from recovery_service.stage2.f4.contracts import (
    PRIMARY_METRIC_NAME,
    PRIMARY_POINT_ESTIMATOR_SYMBOL,
)


def test_valid_observations_accepted():
    """Verify valid observations for CONTROL and TREATMENT arms are accepted."""
    obs_ctrl = F4Observation(
        case_id="case_001",
        assignment_unit_id="cust_100",
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
        arm=ArmType.CONTROL,
        outcome_state=OutcomeState.RECOVERED,
        verified_revenue_subunits=1500,
        semantic_status=MetricSemanticStatus.VERIFIED,
    )
    assert obs_ctrl.case_id == "case_001"
    assert obs_ctrl.arm == ArmType.CONTROL
    assert obs_ctrl.verified_revenue_subunits == 1500

    obs_treat = F4Observation(
        case_id="case_002",
        assignment_unit_id="cust_101",
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
        arm=ArmType.TREATMENT,
        outcome_state=OutcomeState.PARTIALLY_RECOVERED,
        verified_revenue_subunits=2500,
        semantic_status=MetricSemanticStatus.VERIFIED,
    )
    assert obs_treat.arm == ArmType.TREATMENT
    assert obs_treat.verified_revenue_subunits == 2500


def test_outcome_state_frozen_vocabulary():
    """Verify all 7 frozen outcome vocabulary states exist."""
    expected_outcomes = {
        "NO_RECOVERY",
        "RECOVERED",
        "PARTIALLY_RECOVERED",
        "RECOVERED_THEN_REFUNDED",
        "RECOVERED_THEN_REVERSED",
        "OUTCOME_PENDING",
        "OUTCOME_UNKNOWN",
    }
    actual_outcomes = {o.value for o in OutcomeState}
    assert expected_outcomes == actual_outcomes


def test_assignment_unit_information_preserved():
    """Verify assignment_unit_id and assignment_unit_type fields are strictly preserved."""
    obs = F4Observation(
        case_id="case_100",
        assignment_unit_id="merchant_99_user_44",
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
        arm=ArmType.TREATMENT,
        outcome_state=OutcomeState.NO_RECOVERY,
        verified_revenue_subunits=0,
    )
    assert obs.assignment_unit_id == "merchant_99_user_44"
    assert obs.assignment_unit_type == "MERCHANT_SCOPED_CUSTOMER_STABLE"


def test_unknown_and_outcome_pending_semantics_preserved():
    """Verify OUTCOME_UNKNOWN and OUTCOME_PENDING states remain intact and cannot be coerced to 0."""
    obs_unk = F4Observation(
        case_id="case_unk",
        assignment_unit_id="cust_unk",
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
        arm=ArmType.CONTROL,
        outcome_state=OutcomeState.OUTCOME_UNKNOWN,
        semantic_status=MetricSemanticStatus.UNKNOWN,
    )
    assert obs_unk.outcome_state == OutcomeState.OUTCOME_UNKNOWN
    assert obs_unk.verified_revenue_subunits is None
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        obs_unk.numeric_revenue_or_raise()

    obs_pend = F4Observation(
        case_id="case_pend",
        assignment_unit_id="cust_pend",
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
        arm=ArmType.TREATMENT,
        outcome_state=OutcomeState.OUTCOME_PENDING,
        semantic_status=MetricSemanticStatus.OBSERVED,
    )
    assert obs_pend.outcome_state == OutcomeState.OUTCOME_PENDING
    assert obs_pend.verified_revenue_subunits is None
    with pytest.raises(ValueError, match="OUTCOME_PENDING"):
        obs_pend.numeric_revenue_or_raise()


def test_contradictory_semantic_combinations_rejected():
    """Reject contradictory combinations in F4Observation."""
    # 1. OUTCOME_UNKNOWN with VERIFIED semantic status
    with pytest.raises(ValidationError, match="cannot have MetricSemanticStatus.VERIFIED"):
        F4Observation(
            case_id="c1",
            assignment_unit_id="u1",
            assignment_unit_type="TYPE",
            arm=ArmType.CONTROL,
            outcome_state=OutcomeState.OUTCOME_UNKNOWN,
            semantic_status=MetricSemanticStatus.VERIFIED,
        )

    # 2. OUTCOME_PENDING with VERIFIED semantic status
    with pytest.raises(ValidationError, match="cannot have MetricSemanticStatus.VERIFIED"):
        F4Observation(
            case_id="c2",
            assignment_unit_id="u2",
            assignment_unit_type="TYPE",
            arm=ArmType.TREATMENT,
            outcome_state=OutcomeState.OUTCOME_PENDING,
            semantic_status=MetricSemanticStatus.VERIFIED,
        )

    # 3. Revenue attached to OUTCOME_UNKNOWN
    with pytest.raises(ValidationError, match="cannot have verified_revenue_subunits set"):
        F4Observation(
            case_id="c3",
            assignment_unit_id="u3",
            assignment_unit_type="TYPE",
            arm=ArmType.CONTROL,
            outcome_state=OutcomeState.OUTCOME_UNKNOWN,
            verified_revenue_subunits=1000,
        )

    # 4. Positive revenue with NO_RECOVERY
    with pytest.raises(ValidationError, match="Positive revenue .* contradicts OutcomeState.NO_RECOVERY"):
        F4Observation(
            case_id="c4",
            assignment_unit_id="u4",
            assignment_unit_type="TYPE",
            arm=ArmType.CONTROL,
            outcome_state=OutcomeState.NO_RECOVERY,
            verified_revenue_subunits=500,
        )


def test_full_semantic_status_vocabulary():
    """Verify all 10 metric semantic statuses exist and can be represented."""
    expected_statuses = {
        "OBSERVED",
        "PREDICTED",
        "PROPOSED",
        "ESTIMATED",
        "VERIFIED",
        "UNKNOWN",
        "INSUFFICIENT_DATA",
        "UNAVAILABLE",
        "STALE",
        "BLOCKED",
    }
    actual_statuses = {s.value for s in MetricSemanticStatus}
    assert expected_statuses == actual_statuses


def test_primary_metric_is_exactly_verified_incremental_recovered_revenue():
    """Verify primary metric is strictly VERIFIED_INCREMENTAL_RECOVERED_REVENUE."""
    unc = ClusteredUncertaintyMetric(
        standard_error=12.5,
        confidence_interval_lower=50.0,
        confidence_interval_upper=100.0,
        confidence_level=0.95,
        clustering_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
        clustering_unit_count=500,
    )
    res = F4PrimaryResult(
        point_estimate=75.0,
        allocation_proportion_p=0.5,
        eligible_population_count=1000,
        observed_population_count=980,
        uncertainty=unc,
    )
    assert res.primary_metric_name == PRIMARY_METRIC_NAME
    assert res.primary_metric_name == "VERIFIED_INCREMENTAL_RECOVERED_REVENUE"
    assert res.point_estimator_symbol == PRIMARY_POINT_ESTIMATOR_SYMBOL
    assert res.estimand_population == EstimandPopulation.PRE_REGISTERED_ELIGIBLE

    with pytest.raises(ValidationError, match="Primary metric name must strictly be"):
        F4PrimaryResult(
            primary_metric_name="RAW_REVENUE",
            point_estimate=75.0,
            allocation_proportion_p=0.5,
            eligible_population_count=1000,
            observed_population_count=980,
            uncertainty=unc,
        )


def test_secondary_metrics_structurally_separated():
    """Verify secondary metrics are structurally separate from primary result."""
    sec = F4SecondaryMetrics(
        conversion_rate_control=0.12,
        conversion_rate_treatment=0.15,
        recovery_count_control=120,
        recovery_count_treatment=150,
        average_latency_seconds_control=2.4,
        average_latency_seconds_treatment=2.1,
        raw_unverified_revenue_subunits=50000,
    )
    assert sec.conversion_rate_control == 0.12
    assert sec.raw_unverified_revenue_subunits == 50000


def test_uncertainty_mandatory_for_primary_result():
    """Verify F4PrimaryResult requires mandatory ClusteredUncertaintyMetric."""
    with pytest.raises(ValidationError, match="uncertainty"):
        F4PrimaryResult(
            point_estimate=100.0,
            allocation_proportion_p=0.5,
            eligible_population_count=100,
            observed_population_count=90,
        )


def test_differential_attrition_gap_validation():
    """Verify DifferentialAttrition gap validation rejects inconsistent gaps."""
    # Valid attrition
    attr = DifferentialAttrition(
        control_observation_rate=0.95,
        treatment_observation_rate=0.85,
        attrition_gap=0.10,
        configured_threshold=0.04,
    )
    assert attr.configured_threshold == 0.04
    assert attr.threshold_breached is True

    # Inconsistent gap must raise validation error
    with pytest.raises(ValidationError, match="Supplied attrition_gap .* does not match expected gap"):
        DifferentialAttrition(
            control_observation_rate=0.95,
            treatment_observation_rate=0.85,
            attrition_gap=0.50,  # Wrong! Expected 0.10
        )


def test_population_accounting_impossible_counts_rejected():
    """Verify PopulationAccounting rejects impossible counts where observed+pending+unknown > assigned."""
    attrition = DifferentialAttrition(
        control_observation_rate=0.95,
        treatment_observation_rate=0.95,
        attrition_gap=0.0,
    )

    # Impossible CONTROL sum
    with pytest.raises(ValidationError, match="CONTROL arm observed .* exceeds total assigned"):
        PopulationAccounting(
            total_assigned_control=100,
            total_assigned_treatment=100,
            observed_control=90,
            pending_control=15,
            unknown_control=5,  # 90+15+5 = 110 > 100
            observed_treatment=90,
            pending_treatment=5,
            unknown_treatment=5,
            differential_attrition=attrition,
        )

    # Impossible TREATMENT sum
    with pytest.raises(ValidationError, match="TREATMENT arm observed .* exceeds total assigned"):
        PopulationAccounting(
            total_assigned_control=100,
            total_assigned_treatment=100,
            observed_control=90,
            pending_control=5,
            unknown_control=5,
            observed_treatment=95,
            pending_treatment=10,
            unknown_treatment=0,  # 95+10+0 = 105 > 100
            differential_attrition=attrition,
        )


def test_exact_invariant_mapping():
    """Verify exact invariant naming for F4-I001 through F4-I031."""
    expected_mapping = {
        "F4-I001": "Primary Metric Immutability",
        "F4-I002": "Allocation-Adjusted Estimation",
        "F4-I003": "Mandatory Uncertainty",
        "F4-I004": "Frozen Population",
        "F4-I005": "Explicit Compliance-Block Handling",
        "F4-I006": "Outcome Semantic Preservation",
        "F4-I007": "UNKNOWN != 0",
        "F4-I008": "Verified-Only Primary Revenue",
        "F4-I009": "Differential Attrition Monitoring",
        "F4-I010": "Independent Safety Stopping",
        "F4-I011": "No Efficacy Claim from Safety-Stopped Partial Data",
        "F4-I012": "Fixed-Horizon Efficacy",
        "F4-I013": "Invalidation Handling",
        "F4-I014": "Version Consistency",
        "F4-I015": "No Cross-Version Pooling",
        "F4-I016": "Explicit Control-Arm Semantics",
        "F4-I017": "Net Verified Recovery",
        "F4-I018": "Attribution Window",
        "F4-I019": "Read-Only Upstream Behavior",
        "F4-I020": "Assignment-Unit Correlation",
        "F4-I021": "Denominator Preservation",
        "F4-I022": "Sourced Statistical Assumptions",
        "F4-I023": "Insufficient-Data Semantics",
        "F4-I024": "Tenant Isolation",
        "F4-I025": "Primary-Metric Data-Loss Invalidation",
        "F4-I026": "Timestamp Integrity",
        "F4-I027": "Configuration-Hash Integrity",
        "F4-I028": "Contamination Handling",
        "F4-I029": "Outcome-Linkage Integrity",
        "F4-I030": "Verified-Only Primary Result",
        "F4-I031": "Secondary Metrics Structurally Subordinate",
    }

    assert len(F4_INVARIANTS_REGISTRY) == 31
    for code, expected_name in expected_mapping.items():
        inv = get_invariant(code)
        assert inv is not None, f"Invariant {code} missing from registry"
        assert inv.name == expected_name, f"Invariant {code} name mismatch: expected '{expected_name}', got '{inv.name}'"

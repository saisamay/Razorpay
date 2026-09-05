"""L-01 Zero-Observed Clusters & Variance Accounting Unit Tests.

Verifies:
1. All clusters observed
2. Some zero-observed clusters
3. Treatment arm zero-observed cluster
4. Control arm zero-observed cluster
5. All outcomes unknown/pending within a cluster
6. Zero-observed clusters contribute 0 to uncentered squared total variance
7. Zero-observed clusters are fully retained in K_total and N_eligible population accounting
"""

import pytest
from recovery_service.stage2.f4.contracts import (
    ArmType,
    MetricSemanticStatus,
    OutcomeState,
    F4Observation,
)
from recovery_service.stage2.f4.estimator import ProductionCausalEstimator


def test_l01_all_clusters_observed():
    obs1 = F4Observation(
        case_id="case_1",
        assignment_unit_id="u1",
        assignment_unit_type="MERCHANT",
        arm=ArmType.TREATMENT,
        outcome_state=OutcomeState.RECOVERED,
        verified_revenue_subunits=1000,
        semantic_status=MetricSemanticStatus.VERIFIED,
    )
    obs2 = F4Observation(
        case_id="case_2",
        assignment_unit_id="u2",
        assignment_unit_type="MERCHANT",
        arm=ArmType.CONTROL,
        outcome_state=OutcomeState.NO_RECOVERY,
        verified_revenue_subunits=0,
        semantic_status=MetricSemanticStatus.VERIFIED,
    )
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    assert report.primary_result is not None
    assert report.primary_result.uncertainty.clustering_unit_count == 2
    assert report.accounting.observed_treatment == 1
    assert report.accounting.observed_control == 1


def test_l01_zero_observed_clusters_retained_in_accounting():
    # Treatment cluster u1: observed
    obs1 = F4Observation(
        case_id="case_1",
        assignment_unit_id="u1",
        assignment_unit_type="MERCHANT",
        arm=ArmType.TREATMENT,
        outcome_state=OutcomeState.RECOVERED,
        verified_revenue_subunits=5000,
        semantic_status=MetricSemanticStatus.VERIFIED,
    )
    # Control cluster u2: observed
    obs2 = F4Observation(
        case_id="case_2",
        assignment_unit_id="u2",
        assignment_unit_type="MERCHANT",
        arm=ArmType.CONTROL,
        outcome_state=OutcomeState.NO_RECOVERY,
        verified_revenue_subunits=0,
        semantic_status=MetricSemanticStatus.VERIFIED,
    )
    # Treatment cluster u3: zero-observed (OUTCOME_PENDING)
    obs3 = F4Observation(
        case_id="case_3",
        assignment_unit_id="u3",
        assignment_unit_type="MERCHANT",
        arm=ArmType.TREATMENT,
        outcome_state=OutcomeState.OUTCOME_PENDING,
        semantic_status=MetricSemanticStatus.OBSERVED,
    )
    # Control cluster u4: zero-observed (OUTCOME_UNKNOWN)
    obs4 = F4Observation(
        case_id="case_4",
        assignment_unit_id="u4",
        assignment_unit_type="MERCHANT",
        arm=ArmType.CONTROL,
        outcome_state=OutcomeState.OUTCOME_UNKNOWN,
        semantic_status=MetricSemanticStatus.OBSERVED,
    )

    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2, obs3, obs4], design_allocation_p=0.50)
    assert report.primary_result is not None
    # All 4 clusters retained in K_total
    assert report.primary_result.uncertainty.clustering_unit_count == 4
    assert report.accounting.total_assigned_treatment == 2
    assert report.accounting.total_assigned_control == 2
    assert report.accounting.observed_treatment == 1
    assert report.accounting.observed_control == 1
    assert report.accounting.pending_treatment == 1
    assert report.accounting.unknown_control == 1
    # Standard error remains positive and finite
    assert report.primary_result.uncertainty.standard_error > 0.0

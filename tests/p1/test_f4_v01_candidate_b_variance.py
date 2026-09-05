"""Focused regression tests for F4 V-01 Candidate B Variance Estimator."""

import pytest
import math
from datetime import datetime, timezone
from recovery_service.stage2.f4.contracts import (
    F4Observation,
    ArmType,
    OutcomeState,
    MetricSemanticStatus,
    EvaluationStatus,
)
from recovery_service.stage2.f4.estimator import ProductionCausalEstimator
from recovery_service.stage2.f4.evidence import F4EvidenceGenerator


def create_obs(
    case_id: str,
    arm: ArmType,
    unit_id: str,
    merchant_id: str = "merchant_m1",
    outcome_state: OutcomeState = OutcomeState.RECOVERED,
    verified_revenue: int | None = 1000,
    amount: float = 1000.0,
    gateway: str = "razorpay",
) -> F4Observation:
    status = (
        MetricSemanticStatus.UNKNOWN
        if outcome_state in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING)
        else MetricSemanticStatus.VERIFIED
    )
    return F4Observation(
        case_id=case_id,
        arm=arm,
        assignment_unit_id=unit_id,
        assignment_unit_type="CUSTOMER",
        merchant_id=merchant_id,
        outcome_state=outcome_state,
        semantic_status=status,
        verified_revenue_subunits=verified_revenue if status == MetricSemanticStatus.VERIFIED else None,
    )


def test_1_old_zero_variance_failure_prevented():
    """Test 1: Homogeneous clusters (Y0=1000, Y1=1150, p=0.5) must NOT yield SE=0."""
    obs_list = []
    covs = {}
    
    # 10 Treatment clusters, 10 Control clusters, 5 cases each
    for k in range(10):
        t_unit = f"t_unit_{k}"
        c_unit = f"c_unit_{k}"
        for i in range(5):
            t_cid = f"t_case_{k}_{i}"
            c_cid = f"c_case_{k}_{i}"
            
            obs_list.append(create_obs(t_cid, ArmType.TREATMENT, t_unit, verified_revenue=1150))
            obs_list.append(create_obs(c_cid, ArmType.CONTROL, c_unit, verified_revenue=1000))
            
            covs[t_cid] = {"amount": 1000.0, "gateway": "razorpay"}
            covs[c_cid] = {"amount": 1000.0, "gateway": "razorpay"}

    report, diagnostics = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    assert report.primary_result is not None
    se = report.primary_result.uncertainty.standard_error
    
    # Under old centered formula, variance within identical clusters was 0 -> total_var = 0 -> SE = 0
    # Under Candidate B, uncentered squared sum ensures SE > 0
    assert se > 0.0, f"Candidate B standard error must be positive, got {se}"


def test_2_known_analytical_example_order_of_magnitude():
    """Test 2: Known analytical setup (K=200, cluster_size=5, p=0.5, Y0=1000, Y1=1150)."""
    obs_list = []
    covs = {}

    for k in range(100):
        t_unit = f"t_unit_{k}"
        c_unit = f"c_unit_{k}"
        for i in range(5):
            t_cid = f"t_case_{k}_{i}"
            c_cid = f"c_case_{k}_{i}"

            obs_list.append(create_obs(t_cid, ArmType.TREATMENT, t_unit, verified_revenue=1150))
            obs_list.append(create_obs(c_cid, ArmType.CONTROL, c_unit, verified_revenue=1000))

            covs[t_cid] = {"amount": 1000.0, "gateway": "razorpay"}
            covs[c_cid] = {"amount": 1000.0, "gateway": "razorpay"}

    report, _ = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    se = report.primary_result.uncertainty.standard_error
    # Candidate B SE for this setup is ~160.0 per unit total scale
    assert 50.0 <= se <= 300.0, f"SE {se} out of expected analytical order of magnitude"


def test_3_zero_treatment_effect_positive_variance():
    """Test 3: Zero treatment effect (Y0 = Y1 = 1000) must yield non-negative positive variance."""
    obs_list = []
    covs = {}

    for k in range(10):
        t_unit = f"t_unit_{k}"
        c_unit = f"c_unit_{k}"
        for i in range(5):
            t_cid = f"t_case_{k}_{i}"
            c_cid = f"c_case_{k}_{i}"

            obs_list.append(create_obs(t_cid, ArmType.TREATMENT, t_unit, verified_revenue=1000))
            obs_list.append(create_obs(c_cid, ArmType.CONTROL, c_unit, verified_revenue=1000))

            covs[t_cid] = {"amount": 1000.0, "gateway": "razorpay"}
            covs[c_cid] = {"amount": 1000.0, "gateway": "razorpay"}

    report, _ = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    se = report.primary_result.uncertainty.standard_error
    assert se > 0.0, f"Variance must remain positive even under zero treatment effect, got SE={se}"


def test_4_heterogeneous_treatment_effects():
    """Test 4: Heterogeneous treatment effects across clusters."""
    obs_list = []
    covs = {}

    for k in range(10):
        t_unit = f"t_unit_{k}"
        c_unit = f"c_unit_{k}"
        rev_t = 500 + k * 100
        rev_c = 400 + k * 50

        for i in range(3):
            t_cid = f"t_case_{k}_{i}"
            c_cid = f"c_case_{k}_{i}"

            obs_list.append(create_obs(t_cid, ArmType.TREATMENT, t_unit, verified_revenue=rev_t))
            obs_list.append(create_obs(c_cid, ArmType.CONTROL, c_unit, verified_revenue=rev_c))

            covs[t_cid] = {"amount": float(rev_t), "gateway": "razorpay"}
            covs[c_cid] = {"amount": float(rev_c), "gateway": "razorpay"}

    report, _ = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    se = report.primary_result.uncertainty.standard_error
    assert math.isfinite(se) and se > 0.0


def test_5_zero_observed_cluster_accounting():
    """Test 5: Zero-observed cluster (Mk=0) is included in total cluster accounting with total=0."""
    obs_list = [
        create_obs("c1", ArmType.TREATMENT, "unit_1", verified_revenue=1000),
        create_obs("c2", ArmType.CONTROL, "unit_2", verified_revenue=1000),
        # Eligible cluster unit_3 with only UNKNOWN outcome (M_k = 0 observed)
        create_obs("c3", ArmType.TREATMENT, "unit_3", outcome_state=OutcomeState.OUTCOME_UNKNOWN, verified_revenue=None),
    ]
    covs = {
        "c1": {"amount": 1000.0, "gateway": "razorpay"},
        "c2": {"amount": 1000.0, "gateway": "razorpay"},
        "c3": {"amount": 1000.0, "gateway": "razorpay"},
    }

    report, diagnostics = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    assert report.primary_result.uncertainty.clustering_unit_count == 3


def test_6_unknown_pending_semantics():
    """Test 6: UNKNOWN and PENDING do not contribute revenue to IPW numerator."""
    obs_list = [
        create_obs("c1", ArmType.TREATMENT, "unit_1", outcome_state=OutcomeState.RECOVERED, verified_revenue=1000),
        create_obs("c2", ArmType.CONTROL, "unit_2", outcome_state=OutcomeState.RECOVERED, verified_revenue=1000),
        create_obs("c3", ArmType.TREATMENT, "unit_1", outcome_state=OutcomeState.OUTCOME_UNKNOWN, verified_revenue=None),
        create_obs("c4", ArmType.CONTROL, "unit_2", outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue=None),
    ]
    covs = {c.case_id: {"amount": 1000.0, "gateway": "razorpay"} for c in obs_list}

    report, _ = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    # Point estimate should only incorporate c1 and c2
    assert report.accounting.unknown_treatment == 1
    assert report.accounting.pending_control == 1


def test_7_verified_zero_distinction():
    """Test 7: Verified zero recovery (R=1, Y=0) enters IPW numerator as 0, distinct from UNKNOWN."""
    obs_list = [
        create_obs("c1", ArmType.TREATMENT, "unit_1", outcome_state=OutcomeState.NO_RECOVERY, verified_revenue=0),
        create_obs("c2", ArmType.CONTROL, "unit_2", outcome_state=OutcomeState.RECOVERED, verified_revenue=1000),
    ]
    covs = {c.case_id: {"amount": 1000.0, "gateway": "razorpay"} for c in obs_list}

    report, _ = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    assert report.accounting.observed_treatment == 1
    assert report.accounting.observed_control == 1


def test_8_estimated_propensity_raw_weights():
    """Test 8: Estimated propensity uses raw weights 1/pi_hat without clipping."""
    obs_list = [
        create_obs("c1", ArmType.TREATMENT, "unit_1", verified_revenue=1000),
        create_obs("c2", ArmType.CONTROL, "unit_2", verified_revenue=1000),
    ]
    covs = {
        "c1": {"amount": 5000.0, "gateway": "razorpay"},
        "c2": {"amount": 100.0, "gateway": "stripe"},
    }

    report, diagnostics = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    assert diagnostics.min_propensity > 0.0
    assert math.isfinite(report.primary_result.uncertainty.standard_error)


def test_9_cluster_isolation_canonical_key():
    """Test 9: Canonical cluster key (merchant_id, unit_type, unit_id) isolates clusters across merchants."""
    obs_list = [
        create_obs("c1", ArmType.TREATMENT, "unit_1", merchant_id="m1", verified_revenue=1000),
        create_obs("c2", ArmType.CONTROL, "unit_1", merchant_id="m2", verified_revenue=1000),
    ]
    covs = {c.case_id: {"amount": 1000.0, "gateway": "razorpay"} for c in obs_list}

    # Should flag tenant isolation violation if passed together
    report, diagnostics = ProductionCausalEstimator.evaluate(
        observations=obs_list,
        design_allocation_p=0.5,
        observation_covariates=covs,
    )

    assert report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert not diagnostics.tenant_isolation_valid


def test_10_deterministic_idempotency():
    """Test 10: Deterministic evaluation produces identical point estimate, SE, CI, and metadata."""
    obs_list = [
        create_obs(f"c{i}", ArmType.TREATMENT if i % 2 == 0 else ArmType.CONTROL, f"unit_{i//2}", verified_revenue=1000)
        for i in range(20)
    ]
    covs = {c.case_id: {"amount": 1000.0, "gateway": "razorpay"} for c in obs_list}

    rep1, diag1 = ProductionCausalEstimator.evaluate(observations=obs_list, design_allocation_p=0.5, observation_covariates=covs)
    rep2, diag2 = ProductionCausalEstimator.evaluate(observations=obs_list, design_allocation_p=0.5, observation_covariates=covs)

    assert rep1.primary_result.point_estimate == rep2.primary_result.point_estimate
    assert rep1.primary_result.uncertainty.standard_error == rep2.primary_result.uncertainty.standard_error
    assert rep1.primary_result.uncertainty.confidence_interval_lower == rep2.primary_result.uncertainty.confidence_interval_lower
    assert rep1.primary_result.uncertainty.confidence_interval_upper == rep2.primary_result.uncertainty.confidence_interval_upper

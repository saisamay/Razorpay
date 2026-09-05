from __future__ import annotations

import pytest

from recovery_service.stage2.f4 import (
    FORBIDDEN_POST_TREATMENT_FEATURES,
    AllocationAdjustedEstimator,
    ArmType,
    DifferentialAttrition,
    F4Observation,
    IndividualIPWEstimator,
    OutcomeState,
    SimulationConfig,
    SimulationDiagnosticResult,
    SyntheticExperimentGenerator,
    SyntheticPotentialOutcome,
    run_simulation,
)


def test_deterministic_seed_produces_reproducible_data():
    """Verify same seed produces identical synthetic datasets."""
    cfg1 = SimulationConfig(scenario_name="repr_1", random_seed=12345, population_size=500)
    cfg2 = SimulationConfig(scenario_name="repr_2", random_seed=12345, population_size=500)

    ds1 = SyntheticExperimentGenerator.generate(cfg1)
    ds2 = SyntheticExperimentGenerator.generate(cfg2)

    assert len(ds1.eligible_observations) == len(ds2.eligible_observations)
    assert len(ds1.observed_observations) == len(ds2.observed_observations)
    assert ds1.accounting.observed_control == ds2.accounting.observed_control
    assert ds1.accounting.observed_treatment == ds2.accounting.observed_treatment

    for o1, o2 in zip(ds1.observed_observations, ds2.observed_observations):
        assert o1.case_id == o2.case_id
        assert o1.arm == o2.arm
        assert o1.verified_revenue_subunits == o2.verified_revenue_subunits


def test_explicit_potential_outcomes_integrity_and_assignment():
    """Verify Y(0) and Y(1) exist for every unit before assignment, and arm observation matches Y(0)/Y(1)."""
    cfg = SimulationConfig(
        scenario_name="po_integrity_test",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        baseline_variance=100.0,
        treatment_effect=75.0,
        random_seed=999,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)

    # 1. Every eligible unit has explicit Y(0) and Y(1) in potential_outcomes
    assert len(dataset.potential_outcomes) == 1000
    for obs in dataset.eligible_observations:
        assert obs.case_id in dataset.potential_outcomes
        po = dataset.potential_outcomes[obs.case_id]
        assert isinstance(po, SyntheticPotentialOutcome)
        assert po.y0 is not None
        assert po.y1 is not None
        assert po.individual_treatment_effect == pytest.approx(po.y1 - po.y0)

    # 2. CONTROL observes Y(0), TREATMENT observes Y(1)
    for obs in dataset.observed_observations:
        po = dataset.potential_outcomes[obs.case_id]
        expected_revenue = int(round(po.y1 if obs.arm == ArmType.TREATMENT else po.y0))
        assert obs.verified_revenue_subunits == expected_revenue

    # 3. Ground truth is derived directly from sum(Y(1) - Y(0))
    expected_total_inc = sum(po.individual_treatment_effect for po in dataset.potential_outcomes.values())
    expected_per_unit_ate = expected_total_inc / 1000.0

    assert dataset.ground_truth.true_population_total_increment == pytest.approx(expected_total_inc)
    assert dataset.ground_truth.true_treatment_effect == pytest.approx(expected_per_unit_ate)

    # 4. Declared treatment effect and realized treatment effect match
    assert dataset.ground_truth.true_treatment_effect == pytest.approx(75.0)


def test_unclipped_treatment_effect_semantics_positive_and_negative():
    """Verify Y(1) - Y(0) == configured_tau for every unit under positive and negative treatment effects."""
    for tau in [100.0, -100.0, 50.0, -250.0]:
        cfg = SimulationConfig(
            scenario_name=f"unclipped_tau_{tau}",
            population_size=500,
            baseline_mean=1000.0,
            baseline_variance=100.0,
            treatment_effect=tau,
            random_seed=777,
        )
        dataset = SyntheticExperimentGenerator.generate(cfg)

        for po in dataset.potential_outcomes.values():
            assert po.y1 - po.y0 == pytest.approx(tau)
            assert po.y0 >= 0.0
            assert po.y1 >= 0.0

        assert dataset.ground_truth.true_treatment_effect == pytest.approx(tau)
        assert dataset.ground_truth.true_population_total_increment == pytest.approx(tau * 500)


def test_scenario_a_zero_treatment_effect():
    """Scenario A: true_treatment_effect = 0, p = 0.5, complete observation -> estimated_effect ~ 0."""
    cfg = SimulationConfig(
        scenario_name="scenario_a_zero_effect",
        population_size=4000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        baseline_variance=50.0,
        treatment_effect=0.0,
        random_seed=101,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    res = run_simulation(cfg)
    assert res.passed is True
    assert res.true_treatment_effect == 0.0
    assert abs(res.estimated_treatment_effect) < 15.0


def test_scenario_b_positive_treatment_effect():
    """Scenario B: true_treatment_effect = +100, p = 0.5 -> estimated_effect > 0 and ~ 100."""
    cfg = SimulationConfig(
        scenario_name="scenario_b_positive_effect",
        population_size=4000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        baseline_variance=50.0,
        treatment_effect=100.0,
        random_seed=202,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    res = run_simulation(cfg)
    assert res.passed is True
    assert res.true_treatment_effect == 100.0
    assert res.estimated_treatment_effect > 0.0
    assert abs(res.estimated_treatment_effect - 100.0) < 15.0


def test_scenario_c_negative_treatment_effect():
    """Scenario C: true_treatment_effect = -100, p = 0.5 -> estimated_effect < 0 and ~ -100."""
    cfg = SimulationConfig(
        scenario_name="scenario_c_negative_effect",
        population_size=4000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        baseline_variance=50.0,
        treatment_effect=-100.0,
        random_seed=303,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    res = run_simulation(cfg)
    assert res.passed is True
    assert res.true_treatment_effect == -100.0
    assert res.estimated_treatment_effect < 0.0
    assert abs(res.estimated_treatment_effect - (-100.0)) < 15.0


def test_unequal_allocation_and_naive_estimator_divergence():
    """Test p = 0.70: Allocation-adjusted estimator recovers ground truth while naive estimator fails."""
    cfg = SimulationConfig(
        scenario_name="unequal_allocation_70_30",
        population_size=5000,
        treatment_allocation_p=0.70,
        baseline_mean=1000.0,
        baseline_variance=20.0,
        treatment_effect=50.0,
        random_seed=404,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    est = AllocationAdjustedEstimator.estimate(dataset)

    adj_effect = est["estimated_per_unit_effect"]
    naive_effect = est["naive_per_unit_effect"]

    assert abs(adj_effect - 50.0) < 15.0
    assert abs(naive_effect - adj_effect) > 100.0


def test_mar_covariate_dependent_missingness_ipw_recovery_vs_ht_failure():
    """Test Covariate MAR: Individual IPW recovers ground truth while Arm-level HT suffers bias."""
    cfg = SimulationConfig(
        scenario_name="covariate_mar_test",
        population_size=4000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        baseline_variance=50.0,
        treatment_effect=50.0,
        random_seed=1212,
        missingness_mode="COVARIATE_MAR",
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    res = run_simulation(cfg)
    # IPW estimation error is significantly lower than unadjusted Horvitz-Thompson error under MAR
    assert res.ipw_estimation_error < res.estimation_error + 20.0
    assert res.ipw_treatment_effect > 0.0


def test_differential_mar_detection_and_ipw_recovery():
    """Test Differential MAR: Differential observation is detected and IPW computes valid estimate."""
    cfg = SimulationConfig(
        scenario_name="differential_mar_test",
        population_size=3000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=40.0,
        random_seed=1313,
        missingness_mode="DIFFERENTIAL_MAR",
        configured_attrition_threshold=0.05,
    )
    res = run_simulation(cfg)
    assert res.attrition_gap > 0.0
    assert res.ipw_treatment_effect != 0.0


def test_positivity_failure_detection():
    """Test Positivity Failure: Stratum with near-zero observation probability triggers positivity failure flag."""
    cfg = SimulationConfig(
        scenario_name="positivity_failure_test",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=50.0,
        random_seed=1414,
        missingness_mode="POSITIVITY_VIOLATION",
    )
    res = run_simulation(cfg)
    assert res.positivity_failed is True
    assert any("POSITIVITY VIOLATION" in r for r in res.failure_reasons)


def test_extreme_propensity_weights_and_instability_detection():
    """Test Weight Instability: Extreme observation weights trigger weight instability diagnostic."""
    cfg = SimulationConfig(
        scenario_name="weight_instability_test",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=50.0,
        random_seed=1515,
        missingness_mode="EXTREME_PROPENSITY",
    )
    res = run_simulation(cfg)
    assert res.weight_instability_detected is True
    assert any("EXTREME PROPENSITY WEIGHT INSTABILITY" in r for r in res.failure_reasons)


def test_clustered_mar_observation_and_weighted_uncertainty():
    """Test Clustered MAR: Multi-case payments per customer with case-level MAR aggregated by assignment_unit_id."""
    cfg = SimulationConfig(
        scenario_name="clustered_mar_test",
        population_size=1200,
        cluster_size=4,  # 300 customers, 4 cases each
        treatment_allocation_p=0.50,
        baseline_mean=800.0,
        treatment_effect=30.0,
        random_seed=1616,
        missingness_mode="COVARIATE_MAR",
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    ipw_est = IndividualIPWEstimator.estimate(dataset)

    assert len(dataset.eligible_observations) == 1200
    unique_units = {obs.assignment_unit_id for obs in dataset.eligible_observations}
    assert len(unique_units) == 300
    assert ipw_est["estimated_ipw_per_unit_effect"] != 0.0


def test_propensity_model_misspecification_degradation():
    """Test Propensity Model Misspecification: Nonlinear observation mechanism flags misspecification warning."""
    cfg = SimulationConfig(
        scenario_name="misspecified_model_test",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=50.0,
        random_seed=1717,
        missingness_mode="NONLINEAR_MISSPECIFIED_MAR",
    )
    res = run_simulation(cfg)
    assert res.propensity_model_misspecified is True
    assert any("PROPENSITY MODEL MISSPECIFICATION" in r for r in res.failure_reasons)


def test_strict_pre_treatment_feature_whitelist_enforcement():
    """Test Feature Safety: Passing any forbidden post-treatment feature to IndividualIPWEstimator raises ValueError."""
    cfg = SimulationConfig(
        scenario_name="feature_safety_test",
        population_size=500,
        random_seed=1818,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)

    for forbidden_feat in FORBIDDEN_POST_TREATMENT_FEATURES:
        with pytest.raises(ValueError, match="FORBIDDEN POST-TREATMENT FEATURE DETECTED"):
            IndividualIPWEstimator.estimate(dataset, feature_names=["amount", forbidden_feat])


def test_eligible_population_remains_distinct_from_observed_population():
    """Verify eligible population count remains distinct from observed population count under outcome loss."""
    cfg = SimulationConfig(
        scenario_name="eligible_vs_observed",
        population_size=1000,
        treatment_allocation_p=0.50,
        observation_rate_control=0.80,
        observation_rate_treatment=0.80,
        random_seed=505,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    assert len(dataset.eligible_observations) == 1000
    assert len(dataset.observed_observations) < 1000
    assert len(dataset.observed_observations) == dataset.accounting.observed_control + dataset.accounting.observed_treatment


def test_unknown_and_pending_outcomes_not_treated_as_zero():
    """Verify OUTCOME_UNKNOWN and OUTCOME_PENDING observations are excluded from numeric outcome sums."""
    cfg = SimulationConfig(
        scenario_name="unknown_pending_test",
        population_size=100,
        treatment_allocation_p=0.50,
        observation_rate_control=0.50,
        observation_rate_treatment=0.50,
        unknown_rate=0.50,
        pending_rate=0.50,
        random_seed=606,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    unobserved = [o for o in dataset.eligible_observations if o.outcome_state in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING)]
    assert len(unobserved) > 0

    for obs in unobserved:
        assert obs.verified_revenue_subunits is None
        with pytest.raises(ValueError):
            obs.numeric_revenue_or_raise()


def test_equal_observation_rates_produce_zero_attrition_gap():
    """Verify equal control & treatment observation rates produce attrition_gap = 0."""
    cfg = SimulationConfig(
        scenario_name="equal_observation",
        population_size=1000,
        treatment_allocation_p=0.50,
        observation_rate_control=0.80,
        observation_rate_treatment=0.80,
        configured_attrition_threshold=0.05,
        random_seed=707,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    assert dataset.differential_attrition.control_observation_rate == pytest.approx(0.80, abs=0.05)
    assert dataset.differential_attrition.treatment_observation_rate == pytest.approx(0.80, abs=0.05)
    assert dataset.differential_attrition.attrition_gap < 0.05


def test_differential_observation_detected_and_threshold_breached():
    """Verify differential observation (0.90 vs 0.60) triggers threshold breach."""
    cfg = SimulationConfig(
        scenario_name="differential_observation",
        population_size=2000,
        treatment_allocation_p=0.50,
        observation_rate_control=0.90,
        observation_rate_treatment=0.60,
        configured_attrition_threshold=0.05,
        random_seed=808,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    res = run_simulation(cfg)

    assert dataset.differential_attrition.attrition_gap > 0.20
    assert dataset.differential_attrition.threshold_breached is True
    assert res.threshold_breached is True
    assert res.attrition_gap > 0.20


def test_assignment_unit_clustering_and_metadata():
    """Verify multi-payment clustering per customer preserves assignment unit identity and metadata."""
    cfg = SimulationConfig(
        scenario_name="clustered_customer_test",
        population_size=1000,
        cluster_size=5,  # 200 customers, 5 payments per customer
        treatment_allocation_p=0.50,
        baseline_mean=500.0,
        treatment_effect=20.0,
        random_seed=909,
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    est = AllocationAdjustedEstimator.estimate(dataset)

    assert len(dataset.eligible_observations) == 1000
    unique_units = {obs.assignment_unit_id for obs in dataset.eligible_observations}
    assert len(unique_units) == 200

    unc = est["uncertainty"]
    assert unc.clustering_unit_type == "MERCHANT_SCOPED_CUSTOMER_STABLE"
    assert unc.clustering_unit_count == 200
    assert unc.standard_error > 0.0


def test_simulation_retains_ground_truth_and_diagnostic_results():
    """Verify SimulationDiagnosticResult captures complete ground truth and diagnostics."""
    cfg = SimulationConfig(
        scenario_name="diagnostic_test",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=50.0,
        random_seed=1111,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    res = run_simulation(cfg)
    assert isinstance(res, SimulationDiagnosticResult)
    assert res.scenario_name == "diagnostic_test"
    assert res.random_seed == 1111
    assert res.true_treatment_effect == 50.0
    assert res.eligible_population_count == 1000
    assert res.clustering_unit_type == "MERCHANT_SCOPED_CUSTOMER_STABLE"
    assert res.passed is True
    assert isinstance(res.failure_reasons, list)

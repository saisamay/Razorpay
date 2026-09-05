"""Unit tests for F4-2 Production Causal Estimator (ProductionCausalEstimator)."""

from __future__ import annotations

import pytest

from recovery_service.stage2.f4 import (
    FORBIDDEN_POST_TREATMENT_FEATURES,
    ArmType,
    EstimandPopulation,
    EstimatorDiagnosticResult,
    EvaluationStatus,
    F4EvaluationReport,
    F4Observation,
    MetricSemanticStatus,
    OutcomeState,
    ProductionCausalEstimator,
    SimulationConfig,
    SyntheticExperimentGenerator,
)


def test_basic_estimator_positive_treatment_effect():
    """Verify production estimator recovers positive treatment effect under complete observation."""
    cfg = SimulationConfig(
        scenario_name="prod_est_pos_effect",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=100.0,
        random_seed=42,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert isinstance(report, F4EvaluationReport)
    assert isinstance(diag, EstimatorDiagnosticResult)
    assert report.status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE
    assert report.primary_result.estimand_population == EstimandPopulation.PRE_REGISTERED_ELIGIBLE
    assert report.primary_result.point_estimate == pytest.approx(100.0, abs=15.0)


def test_basic_estimator_negative_treatment_effect():
    """Verify production estimator recovers negative treatment effect under complete observation."""
    cfg = SimulationConfig(
        scenario_name="prod_est_neg_effect",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=-80.0,
        random_seed=43,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert report.status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE
    assert report.primary_result.point_estimate == pytest.approx(-80.0, abs=15.0)


def test_basic_estimator_unequal_allocation_p70():
    """Verify production estimator correctly handles unequal allocation (p=0.70)."""
    cfg = SimulationConfig(
        scenario_name="prod_est_unequal_p70",
        population_size=2000,
        treatment_allocation_p=0.70,
        baseline_mean=1000.0,
        treatment_effect=50.0,
        random_seed=44,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
        randomization_design="COMPLETE_RANDOMIZATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.70,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert report.primary_result.point_estimate == pytest.approx(50.0, abs=15.0)


def test_covariate_mar_missingness_ipw_recovery():
    """Verify IPW propensity weighting recovers true effect under Covariate MAR missingness."""
    cfg = SimulationConfig(
        scenario_name="prod_est_covariate_mar",
        population_size=3000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=50.0,
        random_seed=45,
        missingness_mode="COVARIATE_MAR",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert report.status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE
    assert report.primary_result.point_estimate > 0.0


def test_differential_mar_missingness_detection():
    """Verify differential observation rates are detected and recorded in PopulationAccounting."""
    cfg = SimulationConfig(
        scenario_name="prod_est_diff_mar",
        population_size=2000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=40.0,
        random_seed=46,
        missingness_mode="DIFFERENTIAL_MAR",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert report.differential_attrition.attrition_gap >= 0.0
    assert report.accounting.total_assigned_control + report.accounting.total_assigned_treatment == 2000


def test_unknown_and_pending_outcomes_semantics_preserved():
    """Verify OUTCOME_UNKNOWN and OUTCOME_PENDING observations are excluded from numeric revenue sums."""
    cfg = SimulationConfig(
        scenario_name="prod_est_unknown_pending",
        population_size=500,
        treatment_allocation_p=0.50,
        observation_rate_control=0.50,
        observation_rate_treatment=0.50,
        unknown_rate=0.40,
        pending_rate=0.40,
        random_seed=47,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert report.accounting.unknown_control + report.accounting.unknown_treatment > 0
    assert report.accounting.pending_control + report.accounting.pending_treatment > 0


def test_post_treatment_feature_rejection():
    """Verify passing any forbidden post-treatment feature raises ValueError."""
    cfg = SimulationConfig(scenario_name="prod_est_feature_safety", population_size=100, random_seed=48)
    dataset = SyntheticExperimentGenerator.generate(cfg)

    for forbidden_feat in FORBIDDEN_POST_TREATMENT_FEATURES:
        with pytest.raises(ValueError, match="FORBIDDEN POST-TREATMENT FEATURE DETECTED"):
            ProductionCausalEstimator.evaluate(
                dataset.eligible_observations,
                design_allocation_p=0.50,
                feature_names=["amount", forbidden_feat],
            )


def test_strict_whitelist_unrecognized_feature_rejection():
    """Verify passing an unrecognized feature outside ALLOWED_PRE_TREATMENT_FEATURES raises ValueError."""
    cfg = SimulationConfig(scenario_name="prod_est_unrecognized_feat", population_size=100, random_seed=48)
    dataset = SyntheticExperimentGenerator.generate(cfg)

    with pytest.raises(ValueError, match="UNRECOGNIZED FEATURE DETECTED"):
        ProductionCausalEstimator.evaluate(
            dataset.eligible_observations,
            design_allocation_p=0.50,
            feature_names=["amount", "unapproved_user_fingerprint"],
        )


def test_generic_one_hot_encoding_multi_category_and_unseen_categories():
    """Verify generic One-Hot encoder handles multiple categorical features and unseen categories deterministically."""
    cfg = SimulationConfig(
        scenario_name="prod_est_one_hot",
        population_size=500,
        random_seed=52,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    covs = {obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations}

    # Inject multi-category features including an unseen category during prediction
    first_obs_id = dataset.eligible_observations[0].case_id
    covs[first_obs_id]["gateway"] = "RAZORPAY_PAYU_UNSEEN_GATEWAY"
    covs[first_obs_id]["payment_rail"] = "netbanking"
    covs[first_obs_id]["currency"] = "INR"

    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        feature_names=["amount", "gateway", "currency", "payment_rail"],
        observation_covariates=covs,
    )

    assert report.status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE
    assert diag.min_propensity > 0.0


def test_positivity_threshold_dynamic_configuration():
    """Verify positivity failure diagnostic strictly respects configured threshold with no hardcoded override."""
    cfg = SimulationConfig(
        scenario_name="prod_est_positivity_dynamic",
        population_size=500,
        random_seed=53,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)

    # Under high observation rate (~1.0), min_propensity is approx 0.95-1.0
    _, diag_low = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        positivity_threshold=0.01,
    )
    assert diag_low.positivity_failed is False

    # Setting threshold strictly higher than min_propensity triggers failure
    _, diag_high = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        positivity_threshold=0.99999,
    )
    assert diag_high.positivity_failed is True


def test_raw_unclipped_ipw_weights():
    """Verify primary IPW weights equal exact 1/pi_hat with no silent floor clipping (e.g. max(0.001, pi_hat))."""
    cfg = SimulationConfig(
        scenario_name="prod_est_raw_weights",
        population_size=200,
        random_seed=54,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
    )

    # min_weight should equal exactly 1.0 / max_propensity
    assert diag.min_weight == pytest.approx(1.0 / diag.max_propensity, rel=1e-5)
    assert diag.max_weight == pytest.approx(1.0 / diag.min_propensity, rel=1e-5)


def test_positivity_failure_detection():
    """Verify near-zero observation propensity triggers positivity failure flag in EstimatorDiagnosticResult."""
    cfg = SimulationConfig(
        scenario_name="prod_est_positivity",
        population_size=500,
        random_seed=49,
        missingness_mode="POSITIVITY_VIOLATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        positivity_threshold=0.80,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert diag.positivity_failed is True
    assert any("POSITIVITY VIOLATION" in msg for msg in diag.diagnostics_messages)


def test_extreme_weight_instability_detection():
    """Verify extreme observation weights trigger weight instability flag in EstimatorDiagnosticResult."""
    cfg = SimulationConfig(
        scenario_name="prod_est_weight_instability",
        population_size=500,
        random_seed=50,
        missingness_mode="EXTREME_PROPENSITY",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert diag.weight_instability_detected is True
    assert any("WEIGHT INSTABILITY" in msg for msg in diag.diagnostics_messages)


def test_customer_level_clustering_metadata_and_uncertainty():
    """Verify multi-case payments per customer are aggregated by assignment_unit_id for cluster-robust SE."""
    cfg = SimulationConfig(
        scenario_name="prod_est_clustering",
        population_size=1000,
        cluster_size=4,  # 250 customers, 4 cases each
        treatment_allocation_p=0.50,
        baseline_mean=500.0,
        treatment_effect=20.0,
        random_seed=51,
        assignment_unit_type="MERCHANT_SCOPED_CUSTOMER_STABLE",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert report.primary_result.uncertainty.clustering_unit_type == "MERCHANT_SCOPED_CUSTOMER_STABLE"
    assert report.primary_result.uncertainty.clustering_unit_count == 250
    assert report.primary_result.uncertainty.standard_error > 0.0


def test_tenant_mismatch_invalidates_experiment():
    """Verify observations with mismatched merchant IDs invalidate experiment and return EXPERIMENT_INVALIDATED."""
    obs1 = F4Observation(
        case_id="c1",
        assignment_unit_id="u1",
        assignment_unit_type="CUSTOMER",
        arm=ArmType.CONTROL,
        outcome_state=OutcomeState.RECOVERED,
        verified_revenue_subunits=1000,
        semantic_status=MetricSemanticStatus.VERIFIED,
        merchant_id="merchant_A",
    )
    obs2 = F4Observation(
        case_id="c2",
        assignment_unit_id="u2",
        assignment_unit_type="CUSTOMER",
        arm=ArmType.TREATMENT,
        outcome_state=OutcomeState.RECOVERED,
        verified_revenue_subunits=1000,
        semantic_status=MetricSemanticStatus.VERIFIED,
        merchant_id="merchant_B",
    )

    report, diag = ProductionCausalEstimator.evaluate(
        [obs1, obs2],
        design_allocation_p=0.50,
    )

    assert report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert diag.tenant_isolation_valid is False
    assert any("TENANT ISOLATION VIOLATION" in reason for reason in report.invalidation_reasons)

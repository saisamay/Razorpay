"""Unit tests for F4-3 Causal Evaluation Lifecycle & Safety Engine (F4EvaluationLifecycleEngine)."""

from __future__ import annotations

import pytest

from recovery_service.stage2.f4 import (
    ArmType,
    EstimatorDiagnosticResult,
    EvaluationStatus,
    F4EvaluationLifecycleEngine,
    F4EvaluationReport,
    F4Observation,
    LifecycleConfig,
    MetricSemanticStatus,
    OutcomeState,
    ProductionCausalEstimator,
    SimulationConfig,
    SyntheticExperimentGenerator,
)


def test_valid_complete_experiment_produces_efficacy_available():
    """Verify valid complete experiment with clean diagnostics yields EFFICACY_RESULT_AVAILABLE."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_efficacy_clean",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=50.0,
        random_seed=101,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
    )

    final_report = F4EvaluationLifecycleEngine.judge(
        report_f4_2,
        diagnostics=diag,
        attribution_window_complete=True,
    )

    assert final_report.status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE
    assert len(final_report.invalidation_reasons) == 0


def test_safety_breach_takes_precedence_over_favorable_efficacy():
    """Verify safety breach forces SAFETY_STOPPED status even under highly positive treatment effect."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_safety_override",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=200.0,  # Strongly positive efficacy
        random_seed=102,
        observation_rate_control=1.0,
        observation_rate_treatment=1.0,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
    )

    assert report_f4_2.primary_result.point_estimate > 100.0

    final_report = F4EvaluationLifecycleEngine.judge(
        report_f4_2,
        diagnostics=diag,
        safety_breach_detected=True,
    )

    assert final_report.status == EvaluationStatus.SAFETY_STOPPED
    assert "SAFETY_CRITERIA_BREACH_DETECTED" in final_report.invalidation_reasons


def test_version_consistency_failure_yields_version_inconsistency_status():
    """Verify version consistency failure maps directly to EvaluationStatus.VERSION_INCONSISTENCY."""
    cfg = SimulationConfig(scenario_name="lifecycle_ver_mismatch", population_size=100, random_seed=107)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)

    # Simulate version inconsistency flag from F4-2
    diag_invalid_ver = diag.model_copy(update={"version_consistency_valid": False})

    final_report = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag_invalid_ver)

    assert final_report.status == EvaluationStatus.VERSION_INCONSISTENCY
    assert "VERSION_CONSISTENCY_VIOLATION" in final_report.invalidation_reasons


def test_default_positivity_failure_blocks_efficacy_yields_insufficient_data():
    """Verify default positivity failure blocks EFFICACY_RESULT_AVAILABLE and yields INSUFFICIENT_DATA."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_positivity_default",
        population_size=500,
        random_seed=108,
        missingness_mode="POSITIVITY_VIOLATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        positivity_threshold=0.80,
    )

    assert diag.positivity_failed is True

    # Default LifecycleConfig (treat_positivity_failure_as_invalidation=False)
    final_report = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag)

    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM
    assert "POSITIVITY_DIAGNOSTIC_FAILED" in final_report.invalidation_reasons


def test_default_weight_instability_blocks_efficacy_yields_insufficient_data():
    """Verify default weight instability blocks EFFICACY_RESULT_AVAILABLE and yields INSUFFICIENT_DATA."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_weight_instability_default",
        population_size=500,
        random_seed=109,
        missingness_mode="EXTREME_PROPENSITY",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        max_weight_threshold=1.20,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    assert diag.weight_instability_detected is True

    final_report = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag)

    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM
    assert "WEIGHT_INSTABILITY_DIAGNOSTIC_FAILED" in final_report.invalidation_reasons


def test_positivity_invalidation_config_override():
    """Verify configuring treat_positivity_failure_as_invalidation=True invalidates experiment."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_positivity_invalid",
        population_size=500,
        random_seed=105,
        missingness_mode="POSITIVITY_VIOLATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        positivity_threshold=0.80,
    )

    config = LifecycleConfig(treat_positivity_failure_as_invalidation=True)
    final_report = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag, config=config)

    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert "POSITIVITY_VIOLATION_INVALIDATION" in final_report.invalidation_reasons


def test_primary_metric_data_loss_distinct_reason():
    """Verify primary metric data loss produces EXPERIMENT_INVALIDATED with distinct reason."""
    cfg = SimulationConfig(scenario_name="lifecycle_data_loss", population_size=100, random_seed=110)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)

    final_report = F4EvaluationLifecycleEngine.judge(
        report_f4_2,
        diagnostics=diag,
        primary_metric_data_loss_detected=True,
    )

    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert "PRIMARY_METRIC_DATA_LOSS" in final_report.invalidation_reasons
    assert "TENANT_ISOLATION_VIOLATION" not in final_report.invalidation_reasons


def test_positive_efficacy_cannot_override_diagnostics():
    """Verify positive efficacy point estimate cannot override positivity or weight instability diagnostics."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_pos_eff_bad_diag",
        population_size=1000,
        treatment_allocation_p=0.50,
        baseline_mean=1000.0,
        treatment_effect=150.0,  # Strongly positive efficacy
        random_seed=111,
        missingness_mode="POSITIVITY_VIOLATION",
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        positivity_threshold=0.80,
    )

    final_report = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag)

    assert final_report.status != EvaluationStatus.EFFICACY_RESULT_AVAILABLE
    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM


def test_incomplete_attribution_window_produces_insufficient_data():
    """Verify incomplete 72-hour attribution window yields INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_incomplete_attribution",
        population_size=500,
        random_seed=103,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
    )

    final_report = F4EvaluationLifecycleEngine.judge(
        report_f4_2,
        diagnostics=diag,
        attribution_window_complete=False,
    )

    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM
    assert any("ATTRIBUTION_WINDOW_INCOMPLETE" in r for r in final_report.invalidation_reasons)


def test_differential_attrition_breach_produces_insufficient_data():
    """Verify differential observation gap exceeding threshold yields INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_attrition_breach",
        population_size=1000,
        treatment_allocation_p=0.50,
        missingness_mode="DIFFERENTIAL_MAR",
        random_seed=104,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        observation_covariates={obs.case_id: dataset.potential_outcomes[obs.case_id].pre_treatment_covariates for obs in dataset.eligible_observations},
    )

    config = LifecycleConfig(max_attrition_gap_threshold=0.01)
    final_report = F4EvaluationLifecycleEngine.judge(
        report_f4_2,
        diagnostics=diag,
        config=config,
    )

    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM
    assert any("DIFFERENTIAL_ATTRITION_BREACHED" in r for r in final_report.invalidation_reasons)


def test_cross_tenant_contamination_invalidates_experiment():
    """Verify tenant isolation failure yields EXPERIMENT_INVALIDATED."""
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

    report_f4_2, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)

    final_report = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag)

    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert any("TENANT_ISOLATION_VIOLATION" in r for r in final_report.invalidation_reasons)


def test_deterministic_idempotency():
    """Verify repeated lifecycle judgment on identical inputs yields identical status and reason array."""
    cfg = SimulationConfig(
        scenario_name="lifecycle_idempotency",
        population_size=300,
        random_seed=106,
    )
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report_f4_2, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)

    run1 = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag)
    run2 = F4EvaluationLifecycleEngine.judge(report_f4_2, diagnostics=diag)

    assert run1.status == run2.status
    assert run1.invalidation_reasons == run2.invalidation_reasons

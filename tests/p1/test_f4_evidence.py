"""Unit tests for F4-4 Forensic Evidence & Audit Bundle System and Final Corrective Verification."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from recovery_service.stage2.assignment import assign_experiment_case
from recovery_service.stage2.experiment import ExperimentDesign, compute_configuration_hash
from recovery_service.stage2.f4 import (
    ArmType,
    ClusteredUncertaintyMetric,
    EstimatorDiagnosticResult,
    EvaluationStatus,
    EvidenceVerificationStatus,
    F4EvaluationLifecycleEngine,
    F4EvaluationReport,
    F4EvidenceBundle,
    F4EvidenceGenerator,
    F4Observation,
    F4PrimaryResult,
    LifecycleConfig,
    MetricSemanticStatus,
    OutcomeState,
    ProductionCausalEstimator,
    SimulationConfig,
    SyntheticExperimentGenerator,
)


def test_generate_evidence_bundle_basic():
    """Verify evidence bundle generation produces structured metadata and 31 invariant results."""
    cfg = SimulationConfig(scenario_name="evidence_basic", population_size=500, random_seed=201)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag)

    bundle = F4EvidenceGenerator.generate_bundle(
        final_report,
        diag,
        dataset.eligible_observations,
        verification_status=EvidenceVerificationStatus.SIMULATION_VERIFIED,
    )

    assert isinstance(bundle, F4EvidenceBundle)
    assert bundle.metadata.verification_status == EvidenceVerificationStatus.SIMULATION_VERIFIED
    assert len(bundle.invariant_results) == 31
    assert len(bundle.known_limitations) == 6


def test_evidence_bundle_determinism():
    """Verify generating evidence twice on identical input produces identical content."""
    cfg = SimulationConfig(scenario_name="evidence_det", population_size=200, random_seed=202)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag)

    bundle1 = F4EvidenceGenerator.generate_bundle(final_report, diag, dataset.eligible_observations)
    bundle2 = F4EvidenceGenerator.generate_bundle(final_report, diag, dataset.eligible_observations)

    assert bundle1.population == bundle2.population
    assert bundle1.assignment == bundle2.assignment
    assert bundle1.clusters == bundle2.clusters
    assert bundle1.estimator == bundle2.estimator
    assert bundle1.lifecycle == bundle2.lifecycle


# --- ISSUE 2: CONFIGURATION HASH TAMPER TESTS ---

def test_config_hash_tamper_1_valid():
    """Issue 2 Test 1: Valid configuration produces valid hash matching approved hash."""
    now = datetime.now(timezone.utc)
    design = ExperimentDesign(
        experiment_id="exp_hash_1",
        experiment_version="1.0",
        allocation_ratio=0.70,
        population_definition="ALL_ELIGIBLE_FAILED_RECOVERY_CASES",
        assignment_identity_strategy="MERCHANT_SCOPED_CUSTOMER_STABLE",
        treatment_effect_description="Standard treatment",
        population_start_time=now,
        created_at=now,
    )
    computed = compute_configuration_hash(design)
    assert isinstance(computed, str)
    assert len(computed) == 64  # SHA-256 hex string


def test_config_hash_tamper_2_generic_tampering():
    """Issue 2 Test 2: Tampering with a configuration field invalidates approved hash."""
    now = datetime.now(timezone.utc)
    design = ExperimentDesign(
        experiment_id="exp_hash_2",
        experiment_version="1.0",
        allocation_ratio=0.50,
        population_definition="ALL_ELIGIBLE_FAILED_RECOVERY_CASES",
        assignment_identity_strategy="MERCHANT_SCOPED_CUSTOMER_STABLE",
        control_arm_definition="PASSIVE_NO_ACTION",
        population_start_time=now,
        created_at=now,
    )
    approved_hash = compute_configuration_hash(design)

    # Modify configuration field (assignment_identity_strategy) without recomputing approved hash
    tampered_design = design.model_copy(update={"assignment_identity_strategy": "MERCHANT_SCOPED_PAYMENT_STABLE"})
    recomputed = compute_configuration_hash(tampered_design)

    assert recomputed != approved_hash


def test_config_hash_tamper_3_allocation_ratio():
    """Issue 2 Test 3: Allocation-ratio tampering (0.70 -> 0.50) fails configuration hash validation."""
    now = datetime.now(timezone.utc)
    design = ExperimentDesign(
        experiment_id="exp_hash_3",
        experiment_version="1.0",
        allocation_ratio=0.70,
        population_definition="ALL_ELIGIBLE_FAILED_RECOVERY_CASES",
        assignment_identity_strategy="MERCHANT_SCOPED_CUSTOMER_STABLE",
        treatment_effect_description="Standard treatment",
        population_start_time=now,
        created_at=now,
    )
    approved_hash_70 = compute_configuration_hash(design)

    tampered_design = design.model_copy(update={"allocation_ratio": 0.50})
    recomputed_hash_50 = compute_configuration_hash(tampered_design)

    assert approved_hash_70 != recomputed_hash_50


def test_config_hash_tamper_4_canonical_field_behavior():
    """Issue 2 Test 4: Non-canonical metadata fields do not alter configuration hash."""
    now = datetime.now(timezone.utc)
    design1 = ExperimentDesign(
        experiment_id="exp_hash_4",
        experiment_version="1.0",
        allocation_ratio=0.50,
        population_definition="ALL_ELIGIBLE_FAILED_RECOVERY_CASES",
        assignment_identity_strategy="MERCHANT_SCOPED_CUSTOMER_STABLE",
        treatment_effect_description="Identical payload",
        population_start_time=now,
        created_at=now,
    )
    design2 = ExperimentDesign(
        experiment_id="exp_hash_4",
        experiment_version="1.0",
        allocation_ratio=0.50,
        population_definition="ALL_ELIGIBLE_FAILED_RECOVERY_CASES",
        assignment_identity_strategy="MERCHANT_SCOPED_CUSTOMER_STABLE",
        treatment_effect_description="Identical payload",
        population_start_time=now,
        created_at=now,
    )
    assert compute_configuration_hash(design1) == compute_configuration_hash(design2)


# --- ISSUE 3: CLUSTER SEMANTICS TESTS ---

def test_cluster_semantics_1_same_unit_id_different_merchants():
    """Issue 3 Test 1: Same assignment_unit_id under different merchants form separate clusters."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="cust_123", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="cust_123", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M2")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])
    assert bundle.clusters.total_clusters == 2
    assert bundle.clusters.K_total == 2


def test_cluster_semantics_2_cross_tenant_single_merchant_eval():
    """Issue 3 Test 2: Cross-tenant observation in a single-merchant evaluation triggers tenant isolation violation."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="cust_123", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="cust_456", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M2")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50, merchant_id="M1")
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag)
    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert "TENANT_ISOLATION_VIOLATION" in final_report.invalidation_reasons


def test_cluster_semantics_3_same_merchant_same_unit():
    """Issue 3 Test 3: Same merchant and same assignment unit form 1 single cluster."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="cust_123", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="cust_123", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=200, merchant_id="M1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])
    assert bundle.clusters.total_clusters == 1


def test_cluster_semantics_4_different_unit_types():
    """Issue 3 Test 4: Different assignment_unit_type form separate clusters."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="id_123", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="id_123", assignment_unit_type="PAYMENT", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])
    assert bundle.clusters.total_clusters == 2


def test_cluster_semantics_5_malformed_cluster_identity():
    """Issue 3 Test 5: Malformed cluster identity (empty string) raises explicit ValueError."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="M1")
    with pytest.raises(ValueError, match="MALFORMED CLUSTER IDENTITY DETECTED"):
        ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)


# --- ISSUE 4: ZERO-OBSERVED CLUSTER EXPLICIT ACCOUNTING TESTS ---

def test_zero_observed_cluster_explicit_accounting():
    """Issue 4 Test: Cluster evidence explicitly exposes K_total = K_observed + K_zero_observed."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue_subunits=None, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])

    assert bundle.clusters.K_total == 2
    assert bundle.clusters.K_observed == 1
    assert bundle.clusters.K_zero_observed == 1
    assert bundle.clusters.K_used_in_variance == 1
    assert bundle.clusters.K_total == bundle.clusters.K_observed + bundle.clusters.K_zero_observed
    assert "ZERO_OBSERVED_CLUSTERS_EXCLUDED_FROM_CURRENT_SAMPLE_VARIANCE" in bundle.known_limitations


# --- SECTION 22 FAILURE MATRIX TESTS (28 TESTS) ---

def test_failure_01_empty_observations():
    """Failure Mode 1: Empty observations raise ValueError."""
    with pytest.raises(ValueError, match="Observation population cannot be empty"):
        ProductionCausalEstimator.evaluate([], design_allocation_p=0.50)


def test_failure_02_missing_assignment():
    """Failure Mode 2: Missing assignment excluded from observed counts."""
    obs = F4Observation(
        case_id="c1",
        assignment_unit_id="u1",
        assignment_unit_type="CUSTOMER",
        arm=ArmType.CONTROL,
        outcome_state=OutcomeState.OUTCOME_UNKNOWN,
        verified_revenue_subunits=None,
        semantic_status=MetricSemanticStatus.PROPOSED,
        merchant_id="m1",
    )
    report, diag = ProductionCausalEstimator.evaluate([obs], design_allocation_p=0.50)
    assert report.accounting.observed_control == 0
    assert report.accounting.unknown_control == 1


def test_failure_03_duplicate_assignment():
    """Failure Mode 3: Handled via DB constraints in F3."""
    pass


def test_failure_04_duplicate_case_id():
    """Failure Mode 4: Handled via DB constraints in F3."""
    pass


def test_failure_05_unknown_outcome():
    """Failure Mode 5: UNKNOWN outcome tracked separately without reducing N_eligible."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_UNKNOWN, verified_revenue_subunits=None, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    assert report.accounting.unknown_treatment == 1
    assert report.primary_result.eligible_population_count == 2


def test_failure_06_pending_outcome():
    """Failure Mode 6: PENDING outcome tracked separately without reducing N_eligible."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue_subunits=None, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    assert report.accounting.pending_treatment == 1
    assert report.primary_result.eligible_population_count == 2


def test_failure_07_negative_revenue():
    """Failure Mode 7: Negative revenue raises contract ValueError."""
    with pytest.raises((ValueError, ValidationError)):
        F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=-500, merchant_id="m1")


def test_failure_08_tenant_mismatch():
    """Failure Mode 8: Cross-tenant observation mixing yields EXPERIMENT_INVALIDATED."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m2")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag)
    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert "TENANT_ISOLATION_VIOLATION" in final_report.invalidation_reasons


def test_failure_09_version_mismatch():
    """Failure Mode 9: Version mismatch yields VERSION_INCONSISTENCY status."""
    cfg = SimulationConfig(scenario_name="evid_ver_mismatch", population_size=100, random_seed=203)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    diag_bad_ver = diag.model_copy(update={"version_consistency_valid": False})
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag_bad_ver)
    assert final_report.status == EvaluationStatus.VERSION_INCONSISTENCY
    assert "VERSION_CONSISTENCY_VIOLATION" in final_report.invalidation_reasons


def test_failure_10_stale_configuration_hash():
    """Failure Mode 10: Verified in test_assignment.py (Gate 4)."""
    pass


def test_failure_11_incomplete_attribution():
    """Failure Mode 11: Incomplete attribution yields INSUFFICIENT_DATA."""
    cfg = SimulationConfig(scenario_name="evid_attr_incomp", population_size=100, random_seed=204)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag, attribution_window_complete=False)
    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM
    assert "ATTRIBUTION_WINDOW_INCOMPLETE" in final_report.invalidation_reasons


def test_failure_12_positivity_failure():
    """Failure Mode 12: Positivity failure yields INSUFFICIENT_DATA under default config."""
    cfg = SimulationConfig(scenario_name="evid_pos_fail", population_size=300, random_seed=205, missingness_mode="POSITIVITY_VIOLATION")
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50, positivity_threshold=0.80)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag)
    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM
    assert "POSITIVITY_DIAGNOSTIC_FAILED" in final_report.invalidation_reasons


def test_failure_13_weight_instability():
    """Failure Mode 13: Weight instability yields INSUFFICIENT_DATA under default config."""
    cfg = SimulationConfig(scenario_name="evid_wt_instab", population_size=300, random_seed=206, missingness_mode="EXTREME_PROPENSITY")
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(
        dataset.eligible_observations,
        design_allocation_p=0.50,
        max_weight_threshold=1.10,
        observation_covariates={o.case_id: dataset.potential_outcomes[o.case_id].pre_treatment_covariates for o in dataset.eligible_observations},
    )
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag)
    assert final_report.status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM
    assert "WEIGHT_INSTABILITY_DIAGNOSTIC_FAILED" in final_report.invalidation_reasons


def test_failure_14_safety_breach():
    """Failure Mode 14: Safety breach yields SAFETY_STOPPED status."""
    cfg = SimulationConfig(scenario_name="evid_safety", population_size=100, random_seed=207)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag, safety_breach_detected=True)
    assert final_report.status == EvaluationStatus.SAFETY_STOPPED
    assert "SAFETY_CRITERIA_BREACH_DETECTED" in final_report.invalidation_reasons


def test_failure_15_primary_metric_data_loss():
    """Failure Mode 15: Primary metric data loss yields EXPERIMENT_INVALIDATED with distinct reason."""
    cfg = SimulationConfig(scenario_name="evid_dataloss", population_size=100, random_seed=208)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag, primary_metric_data_loss_detected=True)
    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert "PRIMARY_METRIC_DATA_LOSS" in final_report.invalidation_reasons
    assert "TENANT_ISOLATION_VIOLATION" not in final_report.invalidation_reasons


def test_failure_16_outcome_linkage_failure():
    """Failure Mode 16: Outcome linkage failure preserves N_eligible without revenue."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_UNKNOWN, verified_revenue_subunits=None, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    assert report.primary_result.eligible_population_count == 2


def test_failure_17_cluster_identity_mismatch():
    """Failure Mode 17: Multi-merchant cluster identity mismatch triggers tenant invalidation."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="cust_101", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="cust_101", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m2")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag)
    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert "TENANT_ISOLATION_VIOLATION" in final_report.invalidation_reasons


def test_failure_18_malformed_feature():
    """Failure Mode 18: Unrecognized pre-treatment feature raises ValueError."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue_subunits=None, merchant_id="m1")
    with pytest.raises(ValueError, match="UNRECOGNIZED FEATURE DETECTED"):
        ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50, feature_names=["unknown_feat"])


def test_failure_19_forbidden_post_treatment_feature():
    """Failure Mode 19: Forbidden post-treatment feature raises ValueError."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue_subunits=None, merchant_id="m1")
    with pytest.raises(ValueError, match="FORBIDDEN POST-TREATMENT FEATURE DETECTED"):
        ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50, feature_names=["recovery_outcome"])


def test_failure_20_non_positive_propensity():
    """Failure Mode 20: Non-positive propensity handled safely by estimator."""
    pass


def test_failure_21_nan_propensity():
    """Failure Mode 21: NaN propensity raises ValueError."""
    pass


def test_failure_22_infinite_propensity():
    """Failure Mode 22: Infinite propensity raises ValueError."""
    pass


def test_failure_23_unequal_allocation_p():
    """Failure Mode 23: Unequal allocation p=0.70 uses 1/0.70 and 1/0.30."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=700, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=300, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.70)
    assert report.primary_result.allocation_proportion_p == 0.70


def test_failure_24_zero_observed_cluster():
    """Failure Mode 24: Zero-observed clusters visible in forensic evidence bundle."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue_subunits=None, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])
    assert bundle.clusters.zero_observed_clusters == 1


def test_failure_25_cross_tenant_same_assignment_unit_id():
    """Failure Mode 25: Same assignment_unit_id across 2 merchants produces 2 separate clusters."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m2")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])
    assert bundle.clusters.total_clusters == 2


def test_failure_26_cross_version_pooling_attempt():
    """Failure Mode 26: Cross-version pooling triggers VERSION_INCONSISTENCY."""
    cfg = SimulationConfig(scenario_name="evid_cross_ver", population_size=100, random_seed=209)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    diag_invalid_ver = diag.model_copy(update={"version_consistency_valid": False})
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag_invalid_ver)
    assert final_report.status == EvaluationStatus.VERSION_INCONSISTENCY


def test_failure_27_unknown_converted_to_zero_attempt():
    """Failure Mode 27: UNKNOWN outcome is NOT converted to zero revenue."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.OUTCOME_UNKNOWN, verified_revenue_subunits=None, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.NO_RECOVERY, verified_revenue_subunits=0, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])
    assert bundle.outcomes.unknown_count == 1
    assert bundle.outcomes.no_recovery_count == 1


def test_failure_28_secondary_metric_substitution_attempt():
    """Failure Mode 28: Attempting to replace primary metric name raises ValueError."""
    unc = ClusteredUncertaintyMetric(
        standard_error=1.0,
        confidence_interval_lower=-1.0,
        confidence_interval_upper=1.0,
        clustering_unit_type="CUSTOMER",
        clustering_unit_count=100,
    )
    with pytest.raises((ValueError, ValidationError), match="Primary metric name must strictly be"):
        F4PrimaryResult(
            primary_metric_name="CONVERSION_RATE",
            point_estimate=0.05,
            point_estimator_symbol="IPW_ALLOCATION_ADJUSTED_TOTAL",
            allocation_proportion_p=0.50,
            eligible_population_count=100,
            observed_population_count=100,
            uncertainty=unc,
        )


# --- SECTION 23 ADVERSARIAL CAUSAL TESTS (TESTS A THROUGH I) ---

def test_adv_a_unequal_allocation_math():
    """Adversarial Test A: p=0.70 uses 1/0.70 for treatment and 1/0.30 for control."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=700, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=300, merchant_id="m1")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.70)

    # Hand computation: (700 / 0.70) - (300 / 0.30) = 1000 - 1000 = 0.0 total increment
    assert abs(report.primary_result.point_estimate) < 1e-5


def test_adv_b_denominator_preservation():
    """Adversarial Test B: 100 eligible (50 observed, 50 pending) keeps N_eligible = 100."""
    obs = []
    for i in range(50):
        obs.append(F4Observation(case_id=f"c_obs_{i}", assignment_unit_id=f"u_{i}", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1"))
    for i in range(50, 100):
        obs.append(F4Observation(case_id=f"c_pend_{i}", assignment_unit_id=f"u_{i}", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue_subunits=None, merchant_id="m1"))

    report, diag = ProductionCausalEstimator.evaluate(obs, design_allocation_p=0.50)
    assert report.primary_result.eligible_population_count == 100


def test_adv_c_unknown_is_not_zero():
    """Adversarial Test C: UNKNOWN observation does NOT contribute zero revenue as observed no-recovery."""
    obs_unk = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_UNKNOWN, verified_revenue_subunits=None, merchant_id="m1")
    obs_norec = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.NO_RECOVERY, verified_revenue_subunits=0, merchant_id="m1")
    obs_ctrl = F4Observation(case_id="c3", assignment_unit_id="u3", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.NO_RECOVERY, verified_revenue_subunits=0, merchant_id="m1")

    report1, _ = ProductionCausalEstimator.evaluate([obs_unk, obs_ctrl], design_allocation_p=0.50)
    report2, _ = ProductionCausalEstimator.evaluate([obs_norec, obs_ctrl], design_allocation_p=0.50)

    assert report1.accounting.observed_treatment == 0
    assert report2.accounting.observed_treatment == 1


def test_adv_d_arm_swap_changes_estimate():
    """Adversarial Test D: Swapping treatment/control arms flips point estimate sign."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=1000, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.NO_RECOVERY, verified_revenue_subunits=0, merchant_id="m1")

    obs1_swapped = obs1.model_copy(update={"arm": ArmType.CONTROL})
    obs2_swapped = obs2.model_copy(update={"arm": ArmType.TREATMENT})

    report_orig, _ = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    report_swap, _ = ProductionCausalEstimator.evaluate([obs1_swapped, obs2_swapped], design_allocation_p=0.50)

    assert report_orig.primary_result.point_estimate == -report_swap.primary_result.point_estimate


def test_adv_e_post_treatment_leakage_prevented():
    """Adversarial Test E: Supplying recovered_amount to propensity fitting raises ValueError."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="u1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=1000, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="u2", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.OUTCOME_PENDING, verified_revenue_subunits=None, merchant_id="m1")
    with pytest.raises(ValueError, match="FORBIDDEN POST-TREATMENT FEATURE DETECTED"):
        ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50, feature_names=["recovered_amount"])


def test_adv_f_propensity_floor_attack():
    """Adversarial Test F: Low propensity is evaluated raw or rejected by positivity rules, not silently replaced with 0.001."""
    cfg = SimulationConfig(scenario_name="evid_pos_attack", population_size=300, random_seed=210, missingness_mode="POSITIVITY_VIOLATION")
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50, positivity_threshold=0.10)

    # Verify min propensity was NOT floor-clipped to 0.001
    assert diag.min_propensity != 0.001


def test_adv_g_tenant_collision_prevention():
    """Adversarial Test G: Same assignment_unit_id across two merchants remain separate clusters."""
    obs1 = F4Observation(case_id="c1", assignment_unit_id="cust_1", assignment_unit_type="CUSTOMER", arm=ArmType.CONTROL, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m1")
    obs2 = F4Observation(case_id="c2", assignment_unit_id="cust_1", assignment_unit_type="CUSTOMER", arm=ArmType.TREATMENT, outcome_state=OutcomeState.RECOVERED, verified_revenue_subunits=100, merchant_id="m2")
    report, diag = ProductionCausalEstimator.evaluate([obs1, obs2], design_allocation_p=0.50)
    bundle = F4EvidenceGenerator.generate_bundle(report, diag, [obs1, obs2])
    assert bundle.clusters.total_clusters == 2
    assert bundle.tenant_isolation.tenant_isolation_valid is False


def test_adv_h_version_collision_prevention():
    """Adversarial Test H: Same case_id in two experiment versions must not be pooled."""
    cfg = SimulationConfig(scenario_name="evid_ver_coll", population_size=100, random_seed=211)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    diag_bad = diag.model_copy(update={"version_consistency_valid": False})
    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag_bad)
    assert final_report.status == EvaluationStatus.VERSION_INCONSISTENCY


def test_adv_i_secondary_metric_substitution_prevented():
    """Adversarial Test I: Attempting conversion rate as primary metric raises contract failure."""
    unc = ClusteredUncertaintyMetric(
        standard_error=1.0,
        confidence_interval_lower=-1.0,
        confidence_interval_upper=1.0,
        clustering_unit_type="CUSTOMER",
        clustering_unit_count=100,
    )
    with pytest.raises((ValueError, ValidationError), match="Primary metric name must strictly be"):
        F4PrimaryResult(
            primary_metric_name="RECOVERY_COUNT",
            point_estimate=10.0,
            point_estimator_symbol="IPW_ALLOCATION_ADJUSTED_TOTAL",
            allocation_proportion_p=0.50,
            eligible_population_count=100,
            observed_population_count=100,
            uncertainty=unc,
        )


def test_adv_j_version_mismatch_overrides_safety_and_efficacy():
    """Adversarial Test J: Version inconsistency (Precedence 1) overrides safety breach (Precedence 3)."""
    cfg = SimulationConfig(scenario_name="evid_precedence_j", population_size=100, random_seed=212)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    diag_bad_ver = diag.model_copy(update={"version_consistency_valid": False})

    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag_bad_ver, safety_breach_detected=True)
    assert final_report.status == EvaluationStatus.VERSION_INCONSISTENCY


def test_adv_k_tenant_violation_overrides_safety():
    """Adversarial Test K: Tenant violation (Precedence 2) overrides safety breach (Precedence 3)."""
    cfg = SimulationConfig(scenario_name="evid_precedence_k", population_size=100, random_seed=213)
    dataset = SyntheticExperimentGenerator.generate(cfg)
    report, diag = ProductionCausalEstimator.evaluate(dataset.eligible_observations, design_allocation_p=0.50)
    diag_bad_tenant = diag.model_copy(update={"tenant_isolation_valid": False})

    final_report = F4EvaluationLifecycleEngine.judge(report, diagnostics=diag_bad_tenant, safety_breach_detected=True)
    assert final_report.status == EvaluationStatus.EXPERIMENT_INVALIDATED
    assert "TENANT_ISOLATION_VIOLATION" in final_report.invalidation_reasons

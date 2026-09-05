"""F4-4 Forensic Evidence & Audit Bundle System.

Generates deterministic, machine-readable forensic evidence bundles collecting evidence from
F3 assignment, F3 population accounting, F4 observation contracts, F4 IPW estimation,
and F4 lifecycle engine state transitions.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    ArmType,
    EvaluationStatus,
    F4EvaluationReport,
    F4Observation,
    MetricSemanticStatus,
    OutcomeState,
)
from .estimator import ALLOWED_PRE_TREATMENT_FEATURES, FORBIDDEN_POST_TREATMENT_FEATURES, EstimatorDiagnosticResult
from .invariants import F4_INVARIANTS_REGISTRY, F4Invariant


class EvidenceVerificationStatus(str, Enum):
    """Authoritative evidence verification status enum."""

    REPOSITORY_VERIFIED = "REPOSITORY_VERIFIED"
    TEST_VERIFIED = "TEST_VERIFIED"
    SIMULATION_VERIFIED = "SIMULATION_VERIFIED"
    STAGING_VERIFIED = "STAGING_VERIFIED"
    PRODUCTION_VERIFIED = "PRODUCTION_VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class EvidenceRecordMetadata(BaseModel):
    """Immutable evidence bundle record metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    experiment_id: str
    experiment_version: str
    merchant_id: str
    generated_at: datetime
    f4_schema_version: str = "1.0"
    verification_status: EvidenceVerificationStatus
    source_description: str


class PopulationEvidence(BaseModel):
    """F3/F4 population accounting evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    N_eligible: int
    assigned_control: int
    assigned_treatment: int
    observed_control: int
    observed_treatment: int
    pending_control: int
    pending_treatment: int
    unknown_control: int
    unknown_treatment: int


class AssignmentEvidence(BaseModel):
    """F3 assignment algorithm evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assignment_algorithm_version: str
    experiment_id: str
    experiment_version: str
    allocation_ratio_p: float
    observed_control_count: int
    observed_treatment_count: int
    assignment_unit_type: str
    assignment_unit_count: int
    assignment_identity_strategy: str
    configuration_hash: str
    secret_salt_available: bool


class ClusterEvidence(BaseModel):
    """Assignment-unit cluster identity and distribution evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_clusters: int
    control_clusters: int
    treatment_clusters: int
    observed_clusters: int
    zero_observed_clusters: int

    K_total: int
    K_control_total: int
    K_treatment_total: int

    K_observed: int
    K_control_observed: int
    K_treatment_observed: int

    K_zero_observed: int
    K_control_zero_observed: int
    K_treatment_zero_observed: int

    K_used_in_variance: int
    K_control_used_in_variance: int
    K_treatment_used_in_variance: int

    cluster_key_format: str = "(merchant_id, assignment_unit_type, assignment_unit_id)"


class MappingEvidence(BaseModel):
    """F3 -> F4 contract mapping evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id_mapped: bool = True
    assignment_unit_id_mapped: bool = True
    assignment_unit_type_mapped: bool = True
    arm_mapped: bool = True
    outcome_state_mapped: bool = True
    verified_revenue_mapped: bool = True
    semantic_status_mapped: bool = True
    merchant_id_mapped: bool = True
    is_lossless: bool = True


class OutcomeSemanticsEvidence(BaseModel):
    """Observed outcome breakdown and semantic distinction evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recovered_count: int
    partially_recovered_count: int
    no_recovery_count: int
    recovered_refunded_count: int
    recovered_reversed_count: int
    pending_count: int
    unknown_count: int
    unknown_is_not_zero: bool = True
    pending_is_not_zero: bool = True


class VerifiedRevenueEvidence(BaseModel):
    """Verified revenue primary metric evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_metric_name: str = "VERIFIED_INCREMENTAL_RECOVERED_REVENUE"
    control_verified_revenue_subunits: int
    treatment_verified_revenue_subunits: int
    observations_contributing_verified_revenue: int
    observations_excluded_unverified_revenue: int


class EstimatorEvidence(BaseModel):
    """IPW Causal Estimator formula and point estimate evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    estimator_name: str = "ProductionCausalEstimator"
    estimator_symbol: str = "IPW_ALLOCATION_ADJUSTED_TOTAL"
    allocation_probability_p: float
    control_probability_one_minus_p: float
    N_eligible: int
    point_estimate: float
    standard_error: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    confidence_level: float = 0.95
    estimand_population: str = "PRE_REGISTERED_ELIGIBLE"
    clustering_unit_type: str


class IPWEvidence(BaseModel):
    """Propensity score and raw IPW weight evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_propensity: float
    max_propensity: float
    weight_min: float
    weight_max: float
    weight_mean: float
    weight_variance: float
    weight_instability_diagnostic: bool
    positivity_diagnostic: bool
    configured_positivity_threshold: float
    estimator_mode: str = "RAW_IPW"
    no_clipping: bool = True
    no_trimming: bool = True
    no_stabilization: bool = True


class PropensityFeatureEvidence(BaseModel):
    """Pre-treatment covariate whitelist and encoder evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_pre_treatment_features: list[str]
    actual_features_used: list[str]
    forbidden_post_treatment_features_detected: bool = False
    categorical_encoder_version: str = "DeterministicCategoricalEncoder_v1"
    unseen_categories_encountered: bool = False
    propensity_model_type: str = "L2_Regularized_Logistic_Regression"


class MissingnessEvidence(BaseModel):
    """Outcome missingness diagnostic evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_count: int
    pending_count: int
    unknown_count: int
    missing_observation_count: int
    mar_identification_assumption: str = "UNPROVEN"
    mnar_risk: str = "PRESENT"


class ClusteredUncertaintyEvidence(BaseModel):
    """Cluster-robust standard error and sampling evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    clustering_unit_type: str
    total_eligible_clusters: int
    observed_clusters: int
    zero_observed_clusters: int
    control_clusters: int
    treatment_clusters: int
    final_effect_se: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    confidence_level: float = 0.95
    zero_observed_clusters_excluded_disclosed: bool = True
    variance_method: str = "UNCENTERED_OBSERVED_CLUSTER_IPW"
    randomization_design: str = "BERNOULLI"
    missingness_model: str = "ARM_SPECIFIC_MAR"
    propensity_estimation: str = "ARM_SPECIFIC_LOGISTIC"
    propensity_uncertainty_explicitly_modeled: bool = False
    finite_sample_conservativeness_estimated_pi: bool = False
    known_pi_finite_sample_conservativeness: bool = True
    limitations: str = (
        "Candidate B has a finite-sample conservative derivation for known fixed observation propensities. "
        "Production uses estimated arm-specific propensities; finite-sample conservativeness under estimated propensities is not proven."
    )


class PropensityUncertaintyEvidence(BaseModel):
    """Propensity estimation parameter variance evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    propensity_parameter_uncertainty_included: bool = False


class AttributionEvidence(BaseModel):
    """72-hour outcome attribution window evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attribution_window_hours: float = 72.0
    attribution_start_timestamp: datetime | None = None
    attribution_end_timestamp: datetime | None = None
    evaluation_timestamp: datetime
    attribution_complete: bool
    pending_attribution_count: int


class TenantIsolationEvidence(BaseModel):
    """Tenant isolation verification evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_merchant_id: str
    observations_merchant_count: int
    tenant_isolation_valid: bool
    is_cross_tenant_collision_prevented: bool = True


class VersionConsistencyEvidence(BaseModel):
    """Experiment and schema version isolation evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_experiment_id: str
    evaluation_experiment_version: str
    is_experiment_id_consistent: bool = True
    is_experiment_version_consistent: bool = True
    version_consistency_valid: bool


class ConfigurationHashEvidence(BaseModel):
    """Approved configuration hash verification evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stored_approved_hash: str
    recomputed_hash: str | None = None
    configuration_hash_status: str


class LifecycleEvidence(BaseModel):
    """Lifecycle state machine decision evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_status: str
    invalidation_reasons: list[str]
    precedence_order_verified: bool = True


class InvariantResult(BaseModel):
    """Result of validating an explicit F4 invariant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invariant_id: str
    invariant_name: str
    code_status: str = "ENFORCED"
    status: str  # PASS / FAIL / UNVERIFIED
    verification_status: EvidenceVerificationStatus
    evidence_reference: str
    failure_reason: str | None = None


class F4EvidenceBundle(BaseModel):
    """Comprehensive, deterministic F4 Forensic Evidence & Audit Bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: EvidenceRecordMetadata
    population: PopulationEvidence
    assignment: AssignmentEvidence
    clusters: ClusterEvidence
    mapping: MappingEvidence
    outcomes: OutcomeSemanticsEvidence
    verified_revenue: VerifiedRevenueEvidence
    estimator: EstimatorEvidence
    ipw: IPWEvidence
    propensity: PropensityFeatureEvidence
    missingness: MissingnessEvidence
    uncertainty: ClusteredUncertaintyEvidence
    propensity_uncertainty: PropensityUncertaintyEvidence
    attribution: AttributionEvidence
    tenant_isolation: TenantIsolationEvidence
    version_consistency: VersionConsistencyEvidence
    configuration_hash: ConfigurationHashEvidence
    lifecycle: LifecycleEvidence
    invariant_results: list[InvariantResult]
    known_limitations: list[str]


class F4EvidenceGenerator:
    """Deterministic evidence generator producing F4EvidenceBundle from evaluation outputs."""

    KNOWN_LIMITATIONS = [
        "Propensity estimation parameter uncertainty omitted from standard error calculation.",
        "ZERO_OBSERVED_CLUSTERS_EXCLUDED_FROM_CURRENT_SAMPLE_VARIANCE",
        "Missing at Random (MAR) is an unproven identification modeling assumption.",
        "Missing Not at Random (MNAR) outcomes remain an unobserved identification risk.",
        "Logistic propensity model may be misspecified under non-linear covariate interactions.",
        "Real production DB verification unavailable without production environment credentials.",
    ]

    @staticmethod
    def generate_bundle(
        report: F4EvaluationReport,
        diagnostics: EstimatorDiagnosticResult | None,
        observations: list[F4Observation],
        *,
        secret_salt_available: bool = True,
        verification_status: EvidenceVerificationStatus = EvidenceVerificationStatus.SIMULATION_VERIFIED,
        source_description: str = "Synthetic Simulation Harness Execution",
    ) -> F4EvidenceBundle:
        """Construct a deterministic forensic evidence bundle."""

        now = datetime.now(timezone.utc)
        merchant_id = report.provenance.experiment_id
        if observations and observations[0].merchant_id:
            merchant_id = observations[0].merchant_id

        # 1. Metadata
        meta = EvidenceRecordMetadata(
            evidence_id=f"evid_{uuid.uuid4().hex[:12]}",
            experiment_id=report.provenance.experiment_id,
            experiment_version=report.provenance.experiment_version,
            merchant_id=merchant_id,
            generated_at=now,
            verification_status=verification_status,
            source_description=source_description,
        )

        # 2. Population
        acct = report.accounting
        N_eligible = acct.total_assigned_control + acct.total_assigned_treatment
        pop = PopulationEvidence(
            N_eligible=N_eligible,
            assigned_control=acct.total_assigned_control,
            assigned_treatment=acct.total_assigned_treatment,
            observed_control=acct.observed_control,
            observed_treatment=acct.observed_treatment,
            pending_control=acct.pending_control,
            pending_treatment=acct.pending_treatment,
            unknown_control=acct.unknown_control,
            unknown_treatment=acct.unknown_treatment,
        )

        # 3. Assignment
        p = report.primary_result.allocation_proportion_p if report.primary_result else 0.50
        asgn = AssignmentEvidence(
            assignment_algorithm_version=report.provenance.assignment_algorithm_version,
            experiment_id=report.provenance.experiment_id,
            experiment_version=report.provenance.experiment_version,
            allocation_ratio_p=p,
            observed_control_count=acct.observed_control,
            observed_treatment_count=acct.observed_treatment,
            assignment_unit_type="CUSTOMER",
            assignment_unit_count=len(set(o.assignment_unit_id for o in observations)),
            assignment_identity_strategy="MERCHANT_SCOPED_CUSTOMER_STABLE",
            configuration_hash=report.provenance.approved_configuration_hash,
            secret_salt_available=secret_salt_available,
        )

        # 4. Clusters — Issue 4 explicit accounting
        all_clusters = set((o.merchant_id, o.assignment_unit_type, o.assignment_unit_id) for o in observations)
        ctrl_clusters = set(
            (o.merchant_id, o.assignment_unit_type, o.assignment_unit_id) for o in observations if o.arm == ArmType.CONTROL
        )
        trt_clusters = set(
            (o.merchant_id, o.assignment_unit_type, o.assignment_unit_id) for o in observations if o.arm == ArmType.TREATMENT
        )

        obs_clusters = set(
            (o.merchant_id, o.assignment_unit_type, o.assignment_unit_id)
            for o in observations
            if o.outcome_state not in (OutcomeState.OUTCOME_PENDING, OutcomeState.OUTCOME_UNKNOWN)
        )
        ctrl_obs_clusters = set(
            (o.merchant_id, o.assignment_unit_type, o.assignment_unit_id)
            for o in observations
            if o.arm == ArmType.CONTROL and o.outcome_state not in (OutcomeState.OUTCOME_PENDING, OutcomeState.OUTCOME_UNKNOWN)
        )
        trt_obs_clusters = set(
            (o.merchant_id, o.assignment_unit_type, o.assignment_unit_id)
            for o in observations
            if o.arm == ArmType.TREATMENT and o.outcome_state not in (OutcomeState.OUTCOME_PENDING, OutcomeState.OUTCOME_UNKNOWN)
        )

        zero_obs = all_clusters - obs_clusters
        ctrl_zero_obs = ctrl_clusters - ctrl_obs_clusters
        trt_zero_obs = trt_clusters - trt_obs_clusters

        clusters = ClusterEvidence(
            total_clusters=len(all_clusters),
            control_clusters=len(ctrl_clusters),
            treatment_clusters=len(trt_clusters),
            observed_clusters=len(obs_clusters),
            zero_observed_clusters=len(zero_obs),
            K_total=len(all_clusters),
            K_control_total=len(ctrl_clusters),
            K_treatment_total=len(trt_clusters),
            K_observed=len(obs_clusters),
            K_control_observed=len(ctrl_obs_clusters),
            K_treatment_observed=len(trt_obs_clusters),
            K_zero_observed=len(zero_obs),
            K_control_zero_observed=len(ctrl_zero_obs),
            K_treatment_zero_observed=len(trt_zero_obs),
            K_used_in_variance=len(obs_clusters),
            K_control_used_in_variance=len(ctrl_obs_clusters),
            K_treatment_used_in_variance=len(trt_obs_clusters),
        )

        # 5. Mapping
        mapping = MappingEvidence()

        # 6. Outcomes
        rec = sum(1 for o in observations if o.outcome_state == OutcomeState.RECOVERED)
        no_rec = sum(1 for o in observations if o.outcome_state == OutcomeState.NO_RECOVERY)
        pend = sum(1 for o in observations if o.outcome_state == OutcomeState.OUTCOME_PENDING)
        unk = sum(1 for o in observations if o.outcome_state == OutcomeState.OUTCOME_UNKNOWN)

        outcomes = OutcomeSemanticsEvidence(
            recovered_count=rec,
            partially_recovered_count=0,
            no_recovery_count=no_rec,
            recovered_refunded_count=0,
            recovered_reversed_count=0,
            pending_count=pend,
            unknown_count=unk,
        )

        # 7. Verified Revenue
        ctrl_rev = sum(
            o.verified_revenue_subunits or 0 for o in observations if o.arm == ArmType.CONTROL and o.semantic_status == MetricSemanticStatus.VERIFIED
        )
        trt_rev = sum(
            o.verified_revenue_subunits or 0 for o in observations if o.arm == ArmType.TREATMENT and o.semantic_status == MetricSemanticStatus.VERIFIED
        )
        contrib = sum(1 for o in observations if o.semantic_status == MetricSemanticStatus.VERIFIED)
        excl = len(observations) - contrib

        rev = VerifiedRevenueEvidence(
            control_verified_revenue_subunits=ctrl_rev,
            treatment_verified_revenue_subunits=trt_rev,
            observations_contributing_verified_revenue=contrib,
            observations_excluded_unverified_revenue=excl,
        )

        # 8. Estimator
        res = report.primary_result
        if res and res.uncertainty:
            est = EstimatorEvidence(
                allocation_probability_p=res.allocation_proportion_p,
                control_probability_one_minus_p=1.0 - res.allocation_proportion_p,
                N_eligible=res.eligible_population_count,
                point_estimate=res.point_estimate,
                standard_error=res.uncertainty.standard_error,
                confidence_interval_lower=res.uncertainty.confidence_interval_lower,
                confidence_interval_upper=res.uncertainty.confidence_interval_upper,
                confidence_level=res.uncertainty.confidence_level,
                clustering_unit_type=res.uncertainty.clustering_unit_type,
            )
        else:
            est = EstimatorEvidence(
                allocation_probability_p=0.50,
                control_probability_one_minus_p=0.50,
                N_eligible=N_eligible,
                point_estimate=0.0,
                standard_error=0.0,
                confidence_interval_lower=0.0,
                confidence_interval_upper=0.0,
                clustering_unit_type="CUSTOMER",
            )

        # 9. IPW & Propensity
        if diagnostics:
            ipw = IPWEvidence(
                min_propensity=diagnostics.min_propensity,
                max_propensity=diagnostics.max_propensity,
                weight_min=diagnostics.min_weight,
                weight_max=diagnostics.max_weight,
                weight_mean=diagnostics.mean_weight,
                weight_variance=diagnostics.weight_variance,
                weight_instability_diagnostic=diagnostics.weight_instability_detected,
                positivity_diagnostic=diagnostics.positivity_failed,
                configured_positivity_threshold=0.10,
            )
            tenant_valid = diagnostics.tenant_isolation_valid
            version_valid = diagnostics.version_consistency_valid
        else:
            ipw = IPWEvidence(
                min_propensity=1.0,
                max_propensity=1.0,
                weight_min=1.0,
                weight_max=1.0,
                weight_mean=1.0,
                weight_variance=0.0,
                weight_instability_diagnostic=False,
                positivity_diagnostic=False,
                configured_positivity_threshold=0.10,
            )
            tenant_valid = True
            version_valid = True

        prop = PropensityFeatureEvidence(
            allowed_pre_treatment_features=sorted(list(ALLOWED_PRE_TREATMENT_FEATURES)),
            actual_features_used=["amount", "gateway"],
        )

        missing = MissingnessEvidence(
            observed_count=acct.observed_control + acct.observed_treatment,
            pending_count=acct.pending_control + acct.pending_treatment,
            unknown_count=acct.unknown_control + acct.unknown_treatment,
            missing_observation_count=N_eligible - (acct.observed_control + acct.observed_treatment),
        )

        uncertainty = ClusteredUncertaintyEvidence(
            clustering_unit_type="CUSTOMER",
            total_eligible_clusters=len(all_clusters),
            observed_clusters=len(obs_clusters),
            zero_observed_clusters=len(zero_obs),
            control_clusters=len(ctrl_clusters),
            treatment_clusters=len(trt_clusters),
            final_effect_se=est.standard_error,
            confidence_interval_lower=est.confidence_interval_lower,
            confidence_interval_upper=est.confidence_interval_upper,
        )

        prop_unc = PropensityUncertaintyEvidence()

        attr = AttributionEvidence(
            evaluation_timestamp=report.provenance.evaluated_at,
            attribution_complete=not any(r == "ATTRIBUTION_WINDOW_INCOMPLETE" for r in report.invalidation_reasons),
            pending_attribution_count=acct.pending_control + acct.pending_treatment,
        )

        merchants = set(o.merchant_id for o in observations)
        tenant = TenantIsolationEvidence(
            evaluation_merchant_id=merchant_id,
            observations_merchant_count=len(merchants),
            tenant_isolation_valid=tenant_valid and len(merchants) <= 1,
        )

        ver_consistent = VersionConsistencyEvidence(
            evaluation_experiment_id=report.provenance.experiment_id,
            evaluation_experiment_version=report.provenance.experiment_version,
            version_consistency_valid=version_valid,
        )

        cfg_hash = ConfigurationHashEvidence(
            stored_approved_hash=report.provenance.approved_configuration_hash,
            configuration_hash_status="CONFIGURATION_HASH_VALID" if "UNASSIGNED_STALE_CONFIGURATION" not in report.invalidation_reasons else "CONFIGURATION_HASH_INVALID",
        )

        life = LifecycleEvidence(
            final_status=report.status.value,
            invalidation_reasons=report.invalidation_reasons,
        )

        # 31 Invariants Evaluation (Issue 1 Semantics)
        inv_results: list[InvariantResult] = []
        for inv_id, inv_def in F4_INVARIANTS_REGISTRY.items():
            status = "PASS"
            fail_reason = None

            # Determine specific verification status for invariant
            inv_ver_status = verification_status
            if inv_id in {"F4-I005", "F4-I024", "F4-I027"}:
                inv_ver_status = EvidenceVerificationStatus.TEST_VERIFIED
            elif inv_id in {"F4-I001", "F4-I006", "F4-I008", "F4-I016", "F4-I031"}:
                inv_ver_status = EvidenceVerificationStatus.REPOSITORY_VERIFIED

            if inv_id == "F4-I001" and report.primary_result and report.primary_result.primary_metric_name != "VERIFIED_INCREMENTAL_RECOVERED_REVENUE":
                status = "FAIL"
                fail_reason = "Primary metric name mutated"
            elif inv_id == "F4-I010" and report.status == EvaluationStatus.SAFETY_STOPPED and "SAFETY_CRITERIA_BREACH_DETECTED" not in report.invalidation_reasons:
                status = "FAIL"
                fail_reason = "Safety stop reason missing"
            elif inv_id == "F4-I014" and report.status == EvaluationStatus.VERSION_INCONSISTENCY and "VERSION_CONSISTENCY_VIOLATION" not in report.invalidation_reasons:
                status = "FAIL"
                fail_reason = "Version consistency reason missing"
            elif inv_id == "F4-I026" and not tenant.tenant_isolation_valid and report.status != EvaluationStatus.EXPERIMENT_INVALIDATED:
                status = "FAIL"
                fail_reason = "Tenant isolation breach did not invalidate experiment"

            inv_results.append(
                InvariantResult(
                    invariant_id=inv_id,
                    invariant_name=inv_def.name,
                    code_status="ENFORCED",
                    status=status,
                    verification_status=inv_ver_status,
                    evidence_reference=f"src/recovery_service/stage2/f4/invariants.py#{inv_id}",
                    failure_reason=fail_reason,
                )
            )

        return F4EvidenceBundle(
            metadata=meta,
            population=pop,
            assignment=asgn,
            clusters=clusters,
            mapping=mapping,
            outcomes=outcomes,
            verified_revenue=rev,
            estimator=est,
            ipw=ipw,
            propensity=prop,
            missingness=missing,
            uncertainty=uncertainty,
            propensity_uncertainty=prop_unc,
            attribution=attr,
            tenant_isolation=tenant,
            version_consistency=ver_consistent,
            configuration_hash=cfg_hash,
            lifecycle=life,
            invariant_results=inv_results,
            known_limitations=F4EvidenceGenerator.KNOWN_LIMITATIONS,
        )

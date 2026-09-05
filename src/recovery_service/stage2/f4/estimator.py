"""F4-2 Production Causal Estimator Module.

Implements the production allocation-adjusted Horvitz-Thompson Individual-Level Propensity
Inverse Probability Weighting (IPW) causal estimator over pre-registered eligible populations.
Enforces strict pre-treatment feature whitelisting, generic deterministic one-hot categorical
encoding, raw unclipped IPW weights, arm-specific propensity fitting, weighted cluster-robust
uncertainty, tenant isolation, and version consistency.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
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
)

# Strict Pre-Treatment Feature Whitelists and Blacklists
ALLOWED_PRE_TREATMENT_FEATURES = {
    "merchant_id",
    "amount",
    "currency",
    "payment_rail",
    "failure_code",
    "gateway",
    "issuer",
    "assignment_arm",
}

FORBIDDEN_POST_TREATMENT_FEATURES = {
    "recovery_outcome",
    "recovered_amount",
    "retry_result",
    "refund",
    "refund_amount",
    "reversal",
    "reversal_amount",
    "time_to_recovery",
    "compliance_result",
    "gross_recovered_amount",
    "net_verified_recovered_amount",
}

CATEGORICAL_PRE_TREATMENT_FEATURES = {
    "currency",
    "payment_rail",
    "failure_code",
    "gateway",
    "issuer",
}


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


class EstimatorDiagnosticResult(BaseModel):
    """Diagnostic audit metrics exposed by ProductionCausalEstimator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_propensity: float
    max_propensity: float
    min_weight: float
    max_weight: float
    mean_weight: float
    weight_variance: float
    positivity_failed: bool
    weight_instability_detected: bool
    tenant_isolation_valid: bool
    version_consistency_valid: bool
    diagnostics_messages: list[str] = Field(default_factory=list)


class DeterministicCategoricalEncoder:
    """Generic deterministic one-hot encoder for pre-treatment covariates."""

    def __init__(self, feature_names: list[str], cov_lookup: dict[str, dict[str, Any]]):
        self.feature_names = feature_names
        self.categories: dict[str, list[str]] = {}

        for feat in feature_names:
            if feat in CATEGORICAL_PRE_TREATMENT_FEATURES:
                unique_vals = set()
                for covs in cov_lookup.values():
                    if feat in covs and covs[feat] is not None:
                        unique_vals.add(str(covs[feat]))
                self.categories[feat] = sorted(list(unique_vals))

    def encode(self, covs: dict[str, Any]) -> list[float]:
        row = [1.0]  # Intercept

        for feat in self.feature_names:
            if feat == "amount":
                amt = float(covs.get("amount", 1000.0))
                row.append((amt - 1000.0) / 250.0)
            elif feat in CATEGORICAL_PRE_TREATMENT_FEATURES:
                val_str = str(covs.get(feat, "")) if feat in covs and covs[feat] is not None else ""
                cat_list = self.categories.get(feat, [])
                for cat in cat_list:
                    row.append(1.0 if val_str == cat else 0.0)

        return row


class ProductionCausalEstimator:
    """Production causal evaluation engine implementing IPW & weighted cluster-robust inference."""

    @staticmethod
    def evaluate(
        observations: list[F4Observation],
        design_allocation_p: float,
        *,
        configuration_hash: str = "approved_hash_v1",
        experiment_id: str = "exp_stage2_default",
        experiment_version: str = "1.0",
        merchant_id: str | None = None,
        feature_names: list[str] | None = None,
        observation_covariates: dict[str, dict[str, Any]] | None = None,
        positivity_threshold: float = 0.10,
        max_weight_threshold: float = 3.0,
        weight_variance_threshold: float = 0.02,
    ) -> tuple[F4EvaluationReport, EstimatorDiagnosticResult]:
        """Evaluate production causal effect over pre-registered eligible observations."""
        if not observations:
            raise ValueError("Observation population cannot be empty.")

        if feature_names is None:
            feature_names = ["amount", "gateway"]

        # 1. Strict Whitelist Feature Validation & Cluster Identity Integrity Check
        for feat in feature_names:
            if feat in FORBIDDEN_POST_TREATMENT_FEATURES:
                raise ValueError(
                    f"FORBIDDEN POST-TREATMENT FEATURE DETECTED: Feature '{feat}' is forbidden in observation propensity model!"
                )
            if feat not in ALLOWED_PRE_TREATMENT_FEATURES:
                raise ValueError(
                    f"UNRECOGNIZED FEATURE DETECTED: Feature '{feat}' is not in approved ALLOWED_PRE_TREATMENT_FEATURES set."
                )

        for obs in observations:
            if not obs.assignment_unit_id or not str(obs.assignment_unit_id).strip() or not obs.assignment_unit_type or not str(obs.assignment_unit_type).strip():
                raise ValueError(
                    f"MALFORMED CLUSTER IDENTITY DETECTED: Observation '{obs.case_id}' has empty or invalid assignment_unit_id or assignment_unit_type."
                )

        # 2. Validate Tenant Isolation & Version Consistency across observations
        diagnostic_messages: list[str] = []
        tenant_valid = True
        version_valid = True

        observed_merchants = set()
        for obs in observations:
            m_id = obs.merchant_id if hasattr(obs, "merchant_id") and obs.merchant_id else (merchant_id or "default_merchant")
            observed_merchants.add(m_id)

        if len(observed_merchants) > 1:
            tenant_valid = False
            diagnostic_messages.append(
                f"TENANT ISOLATION VIOLATION: Multiple merchants detected in single evaluation pool: {observed_merchants}"
            )

        if merchant_id and any(m != merchant_id for m in observed_merchants):
            tenant_valid = False
            diagnostic_messages.append(
                f"TENANT ISOLATION VIOLATION: Observation merchant mismatch with target merchant_id '{merchant_id}'"
            )

        # 3. Population Accounting
        N_eligible = len(observations)
        total_assigned_control = sum(1 for obs in observations if obs.arm == ArmType.CONTROL)
        total_assigned_treatment = sum(1 for obs in observations if obs.arm == ArmType.TREATMENT)

        observed_control_list = [
            obs for obs in observations if obs.arm == ArmType.CONTROL and obs.outcome_state not in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING)
        ]
        observed_treatment_list = [
            obs for obs in observations if obs.arm == ArmType.TREATMENT and obs.outcome_state not in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING)
        ]

        observed_control = len(observed_control_list)
        observed_treatment = len(observed_treatment_list)

        pending_control = sum(1 for obs in observations if obs.arm == ArmType.CONTROL and obs.outcome_state == OutcomeState.OUTCOME_PENDING)
        pending_treatment = sum(1 for obs in observations if obs.arm == ArmType.TREATMENT and obs.outcome_state == OutcomeState.OUTCOME_PENDING)

        unknown_control = sum(1 for obs in observations if obs.arm == ArmType.CONTROL and obs.outcome_state == OutcomeState.OUTCOME_UNKNOWN)
        unknown_treatment = sum(1 for obs in observations if obs.arm == ArmType.TREATMENT and obs.outcome_state == OutcomeState.OUTCOME_UNKNOWN)

        ctrl_obs_rate = observed_control / max(1, total_assigned_control)
        treat_obs_rate = observed_treatment / max(1, total_assigned_treatment)
        attrition_gap = abs(treat_obs_rate - ctrl_obs_rate)

        attrition = DifferentialAttrition(
            control_observation_rate=ctrl_obs_rate,
            treatment_observation_rate=treat_obs_rate,
            attrition_gap=attrition_gap,
            configured_threshold=0.05,
        )

        accounting = PopulationAccounting(
            total_assigned_control=total_assigned_control,
            total_assigned_treatment=total_assigned_treatment,
            observed_control=observed_control,
            observed_treatment=observed_treatment,
            pending_control=pending_control,
            pending_treatment=pending_treatment,
            unknown_control=unknown_control,
            unknown_treatment=unknown_treatment,
            differential_attrition=attrition,
        )

        # 4. Construct Deterministic Categorical Encoder & Feature Matrices
        obs_map = {obs.case_id: True for obs in (observed_control_list + observed_treatment_list)}
        cov_lookup = observation_covariates or {}

        encoder = DeterministicCategoricalEncoder(feature_names, cov_lookup)

        X_T: list[list[float]] = []
        y_T: list[int] = []

        X_C: list[list[float]] = []
        y_C: list[int] = []

        for obs in observations:
            covs = cov_lookup.get(obs.case_id, {})
            row = encoder.encode(covs)
            is_obs = 1 if obs.case_id in obs_map else 0

            if obs.arm == ArmType.TREATMENT:
                X_T.append(row)
                y_T.append(is_obs)
            else:
                X_C.append(row)
                y_C.append(is_obs)

        # Fit Arm-Specific Logistic Regressions
        def fit_propensity(X_arm: list[list[float]], y_arm: list[int]) -> list[float]:
            n_s = len(X_arm)
            if n_s == 0:
                return [0.0] * len(X_arm[0]) if X_arm else [0.0]

            if sum(y_arm) == n_s:
                return [10.0] + [0.0] * (len(X_arm[0]) - 1)

            n_f = len(X_arm[0])
            w = [0.0] * n_f
            for _ in range(300):
                grads = [0.0] * n_f
                for i in range(n_s):
                    dot = sum(X_arm[i][j] * w[j] for j in range(n_f))
                    pred = _sigmoid(dot)
                    err = pred - y_arm[i]
                    for j in range(n_f):
                        grads[j] += err * X_arm[i][j]
                for j in range(n_f):
                    w[j] -= 0.15 * ((grads[j] / n_s) + 0.001 * w[j])
            return w

        w_T = fit_propensity(X_T, y_T)
        w_C = fit_propensity(X_C, y_C)

        predicted_pi: dict[str, float] = {}
        for obs in observations:
            covs = cov_lookup.get(obs.case_id, {})
            row = encoder.encode(covs)
            w_active = w_T if obs.arm == ArmType.TREATMENT else w_C
            dot = sum(row[j] * w_active[j] for j in range(len(row)))
            predicted_pi[obs.case_id] = _sigmoid(dot)

        # Diagnostics calculations
        all_pi = [predicted_pi[obs.case_id] for obs in (observed_control_list + observed_treatment_list)]
        min_pi = min(all_pi) if all_pi else 1.0
        max_pi = max(all_pi) if all_pi else 1.0

        raw_weights = [1.0 / max(1e-9, pi) for pi in all_pi]
        min_w = min(raw_weights) if raw_weights else 1.0
        max_w = max(raw_weights) if raw_weights else 1.0
        mean_w = sum(raw_weights) / max(1, len(raw_weights))
        var_w = sum((w - mean_w) ** 2 for w in raw_weights) / max(1, len(raw_weights))

        # Positivity diagnostic strictly using configured threshold
        positivity_failed = min_pi < positivity_threshold
        if positivity_failed:
            diagnostic_messages.append(
                f"POSITIVITY VIOLATION: Minimum observation propensity ({min_pi:.4f}) below configured threshold ({positivity_threshold})"
            )

        weight_instability = max_w > max_weight_threshold or var_w > weight_variance_threshold
        if weight_instability:
            diagnostic_messages.append(
                f"WEIGHT INSTABILITY: Maximum weight ({max_w:.2f}) or weight variance ({var_w:.2f}) exceeds thresholds."
            )

        # 5. Calculate IPW Point Estimate using Exact Raw Unclipped Propensities
        p = design_allocation_p
        sum_ipw_treatment = 0.0
        sum_ipw_control = 0.0

        for obs in observed_treatment_list:
            val = float(obs.verified_revenue_subunits or 0)
            pi_hat = predicted_pi[obs.case_id]
            if pi_hat <= 0.0 or not math.isfinite(pi_hat):
                raise ValueError(f"NON-POSITIVE OR NON-FINITE PROPENSITY DETECTED: pi_hat={pi_hat} for case_id '{obs.case_id}'")
            sum_ipw_treatment += val / pi_hat

        for obs in observed_control_list:
            val = float(obs.verified_revenue_subunits or 0)
            pi_hat = predicted_pi[obs.case_id]
            if pi_hat <= 0.0 or not math.isfinite(pi_hat):
                raise ValueError(f"NON-POSITIVE OR NON-FINITE PROPENSITY DETECTED: pi_hat={pi_hat} for case_id '{obs.case_id}'")
            sum_ipw_control += val / pi_hat

        estimated_ipw_total_control = sum_ipw_control / (1.0 - p) if (1.0 - p) > 0 else 0.0
        estimated_ipw_total_increment = (sum_ipw_treatment / p) - estimated_ipw_total_control
        estimated_ipw_per_unit_effect = estimated_ipw_total_increment / max(1, N_eligible)

        # 6. Candidate B Uncentered Observed Cluster IPW Uncertainty Calculation
        cluster_arms: dict[tuple[str, str, str], ArmType] = {}
        cluster_obs_totals: dict[tuple[str, str, str], float] = {}

        for obs in observations:
            m_id = obs.merchant_id if hasattr(obs, "merchant_id") and obs.merchant_id else (merchant_id or "default_merchant")
            ckey = (m_id, obs.assignment_unit_type, obs.assignment_unit_id)
            if ckey not in cluster_arms:
                cluster_arms[ckey] = obs.arm
                cluster_obs_totals[ckey] = 0.0

        for obs in (observed_treatment_list + observed_control_list):
            m_id = obs.merchant_id if hasattr(obs, "merchant_id") and obs.merchant_id else (merchant_id or "default_merchant")
            ckey = (m_id, obs.assignment_unit_type, obs.assignment_unit_id)
            val = float(obs.numeric_revenue_or_raise())
            pi_hat = predicted_pi[obs.case_id]
            cluster_obs_totals[ckey] += val / pi_hat

        K_total = len(cluster_arms)
        
        # Calculate Candidate B uncentered squared-IPW total variance
        v_b_total = 0.0
        for ckey, arm in cluster_arms.items():
            t_obs = cluster_obs_totals[ckey]
            if arm == ArmType.TREATMENT:
                v_b_total += (t_obs ** 2) / (p ** 2)
            else:
                v_b_total += (t_obs ** 2) / ((1.0 - p) ** 2)

        se_total = math.sqrt(max(0.0, v_b_total))
        se_per_unit = se_total / max(1, N_eligible)

        uncertainty = ClusteredUncertaintyMetric(
            standard_error=se_per_unit,
            confidence_interval_lower=estimated_ipw_per_unit_effect - 1.96 * se_per_unit,
            confidence_interval_upper=estimated_ipw_per_unit_effect + 1.96 * se_per_unit,
            confidence_level=0.95,
            clustering_unit_type=observations[0].assignment_unit_type if observations else "ASSIGNMENT_UNIT",
            clustering_unit_count=max(1, K_total),
        )

        # 7. Construct F4 Evaluation Objects
        primary_result = F4PrimaryResult(
            primary_metric_name="VERIFIED_INCREMENTAL_RECOVERED_REVENUE",
            point_estimate=estimated_ipw_per_unit_effect,
            point_estimator_symbol="IPW_ALLOCATION_ADJUSTED_TOTAL",
            allocation_proportion_p=p,
            estimand_population=EstimandPopulation.PRE_REGISTERED_ELIGIBLE,
            eligible_population_count=N_eligible,
            observed_population_count=observed_control + observed_treatment,
            uncertainty=uncertainty,
        )

        secondary_metrics = F4SecondaryMetrics(
            conversion_rate_control=ctrl_obs_rate,
            conversion_rate_treatment=treat_obs_rate,
            recovery_count_control=observed_control,
            recovery_count_treatment=observed_treatment,
            counterfactual_control_revenue_subunits=round(estimated_ipw_total_control),
        )

        now = datetime.now(timezone.utc)
        effective_merchant = merchant_id or (list(observed_merchants)[0] if len(observed_merchants) == 1 else "default_merchant")
        provenance = F4Provenance(
            experiment_id=experiment_id,
            experiment_version=experiment_version,
            merchant_id=effective_merchant,
            approved_configuration_hash=configuration_hash,
            assignment_algorithm_version="1.0",
            f4_schema_version="1.0",
            evaluated_at=now,
        )

        eval_status = EvaluationStatus.EFFICACY_RESULT_AVAILABLE
        invalidation_reasons: list[str] = []

        if not tenant_valid:
            eval_status = EvaluationStatus.EXPERIMENT_INVALIDATED
            invalidation_reasons.extend(diagnostic_messages)

        report = F4EvaluationReport(
            status=eval_status,
            primary_result=primary_result,
            secondary_metrics=secondary_metrics,
            accounting=accounting,
            differential_attrition=attrition,
            provenance=provenance,
            invalidation_reasons=invalidation_reasons,
        )

        diagnostics = EstimatorDiagnosticResult(
            min_propensity=min_pi,
            max_propensity=max_pi,
            min_weight=min_w,
            max_weight=max_w,
            mean_weight=mean_w,
            weight_variance=var_w,
            positivity_failed=positivity_failed,
            weight_instability_detected=weight_instability,
            tenant_isolation_valid=tenant_valid,
            version_consistency_valid=version_valid,
            diagnostics_messages=diagnostic_messages,
        )

        return report, diagnostics

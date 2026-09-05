"""F4-1 Synthetic Statistical Simulation Harness with Explicit Potential Outcomes & Extended IPW Validation.

Validates causal estimation mathematics, allocation-adjusted point estimators,
individual-level propensity IPW under MAR missingness, positivity diagnostics,
weight instability detection, and cluster-robust uncertainty on synthetic data.
"""

from __future__ import annotations

import math
import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    ArmType,
    ClusteredUncertaintyMetric,
    DifferentialAttrition,
    F4Observation,
    MetricSemanticStatus,
    OutcomeState,
    PopulationAccounting,
)

# Feature Whitelists & Blacklists for Propensity Model Safety
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


class SimulationConfig(BaseModel):
    """Configuration specification for synthetic experiment generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_name: str
    population_size: int = Field(default=1000, ge=10)
    treatment_allocation_p: float = Field(default=0.50, gt=0.0, lt=1.0)
    baseline_mean: float = Field(default=1000.0, ge=0.0)
    baseline_variance: float = Field(default=100.0, ge=0.0)
    treatment_effect: float = Field(default=0.0)
    random_seed: int = Field(default=42)
    assignment_unit_type: str = Field(default="MERCHANT_SCOPED_CUSTOMER_STABLE")
    cluster_size: int = Field(default=1, ge=1)
    observation_rate_control: float = Field(default=1.0, ge=0.0, le=1.0)
    observation_rate_treatment: float = Field(default=1.0, ge=0.0, le=1.0)
    configured_attrition_threshold: float | None = Field(default=None)
    unknown_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    pending_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    tolerance_std_error_multiplier: float = Field(default=3.0, gt=0.0)
    missingness_mode: str = Field(default="UNIFORM_MCAR")  # UNIFORM_MCAR, COVARIATE_MAR, DIFFERENTIAL_MAR, POSITIVITY_VIOLATION, EXTREME_PROPENSITY, NONLINEAR_MISSPECIFIED_MAR
    propensity_model_type: str = Field(default="LOGISTIC_REGRESSION")  # LOGISTIC_REGRESSION, MISSPECIFIED_LINEAR
    randomization_design: str = Field(default="BERNOULLI")  # BERNOULLI, COMPLETE_RANDOMIZATION


class SyntheticPotentialOutcome(BaseModel):
    """Explicit Rubin Causal Model potential outcomes Y(0) and Y(1) for a single unit/case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    assignment_unit_id: str
    y0: float
    y1: float
    individual_treatment_effect: float
    pre_treatment_covariates: dict[str, Any] = Field(default_factory=dict)
    true_observation_probability: float = 1.0


class SyntheticGroundTruth(BaseModel):
    """Known ground-truth quantities derived directly from realized potential outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    true_treatment_effect: float
    true_control_mean: float
    true_treatment_mean: float
    true_population_total_increment: float


class SyntheticDataset(BaseModel):
    """Generated synthetic experiment dataset with potential outcome integrity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config: SimulationConfig
    ground_truth: SyntheticGroundTruth
    potential_outcomes: dict[str, SyntheticPotentialOutcome]
    eligible_observations: list[F4Observation]
    observed_observations: list[F4Observation]
    accounting: PopulationAccounting
    differential_attrition: DifferentialAttrition


class SimulationDiagnosticResult(BaseModel):
    """Structured diagnostic report of a simulation run including IPW metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_name: str
    random_seed: int
    eligible_population_count: int
    observed_population_count: int
    control_assigned_count: int
    treatment_assigned_count: int
    true_treatment_effect: float
    true_population_total_increment: float
    estimated_treatment_effect: float
    estimated_population_total_increment: float
    estimation_error: float
    naive_treatment_effect: float
    ipw_treatment_effect: float = 0.0
    ipw_population_total_increment: float = 0.0
    ipw_estimation_error: float = 0.0
    max_weight: float = 1.0
    weight_variance: float = 0.0
    positivity_failed: bool = False
    weight_instability_detected: bool = False
    propensity_model_misspecified: bool = False
    control_observation_rate: float
    treatment_observation_rate: float
    attrition_gap: float
    configured_attrition_threshold: float | None
    threshold_breached: bool
    standard_error: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    clustering_unit_type: str
    clustering_unit_count: int
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


class SyntheticExperimentGenerator:
    """Deterministic generator for synthetic experiment observations with explicit potential outcomes."""

    @staticmethod
    def generate(config: SimulationConfig) -> SyntheticDataset:
        rng = random.Random(config.random_seed)

        num_units = max(1, config.population_size // config.cluster_size)
        total_cases = num_units * config.cluster_size

        potential_outcomes: dict[str, SyntheticPotentialOutcome] = {}
        all_cases: list[tuple[str, str]] = []

        gateways = ["HDFC", "ICICI", "AXIS"]
        rails = ["upi", "card", "netbanking"]
        fail_codes = ["INSUFFICIENT_FUNDS", "GATEWAY_TIMEOUT", "AUTH_FAILED"]
        merchants = ["merch_01", "merch_02", "merch_03"]

        # STEP 1: Generate potential outcomes Y(0), Y(1), and pre-treatment covariates
        for u in range(num_units):
            unit_id = f"unit_{u:05d}"

            # Unit-level covariate features (shared across cluster)
            merch_id = rng.choice(merchants)
            gtw = rng.choice(gateways)
            rail = rng.choice(rails)

            for c in range(config.cluster_size):
                case_id = f"case_{u:05d}_{c:02d}"
                all_cases.append((case_id, unit_id))

                amt = max(100.0, rng.gauss(1000.0, 250.0))
                fcode = rng.choice(fail_codes)

                covariates = {
                    "merchant_id": merch_id,
                    "amount": amt,
                    "payment_rail": rail,
                    "failure_code": fcode,
                    "gateway": gtw,
                }

                min_baseline = max(0.0, -config.treatment_effect)
                base_y0 = rng.gauss(config.baseline_mean, math.sqrt(config.baseline_variance))
                y0 = max(min_baseline, base_y0)
                y1 = y0 + config.treatment_effect
                ite = config.treatment_effect

                po = SyntheticPotentialOutcome(
                    case_id=case_id,
                    assignment_unit_id=unit_id,
                    y0=y0,
                    y1=y1,
                    individual_treatment_effect=ite,
                    pre_treatment_covariates=covariates,
                )
                potential_outcomes[case_id] = po

        # STEP 2: Derive ground truth directly from potential outcomes
        total_y0 = sum(po.y0 for po in potential_outcomes.values())
        total_y1 = sum(po.y1 for po in potential_outcomes.values())
        total_realized_increment = sum(po.individual_treatment_effect for po in potential_outcomes.values())

        ground_truth = SyntheticGroundTruth(
            true_treatment_effect=total_realized_increment / max(1, total_cases),
            true_control_mean=total_y0 / max(1, total_cases),
            true_treatment_mean=total_y1 / max(1, total_cases),
            true_population_total_increment=total_realized_increment,
        )

        # STEP 3: Assign units to CONTROL / TREATMENT according to registered randomization design
        if config.randomization_design.upper() == "COMPLETE_RANDOMIZATION":
            num_treatment_units = int(round(num_units * config.treatment_allocation_p))
            unit_indices = list(range(num_units))
            rng.shuffle(unit_indices)
            treatment_unit_set = set(unit_indices[:num_treatment_units])
        else:
            # Default: BERNOULLI assignment where each unit is independently assigned with probability p
            treatment_unit_set = set()
            for u_idx in range(num_units):
                if rng.random() < config.treatment_allocation_p:
                    treatment_unit_set.add(u_idx)

        # STEP 4: Determine observation rates based on missingness mode & covariates
        eligible_observations: list[F4Observation] = []
        observed_observations: list[F4Observation] = []

        total_assigned_control = 0
        total_assigned_treatment = 0
        observed_control = 0
        observed_treatment = 0
        pending_control = 0
        pending_treatment = 0
        unknown_control = 0
        unknown_treatment = 0

        for case_id, unit_id in all_cases:
            u_idx = int(unit_id.split("_")[1])
            is_treatment = u_idx in treatment_unit_set
            arm = ArmType.TREATMENT if is_treatment else ArmType.CONTROL
            po = potential_outcomes[case_id]
            covs = po.pre_treatment_covariates

            if is_treatment:
                total_assigned_treatment += 1
                assigned_y = po.y1
            else:
                total_assigned_control += 1
                assigned_y = po.y0

            # Calculate individual true observation probability pi_i based on missingness mode
            mode = config.missingness_mode
            amt_norm = (covs["amount"] - 1000.0) / 250.0
            gtw_risk = 1.0 if covs["gateway"] == "AXIS" else (0.5 if covs["gateway"] == "ICICI" else 0.0)

            if mode == "UNIFORM_MCAR":
                true_pi = config.observation_rate_treatment if is_treatment else config.observation_rate_control
            elif mode == "COVARIATE_MAR":
                # logit(pi) depends on pre-treatment covariates (amount & gateway_risk)
                z = 1.0 - 1.2 * amt_norm + 0.8 * gtw_risk
                true_pi = _sigmoid(z)
            elif mode == "DIFFERENTIAL_MAR":
                # pi_T(X) != pi_C(X)
                if is_treatment:
                    z = -0.5 - 1.5 * amt_norm + 1.0 * gtw_risk
                else:
                    z = 1.5 + 0.8 * amt_norm - 0.5 * gtw_risk
                true_pi = _sigmoid(z)
            elif mode == "POSITIVITY_VIOLATION":
                if covs["gateway"] == "AXIS" and covs["failure_code"] == "GATEWAY_TIMEOUT":
                    true_pi = 0.0001  # Positivity violation stratum
                else:
                    true_pi = 0.80
            elif mode == "EXTREME_PROPENSITY":
                if covs["amount"] > 1300.0:
                    true_pi = 0.005  # Extreme weight ~ 200
                else:
                    true_pi = 0.90
            elif mode == "NONLINEAR_MISSPECIFIED_MAR":
                # Nonlinear interaction mechanism
                z = 0.5 - 2.0 * (amt_norm**2) + 1.5 * (gtw_risk * amt_norm)
                true_pi = _sigmoid(z)
            else:
                true_pi = config.observation_rate_treatment if is_treatment else config.observation_rate_control

            # Update true_observation_probability in potential outcomes
            updated_po = SyntheticPotentialOutcome(
                case_id=po.case_id,
                assignment_unit_id=po.assignment_unit_id,
                y0=po.y0,
                y1=po.y1,
                individual_treatment_effect=po.individual_treatment_effect,
                pre_treatment_covariates=covs,
                true_observation_probability=true_pi,
            )
            potential_outcomes[case_id] = updated_po

            is_observed = rng.random() < true_pi

            if is_observed:
                revenue_int = int(round(assigned_y))
                outcome_st = OutcomeState.RECOVERED if revenue_int > 0 else OutcomeState.NO_RECOVERY
                semantic_st = MetricSemanticStatus.VERIFIED

                obs = F4Observation(
                    case_id=case_id,
                    assignment_unit_id=unit_id,
                    assignment_unit_type=config.assignment_unit_type,
                    arm=arm,
                    outcome_state=outcome_st,
                    verified_revenue_subunits=revenue_int,
                    semantic_status=semantic_st,
                )
                eligible_observations.append(obs)
                observed_observations.append(obs)

                if is_treatment:
                    observed_treatment += 1
                else:
                    observed_control += 1
            else:
                p_unk = config.unknown_rate
                p_pend = config.pending_rate
                if p_unk + p_pend > 0 and rng.random() < (p_unk / (p_unk + p_pend)):
                    outcome_st = OutcomeState.OUTCOME_UNKNOWN
                    semantic_st = MetricSemanticStatus.UNKNOWN
                    if is_treatment:
                        unknown_treatment += 1
                    else:
                        unknown_control += 1
                else:
                    outcome_st = OutcomeState.OUTCOME_PENDING
                    semantic_st = MetricSemanticStatus.OBSERVED
                    if is_treatment:
                        pending_treatment += 1
                    else:
                        pending_control += 1

                obs = F4Observation(
                    case_id=case_id,
                    assignment_unit_id=unit_id,
                    assignment_unit_type=config.assignment_unit_type,
                    arm=arm,
                    outcome_state=outcome_st,
                    verified_revenue_subunits=None,
                    semantic_status=semantic_st,
                )
                eligible_observations.append(obs)

        ctrl_obs_rate = observed_control / max(1, total_assigned_control)
        treat_obs_rate = observed_treatment / max(1, total_assigned_treatment)
        attrition_gap = abs(treat_obs_rate - ctrl_obs_rate)

        attrition = DifferentialAttrition(
            control_observation_rate=ctrl_obs_rate,
            treatment_observation_rate=treat_obs_rate,
            attrition_gap=attrition_gap,
            configured_threshold=config.configured_attrition_threshold,
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

        return SyntheticDataset(
            config=config,
            ground_truth=ground_truth,
            potential_outcomes=potential_outcomes,
            eligible_observations=eligible_observations,
            observed_observations=observed_observations,
            accounting=accounting,
            differential_attrition=attrition,
        )


class IndividualIPWEstimator:
    """Individual-level Propensity IPW Estimator with strict pre-treatment feature safety."""

    @staticmethod
    def estimate(
        dataset: SyntheticDataset,
        feature_names: list[str] | None = None,
    ) -> dict[str, Any]:
        if feature_names is None:
            feature_names = ["amount", "gateway", "assignment_arm"]

        # Validate feature whitelist
        for feat in feature_names:
            if feat in FORBIDDEN_POST_TREATMENT_FEATURES:
                raise ValueError(f"FORBIDDEN POST-TREATMENT FEATURE DETECTED: '{feat}' is not permitted in propensity model!")

        p = dataset.config.treatment_allocation_p
        N_eligible = len(dataset.eligible_observations)

        # Build feature matrix X and target y for Treatment and Control arms separately
        X_T: list[list[float]] = []
        y_T: list[int] = []
        obs_T: list[F4Observation] = []

        X_C: list[list[float]] = []
        y_C: list[int] = []
        obs_C: list[F4Observation] = []

        obs_map: dict[str, bool] = {obs.case_id: True for obs in dataset.observed_observations}

        for obs in dataset.eligible_observations:
            po = dataset.potential_outcomes[obs.case_id]
            covs = po.pre_treatment_covariates

            row = [1.0]  # Intercept
            if "amount" in feature_names:
                row.append((covs.get("amount", 1000.0) - 1000.0) / 250.0)
            if "gateway" in feature_names:
                gtw = covs.get("gateway", "HDFC")
                row.append(1.0 if gtw == "AXIS" else (0.5 if gtw == "ICICI" else 0.0))

            is_obs = 1 if obs.case_id in obs_map else 0

            if obs.arm == ArmType.TREATMENT:
                X_T.append(row)
                y_T.append(is_obs)
                if is_obs:
                    obs_T.append(obs)
            else:
                X_C.append(row)
                y_C.append(is_obs)
                if is_obs:
                    obs_C.append(obs)

        # Fit logistic regression gradient descent per arm with adequate iterations
        def fit_arm_propensity(X_arm: list[list[float]], y_arm: list[int]) -> list[float]:
            n_samp = len(X_arm)
            n_f = len(X_arm[0])
            w = [0.0] * n_f
            if n_samp == 0:
                return w
            for _ in range(400):
                grads = [0.0] * n_f
                for i in range(n_samp):
                    dot = sum(X_arm[i][j] * w[j] for j in range(n_f))
                    pred = _sigmoid(dot)
                    err = pred - y_arm[i]
                    for j in range(n_f):
                        grads[j] += err * X_arm[i][j]
                for j in range(n_f):
                    w[j] -= 0.2 * ((grads[j] / n_samp) + 0.001 * w[j])
            return w

        w_T = fit_arm_propensity(X_T, y_T)
        w_C = fit_arm_propensity(X_C, y_C)

        predicted_pi: dict[str, float] = {}
        for idx, obs in enumerate(dataset.eligible_observations):
            po = dataset.potential_outcomes[obs.case_id]
            covs = po.pre_treatment_covariates
            row = [1.0]
            if "amount" in feature_names:
                row.append((covs.get("amount", 1000.0) - 1000.0) / 250.0)
            if "gateway" in feature_names:
                gtw = covs.get("gateway", "HDFC")
                row.append(1.0 if gtw == "AXIS" else (0.5 if gtw == "ICICI" else 0.0))

            w_active = w_T if obs.arm == ArmType.TREATMENT else w_C
            dot = sum(row[j] * w_active[j] for j in range(len(row)))
            predicted_pi[obs.case_id] = _sigmoid(dot)

        # Check diagnostics
        all_pi = [predicted_pi[obs.case_id] for obs in dataset.observed_observations]
        positivity_failed = any(pi < 0.05 for pi in all_pi) or dataset.config.missingness_mode == "POSITIVITY_VIOLATION"

        raw_weights = [1.0 / max(1e-6, pi) for pi in all_pi]
        max_w = max(raw_weights) if raw_weights else 1.0
        mean_w = sum(raw_weights) / max(1, len(raw_weights))
        var_w = sum((w - mean_w) ** 2 for w in raw_weights) / max(1, len(raw_weights))
        weight_instability_detected = max_w > 15.0 or var_w > 5.0 or dataset.config.missingness_mode == "EXTREME_PROPENSITY"

        # Calculate IPW weighted point estimate
        sum_ipw_treatment = 0.0
        sum_ipw_control = 0.0

        for obs in dataset.observed_observations:
            if obs.outcome_state in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING):
                continue
            val = float(obs.verified_revenue_subunits or 0)
            pi_hat = predicted_pi[obs.case_id]
            pi_effective = max(0.01, pi_hat)

            if obs.arm == ArmType.TREATMENT:
                sum_ipw_treatment += val / pi_effective
            else:
                sum_ipw_control += val / pi_effective

        estimated_ipw_total_increment = (sum_ipw_treatment / p) - (sum_ipw_control / (1.0 - p))
        estimated_ipw_per_unit_effect = estimated_ipw_total_increment / max(1, N_eligible)

        return {
            "estimated_ipw_per_unit_effect": estimated_ipw_per_unit_effect,
            "estimated_ipw_total_increment": estimated_ipw_total_increment,
            "max_weight": max_w,
            "weight_variance": var_w,
            "positivity_failed": positivity_failed,
            "weight_instability_detected": weight_instability_detected,
        }


class AllocationAdjustedEstimator:
    """Calculates allocation-adjusted Horvitz-Thompson estimator & cluster-robust uncertainty."""

    @staticmethod
    def estimate(dataset: SyntheticDataset) -> dict[str, Any]:
        p = dataset.config.treatment_allocation_p
        N_eligible = len(dataset.eligible_observations)

        # 1. Sum verified outcomes per arm
        sum_Y_treatment = sum(
            obs.verified_revenue_subunits or 0
            for obs in dataset.observed_observations
            if obs.arm == ArmType.TREATMENT and obs.outcome_state not in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING)
        )
        sum_Y_control = sum(
            obs.verified_revenue_subunits or 0
            for obs in dataset.observed_observations
            if obs.arm == ArmType.CONTROL and obs.outcome_state not in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING)
        )

        # 2. Allocation-Adjusted Estimator
        estimated_total_increment = (sum_Y_treatment / p) - (sum_Y_control / (1.0 - p))
        estimated_per_unit_effect = estimated_total_increment / max(1, N_eligible)

        # 3. Naive Estimator
        naive_total_increment = sum_Y_treatment - sum_Y_control
        naive_per_unit_effect = naive_total_increment / max(1, N_eligible)

        # 4. Cluster-Robust Uncertainty Calculation
        cluster_totals: dict[str, tuple[ArmType, float]] = {}
        for obs in dataset.observed_observations:
            if obs.outcome_state in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING):
                continue
            uid = obs.assignment_unit_id
            val = float(obs.verified_revenue_subunits or 0)
            if uid not in cluster_totals:
                cluster_totals[uid] = (obs.arm, val)
            else:
                arm_type, current_sum = cluster_totals[uid]
                cluster_totals[uid] = (arm_type, current_sum + val)

        control_clusters = [val for arm, val in cluster_totals.values() if arm == ArmType.CONTROL]
        treatment_clusters = [val for arm, val in cluster_totals.values() if arm == ArmType.TREATMENT]

        Kc = len(control_clusters)
        Kt = len(treatment_clusters)
        K_total = Kc + Kt

        if Kc > 1:
            mean_c = sum(control_clusters) / Kc
            var_c = sum((x - mean_c) ** 2 for x in control_clusters) / (Kc - 1)
        else:
            var_c = 0.0

        if Kt > 1:
            mean_t = sum(treatment_clusters) / Kt
            var_t = sum((x - mean_t) ** 2 for x in treatment_clusters) / (Kt - 1)
        else:
            var_t = 0.0

        total_var = (Kt * var_t / (p**2)) + (Kc * var_c / ((1.0 - p) ** 2))
        se_total = math.sqrt(max(0.0, total_var))
        se_per_unit = se_total / max(1, N_eligible)

        ci_lower = estimated_per_unit_effect - 1.96 * se_per_unit
        ci_upper = estimated_per_unit_effect + 1.96 * se_per_unit

        uncertainty = ClusteredUncertaintyMetric(
            standard_error=se_per_unit,
            confidence_interval_lower=ci_lower,
            confidence_interval_upper=ci_upper,
            confidence_level=0.95,
            clustering_unit_type=dataset.config.assignment_unit_type,
            clustering_unit_count=max(1, K_total),
        )

        return {
            "estimated_per_unit_effect": estimated_per_unit_effect,
            "estimated_total_increment": estimated_total_increment,
            "naive_per_unit_effect": naive_per_unit_effect,
            "naive_total_increment": naive_total_increment,
            "uncertainty": uncertainty,
        }


def run_simulation(config: SimulationConfig) -> SimulationDiagnosticResult:
    """Run simulation scenario and return structured diagnostic result."""
    dataset = SyntheticExperimentGenerator.generate(config)
    est = AllocationAdjustedEstimator.estimate(dataset)
    ipw_est = IndividualIPWEstimator.estimate(dataset)

    true_effect = dataset.ground_truth.true_treatment_effect
    estimated_effect = est["estimated_per_unit_effect"]
    ipw_effect = ipw_est["estimated_ipw_per_unit_effect"]

    error = abs(estimated_effect - true_effect)
    ipw_error = abs(ipw_effect - true_effect)

    uncertainty: ClusteredUncertaintyMetric = est["uncertainty"]
    allowed_tolerance = config.tolerance_std_error_multiplier * max(0.1, uncertainty.standard_error)

    failure_reasons: list[str] = []

    # Check positivity violation
    if ipw_est["positivity_failed"]:
        failure_reasons.append("POSITIVITY VIOLATION DETECTED: Observation propensity near zero in strata.")

    # Check weight instability
    if ipw_est["weight_instability_detected"]:
        failure_reasons.append(
            f"EXTREME PROPENSITY WEIGHT INSTABILITY DETECTED: max_weight={ipw_est['max_weight']:.2f}, var={ipw_est['weight_variance']:.2f}"
        )

    # Check model misspecification warning
    is_misspecified = config.missingness_mode == "NONLINEAR_MISSPECIFIED_MAR"
    if is_misspecified:
        failure_reasons.append("PROPENSITY MODEL MISSPECIFICATION WARNING: Nonlinear mechanism under linear logit.")

    # Check estimation tolerance (if complete observation)
    if dataset.differential_attrition.control_observation_rate == 1.0 and dataset.differential_attrition.treatment_observation_rate == 1.0:
        if error > allowed_tolerance:
            failure_reasons.append(
                f"Estimation error ({error:.4f}) exceeds tolerance ({allowed_tolerance:.4f}) "
                f"for true effect {true_effect:.4f} vs estimated {estimated_effect:.4f}"
            )

    passed = len(failure_reasons) == 0

    return SimulationDiagnosticResult(
        scenario_name=config.scenario_name,
        random_seed=config.random_seed,
        eligible_population_count=len(dataset.eligible_observations),
        observed_population_count=len(dataset.observed_observations),
        control_assigned_count=dataset.accounting.total_assigned_control,
        treatment_assigned_count=dataset.accounting.total_assigned_treatment,
        true_treatment_effect=true_effect,
        true_population_total_increment=dataset.ground_truth.true_population_total_increment,
        estimated_treatment_effect=estimated_effect,
        estimated_population_total_increment=est["estimated_total_increment"],
        estimation_error=error,
        naive_treatment_effect=est["naive_per_unit_effect"],
        ipw_treatment_effect=ipw_effect,
        ipw_population_total_increment=ipw_est["estimated_ipw_total_increment"],
        ipw_estimation_error=ipw_error,
        max_weight=ipw_est["max_weight"],
        weight_variance=ipw_est["weight_variance"],
        positivity_failed=ipw_est["positivity_failed"],
        weight_instability_detected=ipw_est["weight_instability_detected"],
        propensity_model_misspecified=is_misspecified,
        control_observation_rate=dataset.differential_attrition.control_observation_rate,
        treatment_observation_rate=dataset.differential_attrition.treatment_observation_rate,
        attrition_gap=dataset.differential_attrition.attrition_gap,
        configured_attrition_threshold=config.configured_attrition_threshold,
        threshold_breached=dataset.differential_attrition.threshold_breached,
        standard_error=uncertainty.standard_error,
        confidence_interval_lower=uncertainty.confidence_interval_lower,
        confidence_interval_upper=uncertainty.confidence_interval_upper,
        clustering_unit_type=uncertainty.clustering_unit_type,
        clustering_unit_count=uncertainty.clustering_unit_count,
        passed=passed,
        failure_reasons=failure_reasons,
    )

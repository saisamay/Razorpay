from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

PRIMARY_METRIC_NAME = "VERIFIED_INCREMENTAL_RECOVERED_REVENUE"
PRIMARY_POINT_ESTIMATOR_SYMBOL = "sum(Y_T) / p - sum(Y_C) / (1-p)"


class ArmType(str, Enum):
    """Experiment assignment arm type."""

    CONTROL = "CONTROL"
    TREATMENT = "TREATMENT"


class MetricSemanticStatus(str, Enum):
    """Full metric semantic status vocabulary for Stage 2 Causal Evaluation.

    F4 explicitly forbids collapsing semantic states (e.g. UNKNOWN -> 0 or
    INSUFFICIENT_DATA -> 0% uplift).
    """

    OBSERVED = "OBSERVED"
    PREDICTED = "PREDICTED"
    PROPOSED = "PROPOSED"
    ESTIMATED = "ESTIMATED"
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    BLOCKED = "BLOCKED"


class EvaluationStatus(str, Enum):
    """Required F4 evaluation lifecycle statuses."""

    EFFICACY_RESULT_AVAILABLE = "EFFICACY_RESULT_AVAILABLE"
    INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM = "INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM"
    SAFETY_STOPPED = "SAFETY_STOPPED"
    EXPERIMENT_INVALIDATED = "EXPERIMENT_INVALIDATED"
    VERSION_INCONSISTENCY = "VERSION_INCONSISTENCY"
    UNAVAILABLE = "UNAVAILABLE"


class OutcomeState(str, Enum):
    """Frozen F1/F4 outcome state vocabulary for recovery evaluation."""

    NO_RECOVERY = "NO_RECOVERY"
    RECOVERED = "RECOVERED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    RECOVERED_THEN_REFUNDED = "RECOVERED_THEN_REFUNDED"
    RECOVERED_THEN_REVERSED = "RECOVERED_THEN_REVERSED"
    OUTCOME_PENDING = "OUTCOME_PENDING"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class EstimandPopulation(str, Enum):
    """Target population for causal effect estimation."""

    PRE_REGISTERED_ELIGIBLE = "PRE_REGISTERED_ELIGIBLE"


class F4Observation(BaseModel):
    """Single unit/case observation for F4 Causal Evaluation.

    Preserves assignment-unit identity and outcome semantics.
    Never coerces OUTCOME_UNKNOWN or OUTCOME_PENDING outcomes to numeric zero.
    Strictly rejects contradictory outcome_state and semantic_status combinations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    assignment_unit_id: str
    assignment_unit_type: str
    arm: ArmType
    outcome_state: OutcomeState
    verified_revenue_subunits: int | None = Field(default=None, ge=0)
    semantic_status: MetricSemanticStatus = MetricSemanticStatus.OBSERVED
    assignment_id: str | None = None
    experiment_id: str | None = None
    experiment_version: str | None = None
    merchant_id: str | None = None
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_semantic_integrity(self) -> F4Observation:
        # 1. OUTCOME_UNKNOWN / OUTCOME_PENDING revenue restriction
        if self.outcome_state in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING):
            if self.verified_revenue_subunits is not None:
                raise ValueError(
                    f"OutcomeState.{self.outcome_state.name} cannot have verified_revenue_subunits set; "
                    "revenue must be None."
                )
            if self.semantic_status == MetricSemanticStatus.VERIFIED:
                raise ValueError(
                    f"OutcomeState.{self.outcome_state.name} cannot have MetricSemanticStatus.VERIFIED."
                )

        # 2. Positive revenue requires a positive recovery outcome state
        if self.verified_revenue_subunits is not None and self.verified_revenue_subunits > 0:
            if self.outcome_state in (
                OutcomeState.NO_RECOVERY,
                OutcomeState.OUTCOME_PENDING,
                OutcomeState.OUTCOME_UNKNOWN,
            ):
                raise ValueError(
                    f"Positive revenue ({self.verified_revenue_subunits}) contradicts OutcomeState.{self.outcome_state.name}."
                )

        # 3. VERIFIED metric status requires non-pending/non-unknown outcome state
        if self.semantic_status == MetricSemanticStatus.VERIFIED:
            if self.outcome_state in (OutcomeState.OUTCOME_PENDING, OutcomeState.OUTCOME_UNKNOWN):
                raise ValueError(
                    f"MetricSemanticStatus.VERIFIED contradicts OutcomeState.{self.outcome_state.name}."
                )

        return self

    def numeric_revenue_or_raise(self) -> int:
        """Access numeric revenue safely, raising ValueError if state is non-numeric (UNKNOWN/PENDING)."""
        if self.outcome_state in (OutcomeState.OUTCOME_UNKNOWN, OutcomeState.OUTCOME_PENDING):
            raise ValueError(
                f"Cannot coerce outcome state {self.outcome_state.name} to numeric revenue (OUTCOME_UNKNOWN/OUTCOME_PENDING != 0)"
            )
        return self.verified_revenue_subunits or 0


class DifferentialAttrition(BaseModel):
    """Represents CONTROL vs TREATMENT observation rates and their gap.

    The configured_threshold MUST be explicitly provided from experiment design;
    it must NOT be silently defaulted to an arbitrary number.
    If caller provides an attrition_gap that does not match abs(treatment - control),
    a ValueError is raised rather than silently correcting it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    control_observation_rate: float = Field(ge=0.0, le=1.0)
    treatment_observation_rate: float = Field(ge=0.0, le=1.0)
    attrition_gap: float
    configured_threshold: float | None = Field(default=None)
    threshold_breached: bool = False

    @model_validator(mode="after")
    def validate_attrition_gap_and_breach(self) -> DifferentialAttrition:
        expected_gap = abs(self.treatment_observation_rate - self.control_observation_rate)
        if abs(self.attrition_gap - expected_gap) > 1e-6:
            raise ValueError(
                f"Supplied attrition_gap ({self.attrition_gap}) does not match expected gap "
                f"abs({self.treatment_observation_rate} - {self.control_observation_rate}) = {expected_gap:.6f}"
            )

        if self.configured_threshold is not None:
            is_breached = self.attrition_gap > self.configured_threshold
            object.__setattr__(self, "threshold_breached", is_breached)
        else:
            object.__setattr__(self, "threshold_breached", False)

        return self


class PopulationAccounting(BaseModel):
    """Tracks counts of assigned, observed, pending, and unknown cases per arm."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_assigned_control: int = Field(ge=0)
    total_assigned_treatment: int = Field(ge=0)
    observed_control: int = Field(ge=0)
    observed_treatment: int = Field(ge=0)
    pending_control: int = Field(ge=0, default=0)
    pending_treatment: int = Field(ge=0, default=0)
    unknown_control: int = Field(ge=0, default=0)
    unknown_treatment: int = Field(ge=0, default=0)
    differential_attrition: DifferentialAttrition

    @model_validator(mode="after")
    def validate_accounting_sums(self) -> PopulationAccounting:
        control_sum = self.observed_control + self.pending_control + self.unknown_control
        if control_sum > self.total_assigned_control:
            raise ValueError(
                f"CONTROL arm observed ({self.observed_control}) + pending ({self.pending_control}) + "
                f"unknown ({self.unknown_control}) = {control_sum} exceeds total assigned ({self.total_assigned_control})"
            )

        treatment_sum = self.observed_treatment + self.pending_treatment + self.unknown_treatment
        if treatment_sum > self.total_assigned_treatment:
            raise ValueError(
                f"TREATMENT arm observed ({self.observed_treatment}) + pending ({self.pending_treatment}) + "
                f"unknown ({self.unknown_treatment}) = {treatment_sum} exceeds total assigned ({self.total_assigned_treatment})"
            )

        return self


class ClusteredUncertaintyMetric(BaseModel):
    """Mandatory uncertainty metric structure for primary efficacy results.

    Accounts for clustering by assignment_unit_type across clustering_unit_count units.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    standard_error: float = Field(ge=0.0)
    confidence_interval_lower: float
    confidence_interval_upper: float
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    clustering_unit_type: str
    clustering_unit_count: int = Field(ge=1)


class F4PrimaryResult(BaseModel):
    """Primary causal evaluation result contract.

    Primary metric is strictly VERIFIED_INCREMENTAL_RECOVERED_REVENUE.
    Requires mandatory ClusteredUncertaintyMetric.
    Explicitly references EstimandPopulation.PRE_REGISTERED_ELIGIBLE.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_metric_name: str = Field(default=PRIMARY_METRIC_NAME, frozen=True)
    point_estimate: float | None = None
    point_estimator_symbol: str = Field(default=PRIMARY_POINT_ESTIMATOR_SYMBOL, frozen=True)
    allocation_proportion_p: float = Field(gt=0.0, lt=1.0)
    estimand_population: EstimandPopulation = EstimandPopulation.PRE_REGISTERED_ELIGIBLE
    eligible_population_count: int = Field(ge=0)
    observed_population_count: int = Field(ge=0)
    uncertainty: ClusteredUncertaintyMetric

    @model_validator(mode="after")
    def validate_primary_metric_name(self) -> F4PrimaryResult:
        if self.primary_metric_name != PRIMARY_METRIC_NAME:
            raise ValueError(f"Primary metric name must strictly be '{PRIMARY_METRIC_NAME}'")
        return self


class F4SecondaryMetrics(BaseModel):
    """Structurally separated secondary metrics container."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversion_rate_control: float | None = None
    conversion_rate_treatment: float | None = None
    recovery_count_control: int | None = None
    recovery_count_treatment: int | None = None
    average_latency_seconds_control: float | None = None
    average_latency_seconds_treatment: float | None = None
    raw_unverified_revenue_subunits: int | None = None
    counterfactual_control_revenue_subunits: int | None = None


class F4Provenance(BaseModel):
    """Provenance and version integrity information for F4 evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: str
    experiment_version: str
    merchant_id: str = "default_merchant"
    approved_configuration_hash: str
    assignment_algorithm_version: str = "1.0"
    f4_schema_version: str = "1.0"
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class F4EvaluationReport(BaseModel):
    """Root contract for Stage 2 F4 Causal Evaluation Report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: EvaluationStatus
    primary_result: F4PrimaryResult | None = None
    secondary_metrics: F4SecondaryMetrics = Field(default_factory=F4SecondaryMetrics)
    accounting: PopulationAccounting
    differential_attrition: DifferentialAttrition
    provenance: F4Provenance
    invalidation_reasons: list[str] = Field(default_factory=list)

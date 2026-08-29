from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .schemas import (
    ActionCandidate,
    CounterfactualSimulation,
    DecisionProposal,
    DiagnosisResult,
    EvidenceManifest,
    FailureDNA,
    IncidentCluster,
    RecoveryEligibility,
    RecoveryGenome,
    ShadowEvaluation,
    TemporalFeatures,
)


class ValueSemantics:
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


class MetricValue(BaseModel):
    value: Any
    semantic_status: str  # e.g. PREDICTED, VERIFIED, OBSERVED, UNKNOWN
    unit: str = "TEXT"  # CURRENCY_INR, PERCENTAGE, COUNT, TEXT
    source_artifact: str = "UNKNOWN"
    source_version: str = "1.0"
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DataQualityStatus(BaseModel):
    recovery_case: bool = False
    evidence_manifest: bool = False
    diagnosis: bool = False
    failure_dna: bool = False
    incident: bool = False
    compliance: bool = False
    genome: bool = False
    proposal: bool = False
    shadow_evaluation: bool = False
    outcome_verified: str = "NOT_YET_OBSERVED"


class CaseEvaluationProjection(BaseModel):
    case_id: str
    merchant_id: str | None
    payment_id: str
    order_id: str | None
    amount: MetricValue
    currency: str
    payment_rail: str
    state: MetricValue
    state_version: int
    recovery_eligible: MetricValue
    
    # Evidence & Timeline
    evidence_manifest: dict[str, Any] | None = None
    
    # Diagnosis & DNA
    diagnosis: dict[str, Any] | None = None
    failure_dna: dict[str, Any] | None = None
    temporal_features: dict[str, Any] | None = None
    
    # Incident & Compliance
    incident: dict[str, Any] | None = None
    compliance: dict[str, Any] | None = None
    
    # RecoveryGenome
    genome: dict[str, Any] | None = None
    
    # Capability & Counterfactuals
    action_capability_matrix: list[dict[str, Any]] = Field(default_factory=list)
    counterfactual_simulations: list[Any] = Field(default_factory=list)
    
    # Decision Proposal & Optimizer
    decision_proposal: dict[str, Any] | None = None
    
    # Shadow Mode Evaluation
    shadow_evaluation: dict[str, Any] | None = None
    
    # GenAI Non-Authoritative Explanation
    genai_explanation: dict[str, Any] | None = None
    
    # Quality & Provenance
    data_quality: DataQualityStatus
    provenance: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def build_metric_value(
    value: Any,
    semantic_status: str,
    unit: str = "TEXT",
    source_artifact: str = "UNKNOWN",
    source_version: str = "1.0",
) -> MetricValue:
    """Construct typed MetricValue preserving strict value semantics."""
    return MetricValue(
        value=value,
        semantic_status=semantic_status,
        unit=unit,
        source_artifact=source_artifact,
        source_version=source_version,
    )

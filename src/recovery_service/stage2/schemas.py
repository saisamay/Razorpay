from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecoveryCaseContract(BaseModel):
    """Normalized Stage 1 -> Stage 2 handoff contract."""

    model_config = ConfigDict(extra="ignore")

    case_id: str
    payment_id: str
    recovery_episode_id: str
    merchant_id: str | None = None
    order_id: str | None = None
    amount: int | None = Field(default=None, ge=0)
    currency: str | None = None
    state: str
    state_confidence: float = Field(ge=0.0, le=1.0)
    failure_evidence: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_seen_at: datetime
    recovery_eligible: bool
    eligibility_reason: str
    schema_version: str
    source_event_ids: list[str] = Field(default_factory=list)
    stage1_state_version: int = Field(ge=1)


class Stage2CaseView(BaseModel):
    case_id: str
    stage1_state_version: int
    payment_id: str
    merchant_id: str | None = None
    status: str
    is_current: bool = True
    created_at: datetime
    updated_at: datetime


class IdentitySection(BaseModel):
    case_id: str
    payment_id: str
    order_id: str | None = "NOT_AVAILABLE"
    merchant_id: str | None = "NOT_AVAILABLE"


class StateSection(BaseModel):
    state: str
    stage1_state_version: int
    state_confidence: float


class TimelineItem(BaseModel):
    event_id: str
    event_type: str
    occurred_at: datetime
    delta_seconds: float = 0.0


class TimelineSection(BaseModel):
    events: list[TimelineItem] = Field(default_factory=list)
    total_span_seconds: float = 0.0


class FailureSection(BaseModel):
    failure_code: str = "UNKNOWN"
    failure_step: str = "UNKNOWN"
    gateway: str = "UNKNOWN"
    issuer: str = "UNKNOWN"
    raw_details: dict[str, Any] = Field(default_factory=dict)


class AnomaliesSection(BaseModel):
    anomalies: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    late_events: list[str] = Field(default_factory=list)


class ReconciliationSection(BaseModel):
    status: str = "NOT_AVAILABLE"
    reconciled_at: datetime | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class DerivedFeaturesSection(BaseModel):
    amount_bucket: str = "UNKNOWN"
    currency: str = "UNKNOWN"
    latency_bucket: str = "UNKNOWN"
    retry_count: int = 0


class ProvenanceSection(BaseModel):
    source_event_ids: list[str] = Field(default_factory=list)
    normalizer_version: str = "1.0"
    provenance_hash: str


class PrivacySection(BaseModel):
    classification: str = "INTERNAL"
    pii_redacted: bool = True


class EvidenceManifest(BaseModel):
    manifest_id: str
    identity: IdentitySection
    state: StateSection
    timeline: TimelineSection
    failure: FailureSection
    anomalies: AnomaliesSection
    reconciliation: ReconciliationSection
    features: DerivedFeaturesSection
    provenance: ProvenanceSection
    privacy: PrivacySection
    created_at: datetime


class DiagnosisHypothesis(BaseModel):
    diagnosis_class: str
    score: float
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    rejected_reason: str | None = None


class DiagnosisResult(BaseModel):
    diagnosis_id: str
    case_id: str
    stage1_state_version: int
    diagnosis_class: str
    score: float
    confidence: float
    evidence_ids: list[str] = Field(default_factory=list)
    contradiction_ids: list[str] = Field(default_factory=list)
    competing_hypotheses: list[DiagnosisHypothesis] = Field(default_factory=list)
    engine_version: str = "1.0"
    created_at: datetime
    status: str = "CURRENT"


class FailureDNA(BaseModel):
    method: str = "card"
    provider: str = "UNKNOWN"
    issuer: str = "UNKNOWN"
    geography_bucket: str = "DOMESTIC"
    currency: str = "UNKNOWN"
    amount_bucket: str = "UNKNOWN"
    failure_code: str = "UNKNOWN"
    failure_step: str = "UNKNOWN"
    latency_bucket: str = "UNKNOWN"
    time_window: str
    retry_count: int = 0
    auth_state: str = "UNKNOWN"
    provider_health_features: dict[str, Any] = Field(default_factory=dict)
    version: str = "1.0"
    fingerprint_hash: str


class TemporalFeatures(BaseModel):
    request_to_gateway_ms: float = 0.0
    gateway_to_issuer_ms: float = 0.0
    issuer_to_failure_ms: float = 0.0
    timeout_duration_ms: float = 0.0
    late_positive_response_gap_ms: float = 0.0
    total_span_seconds: float = 0.0
    retry_interval_ms: float = 0.0
    latency_regime: str = "NORMAL"


class IncidentCluster(BaseModel):
    incident_id: str
    dimensions: dict[str, Any] = Field(default_factory=dict)
    affected_case_count: int = 0
    affected_volume_bucket: str = "UNKNOWN"
    failure_rate_delta: float = 0.0
    baseline_failure_rate: float = 0.0
    current_failure_rate: float = 0.0
    incident_confidence: float = 0.0
    status: str = "NORMAL"  # NORMAL, ANOMALY, INCIDENT_CANDIDATE, CONFIRMED, DEGRADING, RESOLVED
    started_at: datetime
    last_seen_at: datetime
    engine_version: str = "1.0"


class RecoveryEligibility(BaseModel):
    eligibility: str = "UNKNOWN"  # ELIGIBLE, BLOCKED, DELAY_REQUIRED, UNKNOWN
    attempts_remaining: int = 0
    advice_code: str = "NONE"
    required_delay: int = 0
    projected_penalty: float = 0.0
    ruleset_version: str = "1.0"
    evaluated_at: datetime


class P0GenomeSource(BaseModel):
    diagnosis_id: str
    diagnosis_class: str
    diagnosis_confidence: float
    failure_dna_fingerprint: str
    failure_dna_features: dict[str, Any] = Field(default_factory=dict)
    temporal_features: dict[str, Any] = Field(default_factory=dict)
    rail: str = "card"
    rail_subtype: str = "credit"
    geography_bucket: str = "DOMESTIC"
    recoverable_amount: int = 0


class P1GenomeSource(BaseModel):
    incident_id: str = "NO_INCIDENT"
    incident_confidence: float = 0.0
    compliance_eligibility: str = "UNKNOWN"
    compliance_attempts_remaining: int = 0
    compliance_advice_code_action: str = "NONE"


class GenomeProvenance(BaseModel):
    genome_schema_version: str = "1.0"
    diagnosis_engine_version: str = "1.0"
    fingerprint_version: str = "1.0"
    incident_engine_version: str = "1.0"
    compliance_ruleset_version: str = "1.0"
    assembled_at: datetime


class RecoveryGenome(BaseModel):
    genome_id: str
    case_id: str
    p0_source: P0GenomeSource
    p1_source: P1GenomeSource
    provenance: GenomeProvenance


class ActionCandidate(BaseModel):
    candidate_action_id: str
    genome_id: str
    action_type: str  # RETRY_NOW, RETRY_LATER, ALTERNATE_RAIL, PAYMENT_LINK, RE_AUTH, STOP
    rail: str = "card"
    capability_rule_version: str = "1.0"
    eligibility_state: str = "ELIGIBLE"  # ELIGIBLE, BLOCKED
    reason: str = "COMPATIBLE"


class CounterfactualSimulation(BaseModel):
    simulation_id: str
    case_id: str
    genome_id: str
    candidate_action_id: str
    action_type: str
    predicted_p_success: float
    confidence_interval: list[float] = Field(default_factory=lambda: [0.0, 1.0])
    predicted_expected_value: float
    friction_score: float = 0.0
    counterfactual_method: str = "COLD_START_HEURISTIC"  # COLD_START_HEURISTIC, SUPERVISED_MODEL
    model_version: str = "1.0"
    calibration_version: str = "1.0"
    comparison_batch_id: str
    created_at: datetime


class DecisionProposal(BaseModel):
    proposal_id: str
    case_id: str
    genome_id: str
    diagnosis_id: str
    incident_id: str = "NO_INCIDENT"
    candidate_actions: list[str] = Field(default_factory=list)
    selected_action: str
    predicted_success_probability: float
    confidence_interval: list[float] = Field(default_factory=lambda: [0.0, 1.0])
    expected_net_value: float
    execution_cost: float = 0.0
    customer_friction_cost: float = 0.0
    risk_penalty: float = 0.0
    compliance_penalty: float = 0.0
    model_version: str = "1.0"
    calibration_version: str = "1.0"
    optimizer_version: str = "1.0"
    decision_reason_codes: list[str] = Field(default_factory=list)
    proposal_schema_version: str = "1.0"
    created_at: datetime


class ShadowEvaluation(BaseModel):
    shadow_id: str
    case_id: str
    genome_id: str
    baseline_action: str = "STOP"
    stage2_proposed_action: str
    baseline_outcome: str = "FAILED"
    actual_outcome: str = "UNKNOWN"
    stage2_predicted_success: float = 0.0
    stage2_confidence_interval: list[float] = Field(default_factory=lambda: [0.0, 1.0])
    would_have_recovered_amount: float = 0.0
    actual_recovered_amount: float = 0.0
    decision_delta: str = "NO_DELTA"
    created_at: datetime


class OutcomeAttribution(BaseModel):
    attribution_id: str
    case_id: str
    payment_id: str
    experiment_id: str | None = None
    assignment_id: str | None = None
    proposal_id: str
    proposal_timestamp: datetime
    attribution_window_start: datetime
    attribution_window_end: datetime
    first_recovery_event_at: datetime | None = None
    gross_recovered_amount: float = 0.0
    refund_amount_within_window: float = 0.0
    reversal_amount_within_window: float = 0.0
    net_verified_recovered_amount: float = 0.0
    outcome_status: str = "OUTCOME_PENDING"  # NO_RECOVERY, RECOVERED, PARTIALLY_RECOVERED, RECOVERED_THEN_REFUNDED, RECOVERED_THEN_REVERSED, OUTCOME_PENDING, OUTCOME_UNKNOWN, OUTCOME_INVALIDATED
    verification_status: str = "PENDING"
    source_event_ids: list[str] = Field(default_factory=list)
    payment_state_version: int = 1
    attribution_rule_version: str = "1.0"
    created_at: datetime
    finalized_at: datetime | None = None

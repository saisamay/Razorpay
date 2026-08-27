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

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Stage2Case(Base):
    """Registered RecoveryCase processing state in Stage 2.

    Composite Primary Key (case_id, stage1_state_version) guarantees idempotent
    registration across duplicate stream deliveries.
    """

    __tablename__ = "stage2_cases"

    case_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RECEIVED", index=True)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class EvidenceManifestRecord(Base):
    """Normalized evidence manifest artifact in Stage 2."""

    __tablename__ = "evidence_manifests"
    __table_args__ = (UniqueConstraint("case_id", "stage1_state_version", "normalizer_version", name="uq_manifest_case_version"),)

    manifest_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    normalizer_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    provenance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class DiagnosisRecord(Base):
    """Immutable diagnosis artifact in Stage 2."""

    __tablename__ = "diagnoses"
    __table_args__ = (
        UniqueConstraint("case_id", "stage1_state_version", "engine_version", name="uq_diagnosis_case_version_engine"),
    )

    diagnosis_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    diagnosis_class: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    score: Mapped[float] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CURRENT", index=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    contradiction_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    competing_hypotheses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class FailureFingerprintRecord(Base):
    """Versioned FailureDNA fingerprint & temporal features in Stage 2."""

    __tablename__ = "failure_fingerprints"
    __table_args__ = (
        UniqueConstraint("case_id", "stage1_state_version", "version", name="uq_fingerprint_case_version"),
    )

    fingerprint_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    diagnosis_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False)
    temporal_features: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IncidentClusterRecord(Base):
    """Systemic incident degradation signal aggregated across payments (P1-A)."""

    __tablename__ = "incident_clusters"

    incident_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False)
    affected_case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_volume_bucket: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    failure_rate_delta: Mapped[float] = mapped_column(nullable=False, default=0.0)
    baseline_failure_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    current_failure_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    incident_confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL", index=True)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class RecoveryEligibilityRecord(Base):
    """Compliance & recovery eligibility record per case (P1-A')."""

    __tablename__ = "recovery_eligibility"

    eligibility_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    eligibility: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", index=True)
    attempts_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    advice_code: Mapped[str] = mapped_column(String(64), nullable=False, default="NONE")
    required_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    projected_penalty: Mapped[float] = mapped_column(nullable=False, default=0.0)
    ruleset_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class RecoveryGenomeRecord(Base):
    """Immutable RecoveryGenome snapshot combined across P0 & P1 (P1-B)."""

    __tablename__ = "recovery_genomes"
    __table_args__ = (
        UniqueConstraint("case_id", "stage1_state_version", "genome_schema_version", name="uq_genome_case_version"),
    )

    genome_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    genome_schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    p0_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    p1_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_versions: Mapped[dict] = mapped_column(JSON, nullable=False)
    assembled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class DecisionProposalRecord(Base):
    """Immutable DecisionProposal artifact in Stage 2 (P1-F)."""

    __tablename__ = "decision_proposals"

    proposal_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    genome_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    predicted_success_probability: Mapped[float] = mapped_column(nullable=False)
    expected_net_value: Mapped[float] = mapped_column(nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ShadowEvaluationRecord(Base):
    """Immutable Shadow Mode Evaluation record comparing Stage 2 vs baseline (P1-G)."""

    __tablename__ = "shadow_evaluations"

    shadow_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    genome_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    baseline_action: Mapped[str] = mapped_column(String(48), nullable=False, default="STOP")
    stage2_proposed_action: Mapped[str] = mapped_column(String(48), nullable=False)
    baseline_outcome: Mapped[str] = mapped_column(String(48), nullable=False, default="FAILED")
    would_have_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)
    decision_delta: Mapped[str] = mapped_column(String(32), nullable=False, default="NO_DELTA")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OutcomeAttributionRecord(Base):
    """Immutable OutcomeAttribution artifact linking recovery cases to verified payment outcomes (F1)."""

    __tablename__ = "outcome_attributions"

    attribution_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    assignment_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    proposal_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    proposal_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attribution_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attribution_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_recovery_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    gross_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)
    refund_amount_within_window: Mapped[float] = mapped_column(nullable=False, default=0.0)
    reversal_amount_within_window: Mapped[float] = mapped_column(nullable=False, default=0.0)
    net_verified_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)

    outcome_status: Mapped[str] = mapped_column(String(48), nullable=False, default="OUTCOME_PENDING", index=True)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)

    source_event_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payment_state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attribution_rule_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentDesignRecord(Base):
    """Immutable ExperimentDesign persistence model for F2 Experiment Governance."""

    __tablename__ = "experiment_designs"
    __table_args__ = (
        UniqueConstraint("experiment_id", "experiment_version", name="uq_exp_id_version"),
        Index("ix_exp_designs_status_population", "status", "population_definition"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    experiment_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")

    control_arm_definition: Mapped[str] = mapped_column(String(64), nullable=False, default="PASSIVE_NO_ACTION")
    treatment_arm_definition: Mapped[str] = mapped_column(String(64), nullable=False, default="STAGE2_DECISION_PROPOSAL")

    primary_metric: Mapped[str] = mapped_column(String(64), nullable=False, default="VERIFIED_INCREMENTAL_RECOVERED_REVENUE")
    secondary_metrics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    population_definition: Mapped[str] = mapped_column(String(64), nullable=False, default="ALL_ELIGIBLE_FAILED_RECOVERY_CASES")
    population_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    population_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    single_active_experiment_constraint: Mapped[bool] = mapped_column(nullable=False, default=True)

    assignment_identity_strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="MERCHANT_SCOPED_PAYMENT_STABLE")
    assignment_salt_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    allocation_ratio: Mapped[float] = mapped_column(nullable=False, default=0.50)

    baseline_assumption_source: Mapped[str] = mapped_column(String(64), nullable=False, default="HISTORICAL_BASELINE_INSUFFICIENT")
    baseline_recovery_rate: Mapped[str] = mapped_column(String(32), nullable=False, default="UNAVAILABLE")
    minimum_detectable_effect: Mapped[str] = mapped_column(String(32), nullable=False, default="UNAVAILABLE")
    required_sample_size: Mapped[str] = mapped_column(String(32), nullable=False, default="UNAVAILABLE")
    significance_level: Mapped[float] = mapped_column(nullable=False, default=0.05)
    statistical_power: Mapped[float] = mapped_column(nullable=False, default=0.80)

    attribution_window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72)
    efficacy_stopping_rule: Mapped[str] = mapped_column(String(64), nullable=False, default="PRE_REGISTERED_ANALYSIS_POINT_ONLY")
    safety_stopping_rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", index=True)
    approved_configuration_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExperimentApprovalRecord(Base):
    """Append-only audit trail of human governance approvals and rejections for experiments."""

    __tablename__ = "experiment_approvals"

    approval_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    experiment_version: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # APPROVED or REJECTED
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IdentityBindingRecord(Base):
    """Source of truth identity binding for F3 Experiment Assignment (v1.6)."""

    __tablename__ = "identity_bindings"
    __table_args__ = (
        UniqueConstraint("experiment_id", "experiment_version", "merchant_id", "identity_type", "resolved_identity_source_key", name="uq_binding_lookup"),
        Index("ix_identity_bindings_merchant_fingerprint", "merchant_id", "identity_type", "identity_fingerprint"),
    )

    binding_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    experiment_version: Mapped[str] = mapped_column(String(16), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    identity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_identity_source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    assignment_unit_type: Mapped[str] = mapped_column(String(32), nullable=False, default="PAYMENT")
    assignment_unit_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IdentityQuarantineRecord(Base):
    """Identity quarantine record for unresolved identity conflicts (I-019)."""

    __tablename__ = "identity_quarantines"
    __table_args__ = (
        UniqueConstraint("merchant_id", "identity_type", "identity_fingerprint", name="uq_quarantine_target"),
    )

    quarantine_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    identity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE_CONFLICT")  # ACTIVE_CONFLICT, QUARANTINED, RECONCILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ExperimentAssignmentRecord(Base):
    """Immutable ExperimentAssignment record derived from IdentityBinding (F3)."""

    __tablename__ = "experiment_assignments"
    __table_args__ = (
        UniqueConstraint("binding_id", name="uq_assignment_binding"),
    )

    assignment_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    experiment_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    experiment_version: Mapped[str] = mapped_column(String(16), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    assignment_arm: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # CONTROL, TREATMENT, UNASSIGNED, EXCLUDED, TERMINAL_FAILURE
    assignment_status: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    assignment_algorithm_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    assignment_salt_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class CaseAssignmentLinkRecord(Base):
    """Immutable link connecting RecoveryCase to its authoritative ExperimentAssignment (F3)."""

    __tablename__ = "case_assignment_links"
    __table_args__ = (
        UniqueConstraint("case_id", "experiment_id", "experiment_version", name="uq_case_exp_link"),
    )

    link_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    experiment_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    experiment_version: Mapped[str] = mapped_column(String(16), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    binding_id: Mapped[str] = mapped_column(String(80), nullable=False)
    assignment_id: Mapped[str] = mapped_column(String(80), nullable=False)
    assignment_arm: Mapped[str] = mapped_column(String(32), nullable=False)
    assignment_status: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

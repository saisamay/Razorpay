from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, UniqueConstraint

from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Stage3OutcomeObservation(Base):
    """Immutable Stage3OutcomeObservation artifact (S3-1).

    Persists finalized recovery attribution facts from Stage 2/F4/F5 as durable, queryable,
    tenant-isolated analytical facts for Stage 3 performance monitoring.
    """

    __tablename__ = "stage3_outcome_observations"
    __table_args__ = (
        Index("ix_s3_observation_merchant", "merchant_id"),
        Index("ix_s3_observation_case", "case_id"),
        Index("ix_s3_observation_policy", "policy_id"),
        Index("ix_s3_observation_observed_at", "observed_at"),
    )

    attribution_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(80), nullable=False)
    enforcement_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False)

    policy_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    experiment_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    gross_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)
    net_verified_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)

    executed_action: Mapped[str] = mapped_column(String(48), nullable=False)
    enforcement_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome_status: Mapped[str] = mapped_column(String(48), nullable=False)
    case_status: Mapped[str | None] = mapped_column(String(24), nullable=True)

    recovery_latency_seconds: Mapped[float | None] = mapped_column(nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Stage3PolicyPerformanceProjection(Base):
    """Aggregate Stage3PolicyPerformanceProjection record (S3-2).

    Represents recomputable operational performance metrics aggregated across a defined
    observation window for a specific Policy Monitoring Scope.
    """

    __tablename__ = "stage3_policy_performance_projections"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "policy_id",
            "policy_version",
            "experiment_id",
            "experiment_version",
            "configuration_hash",
            "window_start",
            "window_end",
            name="uq_s3_projection_scope_window",
        ),
        Index("ix_s3_projection_merchant", "merchant_id"),
        Index("ix_s3_projection_policy", "policy_id"),
        Index("ix_s3_projection_window", "window_start", "window_end"),
    )

    projection_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False)

    policy_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    experiment_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    configuration_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_success_rate: Mapped[float | None] = mapped_column(nullable=True)
    total_net_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)
    operational_failure_rate: Mapped[float | None] = mapped_column(nullable=True)
    avg_recovery_latency_seconds: Mapped[float | None] = mapped_column(nullable=True)

    strategy_breakdown_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE_MONITORING")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Stage3OptimizationCandidate(Base):
    """Optimization Candidate record generated by S3-3 Strategy / Treatment Optimization.

    Stores derived optimization candidates proposing policy changes based on operational performance
    projections, while preserving lineage, evidence linkage, and idempotency constraints.
    """

    __tablename__ = "stage3_optimization_candidates"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "source_projection_id",
            "proposed_action",
            "optimizer_version",
            name="uq_s3_candidate_projection_action",
        ),
        Index("ix_s3_candidate_merchant", "merchant_id"),
        Index("ix_s3_candidate_status", "status"),
    )

    candidate_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_projection_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    policy_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    experiment_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    configuration_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    f5_policy_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    f5_policy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    proposed_action: Mapped[str] = mapped_column(String(48), nullable=False)
    baseline_action: Mapped[str] = mapped_column(String(48), nullable=False)

    objective_value: Mapped[float] = mapped_column(nullable=False)
    baseline_objective_value: Mapped[float] = mapped_column(nullable=False)
    expected_improvement_value: Mapped[float] = mapped_column(nullable=False)

    observed_recovery_rate: Mapped[float] = mapped_column(nullable=False)
    baseline_recovery_rate: Mapped[float] = mapped_column(nullable=False)
    expected_improvement_rate: Mapped[float] = mapped_column(nullable=False)

    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_f4_evidence_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    optimizer_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="GENERATED")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class RecoveryOrchestrationRecord(Base):
    """Durable RecoveryOrchestrationRecord for Step 3 Closed-Loop Orchestration.

    Tracks multi-attempt recovery episode state, attempt progression, stopping reasons,
    and escalation status with strict tenant isolation and optimistic concurrency safety.
    """

    __tablename__ = "stage3_recovery_orchestrations"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_orchestration_case"),
        Index("ix_orchestration_merchant", "merchant_id"),
        Index("ix_orchestration_status", "episode_status"),
        Index("ix_orchestration_payment", "payment_id"),
    )

    orchestration_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recovery_episode_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    current_attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    episode_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    current_attempt_status: Mapped[str | None] = mapped_column(String(32), nullable=True, default="NONE")

    selected_action: Mapped[str | None] = mapped_column(String(48), nullable=True)
    proposal_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    enforcement_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    last_outcome_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    total_net_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)

    stopping_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    escalation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class RecoveryAttemptRecord(Base):
    """Durable attempt record ensuring unique attempt numbering per case (Step 3)."""

    __tablename__ = "stage3_recovery_attempts"
    __table_args__ = (
        UniqueConstraint("case_id", "attempt_number", name="uq_attempt_case_number"),
        Index("ix_attempt_orchestration", "orchestration_id"),
        Index("ix_attempt_merchant", "merchant_id"),
    )

    attempt_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    proposed_action: Mapped[str] = mapped_column(String(48), nullable=False)
    executed_action: Mapped[str] = mapped_column(String(48), nullable=False)

    proposal_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    enforcement_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    enforcement_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)

    outcome_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    net_recovered_amount: Mapped[float] = mapped_column(nullable=False, default=0.0)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="INITIATED")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecoveryEscalationRecord(Base):
    """Durable escalation artifact for operator review and workflow governance (Step 3)."""

    __tablename__ = "stage3_recovery_escalations"
    __table_args__ = (
        Index("ix_escalation_merchant_status", "merchant_id", "status"),
        Index("ix_escalation_orchestration", "orchestration_id"),
        Index("ix_escalation_case", "case_id"),
    )

    escalation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="MEDIUM")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)

    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_operator: Mapped[str | None] = mapped_column(String(128), nullable=True)

    resolution_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


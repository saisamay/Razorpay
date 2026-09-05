from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OutcomeCollectionStatus(str, Enum):
    """Explicit collection status enum for Stage 3 Outcome Ingestion."""

    COLLECTED = "COLLECTED"
    ALREADY_COLLECTED = "ALREADY_COLLECTED"
    NOT_FOUND = "NOT_FOUND"
    NOT_READY = "NOT_READY"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class OutcomeCollectionResult:
    """Structured result returned by the Stage 3 Outcome Collector."""

    attribution_id: str
    status: OutcomeCollectionStatus
    message: str
    merchant_id: str | None = None
    observation_id: str | None = None
    collected_at: datetime | None = None


class ProjectionStatus(str, Enum):
    """Explicit analytical status enum for Policy Performance Projections."""

    ACTIVE_MONITORING = "ACTIVE_MONITORING"
    DEGRADED = "DEGRADED"
    SUPERSEDED = "SUPERSEDED"
    NO_DATA = "NO_DATA"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class PolicyMonitoringScope:
    """Explicit Policy Monitoring Scope 6-tuple."""

    merchant_id: str
    policy_id: str | None = None
    policy_version: str | None = None
    experiment_id: str | None = None
    experiment_version: str | None = None
    configuration_hash: str | None = None


@dataclass(frozen=True)
class PolicyPerformanceProjectionResult:
    """Structured result returned by the Stage 3 Performance Monitor."""

    projection_id: str
    scope: PolicyMonitoringScope
    window_start: datetime
    window_end: datetime
    sample_size: int
    recovery_success_rate: float | None
    total_net_recovered_amount: float
    operational_failure_rate: float | None
    avg_recovery_latency_seconds: float | None
    strategy_breakdown: dict
    status: ProjectionStatus
    message: str


class CandidateStatus(str, Enum):
    """Explicit candidate lifecycle status enum for Stage 3 Optimization Candidates (S3-3)."""

    GENERATED = "GENERATED"
    WAITING_FOR_F4 = "WAITING_FOR_F4"
    READY_FOR_F5 = "READY_FOR_F5"
    WAITING_FOR_F5 = "WAITING_FOR_F5"
    SUBMITTED_TO_F5 = "SUBMITTED_TO_F5"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class OptimizationCandidateResult:
    """Structured result returned by the Stage 3 Optimizer (S3-3)."""

    candidate_id: str | None
    merchant_id: str
    source_projection_id: str
    proposed_action: str | None
    baseline_action: str | None
    objective_value: float | None
    baseline_objective_value: float | None
    expected_improvement_value: float | None
    observed_recovery_rate: float | None
    baseline_recovery_rate: float | None
    expected_improvement_rate: float | None
    sample_size: int
    source_f4_evidence_id: str | None
    f5_policy_id: str | None
    f5_policy_version: str | None
    status: CandidateStatus | str
    reason_code: str
    message: str


class EpisodeStatus(str, Enum):
    """Deterministic episode state enum for Step 3 Closed-Loop Recovery Orchestration."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_OUTCOME = "AWAITING_OUTCOME"
    RECOVERED = "RECOVERED"
    STOPPED = "STOPPED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class EscalationStatus(str, Enum):
    """Lifecycle status enum for Recovery Escalation Records."""

    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class StoppingDecision:
    """Structured decision returned by the Stage 3 Stopping Engine."""

    should_stop: bool
    reason_code: str
    explanation: str
    authoritative_source: str
    target_status: str = "STOPPED"


@dataclass(frozen=True)
class EscalationResolutionRequest:
    """Request payload for resolving an operator escalation."""

    resolution_action: str  # RESUME_AUTOMATION, STOP_RECOVERY, CLOSE_CASE
    operator_id: str
    notes: str | None = None


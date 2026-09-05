from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from enum import Enum
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ExperimentApprovalRecord, ExperimentDesignRecord


class RandomizationDesign(str, Enum):
    """Authoritative randomization design enum for experiment inference."""

    BERNOULLI = "BERNOULLI"
    COMPLETE_RANDOMIZATION = "COMPLETE_RANDOMIZATION"


def validate_allocation_ratio(allocation_ratio: Any) -> float:
    """Validate allocation_ratio is a finite float between 0.0 and 1.0 inclusive (I-005)."""
    if allocation_ratio is None or isinstance(allocation_ratio, bool) or not isinstance(allocation_ratio, (int, float)):
        raise ValueError(f"Invalid allocation_ratio {allocation_ratio}: Must be a numeric float")
    val = float(allocation_ratio)
    if math.isnan(val) or math.isinf(val) or not (0.0 <= val <= 1.0):
        raise ValueError(f"Invalid allocation_ratio {allocation_ratio}: Must be a finite float between 0.0 and 1.0 inclusive")
    return val


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentDesign(BaseModel):
    experiment_id: str
    experiment_version: str = "1.0"

    control_arm_definition: str = "PASSIVE_NO_ACTION"
    treatment_arm_definition: str = "STAGE2_DECISION_PROPOSAL"

    primary_metric: str = "VERIFIED_INCREMENTAL_RECOVERED_REVENUE"
    secondary_metrics: list[str] = Field(default_factory=lambda: [
        "recovery_rate",
        "average_recovered_amount",
        "customer_friction",
        "retry_attempts",
        "compliance_blocks",
        "compliance_violations",
        "verified_loss",
        "false_recovery_decisions",
    ])

    population_definition: str = "ALL_ELIGIBLE_FAILED_RECOVERY_CASES"
    population_start_time: datetime
    population_end_time: datetime | None = None
    single_active_experiment_constraint: bool = True

    assignment_identity_strategy: str = "MERCHANT_SCOPED_PAYMENT_STABLE"
    assignment_salt_version: str = "v1"
    allocation_ratio: float = Field(default=0.50, ge=0.0, le=1.0)
    randomization_design: str = RandomizationDesign.BERNOULLI.value

    @field_validator("allocation_ratio")
    @classmethod
    def check_allocation_ratio_finite(cls, v: float) -> float:
        return validate_allocation_ratio(v)

    baseline_assumption_source: str = "HISTORICAL_BASELINE_INSUFFICIENT"
    baseline_recovery_rate: str = "UNAVAILABLE"
    minimum_detectable_effect: str = "UNAVAILABLE"
    required_sample_size: str = "UNAVAILABLE"
    significance_level: float = 0.05
    statistical_power: float = 0.80

    attribution_window_hours: int = 72
    efficacy_stopping_rule: str = "PRE_REGISTERED_ANALYSIS_POINT_ONLY"
    safety_stopping_rules: dict[str, Any] = Field(default_factory=lambda: {
        "max_compliance_violations": 0,
        "max_verified_financial_loss": 5000.0,
        "max_customer_friction_spike": 0.25,
    })

    status: str = "DRAFT"  # DRAFT, FROZEN, READY, APPROVED, RUNNING, COMPLETED, SAFETY_STOPPED, INVALIDATED, REJECTED
    approved_configuration_hash: str | None = None

    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    rejected_at: datetime | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None


def _iso_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond:06d}+00:00"


def compute_configuration_hash(exp: ExperimentDesign) -> str:
    """Compute SHA-256 hash of immutable experiment configuration fields including salt version and randomization design."""
    payload = {
        "experiment_id": exp.experiment_id,
        "experiment_version": exp.experiment_version,
        "control_arm_definition": exp.control_arm_definition,
        "treatment_arm_definition": exp.treatment_arm_definition,
        "primary_metric": exp.primary_metric,
        "secondary_metrics": sorted(exp.secondary_metrics),
        "population_definition": exp.population_definition,
        "population_start_time": _iso_dt(exp.population_start_time),
        "population_end_time": _iso_dt(exp.population_end_time),
        "assignment_identity_strategy": exp.assignment_identity_strategy,
        "assignment_salt_version": exp.assignment_salt_version,
        "allocation_ratio": exp.allocation_ratio,
        "randomization_design": exp.randomization_design,
        "baseline_assumption_source": exp.baseline_assumption_source,
        "baseline_recovery_rate": exp.baseline_recovery_rate,
        "minimum_detectable_effect": exp.minimum_detectable_effect,
        "required_sample_size": exp.required_sample_size,
        "significance_level": exp.significance_level,
        "statistical_power": exp.statistical_power,
        "attribution_window_hours": exp.attribution_window_hours,
        "efficacy_stopping_rule": exp.efficacy_stopping_rule,
        "safety_stopping_rules": exp.safety_stopping_rules,
    }
    raw_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def experiment_design_from_record(rec: ExperimentDesignRecord) -> ExperimentDesign:
    """Reconstruct ExperimentDesign Pydantic DTO from DB record for live hash validation."""
    return ExperimentDesign(
        experiment_id=rec.experiment_id,
        experiment_version=rec.experiment_version,
        control_arm_definition=rec.control_arm_definition,
        treatment_arm_definition=rec.treatment_arm_definition,
        primary_metric=rec.primary_metric,
        secondary_metrics=rec.secondary_metrics or [],
        population_definition=rec.population_definition,
        population_start_time=_ensure_utc(rec.population_start_time),
        population_end_time=_ensure_utc(rec.population_end_time),
        single_active_experiment_constraint=rec.single_active_experiment_constraint,
        assignment_identity_strategy=rec.assignment_identity_strategy,
        assignment_salt_version=rec.assignment_salt_version,
        allocation_ratio=rec.allocation_ratio,
        randomization_design=getattr(rec, "randomization_design", RandomizationDesign.BERNOULLI.value) or RandomizationDesign.BERNOULLI.value,
        baseline_assumption_source=rec.baseline_assumption_source,
        baseline_recovery_rate=rec.baseline_recovery_rate,
        minimum_detectable_effect=rec.minimum_detectable_effect,
        required_sample_size=rec.required_sample_size,
        significance_level=rec.significance_level,
        statistical_power=rec.statistical_power,
        attribution_window_hours=rec.attribution_window_hours,
        efficacy_stopping_rule=rec.efficacy_stopping_rule,
        safety_stopping_rules=rec.safety_stopping_rules or {},
        status=rec.status,
        approved_configuration_hash=rec.approved_configuration_hash,
        created_at=_ensure_utc(rec.created_at),
        approved_at=_ensure_utc(rec.approved_at),
        approved_by=rec.approved_by,
        rejected_at=_ensure_utc(rec.rejected_at),
        rejected_by=rec.rejected_by,
        rejection_reason=rec.rejection_reason,
    )


def create_experiment_design(
    session: Session,
    experiment_id: str,
    *,
    experiment_version: str = "1.0",
    allocation_ratio: float = 0.50,
    population_start_time: datetime | None = None,
) -> ExperimentDesignRecord:
    """Create a new DRAFT experiment design."""
    validated_ratio = validate_allocation_ratio(allocation_ratio)
    now = utc_now()
    start_t = population_start_time or now
    pk_id = f"{experiment_id}:{experiment_version}"

    existing = session.get(ExperimentDesignRecord, pk_id)
    if existing:
        raise ValueError(f"ExperimentDesign {pk_id} already exists")

    default_dto = ExperimentDesign(
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        allocation_ratio=validated_ratio,
        population_start_time=start_t,
        created_at=now,
    )
    rec = ExperimentDesignRecord(
        id=pk_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        control_arm_definition=default_dto.control_arm_definition,
        treatment_arm_definition=default_dto.treatment_arm_definition,
        primary_metric=default_dto.primary_metric,
        secondary_metrics=default_dto.secondary_metrics,
        population_definition=default_dto.population_definition,
        population_start_time=start_t,
        population_end_time=default_dto.population_end_time,
        single_active_experiment_constraint=default_dto.single_active_experiment_constraint,
        assignment_identity_strategy=default_dto.assignment_identity_strategy,
        assignment_salt_version=default_dto.assignment_salt_version,
        allocation_ratio=validated_ratio,
        baseline_assumption_source=default_dto.baseline_assumption_source,
        baseline_recovery_rate=default_dto.baseline_recovery_rate,
        minimum_detectable_effect=default_dto.minimum_detectable_effect,
        required_sample_size=default_dto.required_sample_size,
        significance_level=default_dto.significance_level,
        statistical_power=default_dto.statistical_power,
        attribution_window_hours=default_dto.attribution_window_hours,
        efficacy_stopping_rule=default_dto.efficacy_stopping_rule,
        safety_stopping_rules=default_dto.safety_stopping_rules,
        status="DRAFT",
        created_at=now,
    )
    session.add(rec)
    session.flush()
    return rec


def freeze_experiment_design(session: Session, experiment_id: str, experiment_version: str = "1.0") -> ExperimentDesignRecord:
    """Transition DRAFT -> FROZEN and lock configuration hash."""
    pk_id = f"{experiment_id}:{experiment_version}"
    rec = session.get(ExperimentDesignRecord, pk_id, with_for_update=True)
    if not rec:
        raise ValueError(f"ExperimentDesign {pk_id} not found")
    if rec.status != "DRAFT":
        raise ValueError(f"Cannot freeze experiment in status {rec.status}")

    validate_allocation_ratio(rec.allocation_ratio)

    rec.status = "FROZEN"
    dto = experiment_design_from_record(rec)
    rec.approved_configuration_hash = compute_configuration_hash(dto)
    rec.status = "FROZEN"
    session.flush()
    return rec


def mark_experiment_ready(session: Session, experiment_id: str, experiment_version: str = "1.0") -> ExperimentDesignRecord:
    """Transition FROZEN -> READY for pre-flight governance review."""
    pk_id = f"{experiment_id}:{experiment_version}"
    rec = session.get(ExperimentDesignRecord, pk_id, with_for_update=True)
    if not rec or rec.status != "FROZEN":
        raise ValueError(f"Experiment {pk_id} must be FROZEN before moving to READY")
    rec.status = "READY"
    session.flush()
    return rec


def approve_experiment_design(
    session: Session,
    experiment_id: str,
    experiment_version: str,
    principal_id: str,
    configuration_hash: str,
) -> ExperimentDesignRecord:
    """Human Authorization Gate: Transition READY -> APPROVED."""
    if not principal_id or principal_id.startswith("bot_") or principal_id.startswith("ml_"):
        raise ValueError(f"Unauthorized principal {principal_id}: Only human governance principals may approve experiments")

    pk_id = f"{experiment_id}:{experiment_version}"
    rec = session.get(ExperimentDesignRecord, pk_id, with_for_update=True)
    if not rec:
        raise ValueError(f"Experiment {pk_id} not found")
    if rec.status != "READY":
        raise ValueError(f"Cannot approve experiment in status {rec.status}")

    # Verify configuration hash match
    if rec.approved_configuration_hash != configuration_hash:
        raise ValueError(f"Configuration hash mismatch: expected {rec.approved_configuration_hash}, got {configuration_hash}")

    now = utc_now()
    rec.status = "APPROVED"
    rec.approved_at = now
    rec.approved_by = principal_id

    # Append-only audit record
    audit_id = f"appr_{hashlib.sha256(f'{pk_id}:{principal_id}:{now.isoformat()}'.encode()).hexdigest()[:32]}"
    session.add(ExperimentApprovalRecord(
        approval_id=audit_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        decision="APPROVED",
        principal_id=principal_id,
        configuration_hash=configuration_hash,
        created_at=now,
    ))
    session.flush()
    return rec


def reject_experiment_design(
    session: Session,
    experiment_id: str,
    experiment_version: str,
    principal_id: str,
    reason: str,
) -> ExperimentDesignRecord:
    """Governance Rejection: Transition READY -> REJECTED."""
    pk_id = f"{experiment_id}:{experiment_version}"
    rec = session.get(ExperimentDesignRecord, pk_id, with_for_update=True)
    if not rec or rec.status != "READY":
        raise ValueError(f"Cannot reject experiment in status {rec.status}")

    now = utc_now()
    rec.status = "REJECTED"
    rec.rejected_at = now
    rec.rejected_by = principal_id
    rec.rejection_reason = reason

    audit_id = f"rej_{hashlib.sha256(f'{pk_id}:{principal_id}:{now.isoformat()}'.encode()).hexdigest()[:32]}"
    session.add(ExperimentApprovalRecord(
        approval_id=audit_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        decision="REJECTED",
        principal_id=principal_id,
        configuration_hash=rec.approved_configuration_hash or "NONE",
        reason=reason,
        created_at=now,
    ))
    session.flush()
    return rec


def activate_experiment_running(session: Session, experiment_id: str, experiment_version: str = "1.0") -> ExperimentDesignRecord:
    """Transition APPROVED -> RUNNING. Enforces Single Active Experiment DB constraint."""
    pk_id = f"{experiment_id}:{experiment_version}"
    rec = session.get(ExperimentDesignRecord, pk_id, with_for_update=True)
    if not rec or rec.status != "APPROVED":
        raise ValueError(f"Experiment {pk_id} must be APPROVED before activation")

    # Enforce database single active experiment check
    if rec.single_active_experiment_constraint:
        active_cnt = session.scalars(
            select(ExperimentDesignRecord)
            .where(
                ExperimentDesignRecord.population_definition == rec.population_definition,
                ExperimentDesignRecord.status == "RUNNING",
                ExperimentDesignRecord.id != pk_id,
            )
        ).all()
        if active_cnt:
            raise ValueError(f"Single active experiment constraint violated: {active_cnt[0].experiment_id} is already RUNNING")

    now = utc_now()
    rec.status = "RUNNING"
    if rec.population_start_time is None:
        rec.population_start_time = now
    session.flush()
    return rec

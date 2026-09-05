from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RecoveryEscalationRecord, RecoveryOrchestrationRecord

logger = logging.getLogger(__name__)

ALLOWED_RESOLUTION_ACTIONS = {"RESUME_AUTOMATION", "STOP_RECOVERY", "CLOSE_CASE"}
DEFAULT_ESCALATION_SLA_HOURS = 24.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EscalationError(ValueError):
    """Base exception for escalation validation or permission errors."""
    pass


class TenantAccessError(EscalationError):
    """Raised when tenant boundary is violated."""
    pass


def create_escalation(
    session: Session,
    *,
    orchestration_id: str,
    case_id: str,
    merchant_id: str,
    reason_code: str,
    severity: str = "MEDIUM",
    details: dict[str, Any] | None = None,
) -> RecoveryEscalationRecord:
    """Creates a durable RecoveryEscalationRecord and locks orchestration out of automated execution."""

    now = utc_now()
    escalation_id = f"esc_{uuid4().hex[:16]}"

    escalation = RecoveryEscalationRecord(
        escalation_id=escalation_id,
        orchestration_id=orchestration_id,
        case_id=case_id,
        merchant_id=merchant_id,
        reason_code=reason_code,
        severity=severity,
        status="OPEN",
        triggered_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(escalation)

    # Lock orchestration state to ESCALATED
    orchestration = session.get(RecoveryOrchestrationRecord, orchestration_id, with_for_update=True)
    if orchestration is not None:
        orchestration.episode_status = "ESCALATED"
        orchestration.escalation_id = escalation_id
        orchestration.updated_at = now

    return escalation


def get_escalation(
    session: Session, escalation_id: str, merchant_id: str | None = None
) -> RecoveryEscalationRecord:
    """Retrieve an escalation record with strict tenant boundary enforcement."""

    escalation = session.get(RecoveryEscalationRecord, escalation_id)
    if escalation is None:
        raise EscalationError(f"Escalation record '{escalation_id}' not found.")

    if merchant_id is not None and escalation.merchant_id != merchant_id:
        raise TenantAccessError(
            f"Tenant access denied: merchant '{merchant_id}' cannot access escalation for merchant '{escalation.merchant_id}'."
        )

    return escalation


def list_escalations(
    session: Session,
    merchant_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[RecoveryEscalationRecord]:
    """List tenant-isolated escalations, ordered by creation time descending."""

    stmt = select(RecoveryEscalationRecord).where(RecoveryEscalationRecord.merchant_id == merchant_id)
    if status:
        stmt = stmt.where(RecoveryEscalationRecord.status == status)

    stmt = stmt.order_by(RecoveryEscalationRecord.created_at.desc()).limit(limit).offset(offset)
    return list(session.scalars(stmt).all())


def resolve_escalation(
    session: Session,
    *,
    escalation_id: str,
    merchant_id: str,
    resolution_action: str,
    operator_id: str,
    notes: str | None = None,
) -> RecoveryEscalationRecord:
    """Resolves an escalation with a bounded resolution action and updates the orchestration state."""

    if resolution_action not in ALLOWED_RESOLUTION_ACTIONS:
        raise EscalationError(
            f"Invalid resolution action '{resolution_action}'. Must be one of {ALLOWED_RESOLUTION_ACTIONS}."
        )

    escalation = session.get(RecoveryEscalationRecord, escalation_id, with_for_update=True)
    if escalation is None:
        raise EscalationError(f"Escalation '{escalation_id}' not found.")

    if escalation.merchant_id != merchant_id:
        raise TenantAccessError(
            f"Tenant access denied: merchant '{merchant_id}' cannot modify escalation for merchant '{escalation.merchant_id}'."
        )

    if escalation.status not in {"OPEN", "IN_REVIEW"}:
        raise EscalationError(f"Escalation '{escalation_id}' is already in terminal status '{escalation.status}'.")

    now = utc_now()
    new_status = "RESOLVED" if resolution_action in {"RESUME_AUTOMATION", "STOP_RECOVERY"} else "CLOSED"

    escalation.status = new_status
    escalation.resolution_action = resolution_action
    escalation.assigned_operator = operator_id
    escalation.resolution_notes = notes
    escalation.resolved_at = now
    escalation.updated_at = now

    # Update associated orchestration episode state
    orchestration = session.get(RecoveryOrchestrationRecord, escalation.orchestration_id, with_for_update=True)
    if orchestration is not None:
        if resolution_action in {"STOP_RECOVERY", "CLOSE_CASE"}:
            orchestration.episode_status = "STOPPED"
            orchestration.stopping_reason = f"OPERATOR_{resolution_action}"
        elif resolution_action == "RESUME_AUTOMATION":
            # Unlock episode back to PENDING so next worker sweep can evaluate attempt
            orchestration.episode_status = "PENDING"
            orchestration.escalation_id = None
        orchestration.updated_at = now

    return escalation


def check_and_apply_sla_timeouts(
    session: Session, sla_hours: float = DEFAULT_ESCALATION_SLA_HOURS
) -> list[RecoveryEscalationRecord]:
    """Sweeps unresolved escalations exceeding SLA hours and automatically stops associated recovery episodes."""

    now = utc_now()
    cutoff = now - timedelta(hours=sla_hours)

    stmt = (
        select(RecoveryEscalationRecord)
        .where(
            RecoveryEscalationRecord.status.in_(["OPEN", "IN_REVIEW"]),
            RecoveryEscalationRecord.triggered_at <= cutoff,
        )
        .with_for_update()
    )
    overdue = list(session.scalars(stmt).all())

    resolved_records: list[RecoveryEscalationRecord] = []
    for esc in overdue:
        esc.status = "RESOLVED"
        esc.resolution_action = "AUTO_STOP_SLA_EXPIRED"
        esc.assigned_operator = "SYSTEM_SLA_WORKER"
        esc.resolution_notes = f"Escalation automatically resolved due to SLA expiry (> {sla_hours}h)."
        esc.resolved_at = now
        esc.updated_at = now

        orchestration = session.get(RecoveryOrchestrationRecord, esc.orchestration_id, with_for_update=True)
        if orchestration is not None:
            orchestration.episode_status = "STOPPED"
            orchestration.stopping_reason = "ESCALATION_SLA_EXPIRED"
            orchestration.updated_at = now

        resolved_records.append(esc)

    return resolved_records

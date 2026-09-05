from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from ..models import RecoveryCase
from .escalation import (
    EscalationError,
    TenantAccessError,
    get_escalation,
    list_escalations,
    resolve_escalation,
)
from .models import RecoveryAttemptRecord, RecoveryEscalationRecord, RecoveryOrchestrationRecord

logger = logging.getLogger(__name__)

escalation_router = APIRouter(prefix="/api/v3", tags=["escalations"])


def _verify_tenant_access(merchant_id: str, x_merchant_id: str | None) -> None:
    if x_merchant_id and merchant_id != x_merchant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant access denied: merchant '{x_merchant_id}' cannot access records for merchant '{merchant_id}'.",
        )


class ResolveEscalationPayload(BaseModel):
    resolution_action: str  # RESUME_AUTOMATION, STOP_RECOVERY, CLOSE_CASE
    operator_id: str
    notes: str | None = None


@escalation_router.get("/escalations")
def get_escalations(
    request: Request,
    x_merchant_id: str | None = Header(default=None),
    merchant_id: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Tenant-isolated endpoint to list open/resolved recovery escalations."""

    target_merchant = x_merchant_id or merchant_id
    if not target_merchant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'x-merchant-id' or query parameter 'merchant_id' is required.",
        )

    factory = request.app.state.sessions
    with factory() as session:
        escalations = list_escalations(
            session, merchant_id=target_merchant, status=status_filter, limit=limit, offset=offset
        )
        return [
            {
                "escalation_id": e.escalation_id,
                "orchestration_id": e.orchestration_id,
                "case_id": e.case_id,
                "merchant_id": e.merchant_id,
                "reason_code": e.reason_code,
                "severity": e.severity,
                "status": e.status,
                "triggered_at": e.triggered_at,
                "assigned_operator": e.assigned_operator,
                "resolution_action": e.resolution_action,
                "resolved_at": e.resolved_at,
            }
            for e in escalations
        ]


@escalation_router.get("/escalations/{escalation_id}")
def get_escalation_detail(
    escalation_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-authorized detail view for a specific escalation and its orchestration metadata."""

    factory = request.app.state.sessions
    with factory() as session:
        try:
            esc = get_escalation(session, escalation_id, merchant_id=x_merchant_id)
        except TenantAccessError as err:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err))
        except EscalationError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))

        orch = session.get(RecoveryOrchestrationRecord, esc.orchestration_id)
        case = session.get(RecoveryCase, esc.case_id)

        return {
            "escalation": {
                "escalation_id": esc.escalation_id,
                "orchestration_id": esc.orchestration_id,
                "case_id": esc.case_id,
                "merchant_id": esc.merchant_id,
                "reason_code": esc.reason_code,
                "severity": esc.severity,
                "status": esc.status,
                "triggered_at": esc.triggered_at,
                "assigned_operator": esc.assigned_operator,
                "resolution_action": esc.resolution_action,
                "resolution_notes": esc.resolution_notes,
                "resolved_at": esc.resolved_at,
            },
            "orchestration": {
                "orchestration_id": orch.orchestration_id if orch else None,
                "current_attempt_number": orch.current_attempt_number if orch else 0,
                "max_attempts": orch.max_attempts if orch else 3,
                "episode_status": orch.episode_status if orch else "UNKNOWN",
                "selected_action": orch.selected_action if orch else None,
                "total_net_recovered_amount": orch.total_net_recovered_amount if orch else 0.0,
                "stopping_reason": orch.stopping_reason if orch else None,
            },
            "case": {
                "amount": case.amount if case else None,
                "currency": case.currency if case else "INR",
                "state": case.state if case else "UNKNOWN",
                "recovery_eligible": case.recovery_eligible if case else False,
            },
        }


@escalation_router.post("/escalations/{escalation_id}/resolve")
def resolve_escalation_endpoint(
    escalation_id: str,
    payload: ResolveEscalationPayload,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-authorized endpoint for resolving an escalation with bounded resolution actions."""

    factory = request.app.state.sessions
    with factory() as session:
        try:
            # First fetch to verify tenant authorization before mutating
            esc_pre = session.get(RecoveryEscalationRecord, escalation_id)
            if esc_pre is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Escalation '{escalation_id}' not found.")

            target_merchant = x_merchant_id or esc_pre.merchant_id
            _verify_tenant_access(esc_pre.merchant_id, target_merchant)

            resolved = resolve_escalation(
                session,
                escalation_id=escalation_id,
                merchant_id=target_merchant,
                resolution_action=payload.resolution_action,
                operator_id=payload.operator_id,
                notes=payload.notes,
            )
            session.commit()

            return {
                "escalation_id": resolved.escalation_id,
                "status": resolved.status,
                "resolution_action": resolved.resolution_action,
                "assigned_operator": resolved.assigned_operator,
                "resolved_at": resolved.resolved_at,
            }

        except TenantAccessError as err:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err))
        except EscalationError as err:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@escalation_router.get("/cases/{case_id}/attempts")
def get_case_attempts(
    case_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-isolated read-only endpoint returning recovery attempts for a case in attempt_number ASC order (Gap 1)."""
    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case '{case_id}' not found.")

        _verify_tenant_access(case.merchant_id, x_merchant_id)

        attempts = session.scalars(
            select(RecoveryAttemptRecord)
            .where(RecoveryAttemptRecord.case_id == case_id)
            .order_by(RecoveryAttemptRecord.attempt_number.asc(), RecoveryAttemptRecord.started_at.asc())
        ).all()

        return [
            {
                "attempt_id": a.attempt_id,
                "orchestration_id": a.orchestration_id,
                "case_id": a.case_id,
                "merchant_id": a.merchant_id,
                "attempt_number": a.attempt_number,
                "proposed_action": a.proposed_action,
                "executed_action": a.executed_action,
                "proposal_id": a.proposal_id,
                "enforcement_id": a.enforcement_id,
                "enforcement_decision": a.enforcement_decision,
                "outcome_status": a.outcome_status,
                "net_recovered_amount": a.net_recovered_amount,
                "status": a.status,
                "started_at": a.started_at,
                "completed_at": a.completed_at,
            }
            for a in attempts
        ]


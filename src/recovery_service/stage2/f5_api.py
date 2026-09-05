"""F5-5 Emergency Kill Switch API Router.

Provides privileged administrative REST endpoint for emergency policy kill switch operations.
Enforces strict authentication header verification, tenant/experiment scope validation,
row-level locked database transactions, append-only audit persistence, and structured response.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from .f5.contracts import EnforcementEvidenceBundle, PolicyKillResult
from .f5.repository import execute_emergency_kill, reconstruct_enforcement_evidence

logger = logging.getLogger(__name__)

f5_router = APIRouter(prefix="/api/v2/policies", tags=["F5 Emergency Policy Safety API"])


class KillPolicyRequest(BaseModel):
    merchant_id: str = Field(..., description="Merchant tenant identifier")
    experiment_id: str = Field(..., description="Experiment identifier")
    experiment_version: str = Field("1.0", description="Experiment version string")
    approved_configuration_hash: str = Field(..., description="64-character hex configuration hash")
    operator_id: str | None = Field(None, description="Operator user identifier")
    reason: str | None = Field(None, description="Kill reason description")


def _require_admin_auth(request: Request, x_internal_token: str | None) -> None:
    settings = getattr(request.app.state, "settings", None)
    if settings and getattr(settings, "internal_api_token", None):
        expected = settings.internal_api_token
        if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: invalid or missing administrative internal token",
            )


@f5_router.post("/{policy_id}/kill", response_model=PolicyKillResult)
def kill_policy_endpoint(
    policy_id: str,
    body: KillPolicyRequest,
    request: Request,
    x_internal_token: str | None = Header(default=None),
) -> PolicyKillResult:
    """Executes emergency kill switch on a Stage 2 decision policy.

    Immediately transitions policy state to KILLED_SAFETY_STOP under database row lock.
    Subsequent F5-4 enforcement requests resolve to baseline STOP.
    """
    _require_admin_auth(request, x_internal_token)

    session_factory = getattr(request.app.state, "sessions", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database session factory uninitialized",
        )

    session = session_factory()
    try:
        result = execute_emergency_kill(
            session,
            policy_id=policy_id,
            merchant_id=body.merchant_id,
            experiment_id=body.experiment_id,
            experiment_version=body.experiment_version,
            approved_configuration_hash=body.approved_configuration_hash,
            operator_id=body.operator_id,
            reason=body.reason,
        )
        session.commit()
        return result
    except ValueError as err:
        session.rollback()
        err_msg = str(err)
        if "not found" in err_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except Exception as err:
        session.rollback()
        logger.error(f"Emergency kill switch failed for policy {policy_id}: {err}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Emergency kill switch operation failed: {err}",
        )
    finally:
        session.close()


@f5_router.get("/enforcement/{enforcement_id}/evidence", response_model=EnforcementEvidenceBundle)
def get_enforcement_evidence_endpoint(
    enforcement_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None),
) -> EnforcementEvidenceBundle:
    """Retrieves authoritative forensic evidence bundle for an enforcement decision (F5-6).

    Applies strict tenant boundary verification and returns structured evidence bundle.
    """
    _require_admin_auth(request, x_internal_token)

    session_factory = getattr(request.app.state, "sessions", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database session factory uninitialized",
        )

    session = session_factory()
    try:
        evidence = reconstruct_enforcement_evidence(
            session,
            enforcement_id=enforcement_id,
            merchant_id=x_merchant_id,
        )
        return evidence
    except ValueError as err:
        err_msg = str(err)
        if "Tenant access denied" in err_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=err_msg)
        if "not found" in err_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    finally:
        session.close()


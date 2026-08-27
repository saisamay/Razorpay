from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from ..models import RecoveryCase
from .consumer import process_diagnosis
from .models import DiagnosisRecord, EvidenceManifestRecord, Stage2Case
from .schemas import RecoveryCaseContract


logger = logging.getLogger(__name__)
stage2_router = APIRouter(prefix="/api/v2", tags=["stage2"])


def _verify_tenant_access(case: RecoveryCase, x_merchant_id: str | None) -> None:
    """Enforce strict horizontal tenant boundary: Merchant A cannot read Merchant B's data."""

    if case.merchant_id and x_merchant_id and case.merchant_id != x_merchant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant access denied: merchant {x_merchant_id} cannot access case for merchant {case.merchant_id}",
        )


def _require_admin_auth(request: Request, x_internal_token: str | None) -> None:
    settings = getattr(request.app.state, "settings", None)
    if settings and settings.internal_api_token:
        if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.internal_api_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized internal token")


@stage2_router.get("/cases/{case_id}/diagnosis")
def get_case_diagnosis(
    case_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-authorized read endpoint for active current diagnosis."""

    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case {case_id} not found")

        _verify_tenant_access(case, x_merchant_id)

        diag = session.scalars(
            select(DiagnosisRecord)
            .where(DiagnosisRecord.case_id == case_id, DiagnosisRecord.status == "CURRENT")
            .order_by(DiagnosisRecord.stage1_state_version.desc())
        ).first()

        if diag is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No active diagnosis for case {case_id}")

        return {
            "diagnosis_id": diag.diagnosis_id,
            "case_id": diag.case_id,
            "payment_id": diag.payment_id,
            "merchant_id": diag.merchant_id,
            "stage1_state_version": diag.stage1_state_version,
            "diagnosis_class": diag.diagnosis_class,
            "score": diag.score,
            "confidence": diag.confidence,
            "engine_version": diag.engine_version,
            "status": diag.status,
            "evidence_ids": diag.evidence_ids,
            "contradiction_ids": diag.contradiction_ids,
            "competing_hypotheses": diag.competing_hypotheses,
            "created_at": diag.created_at,
        }


@stage2_router.get("/cases/{case_id}/manifest")
def get_case_manifest(
    case_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-authorized read endpoint for EvidenceManifest."""

    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case {case_id} not found")

        _verify_tenant_access(case, x_merchant_id)

        manifest_rec = session.scalars(
            select(EvidenceManifestRecord)
            .where(EvidenceManifestRecord.case_id == case_id)
            .order_by(EvidenceManifestRecord.stage1_state_version.desc())
        ).first()

        if manifest_rec is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No evidence manifest for case {case_id}")

        return manifest_rec.data


@stage2_router.get("/cases/{case_id}/history")
def get_case_history(
    case_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-authorized read endpoint for complete versioned diagnosis history."""

    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case {case_id} not found")

        _verify_tenant_access(case, x_merchant_id)

        history = session.scalars(
            select(DiagnosisRecord)
            .where(DiagnosisRecord.case_id == case_id)
            .order_by(DiagnosisRecord.stage1_state_version.asc())
        ).all()

        return [
            {
                "diagnosis_id": d.diagnosis_id,
                "stage1_state_version": d.stage1_state_version,
                "diagnosis_class": d.diagnosis_class,
                "score": d.score,
                "confidence": d.confidence,
                "status": d.status,
                "engine_version": d.engine_version,
                "created_at": d.created_at,
            }
            for d in history
        ]


@stage2_router.post("/cases/{case_id}/reprocess")
def reprocess_case(
    case_id: str,
    request: Request,
    x_internal_token: str | None = Header(default=None),
):
    """Authenticated internal endpoint to trigger re-diagnosis of a case."""

    _require_admin_auth(request, x_internal_token)
    factory = request.app.state.sessions

    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case {case_id} not found")

        contract = RecoveryCaseContract(
            case_id=case.case_id,
            payment_id=case.payment_id,
            recovery_episode_id=case.recovery_episode_id,
            merchant_id=case.merchant_id,
            order_id=case.order_id,
            amount=case.amount,
            currency=case.currency,
            state=case.state,
            state_confidence=case.state_confidence,
            failure_evidence=case.failure_evidence,
            first_seen_at=case.first_seen_at,
            last_seen_at=case.last_seen_at,
            recovery_eligible=case.recovery_eligible,
            eligibility_reason=case.eligibility_reason,
            schema_version=case.schema_version,
            source_event_ids=case.source_event_ids,
            stage1_state_version=case.stage1_state_version,
        )

        manifest, diag = process_diagnosis(session, contract, worker_id="reprocess_api")
        session.commit()

        return {
            "reprocessed": True,
            "case_id": case.case_id,
            "stage1_state_version": case.stage1_state_version,
            "diagnosis_class": diag.diagnosis_class,
            "status": diag.status,
        }

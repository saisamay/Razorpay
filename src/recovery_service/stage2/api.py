from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select

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


@stage2_router.get("/cases")
def list_recovery_cases(
    request: Request,
    merchant_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    recovery_eligible: bool | None = None,
    min_amount: int | None = None,
    max_amount: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-authorized paginated read-only endpoint for RecoveryCases (Gap 3).

    Performs database-level SQL LIMIT/OFFSET pagination and server-side filtering.
    """
    if x_merchant_id and merchant_id and not hmac.compare_digest(x_merchant_id, merchant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Authenticated tenant {x_merchant_id} cannot request cases for merchant {merchant_id}",
        )

    effective_merchant = x_merchant_id or merchant_id
    if not effective_merchant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'x-merchant-id' or query parameter 'merchant_id' is required.",
        )

    factory = request.app.state.sessions
    with factory() as session:
        stmt = select(RecoveryCase).where(RecoveryCase.merchant_id == effective_merchant)
        count_stmt = select(func.count(RecoveryCase.case_id)).where(RecoveryCase.merchant_id == effective_merchant)

        if status_filter:
            stmt = stmt.where(RecoveryCase.state == status_filter)
            count_stmt = count_stmt.where(RecoveryCase.state == status_filter)

        if recovery_eligible is not None:
            stmt = stmt.where(RecoveryCase.recovery_eligible == recovery_eligible)
            count_stmt = count_stmt.where(RecoveryCase.recovery_eligible == recovery_eligible)

        if min_amount is not None:
            stmt = stmt.where(RecoveryCase.amount >= min_amount)
            count_stmt = count_stmt.where(RecoveryCase.amount >= min_amount)

        if max_amount is not None:
            stmt = stmt.where(RecoveryCase.amount <= max_amount)
            count_stmt = count_stmt.where(RecoveryCase.amount <= max_amount)

        total = session.scalar(count_stmt) or 0

        stmt = (
            stmt.order_by(RecoveryCase.first_seen_at.desc(), RecoveryCase.case_id.asc())
            .offset(offset)
            .limit(limit)
        )
        cases = session.scalars(stmt).all()

        return {
            "items": [
                {
                    "case_id": c.case_id,
                    "payment_id": c.payment_id,
                    "recovery_episode_id": c.recovery_episode_id,
                    "merchant_id": c.merchant_id,
                    "order_id": c.order_id,
                    "amount": c.amount,
                    "currency": c.currency,
                    "state": c.state,
                    "state_confidence": c.state_confidence,
                    "recovery_eligible": c.recovery_eligible,
                    "eligibility_reason": c.eligibility_reason,
                    "schema_version": c.schema_version,
                    "stage1_state_version": c.stage1_state_version,
                    "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None,
                    "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
                }
                for c in cases
            ],
            "limit": limit,
            "offset": offset,
            "total": total,
        }


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


@stage2_router.get("/cases/{case_id}/genome")
def get_case_genome(
    case_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
):
    """Tenant-authorized read endpoint for RecoveryGenome snapshot."""

    from .models import RecoveryGenomeRecord

    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case {case_id} not found")

        _verify_tenant_access(case, x_merchant_id)

        rec = session.scalars(
            select(RecoveryGenomeRecord)
            .where(RecoveryGenomeRecord.case_id == case_id)
            .order_by(RecoveryGenomeRecord.stage1_state_version.desc())
        ).first()

        if rec is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No RecoveryGenome found for case {case_id}")

        return {
            "genome_id": rec.genome_id,
            "case_id": rec.case_id,
            "stage1_state_version": rec.stage1_state_version,
            "genome_schema_version": rec.genome_schema_version,
            "p0_source": rec.p0_snapshot,
            "p1_source": rec.p1_snapshot,
            "provenance": rec.source_versions,
            "assembled_at": rec.assembled_at,
        }


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

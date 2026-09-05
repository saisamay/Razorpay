from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from .experiment import (
    ExperimentDesign,
    activate_experiment_running,
    approve_experiment_design,
    compute_configuration_hash,
    create_experiment_design,
    freeze_experiment_design,
    mark_experiment_ready,
    reject_experiment_design,
)
from .models import ExperimentApprovalRecord, ExperimentDesignRecord


exp_router = APIRouter(prefix="/api/v2/experiments", tags=["Stage 2 Experiment Governance API"])


class CreateExperimentRequest(BaseModel):
    experiment_id: str
    experiment_version: str = "1.0"
    allocation_ratio: float = 0.50


class ApproveExperimentRequest(BaseModel):
    experiment_version: str = "1.0"
    configuration_hash: str


class RejectExperimentRequest(BaseModel):
    experiment_version: str = "1.0"
    reason: str


def _dto_from_record(rec: ExperimentDesignRecord) -> ExperimentDesign:
    return ExperimentDesign(
        experiment_id=rec.experiment_id,
        experiment_version=rec.experiment_version,
        control_arm_definition=rec.control_arm_definition,
        treatment_arm_definition=rec.treatment_arm_definition,
        primary_metric=rec.primary_metric,
        secondary_metrics=rec.secondary_metrics,
        population_definition=rec.population_definition,
        population_start_time=rec.population_start_time,
        population_end_time=rec.population_end_time,
        single_active_experiment_constraint=rec.single_active_experiment_constraint,
        assignment_identity_strategy=rec.assignment_identity_strategy,
        assignment_salt_version=rec.assignment_salt_version,
        allocation_ratio=rec.allocation_ratio,
        baseline_assumption_source=rec.baseline_assumption_source,
        baseline_recovery_rate=rec.baseline_recovery_rate,
        minimum_detectable_effect=rec.minimum_detectable_effect,
        required_sample_size=rec.required_sample_size,
        significance_level=rec.significance_level,
        statistical_power=rec.statistical_power,
        attribution_window_hours=rec.attribution_window_hours,
        efficacy_stopping_rule=rec.efficacy_stopping_rule,
        safety_stopping_rules=rec.safety_stopping_rules,
        status=rec.status,
        approved_configuration_hash=rec.approved_configuration_hash,
        created_at=rec.created_at,
        approved_at=rec.approved_at,
        approved_by=rec.approved_by,
        rejected_at=rec.rejected_at,
        rejected_by=rec.rejected_by,
        rejection_reason=rec.rejection_reason,
    )


import hmac


def _require_admin_auth(request: Request, x_internal_token: str | None) -> None:
    settings = getattr(request.app.state, "settings", None)
    expected = getattr(settings, "internal_api_token", None) if settings else None
    if expected:
        if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: invalid or missing administrative internal token",
            )
    else:
        env = getattr(settings, "environment", "production") if settings else "production"
        if env not in {"test", "development", "local"}:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: administrative internal token is unconfigured",
            )


@exp_router.post("", response_model=ExperimentDesign, status_code=status.HTTP_201_CREATED)
def create_experiment(
    req: CreateExperimentRequest,
    request: Request,
    x_internal_token: str | None = Header(default=None),
) -> ExperimentDesign:
    _require_admin_auth(request, x_internal_token)
    factory = request.app.state.sessions
    with factory() as session:
        try:
            rec = create_experiment_design(
                session,
                req.experiment_id,
                experiment_version=req.experiment_version,
                allocation_ratio=req.allocation_ratio,
            )
            session.commit()
            return _dto_from_record(rec)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@exp_router.post("/{experiment_id}/freeze", response_model=ExperimentDesign)
def freeze_experiment(
    experiment_id: str,
    request: Request,
    version: str = "1.0",
    x_internal_token: str | None = Header(default=None),
) -> ExperimentDesign:
    _require_admin_auth(request, x_internal_token)
    factory = request.app.state.sessions
    with factory() as session:
        try:
            rec = freeze_experiment_design(session, experiment_id, version)
            session.commit()
            return _dto_from_record(rec)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@exp_router.post("/{experiment_id}/ready", response_model=ExperimentDesign)
def ready_experiment(
    experiment_id: str,
    request: Request,
    version: str = "1.0",
    x_internal_token: str | None = Header(default=None),
) -> ExperimentDesign:
    _require_admin_auth(request, x_internal_token)
    factory = request.app.state.sessions
    with factory() as session:
        try:
            rec = mark_experiment_ready(session, experiment_id, version)
            session.commit()
            return _dto_from_record(rec)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@exp_router.post("/{experiment_id}/approve", response_model=ExperimentDesign)
def approve_experiment(
    experiment_id: str,
    req: ApproveExperimentRequest,
    request: Request,
    x_principal_id: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None),
) -> ExperimentDesign:
    _require_admin_auth(request, x_internal_token)
    if not x_principal_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing required x-principal-id header for human authorization")

    factory = request.app.state.sessions
    with factory() as session:
        try:
            rec = approve_experiment_design(
                session,
                experiment_id,
                req.experiment_version,
                x_principal_id,
                req.configuration_hash,
            )
            session.commit()
            return _dto_from_record(rec)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@exp_router.post("/{experiment_id}/reject", response_model=ExperimentDesign)
def reject_experiment(
    experiment_id: str,
    req: RejectExperimentRequest,
    request: Request,
    x_principal_id: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None),
) -> ExperimentDesign:
    _require_admin_auth(request, x_internal_token)
    if not x_principal_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing required x-principal-id header")

    factory = request.app.state.sessions
    with factory() as session:
        try:
            rec = reject_experiment_design(
                session,
                experiment_id,
                req.experiment_version,
                x_principal_id,
                req.reason,
            )
            session.commit()
            return _dto_from_record(rec)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@exp_router.post("/{experiment_id}/activate", response_model=ExperimentDesign)
def activate_experiment(
    experiment_id: str,
    request: Request,
    version: str = "1.0",
    x_internal_token: str | None = Header(default=None),
) -> ExperimentDesign:
    _require_admin_auth(request, x_internal_token)
    factory = request.app.state.sessions
    with factory() as session:
        try:
            rec = activate_experiment_running(session, experiment_id, version)
            session.commit()
            return _dto_from_record(rec)
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))



@exp_router.get("/{experiment_id}", response_model=ExperimentDesign)
def get_experiment_design(experiment_id: str, request: Request, version: str = "1.0") -> ExperimentDesign:
    factory = request.app.state.sessions
    with factory() as session:
        pk_id = f"{experiment_id}:{version}"
        rec = session.get(ExperimentDesignRecord, pk_id)
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Experiment {pk_id} not found")
        return _dto_from_record(rec)


@exp_router.get("/{experiment_id}/history", response_model=list[dict[str, Any]])
def get_experiment_history(experiment_id: str, request: Request) -> list[dict[str, Any]]:
    factory = request.app.state.sessions
    with factory() as session:
        recs = session.scalars(
            select(ExperimentApprovalRecord)
            .where(ExperimentApprovalRecord.experiment_id == experiment_id)
            .order_by(ExperimentApprovalRecord.created_at.desc())
        ).all()

        return [
            {
                "approval_id": r.approval_id,
                "experiment_id": r.experiment_id,
                "experiment_version": r.experiment_version,
                "decision": r.decision,
                "principal_id": r.principal_id,
                "configuration_hash": r.configuration_hash,
                "reason": r.reason,
                "created_at": r.created_at.isoformat(),
            }
            for r in recs
        ]


@exp_router.get("/{experiment_id}/assignments/{case_id}", response_model=dict[str, Any])
def get_case_assignment(
    experiment_id: str,
    case_id: str,
    request: Request,
    version: str = "1.0",
    x_merchant_id: str | None = Header(default=None),
) -> dict[str, Any]:
    from hmac import compare_digest
    from .models import CaseAssignmentLinkRecord, ExperimentAssignmentRecord, IdentityBindingRecord, RecoveryCase

    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"RecoveryCase {case_id} not found")

        if case.merchant_id and x_merchant_id:
            if not compare_digest(case.merchant_id, x_merchant_id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: merchant mismatch")

        link = session.scalars(
            select(CaseAssignmentLinkRecord)
            .where(
                CaseAssignmentLinkRecord.case_id == case_id,
                CaseAssignmentLinkRecord.experiment_id == experiment_id,
                CaseAssignmentLinkRecord.experiment_version == version,
            )
        ).first()

        if link is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No assignment link found for case")

        asgn = session.get(ExperimentAssignmentRecord, link.assignment_id)
        bind = session.get(IdentityBindingRecord, link.binding_id)

        return {
            "link_id": link.link_id,
            "case_id": link.case_id,
            "experiment_id": link.experiment_id,
            "experiment_version": link.experiment_version,
            "merchant_id": link.merchant_id,
            "assignment_id": link.assignment_id,
            "binding_id": link.binding_id,
            "assignment_arm": link.assignment_arm,
            "assignment_status": link.assignment_status,
            "identity_type": bind.identity_type if bind else "UNASSIGNED",
            "assignment_unit_type": bind.assignment_unit_type if bind else "CASE",
            "assignment_algorithm_version": asgn.assignment_algorithm_version if asgn else "1.0",
            "created_at": link.created_at.isoformat(),
        }

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from ..models import PaymentState, RecoveryCase
from ..revenue_economics import RevenueSummary, compute_revenue_summary
from .evaluation import CaseEvaluationProjection, DataQualityStatus, MetricValue, ValueSemantics, build_metric_value
from .genai_explainer import generate_genai_explanation
from .models import (
    DecisionProposalRecord,
    DiagnosisRecord,
    EvidenceManifestRecord,
    F4EvaluationReportRecord,
    FailureFingerprintRecord,
    IncidentClusterRecord,
    RecoveryEligibilityRecord,
    RecoveryGenomeRecord,
    ShadowEvaluationRecord,
)
from .ai_reasoner import generate_ai_reasoning
from .schemas import CaseAIReasoningProjection, DecisionProposal, P0GenomeSource, P1GenomeSource, RecoveryGenome


eval_router = APIRouter(prefix="/api/v2/evaluation", tags=["Stage 2 Evaluation API"])



@eval_router.get("/revenue-summary", response_model=RevenueSummary)
def get_revenue_summary(
    request: Request,
    merchant_id: str | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    x_merchant_id: str | None = Header(default=None),
) -> RevenueSummary:
    """Deterministic Revenue Economics summary endpoint.

    Enforces strict tenant boundary isolation if X-Merchant-Id header is provided.
    Raises HTTP 403 Forbidden if X-Merchant-Id header conflicts with merchant_id query parameter.
    """
    if x_merchant_id and merchant_id and not hmac.compare_digest(x_merchant_id, merchant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Authenticated tenant {x_merchant_id} cannot request metrics for merchant {merchant_id}",
        )

    effective_merchant_id = x_merchant_id or merchant_id
    f4_report = getattr(request.app.state, "f4_report", None)

    factory = request.app.state.sessions
    with factory() as session:
        return compute_revenue_summary(
            session,
            merchant_id=effective_merchant_id,
            window_start=window_start,
            window_end=window_end,
            f4_report=f4_report,
        )


@eval_router.get("/f4-report")
def get_f4_report(
    request: Request,
    merchant_id: str | None = None,
    experiment_id: str | None = None,
    experiment_version: str | None = None,
    x_merchant_id: str | None = Header(default=None),
) -> dict[str, Any]:
    """Read-only exposure endpoint for persisted F4 Evaluation Reports (Gap 2).

    Preserves exact persisted values without recalculating any causal estimators.
    Enforces strict tenant boundary isolation.
    """
    if x_merchant_id and merchant_id and not hmac.compare_digest(x_merchant_id, merchant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Authenticated tenant {x_merchant_id} cannot request F4 report for merchant {merchant_id}",
        )

    effective_merchant = x_merchant_id or merchant_id
    if not effective_merchant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'x-merchant-id' or query parameter 'merchant_id' is required.",
        )

    factory = request.app.state.sessions
    with factory() as session:
        stmt = select(F4EvaluationReportRecord).where(F4EvaluationReportRecord.merchant_id == effective_merchant)
        if experiment_id:
            stmt = stmt.where(F4EvaluationReportRecord.experiment_id == experiment_id)
        if experiment_version:
            stmt = stmt.where(F4EvaluationReportRecord.experiment_version == experiment_version)

        stmt = stmt.order_by(F4EvaluationReportRecord.evaluated_at.desc())
        rec = session.scalars(stmt).first()

        if rec is None:
            return {
                "status": "NOT_AVAILABLE",
                "positivity_status": None,
                "reason": "No persisted F4 evaluation report found for requested scope",
                "merchant_id": effective_merchant,
                "experiment_id": experiment_id,
                "experiment_version": experiment_version,
            }

        positivity_status = None
        if isinstance(rec.raw_report_json, dict):
            positivity_status = rec.raw_report_json.get("positivity_status")

        return {
            "report_id": rec.report_id,
            "merchant_id": rec.merchant_id,
            "experiment_id": rec.experiment_id,
            "experiment_version": rec.experiment_version,
            "status": rec.status,
            "estimand_population": rec.estimand_population,
            "allocation_proportion_p": rec.allocation_proportion_p,
            "eligible_population_count": rec.eligible_population_count,
            "observed_control_count": rec.observed_control_count,
            "observed_treatment_count": rec.observed_treatment_count,
            "point_estimate_paise_per_unit": rec.point_estimate_paise_per_unit,
            "incremental_recovered_revenue_paise": rec.incremental_recovered_revenue_paise,
            "counterfactual_control_revenue_paise": rec.counterfactual_control_revenue_paise,
            "standard_error": rec.standard_error,
            "confidence_interval_lower": rec.confidence_interval_lower,
            "confidence_interval_upper": rec.confidence_interval_upper,
            "invalidation_reasons": rec.invalidation_reasons or [],
            "positivity_status": positivity_status,
            "raw_report_json": rec.raw_report_json,
            "evaluated_at": rec.evaluated_at.isoformat() if rec.evaluated_at else None,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        }









def _verify_tenant_authorization(case: RecoveryCase, x_merchant_id: str | None) -> None:
    """Enforce strict horizontal tenant boundary isolation.

    Returns HTTP 403 Forbidden if tenant identity does not match case owner.
    """
    if case.merchant_id and x_merchant_id:
        if not hmac.compare_digest(case.merchant_id, x_merchant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Merchant {x_merchant_id} cannot access case owned by {case.merchant_id}",
            )


@eval_router.get("/cases/{case_id}/ai-reasoning", response_model=CaseAIReasoningProjection)
def get_case_ai_reasoning(
    case_id: str,
    request: Request,
    merchant_id: str | None = None,
    x_merchant_id: str | None = Header(default=None),
) -> CaseAIReasoningProjection:
    """Non-authoritative Evidence-Grounded AI Recovery Forensic Copilot endpoint.

    Enforces strict tenant boundary parameter consistency.
    """
    if x_merchant_id and merchant_id and not hmac.compare_digest(x_merchant_id, merchant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Authenticated tenant {x_merchant_id} cannot request metrics for merchant {merchant_id}",
        )

    effective_merchant = x_merchant_id or merchant_id

    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"RecoveryCase {case_id} not found"
            )

        _verify_tenant_authorization(case, effective_merchant)

        return generate_ai_reasoning(session, case_id, effective_merchant)


@eval_router.get("/cases/{case_id}", response_model=CaseEvaluationProjection)
def get_case_evaluation_projection(

    case_id: str,
    request: Request,
    x_merchant_id: str | None = Header(default=None),
) -> CaseEvaluationProjection:
    """Case-scoped read endpoint returning complete investigation projection.

    Enforces strict tenant-scoped authorization.
    """

    factory = request.app.state.sessions
    with factory() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"RecoveryCase {case_id} not found"
            )

        _verify_tenant_authorization(case, x_merchant_id)

        quality = DataQualityStatus(recovery_case=True)

        # 1. EvidenceManifest Record
        manifest_rec = session.scalars(
            select(EvidenceManifestRecord)
            .where(EvidenceManifestRecord.case_id == case_id)
            .order_by(EvidenceManifestRecord.stage1_state_version.desc())
        ).first()
        manifest_data = manifest_rec.data if manifest_rec else None
        if manifest_rec:
            quality.evidence_manifest = True

        # 2. Diagnosis Record
        diag_rec = session.scalars(
            select(DiagnosisRecord)
            .where(DiagnosisRecord.case_id == case_id)
            .order_by(DiagnosisRecord.stage1_state_version.desc())
        ).first()
        diag_data = None
        if diag_rec:
            quality.diagnosis = True
            diag_data = {
                "diagnosis_id": diag_rec.diagnosis_id,
                "diagnosis_class": diag_rec.diagnosis_class,
                "score": diag_rec.score,
                "confidence": diag_rec.confidence,
                "status": diag_rec.status,
                "engine_version": diag_rec.engine_version,
                "evidence_ids": diag_rec.evidence_ids,
                "contradiction_ids": diag_rec.contradiction_ids,
            }

        # 3. FailureDNA Record
        fp_rec = session.scalars(
            select(FailureFingerprintRecord)
            .where(FailureFingerprintRecord.case_id == case_id)
            .order_by(FailureFingerprintRecord.stage1_state_version.desc())
        ).first()
        fp_dims = fp_rec.dimensions if fp_rec else None
        temporal_dims = fp_rec.temporal_features if fp_rec else None
        if fp_rec:
            quality.failure_dna = True

        # 4. Incident & Compliance Records
        inc_rec = session.scalars(
            select(IncidentClusterRecord)
            .order_by(IncidentClusterRecord.started_at.desc())
        ).first()
        inc_data = None
        if inc_rec:
            quality.incident = True
            inc_data = {
                "incident_id": inc_rec.incident_id,
                "status": inc_rec.status,
                "affected_case_count": inc_rec.affected_case_count,
                "failure_rate_delta": inc_rec.failure_rate_delta,
                "confidence": inc_rec.incident_confidence,
                "engine_version": inc_rec.engine_version,
            }

        el_rec = session.scalars(
            select(RecoveryEligibilityRecord)
            .where(RecoveryEligibilityRecord.case_id == case_id)
            .order_by(RecoveryEligibilityRecord.stage1_state_version.desc())
        ).first()
        el_data = None
        if el_rec:
            quality.compliance = True
            el_data = {
                "eligibility_id": el_rec.eligibility_id,
                "eligibility": el_rec.eligibility,
                "attempts_remaining": el_rec.attempts_remaining,
                "advice_code": el_rec.advice_code,
                "required_delay_seconds": el_rec.required_delay_seconds,
                "ruleset_version": el_rec.ruleset_version,
            }

        # 5. RecoveryGenome Record
        gen_rec = session.scalars(
            select(RecoveryGenomeRecord)
            .where(RecoveryGenomeRecord.case_id == case_id)
            .order_by(RecoveryGenomeRecord.stage1_state_version.desc())
        ).first()
        gen_data = None
        if gen_rec:
            quality.genome = True
            gen_data = {
                "genome_id": gen_rec.genome_id,
                "schema_version": gen_rec.genome_schema_version,
                "p0_source": gen_rec.p0_snapshot,
                "p1_source": gen_rec.p1_snapshot,
                "provenance": gen_rec.source_versions,
                "assembled_at": gen_rec.assembled_at.isoformat(),
            }

        # 6. DecisionProposal Record
        prop_rec = session.scalars(
            select(DecisionProposalRecord)
            .where(DecisionProposalRecord.case_id == case_id)
            .order_by(DecisionProposalRecord.stage1_state_version.desc())
        ).first()
        prop_data = prop_rec.data if prop_rec else None
        if prop_rec:
            quality.proposal = True

        # 7. ShadowEvaluation Record
        shd_rec = session.scalars(
            select(ShadowEvaluationRecord)
            .where(ShadowEvaluationRecord.case_id == case_id)
            .order_by(ShadowEvaluationRecord.created_at.desc())
        ).first()
        shd_data = None
        if shd_rec:
            quality.shadow_evaluation = True
            shd_data = {
                "shadow_id": shd_rec.shadow_id,
                "baseline_action": shd_rec.baseline_action,
                "stage2_proposed_action": shd_rec.stage2_proposed_action,
                "baseline_outcome": shd_rec.baseline_outcome,
                "would_have_recovered_amount": shd_rec.would_have_recovered_amount,
                "decision_delta": shd_rec.decision_delta,
                "created_at": shd_rec.created_at.isoformat(),
            }

        # Action Capability Matrix (Section 25 Table)
        capability_matrix = [
            {"action": "RETRY_NOW", "capability": "AVAILABLE", "compliance": "BLOCKED" if el_rec and el_rec.eligibility == "BLOCKED" else "ELIGIBLE", "status": "BLOCKED" if el_rec and el_rec.eligibility == "BLOCKED" else "ELIGIBLE"},
            {"action": "RETRY_LATER", "capability": "AVAILABLE", "compliance": "ELIGIBLE", "status": "ELIGIBLE"},
            {"action": "ALTERNATE_RAIL", "capability": "AVAILABLE", "compliance": "ELIGIBLE", "status": "ELIGIBLE"},
            {"action": "PAYMENT_LINK", "capability": "AVAILABLE", "compliance": "ELIGIBLE", "status": "ELIGIBLE"},
            {"action": "RE_AUTH", "capability": "NOT_CAPABLE", "compliance": "—", "status": "NOT_CAPABLE"},
            {"action": "STOP", "capability": "AVAILABLE", "compliance": "ELIGIBLE", "status": "ELIGIBLE"},
        ]

        # GenAI Explanation
        genai_res = None
        if prop_data and gen_rec:
            mock_proposal = DecisionProposal.model_validate(prop_data)
            mock_genome = RecoveryGenome(
                genome_id=gen_rec.genome_id,
                case_id=case_id,
                p0_source=P0GenomeSource.model_validate(gen_rec.p0_snapshot),
                p1_source=P1GenomeSource.model_validate(gen_rec.p1_snapshot),
                provenance=gen_rec.source_versions,
            )
            genai_res = generate_genai_explanation(mock_proposal, mock_genome)

        # Build typed projection
        return CaseEvaluationProjection(
            case_id=case.case_id,
            merchant_id=case.merchant_id,
            payment_id=case.payment_id,
            order_id=case.order_id,
            amount=build_metric_value(case.amount, ValueSemantics.OBSERVED, "CURRENCY_INR", "RecoveryCase", case.schema_version),
            currency=case.currency,
            payment_rail=fp_dims.get("rail", "card") if fp_dims else "card",
            state=build_metric_value(case.state, ValueSemantics.OBSERVED, "TEXT", "PaymentState", str(case.stage1_state_version)),
            state_version=case.stage1_state_version,
            recovery_eligible=build_metric_value(case.recovery_eligible, ValueSemantics.OBSERVED, "BOOLEAN", "RecoveryCase", case.schema_version),
            evidence_manifest=manifest_data,
            diagnosis=diag_data,
            failure_dna=fp_dims,
            temporal_features=temporal_dims,
            incident=inc_data,
            compliance=el_data,
            genome=gen_data,
            action_capability_matrix=capability_matrix,
            counterfactual_simulations=prop_data.get("candidate_actions", []) if prop_data else [],
            decision_proposal=prop_data,
            shadow_evaluation=shd_data,
            genai_explanation=genai_res,
            data_quality=quality,
            provenance={
                "schema_version": case.schema_version,
                "stage1_state_version": case.stage1_state_version,
                "engine_versions": {
                    "normalizer": manifest_rec.normalizer_version if manifest_rec else "1.0",
                    "diagnosis": diag_rec.engine_version if diag_rec else "1.0",
                    "failure_dna": fp_rec.version if fp_rec else "1.0",
                    "incident": inc_rec.engine_version if inc_rec else "1.0",
                    "compliance": el_rec.ruleset_version if el_rec else "1.0",
                    "genome": gen_rec.genome_schema_version if gen_rec else "1.0",
                    "proposal": prop_rec.data.get("proposal_schema_version", "1.0") if prop_rec else "1.0",
                },
            },
        )

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PaymentState, RecoveryCase
from .stage3.models import Stage3OutcomeObservation

logger = logging.getLogger(__name__)


class CaseRevenueTrace(BaseModel):
    case_id: str
    payment_id: str
    merchant_id: str | None
    amount_paise: int
    amount_inr: float
    recovery_eligible: bool
    eligibility_reason: str
    outcome_status: str = "UNRESOLVED"
    gross_recovered_inr: float = 0.0
    net_verified_recovered_inr: float = 0.0


class UnavailableMetric(BaseModel):
    status: str = "NOT_AVAILABLE"
    reason: str
    value: Any = None


class RevenueSummary(BaseModel):
    merchant_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    case_count: int = 0
    recovered_case_count: int = 0
    revenue_at_risk_paise: int = 0
    revenue_at_risk_inr: float = 0.0
    eligible_revenue_paise: int = 0
    eligible_revenue_inr: float = 0.0
    gross_recovered_inr: float = 0.0
    net_verified_recovered_inr: float = 0.0
    unrecovered_revenue_inr: float = 0.0
    recovery_rate: float | None = None
    baseline_recovery: UnavailableMetric = Field(
        default_factory=lambda: UnavailableMetric(
            reason="No experimental control arm baseline established for selected window"
        )
    )
    incremental_recovery: UnavailableMetric = Field(
        default_factory=lambda: UnavailableMetric(
            reason="Incremental monetary recovery requires pre-registered F4 monetary conversion parameters"
        )
    )
    cases_breakdown: list[CaseRevenueTrace] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def compute_revenue_summary(
    session: Session,
    merchant_id: str | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    f4_report: Any | None = None,
) -> RevenueSummary:
    """Compute deterministic Revenue Economics summary over persisted RecoveryCases & Stage3 Outcomes.

    Guarantees strict tenant isolation when merchant_id is provided.
    Preserves exact monetary integer amounts (paise) for aggregation and converts to INR at boundary.
    Handles zero denominators, partial observations, and empty datasets gracefully.
    Guarantees at most one authoritative finalized Stage3 outcome contributes per recovery case.
    Exposes valid F4-derived baseline and incremental recovered revenue when authorized F4 evidence exists.
    """

    w_start_utc = _utc(window_start)
    w_end_utc = _utc(window_end)

    # 1. Fetch RecoveryCases for scope
    case_stmt = select(RecoveryCase)
    if merchant_id:
        case_stmt = case_stmt.where(RecoveryCase.merchant_id == merchant_id)
    if w_start_utc:
        case_stmt = case_stmt.where(RecoveryCase.first_seen_at >= w_start_utc)
    if w_end_utc:
        case_stmt = case_stmt.where(RecoveryCase.first_seen_at < w_end_utc)

    cases = session.scalars(case_stmt.order_by(RecoveryCase.first_seen_at.desc())).all()

    if not cases:
        return RevenueSummary(
            merchant_id=merchant_id,
            window_start=w_start_utc,
            window_end=w_end_utc,
            recovery_rate=None,
        )

    case_ids = [c.case_id for c in cases]

    # 2. Fetch Stage3OutcomeObservations for cases, ordered deterministically by finalized_at desc, observed_at desc
    obs_stmt = (
        select(Stage3OutcomeObservation)
        .where(Stage3OutcomeObservation.case_id.in_(case_ids))
        .order_by(
            Stage3OutcomeObservation.finalized_at.desc(),
            Stage3OutcomeObservation.observed_at.desc(),
        )
    )
    if merchant_id:
        obs_stmt = obs_stmt.where(Stage3OutcomeObservation.merchant_id == merchant_id)
    
    observations = session.scalars(obs_stmt).all()
    
    # Guarantee exactly ONE authoritative outcome observation (the latest finalized) per case_id
    obs_by_case_id: dict[str, Stage3OutcomeObservation] = {}
    for o in observations:
        if o.case_id not in obs_by_case_id:
            obs_by_case_id[o.case_id] = o

    # 3. Deterministic Revenue Aggregation
    total_case_count = len(cases)
    total_at_risk_paise = 0
    total_eligible_paise = 0
    total_gross_recovered_inr = 0.0
    total_net_verified_recovered_inr = 0.0
    recovered_case_count = 0
    traces: list[CaseRevenueTrace] = []

    for c in cases:
        amt_paise = c.amount or 0
        total_at_risk_paise += amt_paise

        if c.recovery_eligible:
            total_eligible_paise += amt_paise

        obs = obs_by_case_id.get(c.case_id)
        outcome_status = obs.outcome_status if obs else "UNRESOLVED"
        gross_rec = float(obs.gross_recovered_amount) if obs else 0.0
        net_rec = float(obs.net_verified_recovered_amount) if obs else 0.0

        if obs and outcome_status in {"RECOVERED", "PARTIALLY_RECOVERED", "SUCCESS"}:
            recovered_case_count += 1

        total_gross_recovered_inr += gross_rec
        total_net_verified_recovered_inr += net_rec

        traces.append(
            CaseRevenueTrace(
                case_id=c.case_id,
                payment_id=c.payment_id,
                merchant_id=c.merchant_id,
                amount_paise=amt_paise,
                amount_inr=amt_paise / 100.0,
                recovery_eligible=c.recovery_eligible,
                eligibility_reason=c.eligibility_reason,
                outcome_status=outcome_status,
                gross_recovered_inr=gross_rec,
                net_verified_recovered_inr=net_rec,
            )
        )

    at_risk_inr = total_at_risk_paise / 100.0
    eligible_inr = total_eligible_paise / 100.0

    net_verified_paise = int(round(total_net_verified_recovered_inr * 100.0))
    unrecovered_paise = max(0, total_eligible_paise - net_verified_paise)
    unrecovered_inr = unrecovered_paise / 100.0

    recovery_rate = (total_net_verified_recovered_inr / eligible_inr) if eligible_inr > 0 else None

    # Evaluate F4 Causal Evidence Gate for baseline_recovery & incremental_recovery
    baseline_rec = UnavailableMetric(
        reason="No experimental control arm baseline established for selected window"
    )
    incremental_rec = UnavailableMetric(
        reason="Incremental monetary recovery requires pre-registered F4 monetary conversion parameters"
    )

    if f4_report is None and merchant_id:
        try:
            from .stage2.f4.repository import get_latest_f4_report
            f4_report = get_latest_f4_report(session, merchant_id)
        except Exception:
            f4_report = None

    if f4_report is not None:
        status_val = f4_report.status.value if hasattr(f4_report.status, "value") else str(f4_report.status)
        is_valid_status = status_val == "EFFICACY_RESULT_AVAILABLE"
        has_primary = getattr(f4_report, "primary_result", None) is not None
        invalidation = getattr(f4_report, "invalidation_reasons", [])

        if is_valid_status and has_primary and not invalidation:
            p_res = f4_report.primary_result
            sec = getattr(f4_report, "secondary_metrics", None)
            p = getattr(p_res, "allocation_proportion_p", 1.0)
            n_ctrl = getattr(sec, "recovery_count_control", None) if sec else None
            n_obs = getattr(p_res, "observed_population_count", 0)
            metric_name = getattr(p_res, "primary_metric_name", "")
            point_est = getattr(p_res, "point_estimate", None)
            elig_count = getattr(p_res, "eligible_population_count", total_case_count)
            ctrl_subunits = getattr(sec, "counterfactual_control_revenue_subunits", None) if sec else None

            # Tenant isolation / scope check
            prov = getattr(f4_report, "provenance", None)
            prov_merchant = getattr(prov, "merchant_id", None) if prov else None
            tenant_match = (merchant_id is None) or (prov_merchant is None) or (merchant_id == prov_merchant)

            if (
                p < 1.0 and
                n_ctrl is not None and n_ctrl > 0 and
                n_obs > 0 and
                metric_name == "VERIFIED_INCREMENTAL_RECOVERED_REVENUE" and
                point_est is not None and
                ctrl_subunits is not None and
                tenant_match
            ):
                total_inc_paise = float(point_est) * float(elig_count)
                inc_inr = round(total_inc_paise / 100.0, 2)
                base_inr = round(float(ctrl_subunits) / 100.0, 2)

                baseline_rec = UnavailableMetric(
                    status="AVAILABLE",
                    reason="Counterfactual control arm baseline verified from F4 IPW evaluation",
                    value=base_inr,
                )
                incremental_rec = UnavailableMetric(
                    status="AVAILABLE",
                    reason="Verified incremental revenue calculated from F4 IPW point estimate",
                    value=inc_inr,
                )

    return RevenueSummary(
        merchant_id=merchant_id,
        window_start=w_start_utc,
        window_end=w_end_utc,
        case_count=total_case_count,
        recovered_case_count=recovered_case_count,
        revenue_at_risk_paise=total_at_risk_paise,
        revenue_at_risk_inr=at_risk_inr,
        eligible_revenue_paise=total_eligible_paise,
        eligible_revenue_inr=eligible_inr,
        gross_recovered_inr=total_gross_recovered_inr,
        net_verified_recovered_inr=total_net_verified_recovered_inr,
        unrecovered_revenue_inr=unrecovered_inr,
        recovery_rate=recovery_rate,
        baseline_recovery=baseline_rec,
        incremental_recovery=incremental_rec,
        cases_breakdown=traces,
    )


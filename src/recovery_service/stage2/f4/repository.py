"""F4 Evaluation Report Repository module.

Provides database persistence and retrieval for F4EvaluationReport objects in PostgreSQL/SQLite.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import F4EvaluationReportRecord
from .contracts import EvaluationStatus, F4EvaluationReport


def save_f4_report(session: Session, report: F4EvaluationReport) -> F4EvaluationReportRecord:
    """Save or update an F4EvaluationReport in the database."""
    merchant_id = report.provenance.merchant_id
    experiment_id = report.provenance.experiment_id
    experiment_version = report.provenance.experiment_version

    # Check for existing record
    existing = session.execute(
        select(F4EvaluationReportRecord).where(
            F4EvaluationReportRecord.merchant_id == merchant_id,
            F4EvaluationReportRecord.experiment_id == experiment_id,
            F4EvaluationReportRecord.experiment_version == experiment_version,
        )
    ).scalar_one_or_none()

    point_est = report.primary_result.point_estimate if report.primary_result else None
    eligible_count = report.primary_result.eligible_population_count if report.primary_result else report.accounting.observed_control + report.accounting.observed_treatment
    inc_paise = round(point_est * eligible_count) if point_est is not None else None
    ctrl_paise = report.secondary_metrics.counterfactual_control_revenue_subunits

    raw_json = report.model_dump(mode="json")

    if existing is not None:
        existing.status = report.status.value if isinstance(report.status, EvaluationStatus) else str(report.status)
        existing.allocation_proportion_p = report.primary_result.allocation_proportion_p if report.primary_result else 0.5
        existing.eligible_population_count = eligible_count
        existing.observed_control_count = report.accounting.observed_control
        existing.observed_treatment_count = report.accounting.observed_treatment
        existing.point_estimate_paise_per_unit = point_est
        existing.incremental_recovered_revenue_paise = inc_paise
        existing.counterfactual_control_revenue_paise = ctrl_paise
        existing.invalidation_reasons = list(report.invalidation_reasons)
        existing.raw_report_json = raw_json
        existing.evaluated_at = report.provenance.evaluated_at
        session.flush()
        return existing

    record = F4EvaluationReportRecord(
        report_id=f"f4_rep_{uuid.uuid4().hex[:16]}",
        merchant_id=merchant_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        status=report.status.value if isinstance(report.status, EvaluationStatus) else str(report.status),
        estimand_population=report.primary_result.estimand_population.value if report.primary_result else "PRE_REGISTERED_ELIGIBLE",
        allocation_proportion_p=report.primary_result.allocation_proportion_p if report.primary_result else 0.5,
        eligible_population_count=eligible_count,
        observed_control_count=report.accounting.observed_control,
        observed_treatment_count=report.accounting.observed_treatment,
        point_estimate_paise_per_unit=point_est,
        incremental_recovered_revenue_paise=inc_paise,
        counterfactual_control_revenue_paise=ctrl_paise,
        standard_error=report.primary_result.uncertainty.standard_error if report.primary_result else None,
        confidence_interval_lower=report.primary_result.uncertainty.confidence_interval_lower if report.primary_result else None,
        confidence_interval_upper=report.primary_result.uncertainty.confidence_interval_upper if report.primary_result else None,
        invalidation_reasons=list(report.invalidation_reasons),
        raw_report_json=raw_json,
        evaluated_at=report.provenance.evaluated_at,
    )
    session.add(record)
    session.flush()
    return record


def get_latest_f4_report(
    session: Session,
    merchant_id: str,
    experiment_id: str | None = None,
    experiment_version: str | None = None,
) -> F4EvaluationReport | None:
    """Retrieve latest F4EvaluationReport for merchant_id from database."""
    stmt = select(F4EvaluationReportRecord).where(F4EvaluationReportRecord.merchant_id == merchant_id)
    if experiment_id:
        stmt = stmt.where(F4EvaluationReportRecord.experiment_id == experiment_id)
    if experiment_version:
        stmt = stmt.where(F4EvaluationReportRecord.experiment_version == experiment_version)

    stmt = stmt.order_by(F4EvaluationReportRecord.evaluated_at.desc())
    record = session.execute(stmt).scalars().first()

    if record is None:
        return None

    try:
        return F4EvaluationReport.model_validate(record.raw_report_json)
    except Exception:
        return None

"""F4-3 Causal Evaluation Lifecycle & Safety Engine.

Enforces deterministic lifecycle state transitions and safety precedence over F4-2 causal
estimation outputs. Strictly separates computation (F4-2) from judgment (F4-3).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    EvaluationStatus,
    F4EvaluationReport,
)
from .estimator import EstimatorDiagnosticResult


def is_case_attribution_complete(
    attribution_window_start: datetime | None,
    current_time: datetime | None = None,
    required_hours: float = 72.0,
) -> bool:
    """Determines if attribution window is complete for a single recovery case.

    Requires explicit timezone-aware per-case attribution_window_start.
    Missing/invalid timestamp -> returns False (fails safe).
    Formula: current_time >= attribution_window_start + 72 hours.
    """
    if attribution_window_start is None:
        return False
    now = current_time or datetime.now(timezone.utc)
    start_utc = attribution_window_start if attribution_window_start.tzinfo is not None else attribution_window_start.replace(tzinfo=timezone.utc)
    now_utc = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return now_utc >= start_utc + timedelta(hours=required_hours)


def evaluate_batch_attribution_completion(
    window_starts: list[datetime | None],
    current_time: datetime | None = None,
    required_hours: float = 72.0,
) -> bool:
    """Evaluates batch attribution window completion across all cases in evaluation pool.

    Returns True ONLY if ALL cases in the evaluation pool have complete attribution windows.
    Empty batch or any missing/incomplete timestamp -> returns False (fails safe).
    """
    if not window_starts:
        return False
    return all(
        is_case_attribution_complete(start, current_time=current_time, required_hours=required_hours)
        for start in window_starts
    )


class LifecycleConfig(BaseModel):
    """Configuration rules for F4-3 lifecycle judgment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attrition_gap_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    min_observed_outcome_ratio: float = Field(default=0.10, ge=0.0, le=1.0)
    max_pending_unknown_ratio: float = Field(default=0.50, ge=0.0, le=1.0)
    attribution_window_hours: float = Field(default=72.0, gt=0.0)
    require_attribution_window_complete: bool = True
    treat_positivity_failure_as_invalidation: bool = False
    treat_weight_instability_as_invalidation: bool = False


class F4EvaluationLifecycleEngine:
    """Deterministic judgment engine evaluating F4-2 causal outputs against lifecycle and safety rules."""

    @staticmethod
    def judge(
        report: F4EvaluationReport,
        diagnostics: EstimatorDiagnosticResult | None = None,
        config: LifecycleConfig | None = None,
        *,
        safety_breach_detected: bool = False,
        attribution_window_complete: bool | None = None,
        primary_metric_data_loss_detected: bool = False,
    ) -> F4EvaluationReport:
        """Evaluate input report and diagnostics against decision precedence rules."""
        if config is None:
            config = LifecycleConfig()

        invalidation_reasons: list[str] = list(report.invalidation_reasons)

        # PRECEDENCE 1: VERSION INCONSISTENCY
        if diagnostics is not None and not diagnostics.version_consistency_valid:
            if "VERSION_CONSISTENCY_VIOLATION" not in invalidation_reasons:
                invalidation_reasons.append("VERSION_CONSISTENCY_VIOLATION")
            return report.model_copy(
                update={
                    "status": EvaluationStatus.VERSION_INCONSISTENCY,
                    "invalidation_reasons": invalidation_reasons,
                }
            )

        # PRECEDENCE 2: EXPERIMENT INVALIDATION
        is_invalidated = False

        if report.status == EvaluationStatus.EXPERIMENT_INVALIDATED:
            is_invalidated = True

        if primary_metric_data_loss_detected:
            is_invalidated = True
            if "PRIMARY_METRIC_DATA_LOSS" not in invalidation_reasons:
                invalidation_reasons.append("PRIMARY_METRIC_DATA_LOSS")

        if diagnostics is not None:
            if not diagnostics.tenant_isolation_valid:
                is_invalidated = True
                if "TENANT_ISOLATION_VIOLATION" not in invalidation_reasons:
                    invalidation_reasons.append("TENANT_ISOLATION_VIOLATION")

            if config.treat_positivity_failure_as_invalidation and diagnostics.positivity_failed:
                is_invalidated = True
                if "POSITIVITY_VIOLATION_INVALIDATION" not in invalidation_reasons:
                    invalidation_reasons.append("POSITIVITY_VIOLATION_INVALIDATION")

            if config.treat_weight_instability_as_invalidation and diagnostics.weight_instability_detected:
                is_invalidated = True
                if "WEIGHT_INSTABILITY_INVALIDATION" not in invalidation_reasons:
                    invalidation_reasons.append("WEIGHT_INSTABILITY_INVALIDATION")

        if is_invalidated:
            return report.model_copy(
                update={
                    "status": EvaluationStatus.EXPERIMENT_INVALIDATED,
                    "invalidation_reasons": invalidation_reasons,
                }
            )

        # PRECEDENCE 3: SAFETY STOPPED (Safety stopping takes precedence over Efficacy & Data Sufficiency)
        if safety_breach_detected:
            if "SAFETY_CRITERIA_BREACH_DETECTED" not in invalidation_reasons:
                invalidation_reasons.append("SAFETY_CRITERIA_BREACH_DETECTED")

            return report.model_copy(
                update={
                    "status": EvaluationStatus.SAFETY_STOPPED,
                    "invalidation_reasons": invalidation_reasons,
                }
            )

        # PRECEDENCE 4: INSUFFICIENT DATA FOR EFFICACY CLAIM
        insufficient_reasons: list[str] = []

        # Safe attribution window completion check (cannot default to True)
        if config.require_attribution_window_complete:
            if attribution_window_complete is not True:
                insufficient_reasons.append("ATTRIBUTION_WINDOW_INCOMPLETE")

        acct = report.accounting
        N_assigned = acct.total_assigned_control + acct.total_assigned_treatment
        N_observed = acct.observed_control + acct.observed_treatment
        N_pending_unknown = (
            acct.pending_control + acct.pending_treatment + acct.unknown_control + acct.unknown_treatment
        )

        obs_ratio = N_observed / max(1, N_assigned)
        if obs_ratio < config.min_observed_outcome_ratio:
            insufficient_reasons.append(f"INSUFFICIENT_OBSERVED_OUTCOMES_RATIO ({obs_ratio:.4f} < {config.min_observed_outcome_ratio})")

        pu_ratio = N_pending_unknown / max(1, N_assigned)
        if pu_ratio > config.max_pending_unknown_ratio:
            insufficient_reasons.append(f"EXCESSIVE_PENDING_UNKNOWN_OUTCOMES_RATIO ({pu_ratio:.4f} > {config.max_pending_unknown_ratio})")

        attr = report.differential_attrition
        if attr.attrition_gap > config.max_attrition_gap_threshold:
            insufficient_reasons.append(
                f"DIFFERENTIAL_ATTRITION_BREACHED ({attr.attrition_gap:.4f} > {config.max_attrition_gap_threshold})"
            )

        # Efficacy-blocking Positivity & Weight Instability Diagnostics (Default Behavior)
        if diagnostics is not None:
            if diagnostics.positivity_failed and not config.treat_positivity_failure_as_invalidation:
                insufficient_reasons.append("POSITIVITY_DIAGNOSTIC_FAILED")

            if diagnostics.weight_instability_detected and not config.treat_weight_instability_as_invalidation:
                insufficient_reasons.append("WEIGHT_INSTABILITY_DIAGNOSTIC_FAILED")

        if report.primary_result is None or report.primary_result.uncertainty is None:
            insufficient_reasons.append("UNCERTAINTY_METRIC_UNAVAILABLE")

        if insufficient_reasons:
            all_reasons = invalidation_reasons + insufficient_reasons
            return report.model_copy(
                update={
                    "status": EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM,
                    "invalidation_reasons": all_reasons,
                }
            )

        return report.model_copy(
            update={
                "status": EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
                "invalidation_reasons": invalidation_reasons,
            }
        )

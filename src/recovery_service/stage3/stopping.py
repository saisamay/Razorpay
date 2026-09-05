from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .schemas import StoppingDecision

logger = logging.getLogger(__name__)

DEFAULT_RECOVERY_WINDOW_HOURS = 72.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_stopping_rules(
    *,
    episode_status: str,
    current_attempt_number: int,
    max_attempts: int = 3,
    first_failure_at: datetime | None = None,
    current_time: datetime | None = None,
    latest_outcome_status: str | None = None,
    compliance_advice_code: str | None = None,
    expected_net_value: float | None = None,
    f5_enforcement_decision: str | None = None,
    incident_active: bool = False,
    escalation_active: bool = False,
    recovery_eligible: bool = True,
    recovery_window_hours: float = DEFAULT_RECOVERY_WINDOW_HOURS,
) -> StoppingDecision:
    """Evaluates deterministic stopping rules for a recovery episode.

    AI output MUST NOT determine should_stop.
    Stopping decisions are strictly deterministic based on payment state, F5 governance,
    compliance rules, attempt limits, recovery time windows, and incident signals.
    """
    now = current_time or utc_now()

    # 1. ESCALATION_LOCKOUT: Once episode is ESCALATED, no automated attempt is permitted
    if escalation_active or episode_status == "ESCALATED":
        return StoppingDecision(
            should_stop=True,
            reason_code="ESCALATION_LOCKOUT",
            explanation="Recovery episode is currently escalated to operator review; automated attempts are locked out.",
            authoritative_source="STAGE3_ORCHESTRATOR",
            target_status="ESCALATED",
        )

    # 2. ALREADY TERMINAL: If episode is already RECOVERED or STOPPED
    if episode_status in {"RECOVERED", "STOPPED"}:
        return StoppingDecision(
            should_stop=True,
            reason_code=f"EPISODE_ALREADY_{episode_status}",
            explanation=f"Recovery episode is already in terminal state '{episode_status}'.",
            authoritative_source="STAGE3_ORCHESTRATOR",
            target_status=episode_status,
        )

    # 3. PAYMENT_RECOVERED: Authoritative outcome indicates recovery
    if latest_outcome_status in {"RECOVERED", "PARTIALLY_RECOVERED", "SUCCESS"}:
        return StoppingDecision(
            should_stop=True,
            reason_code="PAYMENT_RECOVERED",
            explanation=f"Authoritative Stage 3 outcome confirms payment recovery ({latest_outcome_status}).",
            authoritative_source="STAGE3_OUTCOME_OBSERVATION",
            target_status="RECOVERED",
        )

    # 4. COMPLIANCE INELIGIBILITY / PERMANENT FAILURE
    if not recovery_eligible or compliance_advice_code in {"HARD_DECLINE_DO_NOT_RETRY", "INELIGIBLE", "FRAUD_SUSPECTED"}:
        return StoppingDecision(
            should_stop=True,
            reason_code="PERMANENT_FAILURE",
            explanation=f"Payment is ineligible for automated recovery (compliance advice: {compliance_advice_code}).",
            authoritative_source="STAGE2_COMPLIANCE",
            target_status="STOPPED",
        )

    if latest_outcome_status in {"PERMANENT_FAILURE", "UNRECOVERABLE", "EXPIRED_CARD"}:
        return StoppingDecision(
            should_stop=True,
            reason_code="PERMANENT_FAILURE",
            explanation=f"Authoritative outcome confirmed permanent unrecoverable failure ({latest_outcome_status}).",
            authoritative_source="STAGE3_OUTCOME_OBSERVATION",
            target_status="STOPPED",
        )

    # 5. MAX_ATTEMPTS_REACHED
    if current_attempt_number >= max_attempts:
        return StoppingDecision(
            should_stop=True,
            reason_code="MAX_ATTEMPTS_REACHED",
            explanation=f"Maximum recovery attempts reached ({current_attempt_number}/{max_attempts}).",
            authoritative_source="STAGE3_ORCHESTRATOR",
            target_status="STOPPED",
        )

    # 6. RECOVERY_WINDOW_EXPIRED
    if first_failure_at is not None:
        t_first = first_failure_at if first_failure_at.tzinfo is not None else first_failure_at.replace(tzinfo=timezone.utc)
        elapsed_hours = (now - t_first).total_seconds() / 3600.0
        if elapsed_hours > recovery_window_hours:
            return StoppingDecision(
                should_stop=True,
                reason_code="RECOVERY_WINDOW_EXPIRED",
                explanation=f"Recovery window expired ({elapsed_hours:.1f}h > {recovery_window_hours}h).",
                authoritative_source="STAGE3_ORCHESTRATOR",
                target_status="STOPPED",
            )

    # 7. NON_POSITIVE_EXPECTED_NET_VALUE
    if expected_net_value is not None and expected_net_value <= 0.0:
        return StoppingDecision(
            should_stop=True,
            reason_code="NON_POSITIVE_EXPECTED_NET_VALUE",
            explanation=f"Expected net recovery value is non-positive ({expected_net_value:.2f} <= 0.0).",
            authoritative_source="STAGE2_DECISION_PROPOSAL",
            target_status="STOPPED",
        )

    # 8. F5_GOVERNANCE_DENIAL
    if f5_enforcement_decision in {"DENY_ACTION", "FALLBACK_TO_BASELINE", "FAIL_CLOSED"}:
        return StoppingDecision(
            should_stop=True,
            reason_code="F5_GOVERNANCE_DENIAL",
            explanation=f"F5 policy enforcement denied action execution ({f5_enforcement_decision}).",
            authoritative_source="F5_DECISION_ENGINE",
            target_status="STOPPED",
        )

    # 9. ACTIVE_SYSTEMIC_INCIDENT
    if incident_active:
        return StoppingDecision(
            should_stop=True,
            reason_code="ACTIVE_SYSTEMIC_INCIDENT",
            explanation="Active systemic incident affecting payment rail; automated attempt paused/escalated.",
            authoritative_source="STAGE2_INCIDENT_CLUSTERER",
            target_status="ESCALATED",
        )

    # NO STOPPING RULE TRIGGERED: Episode may proceed with next attempt
    return StoppingDecision(
        should_stop=False,
        reason_code="CONTINUE_ATTEMPT",
        explanation=f"All stopping rules satisfied; attempt {current_attempt_number + 1} permitted.",
        authoritative_source="STAGE3_ORCHESTRATOR",
        target_status="IN_PROGRESS",
    )

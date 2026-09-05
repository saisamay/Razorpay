from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AuditLogEntry, RecoveryCase
from ..stage2.ai_reasoner import generate_ai_reasoning
from ..stage2.consumer import process_p1_pipeline
from ..stage2.f5.enforcement import F5RealtimeEnforcer
from ..stage2.models import CaseAssignmentLinkRecord, Stage2Case

from ..stage2.schemas import RecoveryCaseContract
from .escalation import create_escalation
from .models import RecoveryAttemptRecord, RecoveryOrchestrationRecord, Stage3OutcomeObservation
from .schemas import EpisodeStatus, StoppingDecision
from .stopping import evaluate_stopping_rules

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _log_audit(
    session: Session,
    *,
    operation: str,
    case_id: str,
    payment_id: str | None = None,
    merchant_id: str | None = None,
    details: dict[str, Any],
) -> None:
    audit = AuditLogEntry(
        operation=operation,
        payment_id=payment_id,
        actor="stage3_orchestrator",
        timestamp=utc_now(),
        details={
            "case_id": case_id,
            "merchant_id": merchant_id,
            **details,
        },
    )
    session.add(audit)


def create_or_get_orchestration(
    session: Session, case_id: str, max_attempts: int = 3
) -> RecoveryOrchestrationRecord:
    """Gets existing RecoveryOrchestrationRecord or creates a new one idempotently."""

    case = session.get(RecoveryCase, case_id)
    if case is None:
        raise ValueError(f"RecoveryCase '{case_id}' not found.")

    existing = session.scalars(
        select(RecoveryOrchestrationRecord).where(RecoveryOrchestrationRecord.case_id == case_id).with_for_update()
    ).first()
    if existing is not None:
        return existing

    now = utc_now()
    orch = RecoveryOrchestrationRecord(
        orchestration_id=f"orch_{uuid4().hex[:16]}",
        case_id=case.case_id,
        payment_id=case.payment_id,
        merchant_id=case.merchant_id or "UNKNOWN",
        recovery_episode_id=case.recovery_episode_id,
        current_attempt_number=0,
        max_attempts=max_attempts,
        episode_status="PENDING",
        current_attempt_status="NONE",
        total_net_recovered_amount=0.0,
        first_failure_at=case.first_seen_at or now,
        created_at=now,
        updated_at=now,
    )
    session.add(orch)
    _log_audit(
        session,
        operation="ORCHESTRATION_CREATED",
        case_id=case_id,
        payment_id=case.payment_id,
        merchant_id=case.merchant_id,
        details={"orchestration_id": orch.orchestration_id, "max_attempts": max_attempts},
    )
    return orch


def advance_recovery_episode(
    session: Session, case_id: str, *, worker_id: str | None = None, current_time: datetime | None = None
) -> RecoveryOrchestrationRecord:
    """Advances recovery episode by evaluating stopping rules and triggering the next attempt if eligible."""

    orch = create_or_get_orchestration(session, case_id)

    # If episode is already in a terminal state, return directly
    if orch.episode_status in {"RECOVERED", "STOPPED", "ESCALATED"}:
        return orch

    case = session.get(RecoveryCase, case_id)
    recovery_eligible = case.recovery_eligible if case else False
    compliance_advice = case.eligibility_reason if case else "UNKNOWN"

    # Evaluate deterministic stopping rules
    decision: StoppingDecision = evaluate_stopping_rules(
        episode_status=orch.episode_status,
        current_attempt_number=orch.current_attempt_number,
        max_attempts=orch.max_attempts,
        first_failure_at=orch.first_failure_at,
        current_time=current_time,
        latest_outcome_status=orch.last_outcome_status,
        compliance_advice_code=compliance_advice,
        f5_enforcement_decision=None,
        recovery_eligible=recovery_eligible,
    )

    if decision.should_stop:
        now = current_time or utc_now()
        if decision.target_status == "ESCALATED":
            create_escalation(
                session,
                orchestration_id=orch.orchestration_id,
                case_id=case_id,
                merchant_id=orch.merchant_id,
                reason_code=decision.reason_code,
            )
            orch.episode_status = "ESCALATED"
            orch.stopping_reason = decision.reason_code
        else:
            orch.episode_status = decision.target_status
            orch.stopping_reason = decision.reason_code

        orch.updated_at = now
        _log_audit(
            session,
            operation="EPISODE_STOPPED",
            case_id=case_id,
            payment_id=orch.payment_id,
            merchant_id=orch.merchant_id,
            details={
                "reason_code": decision.reason_code,
                "target_status": decision.target_status,
                "explanation": decision.explanation,
            },
        )
        return orch

    # Not stopping: start next attempt
    orch, _ = start_attempt(session, case_id, worker_id=worker_id, current_time=current_time)
    return orch


def start_attempt(
    session: Session, case_id: str, *, worker_id: str | None = None, current_time: datetime | None = None
) -> tuple[RecoveryOrchestrationRecord, RecoveryAttemptRecord | None]:
    """Executes a single recovery attempt through Stage 2 -> AI Reasoner -> F4 -> F5 Dispatch."""

    orch = create_or_get_orchestration(session, case_id)

    if orch.episode_status in {"RECOVERED", "STOPPED", "ESCALATED"}:
        raise ValueError(f"Cannot start attempt for episode in terminal status '{orch.episode_status}'.")

    if orch.episode_status == "AWAITING_OUTCOME":
        active_attempt = session.scalars(
            select(RecoveryAttemptRecord)
            .where(
                RecoveryAttemptRecord.case_id == case_id,
                RecoveryAttemptRecord.attempt_number == orch.current_attempt_number,
            )
            .with_for_update()
        ).first()
        if active_attempt is not None:
            return orch, active_attempt

    next_attempt_number = orch.current_attempt_number + 1
    if next_attempt_number > orch.max_attempts:
        orch.episode_status = "STOPPED"
        orch.stopping_reason = "MAX_ATTEMPTS_REACHED"
        return orch, None

    # Idempotency & Concurrency Check: Check if attempt number already exists
    existing_attempt = session.scalars(
        select(RecoveryAttemptRecord)
        .where(RecoveryAttemptRecord.case_id == case_id, RecoveryAttemptRecord.attempt_number == next_attempt_number)
        .with_for_update()
    ).first()
    if existing_attempt is not None:
        return orch, existing_attempt

    case = session.get(RecoveryCase, case_id, with_for_update=True)
    if case is None:
        raise ValueError(f"RecoveryCase '{case_id}' not found.")

    contract = RecoveryCaseContract(
        case_id=case.case_id,
        payment_id=case.payment_id,
        recovery_episode_id=case.recovery_episode_id,
        merchant_id=case.merchant_id or "UNKNOWN",
        order_id=case.order_id,
        amount=case.amount,
        currency=case.currency or "INR",
        state=case.state,
        state_confidence=case.state_confidence,
        failure_evidence=case.failure_evidence,
        recovery_eligible=case.recovery_eligible,
        eligibility_reason=case.eligibility_reason,
        schema_version=case.schema_version,
        source_event_ids=case.source_event_ids,
        stage1_state_version=case.stage1_state_version,
        first_seen_at=case.first_seen_at,
        last_seen_at=case.last_seen_at,
    )

    # 1. Execute Stage 2 P1 Pipeline
    genome, proposal, shadow_eval = process_p1_pipeline(session, contract, worker_id=worker_id)

    # 2. Invoke Step 2 / Step 2.1 AI Reasoning & Case Memory Lookup (Selective OpenAI)
    try:
        generate_ai_reasoning(session, case_id, contract.merchant_id)
    except Exception as exc:
        logger.warning(f"AI Reasoning non-fatal warning during attempt: {exc}")

    # 3. F5 Governance & Enforcement Realtime Gate
    enforcer = F5RealtimeEnforcer()
    link_rec = session.scalars(
        select(CaseAssignmentLinkRecord).where(CaseAssignmentLinkRecord.case_id == case_id)
    ).first()
    exp_id = link_rec.experiment_id if link_rec else "EXP_DEFAULT"
    exp_version = link_rec.experiment_version if link_rec else "1.0"
    config_hash = "a" * 64

    if link_rec and link_rec.assignment_id:
        from ..stage2.models import ExperimentAssignmentRecord
        asgn_rec = session.get(ExperimentAssignmentRecord, link_rec.assignment_id)
        if asgn_rec and asgn_rec.configuration_hash:
            config_hash = asgn_rec.configuration_hash

    from ..stage2.models import DecisionPolicyRecord
    pol_rec = session.scalars(
        select(DecisionPolicyRecord).where(
            DecisionPolicyRecord.merchant_id == contract.merchant_id,
            DecisionPolicyRecord.status.in_(["ACTIVE", "ACTIVE_ENFORCED"]),
        )
    ).first()
    if pol_rec:
        exp_id = pol_rec.experiment_id
        exp_version = pol_rec.experiment_version
        config_hash = pol_rec.approved_configuration_hash

    attr_start_time = (case.first_seen_at or now) - timedelta(hours=73)

    f5_res = enforcer.enforce_and_dispatch(
        session,
        case_id=case_id,
        proposal_id=proposal.proposal_id,
        merchant_id=contract.merchant_id,
        experiment_id=exp_id,
        experiment_version=exp_version,
        current_configuration_hash=config_hash,
        stage2_proposed_action=proposal.selected_action,
        attribution_start_time=attr_start_time,
        worker_id=worker_id,
    )

    now = current_time or utc_now()
    attempt_id = f"att_{uuid4().hex[:16]}"
    attempt = RecoveryAttemptRecord(
        attempt_id=attempt_id,
        orchestration_id=orch.orchestration_id,
        case_id=case_id,
        merchant_id=contract.merchant_id,
        attempt_number=next_attempt_number,
        proposed_action=proposal.selected_action,
        executed_action=f5_res.executed_action,
        proposal_id=proposal.proposal_id,
        enforcement_id=f5_res.enforcement_log_id,
        enforcement_decision=f5_res.decision.value,
        status="DISPATCHED" if f5_res.decision.value == "ALLOW_ACTION" else "DENIED",
        started_at=now,
    )
    session.add(attempt)

    # Update Orchestration Record
    orch.current_attempt_number = next_attempt_number
    orch.selected_action = f5_res.executed_action
    orch.proposal_id = proposal.proposal_id
    orch.enforcement_id = f5_res.enforcement_log_id
    orch.current_attempt_status = attempt.status
    orch.updated_at = now

    if f5_res.decision.value == "ALLOW_ACTION":
        orch.episode_status = "AWAITING_OUTCOME"
    else:
        # F5 denied action execution $\rightarrow$ evaluate stopping rule
        orch.episode_status = "STOPPED"
        orch.stopping_reason = f"F5_{f5_res.decision.value}"

    _log_audit(
        session,
        operation="ATTEMPT_DISPATCHED",
        case_id=case_id,
        payment_id=orch.payment_id,
        merchant_id=orch.merchant_id,
        details={
            "attempt_number": next_attempt_number,
            "proposed_action": proposal.selected_action,
            "executed_action": f5_res.executed_action,
            "f5_decision": f5_res.decision.value,
            "episode_status": orch.episode_status,
        },
    )

    return orch, attempt


def handle_outcome(
    session: Session, observation: Stage3OutcomeObservation
) -> RecoveryOrchestrationRecord | None:
    """Processes authoritative Stage 3 outcome observation and advances orchestration state."""

    orch = session.scalars(
        select(RecoveryOrchestrationRecord)
        .where(RecoveryOrchestrationRecord.case_id == observation.case_id)
        .with_for_update()
    ).first()
    if orch is None:
        return None

    now = utc_now()

    session.merge(observation)

    # Update latest attempt record if present
    attempt = session.scalars(
        select(RecoveryAttemptRecord)
        .where(
            RecoveryAttemptRecord.case_id == observation.case_id,
            RecoveryAttemptRecord.attempt_number == orch.current_attempt_number,
        )
        .with_for_update()
    ).first()

    if attempt is not None and attempt.status != "COMPLETED":
        attempt.outcome_status = observation.outcome_status
        attempt.net_recovered_amount = observation.net_verified_recovered_amount
        attempt.status = "COMPLETED"
        attempt.completed_at = observation.finalized_at or now

        orch.last_outcome_status = observation.outcome_status
        orch.total_net_recovered_amount += observation.net_verified_recovered_amount
        orch.updated_at = now

    # Re-evaluate stopping rules after receiving outcome
    case = session.get(RecoveryCase, observation.case_id)
    recovery_eligible = case.recovery_eligible if case else False
    compliance_advice = case.eligibility_reason if case else "UNKNOWN"

    decision: StoppingDecision = evaluate_stopping_rules(
        episode_status=orch.episode_status,
        current_attempt_number=orch.current_attempt_number,
        max_attempts=orch.max_attempts,
        first_failure_at=orch.first_failure_at,
        current_time=now,
        latest_outcome_status=observation.outcome_status,
        compliance_advice_code=compliance_advice,
        recovery_eligible=recovery_eligible,
    )

    if decision.should_stop:
        if decision.target_status == "ESCALATED":
            create_escalation(
                session,
                orchestration_id=orch.orchestration_id,
                case_id=observation.case_id,
                merchant_id=orch.merchant_id,
                reason_code=decision.reason_code,
            )
            orch.episode_status = "ESCALATED"
            orch.stopping_reason = decision.reason_code
        else:
            orch.episode_status = decision.target_status
            orch.stopping_reason = decision.reason_code
    else:
        # Not stopping: reset status to PENDING so next worker loop can attempt retry
        orch.episode_status = "PENDING"

    _log_audit(
        session,
        operation="OUTCOME_HANDLED",
        case_id=observation.case_id,
        payment_id=orch.payment_id,
        merchant_id=orch.merchant_id,
        details={
            "outcome_status": observation.outcome_status,
            "net_recovered_amount": observation.net_verified_recovered_amount,
            "new_episode_status": orch.episode_status,
            "stopping_reason": orch.stopping_reason,
        },
    )

    return orch

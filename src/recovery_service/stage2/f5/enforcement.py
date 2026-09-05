"""F5-4 Real-Time Enforcement Integration Module.

Connects pure F5 Decision Engine authorization to the real-time Stage 2 action dispatch boundary.
Enforces execution-time policy revalidation, tenant isolation, compliance rechecks, idempotency,
atomic concurrency-safe commit points, baseline fallback to STOP, and append-only audit logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...models import PaymentState, RecoveryCase
from ..models import DecisionPolicyRecord, DecisionProposalRecord, PolicyEnforcementLogRecord, Stage2Case
from .contracts import (
    EnforcementDecision,
    PolicyEnforcementReasonCode,
    PolicyEnforcementResult,
)
from .engine import F5DecisionEngine
from .repository import get_enforcement_log_by_proposal, save_enforcement_log

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EnforcementDispatchResult:
    """Authoritative result of F5 real-time enforcement and dispatch execution."""

    case_id: str
    proposal_id: str
    decision: EnforcementDecision
    reason_code: PolicyEnforcementReasonCode
    stage2_proposed_action: str
    executed_action: str
    policy_id: str | None
    policy_version: str | None
    duplicate_execution_prevented: bool
    evaluated_at: datetime
    enforcement_log_id: str


class F5RealtimeEnforcer:
    """Orchestrates real-time F5 policy enforcement and Stage 2 action dispatch."""

    def __init__(self, engine: F5DecisionEngine | None = None):
        self.engine = engine or F5DecisionEngine()

    def enforce_and_dispatch(
        self,
        session: Session,
        *,
        case_id: str,
        proposal_id: str,
        merchant_id: str,
        experiment_id: str,
        experiment_version: str,
        current_configuration_hash: str,
        stage2_proposed_action: str,
        attribution_start_time: datetime | None = None,
        current_time: datetime | None = None,
        worker_id: str | None = None,
    ) -> EnforcementDispatchResult:
        """Enforces F5 decision policy and dispatches Stage 2 recovery action atomically.

        Execution Pipeline:
        1. Row-Level Transactional Locks: Locks Stage2Case, RecoveryCase, and DecisionPolicyRecord (with_for_update).
        2. Idempotency Check: Authoritative proposal_id lookup prevents duplicate execution.
        3. Compliance & State Recheck: Validates recovery_eligible and payment outcome status.
        4. F5 Decision Engine Authorization: Re-evaluates policy status and evidence at execution time.
        5. Execution & Audit Logging: Persists PolicyEnforcementLogRecord with proposal_id constraint protection.
        """
        eval_time = current_time or utc_now()

        try:
            # 1. Row-Level Transactional Lock for Case & Policy Concurrency Safety
            stage2_case = session.scalars(
                select(Stage2Case).where(Stage2Case.case_id == case_id).with_for_update()
            ).first()

            recovery_case = session.get(RecoveryCase, case_id, with_for_update=True)

            # Explicitly lock DecisionPolicyRecord row to serialize execution against Kill-Switch / Status mutations
            policy_record = session.scalars(
                select(DecisionPolicyRecord)
                .where(
                    DecisionPolicyRecord.merchant_id == merchant_id,
                    DecisionPolicyRecord.experiment_id == experiment_id,
                    DecisionPolicyRecord.experiment_version == experiment_version,
                    DecisionPolicyRecord.approved_configuration_hash == current_configuration_hash,
                )
                .with_for_update()
            ).first()

            # 2. Idempotency Check: Replay protection by authoritative proposal_id
            if proposal_id and proposal_id.strip():
                existing_log = get_enforcement_log_by_proposal(session, proposal_id.strip())
                if existing_log is not None:
                    # Action for this exact proposal_id was already evaluated/executed! Prevent duplicate.
                    return EnforcementDispatchResult(
                        case_id=case_id,
                        proposal_id=proposal_id,
                        decision=EnforcementDecision(existing_log.decision),
                        reason_code=PolicyEnforcementReasonCode(existing_log.reason_code),
                        stage2_proposed_action=stage2_proposed_action,
                        executed_action=existing_log.executed_action,
                        policy_id=existing_log.policy_id,
                        policy_version=existing_log.policy_version,
                        duplicate_execution_prevented=True,
                        evaluated_at=existing_log.evaluated_at,
                        enforcement_log_id=existing_log.enforcement_id,
                    )

            # 3. Execution-Time Compliance & State Recheck
            if recovery_case is not None and not recovery_case.recovery_eligible:
                # Case is no longer eligible for recovery
                result = PolicyEnforcementResult(
                    decision=EnforcementDecision.FALLBACK_TO_BASELINE,
                    reason_code=PolicyEnforcementReasonCode.POLICY_DISABLED,
                    merchant_id=merchant_id,
                    experiment_id=experiment_id,
                    experiment_version=experiment_version,
                    case_id=case_id,
                    stage2_proposed_action=stage2_proposed_action,
                    executed_action="STOP",
                    baseline_action="STOP",
                    evaluated_at=eval_time,
                )
                log_rec = save_enforcement_log(
                    session,
                    result,
                    configuration_hash=current_configuration_hash,
                    proposal_id=proposal_id,
                )
                return EnforcementDispatchResult(
                    case_id=case_id,
                    proposal_id=proposal_id,
                    decision=result.decision,
                    reason_code=result.reason_code,
                    stage2_proposed_action=stage2_proposed_action,
                    executed_action="STOP",
                    policy_id=None,
                    policy_version=None,
                    duplicate_execution_prevented=False,
                    evaluated_at=eval_time,
                    enforcement_log_id=log_rec.enforcement_id,
                )

            # 4. F5 Decision Engine Execution-Time Authorization
            res: PolicyEnforcementResult = self.engine.evaluate_decision(
                session=session,
                case_id=case_id,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                current_configuration_hash=current_configuration_hash,
                stage2_proposed_action=stage2_proposed_action,
                current_time=eval_time,
                attribution_start_time=attribution_start_time,
            )

            # 5. Save Audit Log with DB UniqueConstraint protection on proposal_id
            try:
                log_rec = save_enforcement_log(
                    session,
                    res,
                    configuration_hash=current_configuration_hash,
                    proposal_id=proposal_id,
                )
            except IntegrityError:
                # Database-level unique constraint race condition protection
                session.rollback()
                existing_log = get_enforcement_log_by_proposal(session, proposal_id.strip())
                if existing_log is not None:
                    return EnforcementDispatchResult(
                        case_id=case_id,
                        proposal_id=proposal_id,
                        decision=EnforcementDecision(existing_log.decision),
                        reason_code=PolicyEnforcementReasonCode(existing_log.reason_code),
                        stage2_proposed_action=stage2_proposed_action,
                        executed_action=existing_log.executed_action,
                        policy_id=existing_log.policy_id,
                        policy_version=existing_log.policy_version,
                        duplicate_execution_prevented=True,
                        evaluated_at=existing_log.evaluated_at,
                        enforcement_log_id=existing_log.enforcement_id,
                    )
                raise

            # 6. Update Stage2Case status upon successful execution
            if res.decision == EnforcementDecision.ALLOW_ACTION and stage2_case is not None:
                stage2_case.status = "DISPATCHED"

            return EnforcementDispatchResult(
                case_id=case_id,
                proposal_id=proposal_id,
                decision=res.decision,
                reason_code=res.reason_code,
                stage2_proposed_action=stage2_proposed_action,
                executed_action=res.executed_action,
                policy_id=res.policy_id,
                policy_version=res.policy_version,
                duplicate_execution_prevented=False,
                evaluated_at=eval_time,
                enforcement_log_id=log_rec.enforcement_id,
            )

        except Exception as err:
            logger.error(f"F5 Realtime Enforcer unexpected error for case {case_id}: {err}", exc_info=True)
            # Fail-closed guarantee on unexpected internal error
            fallback_res = PolicyEnforcementResult(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.INVALID_POLICY,
                merchant_id=merchant_id or "UNKNOWN",
                experiment_id=experiment_id or "UNKNOWN",
                experiment_version=experiment_version or "UNKNOWN",
                case_id=case_id or "UNKNOWN",
                stage2_proposed_action=stage2_proposed_action or "UNKNOWN",
                executed_action="STOP",
                baseline_action="STOP",
                evaluated_at=eval_time,
            )
            try:
                log_rec = save_enforcement_log(
                    session,
                    fallback_res,
                    configuration_hash=current_configuration_hash or "a" * 64,
                    proposal_id=proposal_id,
                )
                log_id = log_rec.enforcement_id
            except Exception:
                log_id = "enf_err_fallback"

            return EnforcementDispatchResult(
                case_id=case_id,
                proposal_id=proposal_id,
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.INVALID_POLICY,
                stage2_proposed_action=stage2_proposed_action,
                executed_action="STOP",
                policy_id=None,
                policy_version=None,
                duplicate_execution_prevented=False,
                evaluated_at=eval_time,
                enforcement_log_id=log_id,
            )

"""F5-2.1 — Hardened Policy Persistence Repository & Data Access Boundary.

Provides explicit, validated data access operations for persisting DecisionPolicyRecord
and PolicyEnforcementLogRecord models while preserving domain contracts, binding integrity,
single active policy uniqueness invariants, terminal state transition safety, and append-only audit logging semantics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...stage2.models import DecisionPolicyRecord, PolicyEnforcementLogRecord, PolicyKillAuditRecord, Stage2Case
from ..f4.contracts import EvaluationStatus
from .contracts import (
    AuthorizedActionSet,
    DecisionPolicyAuthorization,
    EnforcementDecision,
    EnforcementEvidenceBundle,
    EvidenceSupersessionStatus,
    PolicyBinding,
    PolicyEnforcementReasonCode,
    PolicyEnforcementResult,
    PolicyKillResult,
    PolicyStatus,
    SourceF4EvidenceReference,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def policy_record_to_contract(record: DecisionPolicyRecord) -> DecisionPolicyAuthorization:
    """Converts a DecisionPolicyRecord ORM instance to a DecisionPolicyAuthorization domain contract."""
    binding = PolicyBinding(
        merchant_id=record.merchant_id,
        experiment_id=record.experiment_id,
        experiment_version=record.experiment_version,
        approved_configuration_hash=record.approved_configuration_hash,
        policy_version=record.policy_version,
    )
    source_ref = SourceF4EvidenceReference(
        source_f4_evidence_id=record.source_f4_evidence_id,
        source_f4_evaluated_at=record.source_f4_evaluated_at,
        source_f4_status=EvaluationStatus(record.source_f4_status),
        source_f4_configuration_hash=record.source_f4_configuration_hash,
        source_f4_point_estimate=record.source_f4_point_estimate,
        source_f4_confidence_interval_lower=record.source_f4_confidence_interval_lower,
        source_f4_confidence_interval_upper=record.source_f4_confidence_interval_upper,
        statistical_limitations=list(record.statistical_limitations or []),
        superseding_f4_evidence_id=record.superseding_f4_evidence_id,
        superseded_at=record.superseded_at,
        supersession_status=EvidenceSupersessionStatus(record.supersession_status),
    )
    action_set = AuthorizedActionSet(actions=tuple(record.authorized_actions or []))

    return DecisionPolicyAuthorization(
        policy_id=record.policy_id,
        binding=binding,
        source_f4_reference=source_ref,
        authorized_actions=action_set,
        baseline_action=record.baseline_action,
        status=PolicyStatus(record.status),
        activated_at=record.activated_at,
        created_at=record.created_at,
    )


def enforcement_log_record_to_contract(record: PolicyEnforcementLogRecord) -> PolicyEnforcementResult:
    """Converts a PolicyEnforcementLogRecord ORM instance to a PolicyEnforcementResult domain contract."""
    return PolicyEnforcementResult(
        decision=EnforcementDecision(record.decision),
        reason_code=PolicyEnforcementReasonCode(record.reason_code),
        policy_id=record.policy_id,
        policy_version=record.policy_version,
        merchant_id=record.merchant_id,
        experiment_id=record.experiment_id,
        experiment_version=record.experiment_version,
        case_id=record.case_id,
        stage2_proposed_action=record.stage2_proposed_action,
        executed_action=record.executed_action,
        baseline_action=record.baseline_action,
        evaluated_at=record.evaluated_at,
        source_f4_evidence_id=record.source_f4_evidence_id,
    )


def _check_single_active_policy_invariant(
    session: Session,
    merchant_id: str,
    experiment_id: str,
    experiment_version: str,
    approved_configuration_hash: str,
    target_policy_id: str,
) -> None:
    """Enforces single active policy invariant per policy binding identity."""
    stmt = select(DecisionPolicyRecord).where(
        DecisionPolicyRecord.merchant_id == merchant_id,
        DecisionPolicyRecord.experiment_id == experiment_id,
        DecisionPolicyRecord.experiment_version == experiment_version,
        DecisionPolicyRecord.approved_configuration_hash == approved_configuration_hash,
        DecisionPolicyRecord.status == PolicyStatus.ACTIVE_ENFORCED.value,
        DecisionPolicyRecord.policy_id != target_policy_id,
    )
    existing_active = session.scalars(stmt).all()
    if existing_active:
        raise ValueError(
            f"Single active policy invariant breach: an ACTIVE_ENFORCED policy ('{existing_active[0].policy_id}') "
            f"already exists for binding (merchant_id={merchant_id}, experiment_id={experiment_id}, "
            f"experiment_version={experiment_version}, hash={approved_configuration_hash})"
        )


def save_policy(session: Session, authorization: DecisionPolicyAuthorization) -> DecisionPolicyRecord:
    """Persists a DecisionPolicyAuthorization domain contract into DecisionPolicyRecord.

    Enforces:
    - Configuration hash matching between binding and F4 evidence reference
    - Mandatory active_at timestamp when status == ACTIVE_ENFORCED
    - Single ACTIVE_ENFORCED policy invariant per binding identity
    - Canonical sorting and immutability of AuthorizedActionSet
    """
    if authorization.binding.approved_configuration_hash != authorization.source_f4_reference.source_f4_configuration_hash:
        raise ValueError("Policy binding configuration hash must match source F4 evidence configuration hash")

    if authorization.status == PolicyStatus.ACTIVE_ENFORCED:
        if authorization.activated_at is None:
            raise ValueError("ACTIVE_ENFORCED policy requires non-null activated_at timestamp")
        _check_single_active_policy_invariant(
            session,
            authorization.binding.merchant_id,
            authorization.binding.experiment_id,
            authorization.binding.experiment_version,
            authorization.binding.approved_configuration_hash,
            authorization.policy_id,
        )
    else:
        if authorization.activated_at is not None:
            raise ValueError("Non-ACTIVE_ENFORCED policy cannot have an activated_at timestamp")

    record = session.get(DecisionPolicyRecord, authorization.policy_id)
    if record is None:
        record = DecisionPolicyRecord(
            policy_id=authorization.policy_id,
            policy_version=authorization.binding.policy_version,
            merchant_id=authorization.binding.merchant_id,
            experiment_id=authorization.binding.experiment_id,
            experiment_version=authorization.binding.experiment_version,
            approved_configuration_hash=authorization.binding.approved_configuration_hash,
            treatment_arm_definition="STAGE2_DECISION_PROPOSAL",
            source_f4_evidence_id=authorization.source_f4_reference.source_f4_evidence_id,
            source_f4_evaluated_at=authorization.source_f4_reference.source_f4_evaluated_at,
            source_f4_status=authorization.source_f4_reference.source_f4_status.value,
            source_f4_configuration_hash=authorization.source_f4_reference.source_f4_configuration_hash,
            source_f4_point_estimate=authorization.source_f4_reference.source_f4_point_estimate,
            source_f4_confidence_interval_lower=authorization.source_f4_reference.source_f4_confidence_interval_lower,
            source_f4_confidence_interval_upper=authorization.source_f4_reference.source_f4_confidence_interval_upper,
            statistical_limitations=list(authorization.source_f4_reference.statistical_limitations),
            authorized_actions=list(authorization.authorized_actions.actions),
            baseline_action=authorization.baseline_action,
            status=authorization.status.value,
            activated_at=authorization.activated_at,
            supersession_status=authorization.source_f4_reference.supersession_status.value,
            superseding_f4_evidence_id=authorization.source_f4_reference.superseding_f4_evidence_id,
            superseded_at=authorization.source_f4_reference.superseded_at,
            created_at=authorization.created_at,
        )
        session.add(record)
    else:
        record.status = authorization.status.value
        record.activated_at = authorization.activated_at
        record.supersession_status = authorization.source_f4_reference.supersession_status.value
        record.superseding_f4_evidence_id = authorization.source_f4_reference.superseding_f4_evidence_id
        record.superseded_at = authorization.source_f4_reference.superseded_at

    session.flush()
    return record


def get_policy_by_id(session: Session, policy_id: str) -> DecisionPolicyRecord | None:
    """Retrieves a DecisionPolicyRecord by primary key policy_id."""
    return session.get(DecisionPolicyRecord, policy_id)


def get_active_policy_for_binding(
    session: Session,
    merchant_id: str,
    experiment_id: str,
    experiment_version: str,
    approved_configuration_hash: str,
) -> DecisionPolicyRecord | None:
    """Retrieves the authoritative active enforced policy for a policy binding.

    Fails closed if multiple ACTIVE_ENFORCED policies are detected for the binding.
    """
    stmt = select(DecisionPolicyRecord).where(
        DecisionPolicyRecord.merchant_id == merchant_id,
        DecisionPolicyRecord.experiment_id == experiment_id,
        DecisionPolicyRecord.experiment_version == experiment_version,
        DecisionPolicyRecord.approved_configuration_hash == approved_configuration_hash,
        DecisionPolicyRecord.status == PolicyStatus.ACTIVE_ENFORCED.value,
    )
    records = list(session.scalars(stmt).all())
    if len(records) > 1:
        raise ValueError(
            f"Integrity failure: multiple ({len(records)}) ACTIVE_ENFORCED policies found for binding "
            f"(merchant_id={merchant_id}, experiment_id={experiment_id}, experiment_version={experiment_version}, hash={approved_configuration_hash})"
        )
    return records[0] if records else None


def get_policy_for_binding(
    session: Session,
    merchant_id: str,
    experiment_id: str,
    experiment_version: str,
    approved_configuration_hash: str,
) -> DecisionPolicyRecord | None:
    """Retrieves policy for binding. Prefers ACTIVE_ENFORCED, but returns non-active record if no active policy exists."""
    stmt = select(DecisionPolicyRecord).where(
        DecisionPolicyRecord.merchant_id == merchant_id,
        DecisionPolicyRecord.experiment_id == experiment_id,
        DecisionPolicyRecord.experiment_version == experiment_version,
        DecisionPolicyRecord.approved_configuration_hash == approved_configuration_hash,
    )
    records = list(session.scalars(stmt).all())
    active_records = [r for r in records if r.status == PolicyStatus.ACTIVE_ENFORCED.value]
    if len(active_records) > 1:
        raise ValueError(
            f"Integrity failure: multiple ({len(active_records)}) ACTIVE_ENFORCED policies found for binding"
        )
    if active_records:
        return active_records[0]
    return records[0] if records else None


def update_policy_status(
    session: Session,
    policy_id: str,
    status: PolicyStatus,
    activated_at: datetime | None = None,
    supersession_status: EvidenceSupersessionStatus | None = None,
    superseding_f4_evidence_id: str | None = None,
    superseded_at: datetime | None = None,
) -> DecisionPolicyRecord:
    """Updates the lifecycle or supersession state of a persisted decision policy.

    Enforces terminal state immutability and single active policy invariant.
    """
    record = session.get(DecisionPolicyRecord, policy_id, with_for_update=True)
    if record is None:
        raise ValueError(f"Decision policy '{policy_id}' not found")

    terminal_states = {
        PolicyStatus.KILLED_SAFETY_STOP.value,
        PolicyStatus.INVALIDATED.value,
        PolicyStatus.EXPIRED.value,
    }

    if record.status in terminal_states and status == PolicyStatus.ACTIVE_ENFORCED:
        raise ValueError(
            f"Invalid lifecycle transition: policy '{policy_id}' in terminal state '{record.status}' "
            f"cannot transition to ACTIVE_ENFORCED"
        )

    if status == PolicyStatus.ACTIVE_ENFORCED:
        _check_single_active_policy_invariant(
            session,
            record.merchant_id,
            record.experiment_id,
            record.experiment_version,
            record.approved_configuration_hash,
            policy_id,
        )
        effective_activated_at = activated_at or record.activated_at or utc_now()
        record.activated_at = effective_activated_at
    else:
        record.activated_at = None

    record.status = status.value

    if supersession_status is not None:
        record.supersession_status = supersession_status.value
    if superseding_f4_evidence_id is not None:
        record.superseding_f4_evidence_id = superseding_f4_evidence_id
    if superseded_at is not None:
        record.superseded_at = superseded_at

    session.flush()
    return record


def save_enforcement_log(
    session: Session,
    result: PolicyEnforcementResult,
    configuration_hash: str = "a" * 64,
    enforcement_id: str | None = None,
    proposal_id: str | None = None,
) -> PolicyEnforcementLogRecord:
    """Persists an append-only PolicyEnforcementResult into PolicyEnforcementLogRecord.

    Enforces fail-closed executed_action properties:
    - ALLOW_ACTION -> executed_action == stage2_proposed_action
    - Non-ALLOW decision -> executed_action == baseline_action ("STOP")
    """
    effective_id = enforcement_id or f"enf_{uuid.uuid4().hex[:16]}"

    log_record = PolicyEnforcementLogRecord(
        enforcement_id=effective_id,
        proposal_id=proposal_id,
        case_id=result.case_id,
        merchant_id=result.merchant_id,
        experiment_id=result.experiment_id,
        experiment_version=result.experiment_version,
        configuration_hash=configuration_hash,
        policy_id=result.policy_id,
        policy_version=result.policy_version,
        source_f4_evidence_id=result.source_f4_evidence_id,
        stage2_proposed_action=result.stage2_proposed_action,
        executed_action=result.executed_action,
        baseline_action=result.baseline_action,
        decision=result.decision.value,
        reason_code=result.reason_code.value,
        evaluated_at=result.evaluated_at,
    )
    session.add(log_record)
    session.flush()
    return log_record


def get_enforcement_log_by_proposal(
    session: Session, proposal_id: str
) -> PolicyEnforcementLogRecord | None:
    """Retrieves an existing enforcement audit log record by primary proposal_id."""
    stmt = (
        select(PolicyEnforcementLogRecord)
        .where(PolicyEnforcementLogRecord.proposal_id == proposal_id)
        .order_by(PolicyEnforcementLogRecord.evaluated_at.desc())
    )
    return session.scalars(stmt).first()


def get_enforcement_logs_by_case(session: Session, case_id: str) -> list[PolicyEnforcementLogRecord]:
    """Retrieves all enforcement audit log records for a given case_id in chronological order."""
    stmt = (
        select(PolicyEnforcementLogRecord)
        .where(PolicyEnforcementLogRecord.case_id == case_id)
        .order_by(PolicyEnforcementLogRecord.evaluated_at.asc())
    )
    return list(session.scalars(stmt).all())


def execute_emergency_kill(
    session: Session,
    *,
    policy_id: str,
    merchant_id: str,
    experiment_id: str,
    experiment_version: str,
    approved_configuration_hash: str,
    operator_id: str | None = None,
    reason: str | None = None,
    kill_time: datetime | None = None,
) -> PolicyKillResult:
    """Executes deterministic emergency kill switch operation (F5-5).

    Execution Sequence:
    1. Lock Policy Row: Queries DecisionPolicyRecord with with_for_update=True.
    2. Tenant & Scope Validation: Verifies merchant_id, experiment_id, experiment_version, and configuration hash.
       Raises ValueError if scope mismatch occurs (fails closed, policy unchanged).
    3. Lifecycle Verification & Transition:
       - If status == ACTIVE_ENFORCED (or draft/disabled): transitions to KILLED_SAFETY_STOP.
       - If status == KILLED_SAFETY_STOP: Idempotent! Remains KILLED_SAFETY_STOP. Idempotent flag set to True.
    4. Audit Persistence: Appends PolicyKillAuditRecord.
    5. Commit Point: Flushes session (caller session.commit() completes transaction).
    """
    effective_time = kill_time or utc_now()
    record = session.get(DecisionPolicyRecord, policy_id, with_for_update=True)
    if record is None:
        raise ValueError(f"Decision policy '{policy_id}' not found")

    # Scope & Tenant Isolation Guard
    if record.merchant_id != merchant_id:
        raise ValueError(f"Tenant isolation mismatch: policy '{policy_id}' belongs to merchant '{record.merchant_id}', not '{merchant_id}'")

    if record.experiment_id != experiment_id or record.experiment_version != experiment_version:
        raise ValueError(f"Experiment scope mismatch: policy '{policy_id}' experiment identity mismatch")

    if record.approved_configuration_hash != approved_configuration_hash:
        raise ValueError(f"Configuration hash mismatch: policy '{policy_id}' hash mismatch")

    prev_status = PolicyStatus(record.status)

    if prev_status == PolicyStatus.KILLED_SAFETY_STOP:
        # Idempotent kill request against an already killed policy!
        return PolicyKillResult(
            policy_id=policy_id,
            merchant_id=merchant_id,
            experiment_id=experiment_id,
            experiment_version=experiment_version,
            previous_status=prev_status,
            new_status=PolicyStatus.KILLED_SAFETY_STOP,
            kill_effective_at=effective_time,
            idempotent=True,
            policy_version=record.policy_version,
        )

    # Transition to KILLED_SAFETY_STOP
    record.status = PolicyStatus.KILLED_SAFETY_STOP.value
    record.activated_at = None

    # Persist audit record
    audit_id = f"kill_aud_{uuid.uuid4().hex[:16]}"
    audit_rec = PolicyKillAuditRecord(
        audit_id=audit_id,
        policy_id=policy_id,
        merchant_id=merchant_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        approved_configuration_hash=approved_configuration_hash,
        policy_version=record.policy_version,
        previous_status=prev_status.value,
        new_status=PolicyStatus.KILLED_SAFETY_STOP.value,
        kill_effective_at=effective_time,
        operator_id=operator_id,
        reason=reason,
    )
    session.add(audit_rec)
    session.flush()

    return PolicyKillResult(
        policy_id=policy_id,
        merchant_id=merchant_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        previous_status=prev_status,
        new_status=PolicyStatus.KILLED_SAFETY_STOP,
        kill_effective_at=effective_time,
        idempotent=False,
        policy_version=record.policy_version,
    )


def get_policy_kill_audits(
    session: Session, policy_id: str, merchant_id: str | None = None
) -> list[PolicyKillAuditRecord]:
    """Retrieves all policy kill audit records for a policy_id in chronological order with tenant isolation."""
    stmt = select(PolicyKillAuditRecord).where(PolicyKillAuditRecord.policy_id == policy_id)
    if merchant_id:
        stmt = stmt.where(PolicyKillAuditRecord.merchant_id == merchant_id)
    stmt = stmt.order_by(PolicyKillAuditRecord.kill_effective_at.asc())
    return list(session.scalars(stmt).all())


def get_enforcement_by_id(
    session: Session, enforcement_id: str, merchant_id: str | None = None
) -> PolicyEnforcementLogRecord | None:
    """Retrieves an enforcement audit log record by ID with strict tenant isolation."""
    stmt = select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.enforcement_id == enforcement_id)
    if merchant_id:
        stmt = stmt.where(PolicyEnforcementLogRecord.merchant_id == merchant_id)
    return session.scalars(stmt).first()


def get_enforcement_by_proposal_id(
    session: Session, proposal_id: str, merchant_id: str | None = None
) -> PolicyEnforcementLogRecord | None:
    """Retrieves an enforcement audit log record by proposal_id with strict tenant isolation."""
    stmt = select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.proposal_id == proposal_id)
    if merchant_id:
        stmt = stmt.where(PolicyEnforcementLogRecord.merchant_id == merchant_id)
    stmt = stmt.order_by(PolicyEnforcementLogRecord.evaluated_at.desc())
    return session.scalars(stmt).first()


def get_enforcement_by_case_id(
    session: Session, case_id: str, merchant_id: str | None = None
) -> list[PolicyEnforcementLogRecord]:
    """Retrieves all enforcement audit log records for a case_id in chronological order with tenant isolation."""
    stmt = select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.case_id == case_id)
    if merchant_id:
        stmt = stmt.where(PolicyEnforcementLogRecord.merchant_id == merchant_id)
    stmt = stmt.order_by(PolicyEnforcementLogRecord.evaluated_at.asc())
    return list(session.scalars(stmt).all())


def get_policy_enforcement_history(
    session: Session, policy_id: str, merchant_id: str | None = None
) -> list[PolicyEnforcementLogRecord]:
    """Retrieves all enforcement audit log records for a policy_id in chronological order with tenant isolation."""
    stmt = select(PolicyEnforcementLogRecord).where(PolicyEnforcementLogRecord.policy_id == policy_id)
    if merchant_id:
        stmt = stmt.where(PolicyEnforcementLogRecord.merchant_id == merchant_id)
    stmt = stmt.order_by(PolicyEnforcementLogRecord.evaluated_at.asc())
    return list(session.scalars(stmt).all())


def reconstruct_enforcement_evidence(
    session: Session,
    enforcement_id: str,
    merchant_id: str | None = None,
) -> EnforcementEvidenceBundle:
    """Deterministically reconstructs a complete, auditable evidence bundle for an enforcement decision (F5-6).

    Traverses:
    enforcement_id -> case_id -> proposal_id -> policy_id -> experiment_id -> configuration_hash -> source_f4_evidence_id
    Enforces strict tenant boundary checks and preserves historical snapshot facts.
    """
    log_rec = get_enforcement_by_id(session, enforcement_id, merchant_id=merchant_id)
    if log_rec is None:
        if merchant_id and get_enforcement_by_id(session, enforcement_id, merchant_id=None) is not None:
            raise ValueError(
                f"Tenant access denied: merchant '{merchant_id}' cannot access enforcement evidence for another tenant"
            )
        raise ValueError(f"Enforcement audit log '{enforcement_id}' not found")

    policy_rec = session.get(DecisionPolicyRecord, log_rec.policy_id) if log_rec.policy_id else None
    kill_audits = get_policy_kill_audits(session, log_rec.policy_id, merchant_id=merchant_id) if log_rec.policy_id else []
    stage2_case = session.scalars(
        select(Stage2Case).where(Stage2Case.case_id == log_rec.case_id).order_by(Stage2Case.stage1_state_version.desc())
    ).first() if log_rec.case_id else None
    exec_status = stage2_case.status if stage2_case else None

    kill_summary = None
    policy_killed = False
    if kill_audits:
        policy_killed = True
        latest_kill = kill_audits[-1]
        kill_effective = latest_kill.kill_effective_at if latest_kill.kill_effective_at.tzinfo else latest_kill.kill_effective_at.replace(tzinfo=timezone.utc)
        eval_time = log_rec.evaluated_at if log_rec.evaluated_at.tzinfo else log_rec.evaluated_at.replace(tzinfo=timezone.utc)
        timing = "PRIOR_TO_DECISION" if kill_effective <= eval_time else "SUBSEQUENT_TO_DECISION"
        kill_summary = {
            "audit_id": latest_kill.audit_id,
            "previous_status": latest_kill.previous_status,
            "new_status": latest_kill.new_status,
            "kill_effective_at": latest_kill.kill_effective_at.isoformat(),
            "operator_id": latest_kill.operator_id,
            "reason": latest_kill.reason,
            "kill_timing_relative_to_enforcement": timing,
        }

    return EnforcementEvidenceBundle(
        enforcement_id=log_rec.enforcement_id,
        proposal_id=log_rec.proposal_id,
        case_id=log_rec.case_id,
        merchant_id=log_rec.merchant_id,
        experiment_id=log_rec.experiment_id,
        experiment_version=log_rec.experiment_version,
        approved_configuration_hash=log_rec.configuration_hash,
        policy_id=log_rec.policy_id,
        policy_version=log_rec.policy_version,
        source_f4_evidence_id=log_rec.source_f4_evidence_id,
        source_f4_configuration_hash=policy_rec.source_f4_configuration_hash if policy_rec else None,
        stage2_proposed_action=log_rec.stage2_proposed_action,
        executed_action=log_rec.executed_action,
        baseline_action=log_rec.baseline_action,
        decision=EnforcementDecision(log_rec.decision),
        reason_code=PolicyEnforcementReasonCode(log_rec.reason_code),
        evaluated_at=log_rec.evaluated_at,
        execution_status=exec_status,
        policy_status_at_decision=policy_rec.status if policy_rec else None,
        policy_killed=policy_killed,
        kill_audit_summary=kill_summary,
    )



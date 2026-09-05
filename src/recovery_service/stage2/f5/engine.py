"""F5-3.1 — Decision Engine Implementation (Semantically Hardened).

Pure F5 decision engine for Stage 2 Recovery. Evaluates whether a Stage 2 proposed
recovery action is authorized for execution at the current decision point.

Returns authoritative PolicyEnforcementResult with:
- ALLOW_ACTION -> executed_action == stage2_proposed_action
- FALLBACK_TO_BASELINE -> executed_action == baseline_action ("STOP")
- FAIL_CLOSED -> executed_action == baseline_action ("STOP")
"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from ..f4.contracts import EvaluationStatus
from .contracts import (
    EnforcementDecision,
    EvidenceSupersessionStatus,
    PolicyEnforcementReasonCode,
    PolicyEnforcementResult,
    PolicyStatus,
)
from .repository import get_policy_for_binding, policy_record_to_contract


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensures datetime instance is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class F5DecisionEngine:
    """Pure, deterministic F5 Decision Engine for Stage 2 Recovery (F5-3.1)."""

    def evaluate_decision(
        self,
        session: Session,
        case_id: str,
        merchant_id: str,
        experiment_id: str,
        experiment_version: str,
        current_configuration_hash: str,
        stage2_proposed_action: str,
        current_time: datetime | None = None,
        attribution_start_time: datetime | None = None,
        require_attribution_window_hours: int = 72,
    ) -> PolicyEnforcementResult:
        """Evaluates authorization for a Stage 2 proposed recovery action.

        Executes deterministic fail-closed pipeline:
        1. Context & Identity validation
        2. Active Policy Resolution
        3. Lifecycle Validation
        4. Binding & Provenance Verification
        5. F4 Evidence & Supersession Integrity
        6. F4 Efficacy Authorization
        7. Authoritative 72-Hour Attribution Window Verification
        8. Authorized Action Set Membership Verification
        9. Result Construction
        """
        eval_time = _ensure_utc(current_time or utc_now())

        # Step 1: Context & Identity Validation
        if not case_id or not case_id.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.INVALID_POLICY,
                merchant_id=merchant_id or "UNKNOWN",
                experiment_id=experiment_id or "UNKNOWN",
                experiment_version=experiment_version or "UNKNOWN",
                case_id=case_id or "UNKNOWN",
                stage2_proposed_action=stage2_proposed_action or "UNKNOWN",
                evaluated_at=eval_time,
            )

        if not merchant_id or not merchant_id.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.TENANT_MISMATCH,
                merchant_id="UNKNOWN",
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                evaluated_at=eval_time,
            )

        if not experiment_id or not experiment_id.strip() or not experiment_version or not experiment_version.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.VERSION_MISMATCH,
                merchant_id=merchant_id,
                experiment_id=experiment_id or "UNKNOWN",
                experiment_version=experiment_version or "UNKNOWN",
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                evaluated_at=eval_time,
            )

        if not current_configuration_hash or not current_configuration_hash.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.CONFIG_HASH_MISMATCH,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                evaluated_at=eval_time,
            )

        if not stage2_proposed_action or not stage2_proposed_action.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.UNAUTHORIZED_ACTION,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action="UNKNOWN",
                evaluated_at=eval_time,
            )

        # Step 2: Policy Resolution
        try:
            record = get_policy_for_binding(
                session=session,
                merchant_id=merchant_id.strip(),
                experiment_id=experiment_id.strip(),
                experiment_version=experiment_version.strip(),
                approved_configuration_hash=current_configuration_hash.strip(),
            )
        except ValueError:
            # Integrity failure: multiple active policies detected
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.INVALID_POLICY,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                evaluated_at=eval_time,
            )

        if record is None:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.POLICY_NOT_FOUND,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                evaluated_at=eval_time,
            )

        # Step 3: Policy Conversion & Lifecycle Validation
        try:
            contract = policy_record_to_contract(record)
        except Exception:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.INVALID_POLICY,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                evaluated_at=eval_time,
            )

        if contract.status != PolicyStatus.ACTIVE_ENFORCED:
            reason = PolicyEnforcementReasonCode.POLICY_DISABLED
            if contract.status == PolicyStatus.KILLED_SAFETY_STOP:
                reason = PolicyEnforcementReasonCode.POLICY_KILLED
            elif contract.status == PolicyStatus.EXPIRED:
                reason = PolicyEnforcementReasonCode.POLICY_EXPIRED
            elif contract.status == PolicyStatus.INVALIDATED:
                reason = PolicyEnforcementReasonCode.INVALID_POLICY

            return self._build_result(
                decision=EnforcementDecision.FALLBACK_TO_BASELINE,
                reason_code=reason,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        # Step 4: Binding Identity & Provenance Verification
        if contract.binding.merchant_id != merchant_id.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.TENANT_MISMATCH,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        if contract.binding.experiment_id != experiment_id.strip() or contract.binding.experiment_version != experiment_version.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.VERSION_MISMATCH,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        if contract.binding.approved_configuration_hash != current_configuration_hash.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.CONFIG_HASH_MISMATCH,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        if contract.source_f4_reference.source_f4_configuration_hash != current_configuration_hash.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.CONFIG_HASH_MISMATCH,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        # Step 5: F4 Evidence Integrity & Supersession
        if not contract.source_f4_reference.source_f4_evidence_id or not contract.source_f4_reference.source_f4_evidence_id.strip():
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.MISSING_EVIDENCE,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                evaluated_at=eval_time,
            )

        # F5-3.1 Hardened Evidence Supersession Logic:
        # - SUPERSEDED_CONFLICT fails closed due to safety conflict
        # - SUPERSEDED_CONSISTENT does NOT automatically stop or invalidate an active policy
        if contract.source_f4_reference.supersession_status == EvidenceSupersessionStatus.SUPERSEDED_CONFLICT:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.SUPERSEDING_EVIDENCE_CONFLICT,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        # Step 6: F4 Efficacy Authorization
        f4_status = contract.source_f4_reference.source_f4_status
        if f4_status == EvaluationStatus.VERSION_INCONSISTENCY:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.VERSION_MISMATCH,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )
        elif f4_status == EvaluationStatus.EXPERIMENT_INVALIDATED:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.INVALID_EVIDENCE,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )
        elif f4_status == EvaluationStatus.SAFETY_STOPPED:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.SAFETY_STOP,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )
        elif f4_status == EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM:
            return self._build_result(
                decision=EnforcementDecision.FALLBACK_TO_BASELINE,
                reason_code=PolicyEnforcementReasonCode.F4_STATUS_NOT_EFFICACIOUS,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )
        elif f4_status != EvaluationStatus.EFFICACY_RESULT_AVAILABLE:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.INVALID_EVIDENCE,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        # Step 7: Authoritative 72-Hour Attribution Window Verification
        # F5-3.1 Hardened Timestamp Logic:
        # Requires explicit authoritative attribution_start_time.
        # MUST NOT fall back to source_f4_evaluated_at as the attribution start.
        if attribution_start_time is None:
            return self._build_result(
                decision=EnforcementDecision.FAIL_CLOSED,
                reason_code=PolicyEnforcementReasonCode.STALE_EVALUATION,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        ref_start_time = _ensure_utc(attribution_start_time)
        elapsed_seconds = (eval_time - ref_start_time).total_seconds()
        required_seconds = require_attribution_window_hours * 3600.0

        if elapsed_seconds < required_seconds:
            return self._build_result(
                decision=EnforcementDecision.FALLBACK_TO_BASELINE,
                reason_code=PolicyEnforcementReasonCode.STALE_EVALUATION,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        # Step 8: Authorized Action Set Membership Verification
        if not contract.authorized_actions.contains(stage2_proposed_action):
            return self._build_result(
                decision=EnforcementDecision.FALLBACK_TO_BASELINE,
                reason_code=PolicyEnforcementReasonCode.UNAUTHORIZED_ACTION,
                merchant_id=merchant_id,
                experiment_id=experiment_id,
                experiment_version=experiment_version,
                case_id=case_id,
                stage2_proposed_action=stage2_proposed_action,
                policy_id=contract.policy_id,
                policy_version=contract.binding.policy_version,
                source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
                evaluated_at=eval_time,
            )

        # Step 9: Result Construction (ALLOW_ACTION)
        return self._build_result(
            decision=EnforcementDecision.ALLOW_ACTION,
            reason_code=PolicyEnforcementReasonCode.POLICY_ENFORCED_EFFICACIOUS,
            merchant_id=merchant_id,
            experiment_id=experiment_id,
            experiment_version=experiment_version,
            case_id=case_id,
            stage2_proposed_action=stage2_proposed_action,
            policy_id=contract.policy_id,
            policy_version=contract.binding.policy_version,
            source_f4_evidence_id=contract.source_f4_reference.source_f4_evidence_id,
            evaluated_at=eval_time,
        )

    def _build_result(
        self,
        decision: EnforcementDecision,
        reason_code: PolicyEnforcementReasonCode,
        merchant_id: str,
        experiment_id: str,
        experiment_version: str,
        case_id: str,
        stage2_proposed_action: str,
        policy_id: str | None = None,
        policy_version: str | None = None,
        source_f4_evidence_id: str | None = None,
        evaluated_at: datetime | None = None,
    ) -> PolicyEnforcementResult:
        """Helper constructing fail-closed PolicyEnforcementResult instances."""
        eval_time = _ensure_utc(evaluated_at or utc_now())
        executed = stage2_proposed_action if decision == EnforcementDecision.ALLOW_ACTION else "STOP"

        return PolicyEnforcementResult(
            decision=decision,
            reason_code=reason_code,
            policy_id=policy_id if decision == EnforcementDecision.ALLOW_ACTION or policy_id else None,
            policy_version=policy_version,
            merchant_id=merchant_id,
            experiment_id=experiment_id,
            experiment_version=experiment_version,
            case_id=case_id,
            stage2_proposed_action=stage2_proposed_action,
            executed_action=executed,
            baseline_action="STOP",
            evaluated_at=eval_time,
            source_f4_evidence_id=source_f4_evidence_id,
        )

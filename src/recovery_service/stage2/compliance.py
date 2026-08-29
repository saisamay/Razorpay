from __future__ import annotations

from datetime import datetime, timezone

from .schemas import DiagnosisResult, EvidenceManifest, RecoveryEligibility


COMPLIANCE_RULESET_VERSION = "1.0"
MAX_ATTEMPTS_PER_CASE = 3


class EligibilityStates:
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    DELAY_REQUIRED = "DELAY_REQUIRED"
    UNKNOWN = "UNKNOWN"


def evaluate_compliance_eligibility(
    manifest: EvidenceManifest,
    diagnosis: DiagnosisResult,
    attempt_count: int = 1,
) -> RecoveryEligibility:
    """Evaluate hard compliance rules and technical recovery eligibility.

    MUST be evaluated BEFORE any ML retry prediction or counterfactual evaluation.
    Fail-closed policy: UNKNOWN compliance state resolves to BLOCKED.
    """

    now = datetime.now(timezone.utc)
    attempts_remaining = max(0, MAX_ATTEMPTS_PER_CASE - attempt_count)

    # Hard Rule 1: Zero attempts remaining -> BLOCKED
    if attempts_remaining <= 0:
        return RecoveryEligibility(
            eligibility=EligibilityStates.BLOCKED,
            attempts_remaining=0,
            advice_code="MAX_ATTEMPTS_EXCEEDED",
            required_delay=0,
            projected_penalty=100.0,
            ruleset_version=COMPLIANCE_RULESET_VERSION,
            evaluated_at=now,
        )

    # Hard Rule 2: Payment state captured or Terminal Authorized -> BLOCKED
    if manifest.state.state in {"CAPTURED", "AUTHORIZED"}:
        return RecoveryEligibility(
            eligibility=EligibilityStates.BLOCKED,
            attempts_remaining=0,
            advice_code="PAYMENT_TERMINAL_SUCCESS",
            required_delay=0,
            projected_penalty=500.0,
            ruleset_version=COMPLIANCE_RULESET_VERSION,
            evaluated_at=now,
        )

    # Hard Rule 3: Contradiction penalty or Insufficient Evidence -> BLOCKED (Fail Closed)
    if diagnosis.diagnosis_class in {"INSUFFICIENT_EVIDENCE", "UNKNOWN"}:
        return RecoveryEligibility(
            eligibility=EligibilityStates.BLOCKED,
            attempts_remaining=attempts_remaining,
            advice_code="COMPLIANCE_UNCERTAINTY_FAIL_CLOSED",
            required_delay=0,
            projected_penalty=200.0,
            ruleset_version=COMPLIANCE_RULESET_VERSION,
            evaluated_at=now,
        )

    # Hard Rule 4: Transient Timeout requires cool-down delay
    if diagnosis.diagnosis_class == "TRANSIENT_PROVIDER_TIMEOUT":
        return RecoveryEligibility(
            eligibility=EligibilityStates.DELAY_REQUIRED,
            attempts_remaining=attempts_remaining,
            advice_code="COOLDOWN_REQUIRED_FOR_TIMEOUT",
            required_delay=300,  # 5-minute cool-down
            projected_penalty=10.0,
            ruleset_version=COMPLIANCE_RULESET_VERSION,
            evaluated_at=now,
        )

    # Default: ELIGIBLE
    return RecoveryEligibility(
        eligibility=EligibilityStates.ELIGIBLE,
        attempts_remaining=attempts_remaining,
        advice_code="ELIGIBLE_FOR_RECOVERY",
        required_delay=0,
        projected_penalty=0.0,
        ruleset_version=COMPLIANCE_RULESET_VERSION,
        evaluated_at=now,
    )

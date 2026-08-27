from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .schemas import DiagnosisHypothesis, DiagnosisResult, EvidenceManifest


DIAGNOSIS_ENGINE_VERSION = "1.0"
MIN_DIAGNOSIS_SCORE = 0.5
CONTRADICTION_THRESHOLD = 0.5


class DiagnosisClasses:
    TRANSIENT_PROVIDER_TIMEOUT = "TRANSIENT_PROVIDER_TIMEOUT"
    ISSUER_DECLINE = "ISSUER_DECLINE"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    DUPLICATE_OR_CONFLICTING_ATTEMPT = "DUPLICATE_OR_CONFLICTING_ATTEMPT"
    LATE_SUCCESS_AFTER_TIMEOUT = "LATE_SUCCESS_AFTER_TIMEOUT"
    PROVIDER_DEGRADATION_SUSPECTED = "PROVIDER_DEGRADATION_SUSPECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNKNOWN = "UNKNOWN"


def _evaluate_hypotheses(manifest: EvidenceManifest) -> tuple[list[DiagnosisHypothesis], list[str], list[str]]:
    """Evaluate all 8 candidate diagnosis hypotheses against the EvidenceManifest."""

    hypotheses: list[DiagnosisHypothesis] = []
    evidence = manifest.failure.raw_details or {}
    code = (manifest.failure.failure_code or "").upper()
    step = (manifest.failure.failure_step or "").upper()
    anomalies = manifest.anomalies.anomalies
    contradictions = manifest.anomalies.contradictions
    events = [e.event_type.lower() for e in manifest.timeline.events]

    all_supporting_ids = list(manifest.provenance.source_event_ids)
    all_contradiction_ids = list(manifest.anomalies.contradictions)

    # 1. LATE_SUCCESS_AFTER_TIMEOUT
    has_timeout_signal = "timeout" in code.lower() or "timeout" in step.lower() or "timeout" in anomalies
    has_late_success = any(e in {"payment.authorized", "payment.captured"} for e in events) or "late_authorization" in anomalies
    if has_timeout_signal and has_late_success:
        hypotheses.append(DiagnosisHypothesis(
            diagnosis_class=DiagnosisClasses.LATE_SUCCESS_AFTER_TIMEOUT,
            score=0.95,
            supporting_evidence=["timeout_signal", "late_success_event"],
            contradicting_evidence=[],
        ))
    elif has_timeout_signal and not has_late_success:
        hypotheses.append(DiagnosisHypothesis(
            diagnosis_class=DiagnosisClasses.LATE_SUCCESS_AFTER_TIMEOUT,
            score=0.0,
            supporting_evidence=["timeout_signal"],
            contradicting_evidence=["missing_late_success_event"],
            rejected_reason="No positive late authorization/capture event found",
        ))

    # 2. AUTHENTICATION_FAILURE
    is_auth_step = "AUTHENTICATION" in step or "3DS" in step or "OTP" in step
    is_auth_code = "AUTH" in code or "3DS" in code or "OTP" in code or "PIN" in code
    if is_auth_step or is_auth_code:
        hypotheses.append(DiagnosisHypothesis(
            diagnosis_class=DiagnosisClasses.AUTHENTICATION_FAILURE,
            score=0.90 if (is_auth_step and is_auth_code) else 0.75,
            supporting_evidence=[s for s in ["auth_step", "auth_code"] if (is_auth_step if s == "auth_step" else is_auth_code)],
            contradicting_evidence=[],
        ))

    # 3. ISSUER_DECLINE
    issuer_decline_codes = {"BAD_REQUEST_ERROR", "CARD_DECLINED", "INSUFFICIENT_FUNDS", "EXPIRED_CARD", "INVALID_CVV", "ISSUER_DOWN"}
    if code in issuer_decline_codes or "DECLINE" in code or "ISSUER" in code:
        hypotheses.append(DiagnosisHypothesis(
            diagnosis_class=DiagnosisClasses.ISSUER_DECLINE,
            score=0.85,
            supporting_evidence=[f"issuer_code_{code}"],
            contradicting_evidence=["late_success"] if has_late_success else [],
        ))

    # 4. TRANSIENT_PROVIDER_TIMEOUT
    if has_timeout_signal and not has_late_success:
        hypotheses.append(DiagnosisHypothesis(
            diagnosis_class=DiagnosisClasses.TRANSIENT_PROVIDER_TIMEOUT,
            score=0.88,
            supporting_evidence=["timeout_signal"],
            contradicting_evidence=[],
        ))

    # 5. DUPLICATE_OR_CONFLICTING_ATTEMPT
    if "duplicate_attempt" in anomalies or "competing_attempt" in anomalies or len(contradictions) > 0:
        hypotheses.append(DiagnosisHypothesis(
            diagnosis_class=DiagnosisClasses.DUPLICATE_OR_CONFLICTING_ATTEMPT,
            score=0.80,
            supporting_evidence=["duplicate_or_competing_signal"],
            contradicting_evidence=[],
        ))

    # 6. PROVIDER_DEGRADATION_SUSPECTED
    if "provider_degradation" in anomalies or "systemic_degradation" in anomalies or evidence.get("gateway_degraded"):
        hypotheses.append(DiagnosisHypothesis(
            diagnosis_class=DiagnosisClasses.PROVIDER_DEGRADATION_SUSPECTED,
            score=0.82,
            supporting_evidence=["provider_degradation_signal"],
            contradicting_evidence=[],
        ))

    return hypotheses, all_supporting_ids, all_contradiction_ids


def evaluate_diagnosis(manifest: EvidenceManifest) -> DiagnosisResult:
    """Pure deterministic diagnosis engine enforcing conflict resolution and safety precedence."""

    hypotheses, supporting_ids, contradiction_ids = _evaluate_hypotheses(manifest)

    # Precedence Rule 1: Check if required evidence is completely missing
    if not manifest.provenance.source_event_ids and manifest.failure.failure_code == "UNKNOWN":
        winning_class = DiagnosisClasses.INSUFFICIENT_EVIDENCE
        winning_score = 0.0
    # Precedence Rule 2: Check if contradictions exceed threshold
    elif len(manifest.anomalies.contradictions) > 2:
        winning_class = DiagnosisClasses.INSUFFICIENT_EVIDENCE
        winning_score = 0.0
    else:
        # Filter valid hypotheses (score >= MIN_DIAGNOSIS_SCORE)
        valid_hypotheses = [h for h in hypotheses if h.score >= MIN_DIAGNOSIS_SCORE]
        if not valid_hypotheses:
            winning_class = DiagnosisClasses.UNKNOWN
            winning_score = 0.0
        else:
            # Sort by safety precedence:
            # LATE_SUCCESS_AFTER_TIMEOUT > AUTHENTICATION_FAILURE > ISSUER_DECLINE > TRANSIENT_PROVIDER_TIMEOUT > OTHERS
            precedence_rank = {
                DiagnosisClasses.LATE_SUCCESS_AFTER_TIMEOUT: 1,
                DiagnosisClasses.AUTHENTICATION_FAILURE: 2,
                DiagnosisClasses.ISSUER_DECLINE: 3,
                DiagnosisClasses.TRANSIENT_PROVIDER_TIMEOUT: 4,
                DiagnosisClasses.DUPLICATE_OR_CONFLICTING_ATTEMPT: 5,
                DiagnosisClasses.PROVIDER_DEGRADATION_SUSPECTED: 6,
            }
            valid_hypotheses.sort(key=lambda h: (precedence_rank.get(h.diagnosis_class, 99), -h.score))
            winning = valid_hypotheses[0]
            winning_class = winning.diagnosis_class
            winning_score = winning.score

    diagnosis_id = f"diag_{hashlib.sha256(f'{manifest.identity.case_id}:{manifest.state.stage1_state_version}:{winning_class}:{DIAGNOSIS_ENGINE_VERSION}'.encode('utf-8')).hexdigest()[:32]}"

    return DiagnosisResult(
        diagnosis_id=diagnosis_id,
        case_id=manifest.identity.case_id,
        stage1_state_version=manifest.state.stage1_state_version,
        diagnosis_class=winning_class,
        score=winning_score,
        confidence=min(1.0, max(0.0, winning_score)),
        evidence_ids=supporting_ids,
        contradiction_ids=contradiction_ids,
        competing_hypotheses=hypotheses,
        engine_version=DIAGNOSIS_ENGINE_VERSION,
        created_at=datetime.now(timezone.utc),
        status="CURRENT",
    )

from datetime import datetime, timezone

from recovery_service.stage2.compliance import EligibilityStates, evaluate_compliance_eligibility
from recovery_service.stage2.diagnosis_engine import evaluate_diagnosis
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.schemas import RecoveryCaseContract


def _sample_contract(state: str = "FAILED", reason: str = "CARD_DECLINED") -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id="rc_comp_1",
        payment_id="pay_comp_1",
        recovery_episode_id="evt_fail",
        merchant_id="acc_comp",
        amount=25000,
        currency="INR",
        state=state,
        state_confidence=0.99,
        failure_evidence={"reason": reason},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail"],
        stage1_state_version=1,
    )


def test_compliance_gate_sequence_and_fail_closed():
    contract = _sample_contract("FAILED", "CARD_DECLINED")
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)

    elig = evaluate_compliance_eligibility(manifest, diag, attempt_count=1)
    assert elig.eligibility == EligibilityStates.ELIGIBLE
    assert elig.attempts_remaining == 2


def test_compliance_gate_max_attempts_exceeded_blocks():
    contract = _sample_contract("FAILED", "CARD_DECLINED")
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)

    elig = evaluate_compliance_eligibility(manifest, diag, attempt_count=3)
    assert elig.eligibility == EligibilityStates.BLOCKED
    assert elig.advice_code == "MAX_ATTEMPTS_EXCEEDED"


def test_compliance_gate_captured_payment_blocks():
    contract = _sample_contract("CAPTURED", "CARD_DECLINED")
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)

    elig = evaluate_compliance_eligibility(manifest, diag, attempt_count=1)
    assert elig.eligibility == EligibilityStates.BLOCKED
    assert elig.advice_code == "PAYMENT_TERMINAL_SUCCESS"

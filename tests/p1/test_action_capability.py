from datetime import datetime, timezone

from recovery_service.stage2.capability_matrix import generate_action_candidates
from recovery_service.stage2.compliance import evaluate_compliance_eligibility
from recovery_service.stage2.diagnosis_engine import evaluate_diagnosis
from recovery_service.stage2.failure_dna import compute_failure_dna, compute_temporal_features
from recovery_service.stage2.genome import assemble_recovery_genome
from recovery_service.stage2.incident_clusterer import evaluate_incident_cluster
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.schemas import RecoveryCaseContract


def _build_genome(diag_reason: str = "CARD_DECLINED", attempts: int = 1):
    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_cap_1",
        payment_id="pay_cap_1",
        recovery_episode_id="evt_fail",
        merchant_id="acc_cap",
        amount=50000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": diag_reason, "gateway": "HDFC"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail"],
        stage1_state_version=1,
    )

    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    fdna = compute_failure_dna(manifest)
    temporal = compute_temporal_features(manifest)
    incident = evaluate_incident_cluster(fdna, temporal, manifest)
    compliance = evaluate_compliance_eligibility(manifest, diag, attempt_count=attempts)

    return assemble_recovery_genome(manifest, diag, fdna, temporal, incident, compliance)


def test_action_capability_issuer_decline():
    genome = _build_genome("CARD_DECLINED")
    candidates = generate_action_candidates(genome)
    action_types = [c.action_type for c in candidates]

    assert "RETRY_LATER" in action_types
    assert "PAYMENT_LINK" in action_types
    assert "ALTERNATE_RAIL" in action_types
    assert "STOP" in action_types
    assert "RE_AUTH" not in action_types


def test_action_capability_blocked_compliance_forces_stop_only():
    # Max attempts 3 exceeded -> compliance BLOCKED
    genome = _build_genome("CARD_DECLINED", attempts=3)
    candidates = generate_action_candidates(genome)
    action_types = [c.action_type for c in candidates]

    assert action_types == ["STOP"]
    assert candidates[0].reason == "COMPLIANCE_BLOCKED_FORCES_STOP"

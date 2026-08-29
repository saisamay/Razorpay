from datetime import datetime, timezone

from recovery_service.stage2.failure_dna import compute_failure_dna, compute_temporal_features
from recovery_service.stage2.incident_clusterer import IncidentStates, evaluate_incident_cluster
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.schemas import RecoveryCaseContract


def _sample_contract(case_id: str = "rc_p1_inc_1") -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id="evt_fail",
        merchant_id="acc_p1",
        amount=50000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "GATEWAY_TIMEOUT", "gateway": "HDFC"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail"],
        stage1_state_version=1,
    )


def test_incident_intelligence_isolated_failure_is_normal():
    contract = _sample_contract("rc_single")
    manifest = normalize_evidence(contract)
    fdna = compute_failure_dna(manifest)
    temporal = compute_temporal_features(manifest)

    cluster = evaluate_incident_cluster(fdna, temporal, manifest)
    assert cluster.status == IncidentStates.NORMAL
    assert cluster.incident_id == "NO_INCIDENT"
    assert cluster.affected_case_count == 1


def test_incident_intelligence_systemic_degradation_detection():
    contract = _sample_contract("rc_systemic")
    manifest = normalize_evidence(contract)
    fdna = compute_failure_dna(manifest)
    temporal = compute_temporal_features(manifest)

    recent_fps = [
        {"dimensions": {"provider": "HDFC", "time_window": fdna.time_window}}
        for _ in range(5)
    ]

    cluster = evaluate_incident_cluster(fdna, temporal, manifest, recent_fingerprints=recent_fps)
    assert cluster.status == IncidentStates.CONFIRMED
    assert cluster.incident_id != "NO_INCIDENT"
    assert cluster.affected_case_count == 6
    assert cluster.incident_confidence >= 0.85

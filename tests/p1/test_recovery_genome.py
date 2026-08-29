from datetime import datetime, timezone

from recovery_service.stage2.compliance import evaluate_compliance_eligibility
from recovery_service.stage2.diagnosis_engine import evaluate_diagnosis
from recovery_service.stage2.failure_dna import compute_failure_dna, compute_temporal_features
from recovery_service.stage2.genome import assemble_recovery_genome
from recovery_service.stage2.incident_clusterer import evaluate_incident_cluster
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.schemas import RecoveryCaseContract, RecoveryGenome


def test_recovery_genome_assembly_and_immutability():
    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_gen_1",
        payment_id="pay_gen_1",
        recovery_episode_id="evt_fail",
        merchant_id="acc_gen",
        amount=150000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "BAD_REQUEST_ERROR", "gateway": "HDFC", "issuer": "ICICI"},
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
    compliance = evaluate_compliance_eligibility(manifest, diag)

    genome = assemble_recovery_genome(manifest, diag, fdna, temporal, incident, compliance)

    assert isinstance(genome, RecoveryGenome)
    assert genome.case_id == "rc_gen_1"
    assert genome.genome_id.startswith("genome_")
    assert genome.p0_source.diagnosis_class == "ISSUER_DECLINE"
    assert genome.p0_source.recoverable_amount == 0
    assert genome.p1_source.compliance_eligibility == "ELIGIBLE"
    assert genome.provenance.genome_schema_version == "1.0"

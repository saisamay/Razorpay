from datetime import datetime, timezone

from recovery_service.stage2.capability_matrix import generate_action_candidates
from recovery_service.stage2.compliance import evaluate_compliance_eligibility
from recovery_service.stage2.counterfactual import evaluate_counterfactual_candidates
from recovery_service.stage2.diagnosis_engine import evaluate_diagnosis
from recovery_service.stage2.failure_dna import compute_failure_dna, compute_temporal_features
from recovery_service.stage2.genome import assemble_recovery_genome
from recovery_service.stage2.incident_clusterer import evaluate_incident_cluster
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.schemas import CounterfactualSimulation, RecoveryCaseContract


def test_counterfactual_evaluation_same_snapshot_batch():
    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_cf_1",
        payment_id="pay_cf_1",
        recovery_episode_id="evt_fail",
        merchant_id="acc_cf",
        amount=100000,
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

    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    fdna = compute_failure_dna(manifest)
    temporal = compute_temporal_features(manifest)
    incident = evaluate_incident_cluster(fdna, temporal, manifest)
    compliance = evaluate_compliance_eligibility(manifest, diag)
    genome = assemble_recovery_genome(manifest, diag, fdna, temporal, incident, compliance)

    candidates = generate_action_candidates(genome)
    simulations = evaluate_counterfactual_candidates(genome, candidates)

    assert len(simulations) == len(candidates)
    batch_ids = {s.comparison_batch_id for s in simulations}
    # PDF Critical Rule: All candidate actions MUST be evaluated in the exact same snapshot batch!
    assert len(batch_ids) == 1

    for sim in simulations:
        assert isinstance(sim, CounterfactualSimulation)
        assert len(sim.confidence_interval) == 2
        assert sim.counterfactual_method == "COLD_START_HEURISTIC"

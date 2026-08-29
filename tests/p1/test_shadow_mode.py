from datetime import datetime, timezone

from recovery_service.stage2.capability_matrix import generate_action_candidates
from recovery_service.stage2.compliance import evaluate_compliance_eligibility
from recovery_service.stage2.counterfactual import evaluate_counterfactual_candidates
from recovery_service.stage2.diagnosis_engine import evaluate_diagnosis
from recovery_service.stage2.failure_dna import compute_failure_dna, compute_temporal_features
from recovery_service.stage2.genome import assemble_recovery_genome
from recovery_service.stage2.incident_clusterer import evaluate_incident_cluster
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.optimizer import optimize_recovery_decision
from recovery_service.stage2.schemas import RecoveryCaseContract, ShadowEvaluation
from recovery_service.stage2.shadow import create_shadow_evaluation


def test_shadow_mode_evaluation_logs_without_stage3_mutation():
    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_shd_1",
        payment_id="pay_shd_1",
        recovery_episode_id="evt_fail",
        merchant_id="acc_shd",
        amount=50000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "CARD_DECLINED", "gateway": "HDFC"},
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
    proposal = optimize_recovery_decision(genome, simulations)

    shadow = create_shadow_evaluation(genome, proposal, baseline_action="STOP")

    assert isinstance(shadow, ShadowEvaluation)
    assert shadow.case_id == "rc_shd_1"
    assert shadow.baseline_action == "STOP"
    assert shadow.stage2_proposed_action == proposal.selected_action
    assert shadow.baseline_outcome == "FAILED"
    assert shadow.shadow_id.startswith("shd_")

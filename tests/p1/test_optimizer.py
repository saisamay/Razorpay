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
from recovery_service.stage2.schemas import DecisionProposal, RecoveryCaseContract


def test_optimizer_selects_max_expected_net_value():
    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_opt_1",
        payment_id="pay_opt_1",
        recovery_episode_id="evt_fail",
        merchant_id="acc_opt",
        amount=150000,
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

    proposal = optimize_recovery_decision(genome, simulations)

    assert isinstance(proposal, DecisionProposal)
    assert proposal.case_id == "rc_opt_1"
    assert proposal.selected_action in [c.action_type for c in candidates]
    assert proposal.expected_net_value >= 0.0
    assert proposal.proposal_id.startswith("prop_")

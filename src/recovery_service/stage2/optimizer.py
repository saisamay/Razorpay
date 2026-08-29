from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .schemas import CounterfactualSimulation, DecisionProposal, RecoveryGenome


OPTIMIZER_VERSION = "1.0"


def optimize_recovery_decision(
    genome: RecoveryGenome,
    simulations: list[CounterfactualSimulation],
    *,
    execution_cost_map: dict[str, float] | None = None,
) -> DecisionProposal:
    """Select the action that maximizes Expected Net Value subject to compliance and safety constraints."""

    now = datetime.now(timezone.utc)
    recoverable = float(genome.p0_source.recoverable_amount or 1000)
    costs = execution_cost_map or {
        "RETRY_NOW": 1.0,
        "RETRY_LATER": 2.0,
        "ALTERNATE_RAIL": 5.0,
        "PAYMENT_LINK": 15.0,
        "RE_AUTH": 8.0,
        "STOP": 0.0,
    }

    best_sim: CounterfactualSimulation | None = None
    max_net_value = -1e9

    for sim in simulations:
        exec_cost = costs.get(sim.action_type, 5.0)
        friction_cost = sim.friction_score
        risk_penalty = 5.0 if sim.action_type == "RETRY_NOW" and genome.p1_source.incident_id != "NO_INCIDENT" else 0.0
        compliance_penalty = 1000.0 if genome.p1_source.compliance_eligibility == "BLOCKED" and sim.action_type != "STOP" else 0.0

        net_value = (sim.predicted_p_success * recoverable) - exec_cost - friction_cost - risk_penalty - compliance_penalty
        sim.predicted_expected_value = net_value

        if net_value > max_net_value:
            max_net_value = net_value
            best_sim = sim

    if best_sim is None or max_net_value < 0:
        # Fallback to STOP if net value is negative or no simulations
        selected_action = "STOP"
        p_success = 0.0
        ci = [0.0, 0.0]
        net_val = 0.0
        reasons = ["NEGATIVE_EXPECTED_VALUE_FORCES_STOP"]
    else:
        selected_action = best_sim.action_type
        p_success = best_sim.predicted_p_success
        ci = best_sim.confidence_interval
        net_val = max_net_value
        reasons = [f"OPTIMAL_NET_VALUE_{selected_action}"]

    proposal_raw = f"{genome.genome_id}:{selected_action}:{OPTIMIZER_VERSION}:{now.isoformat()}"
    proposal_id = f"prop_{hashlib.sha256(proposal_raw.encode('utf-8')).hexdigest()[:32]}"

    return DecisionProposal(
        proposal_id=proposal_id,
        case_id=genome.case_id,
        genome_id=genome.genome_id,
        diagnosis_id=genome.p0_source.diagnosis_id,
        incident_id=genome.p1_source.incident_id,
        candidate_actions=[s.action_type for s in simulations],
        selected_action=selected_action,
        predicted_success_probability=p_success,
        confidence_interval=ci,
        expected_net_value=net_val,
        execution_cost=costs.get(selected_action, 0.0),
        customer_friction_cost=best_sim.friction_score if best_sim else 0.0,
        risk_penalty=0.0,
        compliance_penalty=0.0,
        model_version="1.0",
        calibration_version="1.0",
        optimizer_version=OPTIMIZER_VERSION,
        decision_reason_codes=reasons,
        proposal_schema_version="1.0",
        created_at=now,
    )

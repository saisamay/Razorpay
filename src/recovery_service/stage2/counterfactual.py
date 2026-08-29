from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .outcome_model import CALIBRATION_VERSION, MODEL_VERSION, predict_action_outcome_cold_start
from .schemas import ActionCandidate, CounterfactualSimulation, RecoveryGenome


def evaluate_counterfactual_candidates(
    genome: RecoveryGenome, candidates: list[ActionCandidate]
) -> list[CounterfactualSimulation]:
    """Evaluate counterfactual outcome predictions for all candidate actions under the SAME RecoveryGenome snapshot."""

    now = datetime.now(timezone.utc)
    batch_raw = f"{genome.genome_id}:{len(candidates)}:{now.isoformat()}"
    comparison_batch_id = f"batch_{hashlib.sha256(batch_raw.encode('utf-8')).hexdigest()[:16]}"

    simulations: list[CounterfactualSimulation] = []

    recoverable_amount = float(genome.p0_source.recoverable_amount or 1000)

    for candidate in candidates:
        p_success, ci, friction = predict_action_outcome_cold_start(genome, candidate)
        expected_val = p_success * recoverable_amount - friction

        raw_sim = f"{genome.genome_id}:{candidate.candidate_action_id}:{comparison_batch_id}"
        simulation_id = f"sim_{hashlib.sha256(raw_sim.encode('utf-8')).hexdigest()[:32]}"

        simulations.append(CounterfactualSimulation(
            simulation_id=simulation_id,
            case_id=genome.case_id,
            genome_id=genome.genome_id,
            candidate_action_id=candidate.candidate_action_id,
            action_type=candidate.action_type,
            predicted_p_success=p_success,
            confidence_interval=ci,
            predicted_expected_value=expected_val,
            friction_score=friction,
            counterfactual_method="COLD_START_HEURISTIC",
            model_version=MODEL_VERSION,
            calibration_version=CALIBRATION_VERSION,
            comparison_batch_id=comparison_batch_id,
            created_at=now,
        ))

    return simulations

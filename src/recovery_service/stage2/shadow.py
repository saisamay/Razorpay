from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .schemas import DecisionProposal, RecoveryGenome, ShadowEvaluation


def create_shadow_evaluation(
    genome: RecoveryGenome, proposal: DecisionProposal, baseline_action: str = "STOP"
) -> ShadowEvaluation:
    """Create a shadow mode evaluation artifact comparing Stage 2 proposal against baseline action without modifying Stage 3 execution."""

    now = datetime.now(timezone.utc)
    delta = "DELTA_PROPOSED" if proposal.selected_action != baseline_action else "NO_DELTA"

    raw = f"{genome.genome_id}:{proposal.proposal_id}:shadow:{now.isoformat()}"
    shadow_id = f"shd_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"

    would_recover = (proposal.predicted_success_probability * (genome.p0_source.recoverable_amount or 1000)) if proposal.selected_action != "STOP" else 0.0

    return ShadowEvaluation(
        shadow_id=shadow_id,
        case_id=genome.case_id,
        genome_id=genome.genome_id,
        baseline_action=baseline_action,
        stage2_proposed_action=proposal.selected_action,
        baseline_outcome="FAILED",
        actual_outcome="UNKNOWN",
        stage2_predicted_success=proposal.predicted_success_probability,
        stage2_confidence_interval=proposal.confidence_interval,
        would_have_recovered_amount=would_recover,
        actual_recovered_amount=0.0,
        decision_delta=delta,
        created_at=now,
    )

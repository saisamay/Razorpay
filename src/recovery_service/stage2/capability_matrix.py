from __future__ import annotations

import hashlib
from typing import Any

from .schemas import ActionCandidate, RecoveryGenome


CAPABILITY_RULESET_VERSION = "1.0"


class ActionTypes:
    RETRY_NOW = "RETRY_NOW"
    RETRY_LATER = "RETRY_LATER"
    ALTERNATE_RAIL = "ALTERNATE_RAIL"
    PAYMENT_LINK = "PAYMENT_LINK"
    RE_AUTH = "RE_AUTH"
    STOP = "STOP"


ALL_ACTIONS = [
    ActionTypes.RETRY_NOW,
    ActionTypes.RETRY_LATER,
    ActionTypes.ALTERNATE_RAIL,
    ActionTypes.PAYMENT_LINK,
    ActionTypes.RE_AUTH,
    ActionTypes.STOP,
]


def generate_action_candidates(genome: RecoveryGenome) -> list[ActionCandidate]:
    """Generate technically and compliance-valid action candidates per RecoveryGenome snapshot."""

    diag_class = genome.p0_source.diagnosis_class
    eligibility = genome.p1_source.compliance_eligibility
    rail = genome.p0_source.rail

    candidates: list[ActionCandidate] = []

    # Helper to append candidate
    def add_candidate(action: str, state: str = "ELIGIBLE", reason: str = "COMPATIBLE"):
        raw = f"{genome.genome_id}:{action}:{CAPABILITY_RULESET_VERSION}"
        candidate_id = f"cand_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"
        candidates.append(ActionCandidate(
            candidate_action_id=candidate_id,
            genome_id=genome.genome_id,
            action_type=action,
            rail=rail,
            capability_rule_version=CAPABILITY_RULESET_VERSION,
            eligibility_state=state,
            reason=reason,
        ))

    # If compliance is BLOCKED -> only STOP is valid
    if eligibility == "BLOCKED":
        add_candidate(ActionTypes.STOP, "ELIGIBLE", "COMPLIANCE_BLOCKED_FORCES_STOP")
        return candidates

    # 1. ISSUER_DECLINE
    if diag_class == "ISSUER_DECLINE":
        add_candidate(ActionTypes.RETRY_LATER, "ELIGIBLE", "ALLOW_RETRY_LATER_FOR_DECLINE")
        add_candidate(ActionTypes.PAYMENT_LINK, "ELIGIBLE", "ALLOW_CUSTOMER_PAYMENT_LINK")
        add_candidate(ActionTypes.ALTERNATE_RAIL, "ELIGIBLE", "ALLOW_RAIL_SWITCHING")
        add_candidate(ActionTypes.STOP, "ELIGIBLE", "ALLOW_STOP_SAFE_FALLBACK")

    # 2. TRANSIENT_PROVIDER_TIMEOUT
    elif diag_class in {"TRANSIENT_PROVIDER_TIMEOUT", "PROVIDER_DEGRADATION_SUSPECTED"}:
        if eligibility == "DELAY_REQUIRED":
            add_candidate(ActionTypes.RETRY_LATER, "ELIGIBLE", "REQUIRED_COOLDOWN_DELAY")
        else:
            add_candidate(ActionTypes.RETRY_NOW, "ELIGIBLE", "ALLOW_IMMEDIATE_RETRY")
            add_candidate(ActionTypes.RETRY_LATER, "ELIGIBLE", "ALLOW_SCHEDULED_RETRY")
        add_candidate(ActionTypes.ALTERNATE_RAIL, "ELIGIBLE", "ALLOW_ALTERNATE_PROVIDER_RAIL")
        add_candidate(ActionTypes.PAYMENT_LINK, "ELIGIBLE", "ALLOW_PAYMENT_LINK")
        add_candidate(ActionTypes.STOP, "ELIGIBLE", "ALLOW_STOP")

    # 3. AUTHENTICATION_FAILURE
    elif diag_class == "AUTHENTICATION_FAILURE":
        add_candidate(ActionTypes.RE_AUTH, "ELIGIBLE", "ALLOW_RE_AUTHENTICATION")
        add_candidate(ActionTypes.PAYMENT_LINK, "ELIGIBLE", "ALLOW_PAYMENT_LINK")
        add_candidate(ActionTypes.STOP, "ELIGIBLE", "ALLOW_STOP")

    # Default / Unknown
    else:
        add_candidate(ActionTypes.RETRY_LATER, "ELIGIBLE", "DEFAULT_RETRY_LATER")
        add_candidate(ActionTypes.PAYMENT_LINK, "ELIGIBLE", "DEFAULT_PAYMENT_LINK")
        add_candidate(ActionTypes.STOP, "ELIGIBLE", "DEFAULT_STOP")

    return candidates

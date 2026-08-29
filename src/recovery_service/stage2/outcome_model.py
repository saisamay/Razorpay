from __future__ import annotations

import math
from typing import Any

from .schemas import ActionCandidate, RecoveryGenome


MODEL_VERSION = "1.0"
CALIBRATION_VERSION = "1.0"


def predict_action_outcome_cold_start(
    genome: RecoveryGenome, candidate: ActionCandidate
) -> tuple[float, list[float], float]:
    """Cold-start heuristic outcome prediction for P(success | RecoveryGenome, action).

    Returns (calibrated_p_success, confidence_interval, friction_score).
    """

    action = candidate.action_type
    diag_class = genome.p0_source.diagnosis_class
    incident_status = genome.p1_source.incident_id != "NO_INCIDENT"

    # Base priors per action
    if action == "STOP":
        return 0.0, [0.0, 0.0], 0.0

    if action == "PAYMENT_LINK":
        # High friction, moderate success
        p_base = 0.65
        friction = 25.0
    elif action == "ALTERNATE_RAIL":
        # High success if provider incident is active
        p_base = 0.70 if incident_status else 0.50
        friction = 5.0
    elif action == "RETRY_LATER":
        # Good success for transient issues after cooldown
        p_base = 0.60 if diag_class in {"TRANSIENT_PROVIDER_TIMEOUT", "ISSUER_DECLINE"} else 0.40
        friction = 2.0
    elif action == "RETRY_NOW":
        # Low success if provider is degraded
        p_base = 0.15 if incident_status else 0.45
        friction = 1.0
    elif action == "RE_AUTH":
        # Good success for auth failures
        p_base = 0.75 if diag_class == "AUTHENTICATION_FAILURE" else 0.20
        friction = 10.0
    else:
        p_base = 0.30
        friction = 5.0

    # Apply Platt scaling calibration adjustment
    calibrated_p = 1.0 / (1.0 + math.exp(-2.0 * (p_base - 0.5)))
    calibrated_p = min(0.95, max(0.01, calibrated_p))

    # Bounded confidence interval [p - margin, p + margin]
    margin = 0.15 if incident_status else 0.10
    ci = [max(0.0, calibrated_p - margin), min(1.0, calibrated_p + margin)]

    return calibrated_p, ci, friction

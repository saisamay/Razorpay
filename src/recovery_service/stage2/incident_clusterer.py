from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .schemas import EvidenceManifest, FailureDNA, IncidentCluster, TemporalFeatures


INCIDENT_ENGINE_VERSION = "1.0"


class IncidentStates:
    NORMAL = "NORMAL"
    ANOMALY = "ANOMALY"
    INCIDENT_CANDIDATE = "INCIDENT_CANDIDATE"
    CONFIRMED = "CONFIRMED"
    DEGRADING = "DEGRADING"
    RESOLVED = "RESOLVED"


def evaluate_incident_cluster(
    fdna: FailureDNA,
    temporal: TemporalFeatures,
    manifest: EvidenceManifest,
    recent_fingerprints: list[dict[str, Any]] | None = None,
) -> IncidentCluster:
    """Evaluate cross-payment systemic incident signals across FailureDNA clusters."""

    now = datetime.now(timezone.utc)
    provider = fdna.provider or "UNKNOWN"
    issuer = fdna.issuer or "UNKNOWN"

    dimensions = {
        "provider": provider,
        "issuer": issuer,
        "failure_code": fdna.failure_code,
        "time_window": fdna.time_window,
    }

    # Count matching recent fingerprints in the same time window / provider
    matching_count = 1
    if recent_fingerprints:
        for fp in recent_fingerprints:
            dims = fp.get("dimensions", {})
            if dims.get("provider") == provider and dims.get("time_window") == fdna.time_window:
                matching_count += 1

    # State transitions based on aggregate evidence
    if matching_count >= 10:
        status = IncidentStates.DEGRADING
        failure_rate_delta = 0.45
        confidence = 0.95
    elif matching_count >= 5:
        status = IncidentStates.CONFIRMED
        failure_rate_delta = 0.30
        confidence = 0.85
    elif matching_count >= 3:
        status = IncidentStates.INCIDENT_CANDIDATE
        failure_rate_delta = 0.15
        confidence = 0.70
    elif matching_count >= 2:
        status = IncidentStates.ANOMALY
        failure_rate_delta = 0.05
        confidence = 0.50
    else:
        # Isolated single failure -> NORMAL
        status = IncidentStates.NORMAL
        failure_rate_delta = 0.0
        confidence = 0.0

    raw = f"{provider}:{issuer}:{fdna.time_window}:{INCIDENT_ENGINE_VERSION}"
    incident_id = f"inc_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"

    return IncidentCluster(
        incident_id=incident_id if status != IncidentStates.NORMAL else "NO_INCIDENT",
        dimensions=dimensions,
        affected_case_count=matching_count,
        affected_volume_bucket=manifest.features.amount_bucket,
        failure_rate_delta=failure_rate_delta,
        baseline_failure_rate=0.05,
        current_failure_rate=min(1.0, 0.05 + failure_rate_delta),
        incident_confidence=confidence,
        status=status,
        started_at=manifest.created_at,
        last_seen_at=now,
        engine_version=INCIDENT_ENGINE_VERSION,
    )

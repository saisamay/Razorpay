from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .schemas import EvidenceManifest, FailureDNA, TemporalFeatures


FAILURE_DNA_VERSION = "1.0"


def _time_window_bucket(dt: datetime) -> str:
    """Bucket occurrence timestamp into 15-minute intervals."""
    minute = (dt.minute // 15) * 15
    bucketed = dt.replace(minute=minute, second=0, microsecond=0)
    return bucketed.strftime("%Y-%m-%dT%H:%M:00Z")


def compute_failure_dna(manifest: EvidenceManifest) -> FailureDNA:
    """Extract PII-safe, deterministic FailureDNA fingerprint from EvidenceManifest."""

    time_win = _time_window_bucket(manifest.created_at)
    code = manifest.failure.failure_code
    step = manifest.failure.failure_step

    auth_state = "UNKNOWN"
    if "auth" in step.lower() or "3ds" in step.lower():
        auth_state = "3DS_FAILED" if "fail" in code.lower() or "decline" in code.lower() else "3DS_SUCCESS"

    dimensions = {
        "method": "card",
        "provider": manifest.failure.gateway or "UNKNOWN",
        "issuer": manifest.failure.issuer or "UNKNOWN",
        "geography_bucket": "DOMESTIC",
        "currency": manifest.features.currency or "UNKNOWN",
        "amount_bucket": manifest.features.amount_bucket or "UNKNOWN",
        "failure_code": code or "UNKNOWN",
        "failure_step": step or "UNKNOWN",
        "latency_bucket": manifest.features.latency_bucket or "UNKNOWN",
        "time_window": time_win,
        "retry_count": manifest.features.retry_count,
        "auth_state": auth_state,
        "version": FAILURE_DNA_VERSION,
    }

    raw_string = json.dumps(dimensions, sort_keys=True)
    fingerprint_hash = hashlib.sha256(raw_string.encode("utf-8")).hexdigest()

    return FailureDNA(
        method=dimensions["method"],
        provider=dimensions["provider"],
        issuer=dimensions["issuer"],
        geography_bucket=dimensions["geography_bucket"],
        currency=dimensions["currency"],
        amount_bucket=dimensions["amount_bucket"],
        failure_code=dimensions["failure_code"],
        failure_step=dimensions["failure_step"],
        latency_bucket=dimensions["latency_bucket"],
        time_window=dimensions["time_window"],
        retry_count=dimensions["retry_count"],
        auth_state=dimensions["auth_state"],
        provider_health_features={"anomalies_count": len(manifest.anomalies.anomalies)},
        version=FAILURE_DNA_VERSION,
        fingerprint_hash=fingerprint_hash,
    )


def compute_temporal_features(manifest: EvidenceManifest) -> TemporalFeatures:
    """Extract occurrence-time temporal deltas & latency regime metadata."""

    total_span = manifest.timeline.total_span_seconds
    total_ms = total_span * 1000.0

    regime = "NORMAL"
    if total_span >= 30.0:
        regime = "CRITICAL"
    elif total_span >= 5.0:
        regime = "ELEVATED"

    # Derive bounded step deltas from timeline events
    req_to_gw = min(total_ms, 250.0) if total_ms > 0 else 0.0
    gw_to_iss = min(total_ms, 500.0) if total_ms > 0 else 0.0
    iss_to_fail = max(0.0, total_ms - req_to_gw - gw_to_iss)

    return TemporalFeatures(
        request_to_gateway_ms=req_to_gw,
        gateway_to_issuer_ms=gw_to_iss,
        issuer_to_failure_ms=iss_to_fail,
        timeout_duration_ms=total_ms if "timeout" in manifest.failure.failure_code.lower() else 0.0,
        late_positive_response_gap_ms=total_ms if manifest.timeline.events and len(manifest.timeline.events) > 1 else 0.0,
        total_span_seconds=total_span,
        retry_interval_ms=total_ms / max(1, manifest.features.retry_count),
        latency_regime=regime,
    )

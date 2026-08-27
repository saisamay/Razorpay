from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .schemas import (
    AnomaliesSection,
    DerivedFeaturesSection,
    EvidenceManifest,
    FailureSection,
    IdentitySection,
    PrivacySection,
    ProvenanceSection,
    ReconciliationSection,
    RecoveryCaseContract,
    StateSection,
    TimelineItem,
    TimelineSection,
)


NORMALIZER_VERSION = "1.0"


def _amount_bucket(amount: int | None) -> str:
    if amount is None:
        return "NOT_AVAILABLE"
    if amount < 1000:
        return "<1k"
    if amount < 10000:
        return "1k-10k"
    if amount < 50000:
        return "10k-50k"
    if amount < 100000:
        return "50k-100k"
    return ">100k"


def _latency_bucket(seconds: float | None) -> str:
    if seconds is None:
        return "NOT_AVAILABLE"
    if seconds < 1.0:
        return "<1s"
    if seconds < 5.0:
        return "1s-5s"
    if seconds < 30.0:
        return "5s-30s"
    return ">30s"


def compute_provenance_hash(contract: RecoveryCaseContract) -> str:
    payload = {
        "case_id": contract.case_id,
        "payment_id": contract.payment_id,
        "stage1_state_version": contract.stage1_state_version,
        "state": contract.state,
        "source_event_ids": sorted(contract.source_event_ids),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_evidence(
    contract: RecoveryCaseContract,
    *,
    timeline_events: list[dict[str, Any]] | None = None,
    reconciliation_evidence: dict[str, Any] | None = None,
) -> EvidenceManifest:
    """Pure deterministic normalizer producing canonical EvidenceManifest."""

    provenance_hash = compute_provenance_hash(contract)
    manifest_id = f"em_{hashlib.sha256(f'{contract.case_id}:{contract.stage1_state_version}:{NORMALIZER_VERSION}'.encode('utf-8')).hexdigest()[:32]}"

    # Identity Section
    identity = IdentitySection(
        case_id=contract.case_id,
        payment_id=contract.payment_id,
        order_id=contract.order_id or "NOT_AVAILABLE",
        merchant_id=contract.merchant_id or "NOT_AVAILABLE",
    )

    # State Section
    state_sec = StateSection(
        state=contract.state,
        stage1_state_version=contract.stage1_state_version,
        state_confidence=contract.state_confidence,
    )

    # Timeline Section
    items: list[TimelineItem] = []
    total_span = 0.0
    if timeline_events:
        timeline_events_sorted = sorted(timeline_events, key=lambda x: x.get("occurred_at", datetime.min))
        t0 = timeline_events_sorted[0].get("occurred_at") if timeline_events_sorted else None
        for evt in timeline_events_sorted:
            occurred = evt.get("occurred_at")
            delta = 0.0
            if isinstance(occurred, datetime) and isinstance(t0, datetime):
                delta = max(0.0, (occurred - t0).total_seconds())
            items.append(TimelineItem(
                event_id=evt.get("event_id", "UNKNOWN"),
                event_type=evt.get("event_type", "UNKNOWN"),
                occurred_at=occurred if isinstance(occurred, datetime) else datetime.now(timezone.utc),
                delta_seconds=delta,
            ))
        if items:
            total_span = items[-1].delta_seconds
    else:
        # Fallback to contract first_seen / last_seen span
        span = (contract.last_seen_at - contract.first_seen_at).total_seconds()
        total_span = max(0.0, span)

    timeline_sec = TimelineSection(events=items, total_span_seconds=total_span)

    # Failure Section
    failure_details = contract.failure_evidence or {}
    failure_sec = FailureSection(
        failure_code=str(failure_details.get("reason") or failure_details.get("failure_code") or "UNKNOWN"),
        failure_step=str(failure_details.get("failure_step") or failure_details.get("step") or "UNKNOWN"),
        gateway=str(failure_details.get("gateway") or "UNKNOWN"),
        issuer=str(failure_details.get("issuer") or "UNKNOWN"),
        raw_details=failure_details,
    )

    # Anomalies Section
    anomalies_sec = AnomaliesSection(
        anomalies=failure_details.get("anomalies") or [],
        contradictions=failure_details.get("contradictions") or [],
        late_events=failure_details.get("late_events") or [],
    )

    # Reconciliation Section
    rec_sec = ReconciliationSection(
        status=str(reconciliation_evidence.get("status") if reconciliation_evidence else "NOT_AVAILABLE"),
        reconciled_at=reconciliation_evidence.get("reconciled_at") if reconciliation_evidence else None,
        evidence=reconciliation_evidence or {},
    )

    # Derived Features Section
    features_sec = DerivedFeaturesSection(
        amount_bucket=_amount_bucket(contract.amount),
        currency=contract.currency or "UNKNOWN",
        latency_bucket=_latency_bucket(total_span),
        retry_count=len(contract.source_event_ids),
    )

    # Provenance Section
    provenance_sec = ProvenanceSection(
        source_event_ids=sorted(contract.source_event_ids),
        normalizer_version=NORMALIZER_VERSION,
        provenance_hash=provenance_hash,
    )

    # Privacy Section
    privacy_sec = PrivacySection(classification="INTERNAL", pii_redacted=True)

    return EvidenceManifest(
        manifest_id=manifest_id,
        identity=identity,
        state=state_sec,
        timeline=timeline_sec,
        failure=failure_sec,
        anomalies=anomalies_sec,
        reconciliation=rec_sec,
        features=features_sec,
        provenance=provenance_sec,
        privacy=privacy_sec,
        created_at=datetime.now(timezone.utc),
    )

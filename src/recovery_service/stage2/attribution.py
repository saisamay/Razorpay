from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PaymentState, RawEvent, RecoveryCase
from .models import DecisionProposalRecord, OutcomeAttributionRecord
from .schemas import OutcomeAttribution


ATTRIBUTION_RULE_VERSION = "1.0"
DEFAULT_ATTRIBUTION_WINDOW_HOURS = 72


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def evaluate_outcome_attribution(
    session: Session,
    case_id: str,
    *,
    experiment_id: str | None = None,
    assignment_id: str | None = None,
) -> OutcomeAttribution:
    """Evaluate authoritative outcome attribution for a RecoveryCase against payment events."""

    now = datetime.now(timezone.utc)
    case = session.get(RecoveryCase, case_id, with_for_update=True)
    if case is None:
        raise ValueError(f"RecoveryCase {case_id} not found")

    prop_rec = session.scalars(
        select(DecisionProposalRecord)
        .where(DecisionProposalRecord.case_id == case_id)
        .order_by(DecisionProposalRecord.stage1_state_version.desc())
    ).first()

    proposal_id = prop_rec.proposal_id if prop_rec else f"prop_unknown_{case_id}"
    proposal_time = _utc(prop_rec.created_at) if prop_rec else _utc(case.first_seen_at) or now
    first_seen = _utc(case.first_seen_at) or proposal_time

    win_start = min(first_seen, proposal_time)
    win_end = proposal_time + timedelta(hours=DEFAULT_ATTRIBUTION_WINDOW_HOURS)

    # Load canonical raw events for payment within window
    raw_events = session.scalars(
        select(RawEvent)
        .where(RawEvent.payment_id == case.payment_id)
        .order_by(RawEvent.occurred_at.asc())
    ).all()

    state = session.get(PaymentState, case.payment_id)
    state_version = state.state_version if state else 1

    gross = 0.0
    refunds = 0.0
    reversals = 0.0
    first_recovery_at: datetime | None = None
    source_event_ids: list[str] = []

    for ev in raw_events:
        evt_time = _utc(ev.occurred_at or ev.received_at)
        if evt_time and win_start <= evt_time <= win_end:
            etype = ev.event_type.lower()
            source_event_ids.append(ev.id)
            payload = ev.normalized_payload or {}

            if "captured" in etype or "authorized" in etype:
                if first_recovery_at is None:
                    first_recovery_at = evt_time
                amt = (payload.get("amount") or case.amount or 0) / 100.0
                gross = max(gross, amt)
            elif "refund" in etype:
                amt = (payload.get("amount") or 0) / 100.0
                refunds += amt
            elif "reversal" in etype:
                amt = (payload.get("amount") or 0) / 100.0
                reversals += amt

    # Calculate net verified recovered amount
    net_verified = max(0.0, gross - refunds - reversals)

    # Classify explicit outcome status
    recoverable_gross = (case.amount or 0) / 100.0
    if now < win_end and gross == 0.0 and (state is None or state.state not in {"CAPTURED", "AUTHORIZED"}):
        outcome_status = "OUTCOME_PENDING"
        verification_status = "PENDING"
    elif gross == 0.0:
        outcome_status = "NO_RECOVERY"
        verification_status = "VERIFIED"
    elif gross > 0.0 and refunds >= gross:
        outcome_status = "RECOVERED_THEN_REFUNDED"
        verification_status = "VERIFIED"
    elif gross > 0.0 and reversals >= gross:
        outcome_status = "RECOVERED_THEN_REVERSED"
        verification_status = "VERIFIED"
    elif gross < recoverable_gross:
        outcome_status = "PARTIALLY_RECOVERED"
        verification_status = "VERIFIED"
    else:
        outcome_status = "RECOVERED"
        verification_status = "VERIFIED"

    raw_attr = f"{case_id}:{proposal_id}:{ATTRIBUTION_RULE_VERSION}:{win_end.isoformat()}"
    attribution_id = f"attr_{hashlib.sha256(raw_attr.encode('utf-8')).hexdigest()[:32]}"

    finalized = now if outcome_status not in {"OUTCOME_PENDING", "OUTCOME_UNKNOWN"} else None

    # Database persistence
    existing_rec = session.get(OutcomeAttributionRecord, attribution_id, with_for_update=True)
    if existing_rec is None:
        rec = OutcomeAttributionRecord(
            attribution_id=attribution_id,
            case_id=case_id,
            payment_id=case.payment_id,
            experiment_id=experiment_id,
            assignment_id=assignment_id,
            proposal_id=proposal_id,
            proposal_timestamp=proposal_time,
            attribution_window_start=win_start,
            attribution_window_end=win_end,
            first_recovery_event_at=first_recovery_at,
            gross_recovered_amount=gross,
            refund_amount_within_window=refunds,
            reversal_amount_within_window=reversals,
            net_verified_recovered_amount=net_verified,
            outcome_status=outcome_status,
            verification_status=verification_status,
            source_event_ids=source_event_ids,
            payment_state_version=state_version,
            attribution_rule_version=ATTRIBUTION_RULE_VERSION,
            created_at=now,
            finalized_at=finalized,
        )
        session.add(rec)

    return OutcomeAttribution(
        attribution_id=attribution_id,
        case_id=case_id,
        payment_id=case.payment_id,
        experiment_id=experiment_id,
        assignment_id=assignment_id,
        proposal_id=proposal_id,
        proposal_timestamp=proposal_time,
        attribution_window_start=win_start,
        attribution_window_end=win_end,
        first_recovery_event_at=first_recovery_at,
        gross_recovered_amount=gross,
        refund_amount_within_window=refunds,
        reversal_amount_within_window=reversals,
        net_verified_recovered_amount=net_verified,
        outcome_status=outcome_status,
        verification_status=verification_status,
        source_event_ids=source_event_ids,
        payment_state_version=state_version,
        attribution_rule_version=ATTRIBUTION_RULE_VERSION,
        created_at=now,
        finalized_at=finalized,
    )

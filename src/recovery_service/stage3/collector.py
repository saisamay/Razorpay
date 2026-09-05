from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..models import RecoveryCase
from ..stage2.f5.repository import get_enforcement_log_by_proposal
from ..stage2.models import DecisionProposalRecord, OutcomeAttributionRecord, Stage2Case
from .models import Stage3OutcomeObservation
from .repository import Stage3OutcomeObservationRepository
from .schemas import OutcomeCollectionResult, OutcomeCollectionStatus

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def collect_outcome(
    session: Session,
    attribution_id: str,
    merchant_id: str | None = None,
    repository: Stage3OutcomeObservationRepository = Stage3OutcomeObservationRepository(),
) -> OutcomeCollectionResult:
    """Collects a finalized Stage 2 OutcomeAttributionRecord into an immutable Stage3OutcomeObservation.

    Executes:
    1. Canonical attribution lookup
    2. Finalization readiness verification (finalized_at is not None AND verification_status == 'VERIFIED')
    3. Idempotency pre-check
    4. Authoritative tenant (merchant_id) resolution & verification
    5. F5 enforcement & decision policy context resolution
    6. Distinct field provenance mapping for executed_action, enforcement_decision, outcome_status, case_status
    7. Recovery latency derivation and timestamp validation
    8. Atomic database persistence with unique constraint idempotency protection
    """
    # 1. Load canonical attribution record
    attribution = session.get(OutcomeAttributionRecord, attribution_id)
    if attribution is None:
        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.NOT_FOUND,
            message=f"OutcomeAttributionRecord '{attribution_id}' not found",
        )

    # 2. Finalization readiness check (canonical verified + finalized_at check)
    if (
        attribution.finalized_at is None
        or attribution.verification_status != "VERIFIED"
        or attribution.outcome_status in {"OUTCOME_PENDING", "OUTCOME_UNKNOWN"}
    ):
        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.NOT_READY,
            message=f"OutcomeAttributionRecord '{attribution_id}' is not finalized/ready for Stage 3 observation",
        )

    # 3. Idempotency pre-check
    if repository.exists_by_attribution_id(session, attribution_id):
        existing = repository.get_by_attribution_id(session, attribution_id)
        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.ALREADY_COLLECTED,
            message=f"Stage3OutcomeObservation for attribution '{attribution_id}' already exists",
            merchant_id=existing.merchant_id if existing else None,
            observation_id=attribution_id,
            collected_at=existing.observed_at if existing else None,
        )

    # 4. Authoritative tenant (merchant_id) resolution
    recovery_case = session.get(RecoveryCase, attribution.case_id)
    auth_merchant_id = recovery_case.merchant_id if recovery_case else None

    if not auth_merchant_id:
        stage2_case = session.scalars(
            select(Stage2Case)
            .where(Stage2Case.case_id == attribution.case_id)
            .order_by(Stage2Case.stage1_state_version.desc())
        ).first()
        auth_merchant_id = stage2_case.merchant_id if stage2_case else None

    if not auth_merchant_id:
        enforcement_log = get_enforcement_log_by_proposal(session, attribution.proposal_id)
        auth_merchant_id = enforcement_log.merchant_id if enforcement_log else None

    if not auth_merchant_id:
        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.VALIDATION_FAILED,
            message=f"Unable to resolve authoritative merchant_id for attribution '{attribution_id}'",
        )

    # Tenant mismatch verification if caller supplied a merchant_id
    if merchant_id is not None and merchant_id != auth_merchant_id:
        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.TENANT_MISMATCH,
            message=f"Tenant mismatch: requested merchant '{merchant_id}' does not match authoritative merchant '{auth_merchant_id}'",
            merchant_id=auth_merchant_id,
        )

    # 5. Resolve F5 Enforcement & Policy context (0:1 relationship via proposal_id unique constraint)
    enforcement_log = get_enforcement_log_by_proposal(session, attribution.proposal_id)
    enforcement_id = enforcement_log.enforcement_id if enforcement_log else None
    policy_id = enforcement_log.policy_id if enforcement_log else None
    policy_version = enforcement_log.policy_version if enforcement_log else None
    experiment_id = (enforcement_log.experiment_id if enforcement_log else None) or attribution.experiment_id
    experiment_version = enforcement_log.experiment_version if enforcement_log else None

    stage2_case = session.scalars(
        select(Stage2Case)
        .where(Stage2Case.case_id == attribution.case_id)
        .order_by(Stage2Case.stage1_state_version.desc())
    ).first()

    prop_rec = session.get(DecisionProposalRecord, attribution.proposal_id)

    # 6. Distinct field provenance mapping
    if enforcement_log and enforcement_log.executed_action:
        executed_action = enforcement_log.executed_action
    elif prop_rec and prop_rec.selected_action:
        executed_action = prop_rec.selected_action
    else:
        executed_action = "UNKNOWN"

    enforcement_decision = enforcement_log.decision if enforcement_log else None
    outcome_status = attribution.outcome_status
    case_status = stage2_case.status if stage2_case else None

    # 7. Recovery latency derivation & timestamp sequence validation
    T_start = attribution.proposal_timestamp
    T_recovery = attribution.first_recovery_event_at

    recovery_latency_seconds: float | None = None
    if T_recovery is not None:
        t_start_utc = T_start if T_start.tzinfo is not None else T_start.replace(tzinfo=timezone.utc)
        t_rec_utc = T_recovery if T_recovery.tzinfo is not None else T_recovery.replace(tzinfo=timezone.utc)

        if t_rec_utc < t_start_utc:
            return OutcomeCollectionResult(
                attribution_id=attribution_id,
                status=OutcomeCollectionStatus.VALIDATION_FAILED,
                message=f"Invalid timestamp sequence: first_recovery_event_at ({t_rec_utc}) < proposal_timestamp ({t_start_utc})",
                merchant_id=auth_merchant_id,
            )
        recovery_latency_seconds = (t_rec_utc - t_start_utc).total_seconds()

    # 8. Construct & Persist Stage3OutcomeObservation
    observation = Stage3OutcomeObservation(
        attribution_id=attribution.attribution_id,
        case_id=attribution.case_id,
        payment_id=attribution.payment_id,
        proposal_id=attribution.proposal_id,
        enforcement_id=enforcement_id,
        merchant_id=auth_merchant_id,
        policy_id=policy_id,
        policy_version=policy_version,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        gross_recovered_amount=attribution.gross_recovered_amount,
        net_verified_recovered_amount=attribution.net_verified_recovered_amount,
        executed_action=executed_action,
        enforcement_decision=enforcement_decision,
        outcome_status=outcome_status,
        case_status=case_status,
        recovery_latency_seconds=recovery_latency_seconds,
        observed_at=utc_now(),
        finalized_at=attribution.finalized_at,
    )

    try:
        with session.begin_nested():
            repository.insert(session, observation)
            try:
                from ..stage2.ai_learning import ingest_stage3_outcome
                ingest_stage3_outcome(session, observation)
            except Exception as exc:
                logger.warning("AI Learning memory ingestion failed non-fatally: %s", exc)
            try:
                from .orchestrator import handle_outcome as handle_orchestration_outcome
                handle_orchestration_outcome(session, observation)
            except Exception as exc:
                logger.warning("Orchestration outcome handling failed non-fatally: %s", exc)

        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.COLLECTED,
            message="Successfully collected finalized outcome observation",
            merchant_id=auth_merchant_id,
            observation_id=attribution_id,
            collected_at=observation.observed_at,
        )
    except IntegrityError:
        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.ALREADY_COLLECTED,
            message=f"Duplicate insert prevented by database unique constraint for '{attribution_id}'",
            merchant_id=auth_merchant_id,
            observation_id=attribution_id,
        )
    except Exception as exc:
        logger.exception(f"Failed to persist Stage3OutcomeObservation for attribution {attribution_id}")
        return OutcomeCollectionResult(
            attribution_id=attribution_id,
            status=OutcomeCollectionStatus.FAILURE,
            message=f"Database persistence failure: {exc}",
            merchant_id=auth_merchant_id,
        )


def sweep_unobserved_attributions(
    session_factory: sessionmaker[Session], limit: int = 100
) -> list[OutcomeCollectionResult]:
    """Sweeps finalized Stage 2 outcome attributions that have not yet been observed in Stage 3."""
    results: list[OutcomeCollectionResult] = []

    with session_factory() as session:
        subq = select(Stage3OutcomeObservation.attribution_id)
        stmt = (
            select(OutcomeAttributionRecord.attribution_id)
            .where(
                OutcomeAttributionRecord.finalized_at.isnot(None),
                OutcomeAttributionRecord.verification_status == "VERIFIED",
                ~OutcomeAttributionRecord.attribution_id.in_(subq),
            )
            .order_by(OutcomeAttributionRecord.finalized_at.asc())
            .limit(limit)
        )
        unobserved_ids = list(session.scalars(stmt).all())

    for attr_id in unobserved_ids:
        with session_factory() as session:
            try:
                res = collect_outcome(session, attr_id)
                session.commit()
                results.append(res)
            except Exception as exc:
                session.rollback()
                logger.exception(f"Error during sweep collection of attribution '{attr_id}'")
                results.append(
                    OutcomeCollectionResult(
                        attribution_id=attr_id,
                        status=OutcomeCollectionStatus.FAILURE,
                        message=f"Sweep execution exception: {exc}",
                    )
                )

    return results

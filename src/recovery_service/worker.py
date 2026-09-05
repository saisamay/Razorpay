from __future__ import annotations

import logging
import os
import socket
import time
from uuid import uuid4

from sqlalchemy import select

from .database import build_session_factory, ensure_schema
from .models import RawEvent, ReconciliationAttempt, RecoveryCase
from .observability import QUEUE_LAG, structured_log
from .queue import EventQueue, RECONCILIATION_STREAM_NAME, STREAM_NAME
from .service import mark_processing_timeouts, process_event, run_reconciliation
from .settings import Settings


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
EVENT_GROUP = "state-reconstructors"
RECONCILIATION_GROUP = "reconcilers"


def worker_identity() -> str:
    return f"stage1-{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"


def _ensure_group(queue: EventQueue, stream: str, group: str) -> None:
    try:
        queue.client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _process(factory, event_id: str, worker_id: str) -> bool:
    """True means the transaction committed and it is now safe to ACK Redis."""
    with factory() as session:
        try:
            process_event(session, event_id, worker_id=worker_id)
            session.commit()
            return True
        except Exception:
            session.rollback()
            structured_log(logger, "processing_failed", correlation_id=event_id, worker_id=worker_id)
            logger.exception("event processing failed")
            return False


def _sweep_pending(factory, worker_id: str) -> None:
    with factory() as session:
        pending = session.scalars(select(RawEvent.id).where(RawEvent.processing_status == "PENDING").limit(100)).all()
    for event_id in pending:
        _process(factory, event_id, worker_id)


def _sweep_timeouts(factory, timeout_seconds: int) -> list[str]:
    with factory() as session:
        payment_ids = mark_processing_timeouts(session, timeout_seconds)
        session.commit()
        return payment_ids


def _sweep_reconciliation(factory) -> list[str]:
    with factory() as session:
        return session.scalars(select(ReconciliationAttempt.payment_id).where(ReconciliationAttempt.status == "PENDING").limit(100)).all()


def _handle_event_entries(queue: EventQueue, factory, entries, worker_id: str) -> None:
    for message_id, data in entries:
        event_id = data.get("event_id")
        if event_id and _process(factory, event_id, worker_id):
            queue.client.xack(STREAM_NAME, EVENT_GROUP, message_id)


def _handle_reconciliation_entries(queue: EventQueue, factory, settings: Settings, entries, worker_id: str) -> None:
    for message_id, data in entries:
        payment_id = data.get("payment_id")
        committed = False
        try:
            committed = bool(payment_id) and run_reconciliation(factory, settings, payment_id, worker_id=worker_id)
        except Exception:
            structured_log(logger, "reconciliation_processing_failed", payment_id=payment_id, worker_id=worker_id)
            logger.exception("reconciliation processing failed")
        if committed:
            queue.client.xack(RECONCILIATION_STREAM_NAME, RECONCILIATION_GROUP, message_id)


def _sweep_cases(factory, queue: EventQueue) -> list[str]:
    with factory() as session:
        cases = session.scalars(select(RecoveryCase.case_id).where(RecoveryCase.recovery_eligible == True).limit(100)).all()
    for case_id in cases:
        try:
            queue.publish_case(case_id)
        except Exception:
            pass
    return cases


def _sweep_stage3_observations(factory) -> None:
    from .stage3.collector import sweep_unobserved_attributions

    try:
        sweep_unobserved_attributions(factory, limit=100)
    except Exception:
        structured_log(logger, "stage3_observation_sweep_failed")
        logger.exception("Stage 3 observation sweep failed")


def _sweep_stage3_optimizers(factory) -> None:
    from .stage3.optimizer import submit_candidate_to_f5
    from .stage3.repository import Stage3OptimizationCandidateRepository

    try:
        with factory() as session:
            repo = Stage3OptimizationCandidateRepository()
            pending_f4 = repo.list_pending_candidates(session, status="WAITING_FOR_F4", limit=50)
            pending_f5 = repo.list_pending_candidates(session, status="WAITING_FOR_F5", limit=50)

            for cand in pending_f4 + pending_f5:
                try:
                    submit_candidate_to_f5(session, cand.candidate_id, candidate_repository=repo)
                    session.commit()
                except Exception:
                    session.rollback()
    except Exception:
        structured_log(logger, "stage3_optimizer_sweep_failed")
        logger.exception("Stage 3 optimizer sweep failed")


def _sweep_stage3_orchestrations(factory, worker_id: str) -> None:
    from .stage3.models import RecoveryOrchestrationRecord
    from .stage3.orchestrator import advance_recovery_episode

    try:
        with factory() as session:
            pending_cases = list(session.scalars(
                select(RecoveryOrchestrationRecord.case_id).where(
                    RecoveryOrchestrationRecord.episode_status == "PENDING"
                ).limit(50)
            ).all())

        for case_id in pending_cases:
            with factory() as session:
                try:
                    advance_recovery_episode(session, case_id, worker_id=worker_id)
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.exception("Failed to advance recovery episode for case %s", case_id)
    except Exception:
        structured_log(logger, "stage3_orchestration_sweep_failed")
        logger.exception("Stage 3 orchestration sweep failed")


def _sweep_escalation_slas(factory) -> None:
    from .stage3.escalation import check_and_apply_sla_timeouts

    try:
        with factory() as session:
            check_and_apply_sla_timeouts(session)
            session.commit()
    except Exception:
        structured_log(logger, "escalation_sla_sweep_failed")
        logger.exception("Escalation SLA sweep failed")


def main() -> None:
    settings = Settings.from_environment()
    factory = build_session_factory(settings)
    ensure_schema(factory)
    queue = EventQueue(settings.redis_url)
    worker_id = worker_identity()
    _ensure_group(queue, STREAM_NAME, EVENT_GROUP)
    _ensure_group(queue, RECONCILIATION_STREAM_NAME, RECONCILIATION_GROUP)
    structured_log(logger, "worker_started", worker_id=worker_id)
    last_housekeeping = 0.0

    while True:
        # First reclaim abandoned entries.  A crash after COMMIT but before ACK is
        # harmless because processing is idempotent; a crash before COMMIT is retried.
        _handle_event_entries(queue, factory, queue.reclaim(STREAM_NAME, EVENT_GROUP, worker_id, settings.redis_claim_idle_ms), worker_id)
        _handle_reconciliation_entries(queue, factory, settings,
                                      queue.reclaim(RECONCILIATION_STREAM_NAME, RECONCILIATION_GROUP, worker_id, settings.redis_claim_idle_ms), worker_id)

        now = time.monotonic()
        if now - last_housekeeping >= settings.stage3_sweep_interval_seconds:
            _sweep_pending(factory, worker_id)
            _sweep_cases(factory, queue)
            _sweep_stage3_observations(factory)
            _sweep_stage3_optimizers(factory)
            _sweep_stage3_orchestrations(factory, worker_id)
            _sweep_escalation_slas(factory)
            for payment_id in _sweep_timeouts(factory, settings.processing_timeout_seconds):

                try:
                    queue.publish_reconciliation(payment_id)
                except Exception:
                    structured_log(logger, "reconciliation_queue_publish_failed", payment_id=payment_id, worker_id=worker_id)
            # This durable sweep covers a Redis outage after an UNKNOWN commit.
            for payment_id in _sweep_reconciliation(factory):
                try:
                    queue.publish_reconciliation(payment_id)
                except Exception:
                    structured_log(logger, "reconciliation_queue_publish_failed", payment_id=payment_id, worker_id=worker_id)
            QUEUE_LAG.labels(STREAM_NAME).set(queue.queue_lag(STREAM_NAME))
            QUEUE_LAG.labels(RECONCILIATION_STREAM_NAME).set(queue.queue_lag(RECONCILIATION_STREAM_NAME))
            last_housekeeping = now

        messages = queue.client.xreadgroup(EVENT_GROUP, worker_id, {STREAM_NAME: ">"}, count=20, block=500)
        for _, entries in messages:
            _handle_event_entries(queue, factory, entries, worker_id)
        reconciliation_messages = queue.client.xreadgroup(RECONCILIATION_GROUP, worker_id, {RECONCILIATION_STREAM_NAME: ">"}, count=20, block=500)
        for _, entries in reconciliation_messages:
            _handle_reconciliation_entries(queue, factory, settings, entries, worker_id)


if __name__ == "__main__":
    main()

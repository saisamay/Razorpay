from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .database import build_session_factory, ensure_schema
from .models import DeadLetterEvent, PaymentState, RawEvent, RecoveryCase
from .observability import DUPLICATE_EVENTS, INGESTED_EVENTS, INVALID_EVENTS, metrics_payload, structured_log
from .queue import EventQueue
from .service import state_view
from .settings import Settings
from .stage2.api import stage2_router
from .stage2.dashboard import dashboard_router
from .stage2.eval_api import eval_router
from .stage2.exp_api import exp_router
from .stage2.f5_api import f5_router
from .stage3.escalation_api import escalation_router


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _signature_is_valid(raw_body: bytes, signature: str | None, secrets: tuple[str, ...]) -> bool:
    if not signature or not secrets:
        return False
    return any(hmac.compare_digest(hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest(), signature) for secret in secrets)


def _occurred_at(payload: dict, fallback: datetime) -> datetime:
    value = payload.get("created_at")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


def _correlation_fields(payload: dict, received_at: datetime) -> dict[str, object | None]:
    entities = payload.get("payload")
    payment = entities.get("payment") if isinstance(entities, dict) else None
    payment_entity = payment.get("entity") if isinstance(payment, dict) else None
    if not isinstance(payment_entity, dict):
        return {"merchant_id": payload.get("account_id") if isinstance(payload.get("account_id"), str) else None,
                "order_id": None, "payment_id": None, "occurred_at": _occurred_at(payload, received_at)}
    value = lambda key: payment_entity.get(key) if isinstance(payment_entity.get(key), str) else None
    return {"merchant_id": payload.get("account_id") if isinstance(payload.get("account_id"), str) else None,
            "order_id": value("order_id"), "payment_id": value("id"), "occurred_at": _occurred_at(payload, received_at)}


def _require_internal_access(request: Request) -> None:
    settings: Settings = request.app.state.settings
    token = settings.internal_api_token
    if token and hmac.compare_digest(request.headers.get("x-internal-token", ""), token):
        return
    if not token and settings.environment in {"test", "development", "local"}:
        return
    raise HTTPException(status_code=403, detail="internal authorization required")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_environment()
    factory = build_session_factory(settings)
    ensure_schema(factory)
    app.state.settings = settings
    app.state.sessions = factory
    app.state.queue = EventQueue(settings.redis_url)
    yield


app = FastAPI(title="Razorpay Revenue Recovery", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(stage2_router)
app.include_router(eval_router)
app.include_router(dashboard_router)
app.include_router(exp_router)
app.include_router(f5_router)
app.include_router(escalation_router)



@app.get("/health/live")
def health_live() -> dict[str, str]:
    """Process liveness only: intentionally independent of DB and Redis."""
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return health_live()


@app.get("/health/ready")
def health_ready(request: Request) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    errors = settings.readiness_errors()
    try:
        with request.app.state.sessions() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        errors.append("database unavailable")
    try:
        request.app.state.queue.client.ping()
    except Exception:
        errors.append("redis unavailable")
    if errors:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "errors": errors})
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    payload, media_type = metrics_payload()
    return Response(content=payload, media_type=media_type)


def _check_json_nesting_depth(obj: Any, current_depth: int = 1, max_depth: int = 10) -> None:
    if current_depth > max_depth:
        raise ValueError(f"JSON nesting depth exceeds safety limit of {max_depth}")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_json_nesting_depth(v, current_depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            _check_json_nesting_depth(item, current_depth + 1, max_depth)


_REQUEST_TIMESTAMPS: list[float] = []


def _check_rate_limit(max_per_sec: int = 200) -> None:
    now = datetime.now(timezone.utc).timestamp()
    global _REQUEST_TIMESTAMPS
    _REQUEST_TIMESTAMPS = [t for t in _REQUEST_TIMESTAMPS if now - t < 1.0]
    if len(_REQUEST_TIMESTAMPS) >= max_per_sec:
        from .observability import RATE_LIMIT_EXCEEDED
        RATE_LIMIT_EXCEEDED.inc()
        raise HTTPException(status_code=429, detail="too many webhook requests")
    _REQUEST_TIMESTAMPS.append(now)


@app.post("/webhooks/razorpay", status_code=status.HTTP_202_ACCEPTED)
async def razorpay_webhook(request: Request) -> dict[str, str | bool]:
    _check_rate_limit()
    settings: Settings = request.app.state.settings
    raw_body = await request.body()
    if len(raw_body) > settings.max_webhook_bytes:
        INVALID_EVENTS.labels("payload_too_large").inc()
        raise HTTPException(status_code=413, detail="webhook payload too large")
    signature = request.headers.get("x-razorpay-signature")
    if not _signature_is_valid(raw_body, signature, settings.webhook_secrets):
        INVALID_EVENTS.labels("signature").inc()
        structured_log(logger, "webhook_signature_invalid")
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    event_id = request.headers.get("x-razorpay-event-id")
    if not event_id:
        INVALID_EVENTS.labels("missing_event_id").inc()
        raise HTTPException(status_code=400, detail="missing x-razorpay-event-id")
    try:
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError("top-level payload must be a JSON object")
        _check_json_nesting_depth(payload)
        event_type = payload.get("event")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("event must be a non-empty string")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        INVALID_EVENTS.labels("malformed_payload").inc()
        raise HTTPException(status_code=422, detail="malformed webhook payload") from exc

    factory = request.app.state.sessions
    with factory() as session:
        received_at = datetime.now(timezone.utc)
        raw_event = RawEvent(source_event_id=event_id, event_type=event_type, environment=settings.environment,
                             raw_payload=payload, received_at=received_at, **_correlation_fields(payload, received_at))
        session.add(raw_event)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            DUPLICATE_EVENTS.inc()
            return {"accepted": True, "duplicate": True, "event_id": event_id}
    INGESTED_EVENTS.inc()
    queued = True
    try:
        request.app.state.queue.publish(raw_event.id)
    except Exception:
        queued = False
        structured_log(logger, "queue_publish_failed", event_id=event_id, payment_id=raw_event.payment_id,
                       order_id=raw_event.order_id, merchant_id=raw_event.merchant_id, correlation_id=raw_event.id)
    return {"accepted": True, "duplicate": False, "queued": queued, "event_id": event_id}


@app.get("/payments/{payment_id}/state")
def get_payment_state(payment_id: str, request: Request):
    with request.app.state.sessions() as session:
        state = session.get(PaymentState, payment_id)
        if state is None:
            raise HTTPException(status_code=404, detail="payment state not found")
        return state_view(state)


@app.get("/payments/{payment_id}/timeline")
def get_payment_timeline(payment_id: str, request: Request):
    with request.app.state.sessions() as session:
        events = session.scalars(
            select(RawEvent)
            .where(RawEvent.payment_id == payment_id)
            .order_by(RawEvent.occurred_at, RawEvent.received_at, RawEvent.source_event_id)
        ).all()
        if not events:
            raise HTTPException(status_code=404, detail="payment timeline not found")
        return {"payment_id": payment_id, "events": [
            {"event_id": event.source_event_id, "event_type": event.event_type, "occurred_at": event.occurred_at,
             "received_at": event.received_at, "processing_status": event.processing_status,
             "canonical_event": event.normalized_payload, "raw_reference": f"db://raw-events/{event.id}"}
            for event in events
        ]}


@app.get("/recovery-cases/{case_id}")
def get_recovery_case(case_id: str, request: Request):
    with request.app.state.sessions() as session:
        recovery_case = session.get(RecoveryCase, case_id)
        if recovery_case is None:
            raise HTTPException(status_code=404, detail="recovery case not found")
        return recovery_case


@app.get("/recovery-cases/{case_id}/contract")
def get_recovery_case_contract(case_id: str, request: Request):
    """Stage 2 security boundary contract validation endpoint."""
    with request.app.state.sessions() as session:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="recovery case not found")
        return {
            "case_id": case.case_id,
            "payment_id": case.payment_id,
            "recovery_episode_id": case.recovery_episode_id,
            "merchant_id": case.merchant_id,
            "order_id": case.order_id,
            "amount": case.amount,
            "currency": case.currency,
            "state": case.state,
            "state_confidence": case.state_confidence,
            "failure_evidence": case.failure_evidence,
            "recovery_eligible": case.recovery_eligible,
            "eligibility_reason": case.eligibility_reason,
            "schema_version": case.schema_version,
            "source_event_ids": case.source_event_ids,
            "stage1_state_version": case.stage1_state_version,
            "first_seen_at": case.first_seen_at,
            "last_seen_at": case.last_seen_at,
        }


@app.get("/internal/dlq/{event_id}")
def get_dlq_event(event_id: str, request: Request):
    _require_internal_access(request)
    with request.app.state.sessions() as session:
        dead_letter = session.get(DeadLetterEvent, event_id)
        if dead_letter is None:
            raise HTTPException(status_code=404, detail="dead letter event not found")
        return {"event_id": dead_letter.event_id, "reason": dead_letter.failure_type, "attempts": dead_letter.attempt_count,
                "first_error": dead_letter.first_error, "last_error": dead_letter.last_error,
                "first_failed_at": dead_letter.first_failed_at, "last_failed_at": dead_letter.last_failed_at}


@app.post("/internal/replay/{event_id}", status_code=status.HTTP_202_ACCEPTED)
def replay_event(event_id: str, request: Request):
    _require_internal_access(request)
    with request.app.state.sessions() as session:
        event = session.get(RawEvent, event_id, with_for_update=True)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        event.processing_status = "PENDING"
        event.processing_attempts = 0
        event.last_error = None
        session.commit()
    try:
        request.app.state.queue.publish(event_id)
    except Exception:
        structured_log(logger, "replay_queue_publish_failed", event_id=event.source_event_id, payment_id=event.payment_id,
                       order_id=event.order_id, merchant_id=event.merchant_id, correlation_id=event_id)
    return {"accepted": True, "event_id": event_id}

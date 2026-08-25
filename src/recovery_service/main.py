from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import Base, build_session_factory
from .models import PaymentState, RawEvent, RecoveryCase
from .queue import EventQueue
from .service import state_view
from .settings import Settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _signature_is_valid(raw_body: bytes, signature: str | None, secrets: tuple[str, ...]) -> bool:
    if not signature or not secrets:
        return False
    return any(hmac.compare_digest(hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest(), signature) for secret in secrets)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_environment()
    factory = build_session_factory(settings)
    Base.metadata.create_all(factory.kw["bind"])
    app.state.settings = settings
    app.state.sessions = factory
    app.state.queue = EventQueue(settings.redis_url)
    yield


app = FastAPI(title="Razorpay Revenue Recovery — Stage 1", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/razorpay", status_code=status.HTTP_202_ACCEPTED)
async def razorpay_webhook(request: Request) -> dict[str, str | bool]:
    settings: Settings = request.app.state.settings
    raw_body = await request.body()
    if len(raw_body) > settings.max_webhook_bytes:
        raise HTTPException(status_code=413, detail="webhook payload too large")
    signature = request.headers.get("x-razorpay-signature")
    if not _signature_is_valid(raw_body, signature, settings.webhook_secrets):
        logger.warning('{"event":"webhook_signature_invalid"}')
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    event_id = request.headers.get("x-razorpay-event-id")
    if not event_id:
        raise HTTPException(status_code=400, detail="missing x-razorpay-event-id")
    try:
        payload = json.loads(raw_body)
        event_type = payload["event"]
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("event must be a non-empty string")
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="malformed webhook payload") from exc

    factory = request.app.state.sessions
    with factory() as session:
        raw_event = RawEvent(source_event_id=event_id, event_type=event_type, environment=settings.environment, raw_payload=payload)
        session.add(raw_event)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return {"accepted": True, "duplicate": True, "event_id": event_id}

    queued = True
    try:
        request.app.state.queue.publish(raw_event.id)
    except Exception:
        queued = False
        logger.exception('{"event":"queue_publish_failed","raw_event_id":"%s"}', raw_event.id)
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
        events = session.scalars(select(RawEvent).order_by(RawEvent.received_at)).all()
        timeline = []
        for event in events:
            normalized = event.normalized_payload or {}
            if normalized.get("payment_id") == payment_id:
                timeline.append({"event_id": event.source_event_id, "event_type": event.event_type, "received_at": event.received_at, "processing_status": event.processing_status, "canonical_event": normalized, "raw_reference": f"db://raw-events/{event.id}"})
        if not timeline:
            raise HTTPException(status_code=404, detail="payment timeline not found")
        return {"payment_id": payment_id, "events": timeline}


@app.get("/recovery-cases/{case_id}")
def get_recovery_case(case_id: str, request: Request):
    with request.app.state.sessions() as session:
        recovery_case = session.get(RecoveryCase, case_id)
        if recovery_case is None:
            raise HTTPException(status_code=404, detail="recovery case not found")
        return recovery_case


@app.post("/internal/replay/{event_id}", status_code=status.HTTP_202_ACCEPTED)
def replay_event(event_id: str, request: Request):
    with request.app.state.sessions() as session:
        event = session.get(RawEvent, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        event.processing_status = "PENDING"
        event.last_error = None
        session.commit()
    try:
        request.app.state.queue.publish(event_id)
    except Exception:
        logger.exception('{"event":"replay_queue_publish_failed","raw_event_id":"%s"}', event_id)
    return {"accepted": True, "event_id": event_id}


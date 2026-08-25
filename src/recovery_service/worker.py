from __future__ import annotations

import logging
import time

from sqlalchemy import select

from .database import Base, build_session_factory
from .models import RawEvent
from .queue import EventQueue, STREAM_NAME
from .service import process_event
from .settings import Settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _process(factory, event_id: str) -> None:
    with factory() as session:
        try:
            process_event(session, event_id)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception('{"event":"processing_failed","raw_event_id":"%s"}', event_id)


def main() -> None:
    settings = Settings.from_environment()
    factory = build_session_factory(settings)
    Base.metadata.create_all(factory.kw["bind"])
    queue = EventQueue(settings.redis_url)
    consumer = "stage1-worker"
    group = "state-reconstructors"
    try:
        queue.client.xgroup_create(STREAM_NAME, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    while True:
        # The sweep makes delivery recoverable after a Redis outage between DB commit and XADD.
        with factory() as session:
            pending = session.scalars(select(RawEvent.id).where(RawEvent.processing_status == "PENDING").limit(100)).all()
        for event_id in pending:
            _process(factory, event_id)

        messages = queue.client.xreadgroup(group, consumer, {STREAM_NAME: ">"}, count=20, block=1000)
        for _, entries in messages:
            for message_id, data in entries:
                event_id = data.get("event_id")
                if event_id:
                    _process(factory, event_id)
                queue.client.xack(STREAM_NAME, group, message_id)
        time.sleep(0.05)


if __name__ == "__main__":
    main()


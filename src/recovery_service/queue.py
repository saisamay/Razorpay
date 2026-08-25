from __future__ import annotations

import logging

from redis import Redis


logger = logging.getLogger(__name__)
STREAM_NAME = "recovery:events"


class EventQueue:
    def __init__(self, redis_url: str):
        self.client = Redis.from_url(redis_url, decode_responses=True)

    def publish(self, event_id: str) -> None:
        self.client.xadd(STREAM_NAME, {"event_id": event_id})


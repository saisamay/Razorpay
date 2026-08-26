from __future__ import annotations

import logging

from redis import Redis


logger = logging.getLogger(__name__)
STREAM_NAME = "recovery:events"
RECONCILIATION_STREAM_NAME = "recovery:reconciliation"


class EventQueue:
    def __init__(self, redis_url: str):
        self.client = Redis.from_url(redis_url, decode_responses=True)

    def publish(self, event_id: str) -> None:
        self.client.xadd(STREAM_NAME, {"event_id": event_id})

    def publish_reconciliation(self, payment_id: str) -> None:
        self.client.xadd(RECONCILIATION_STREAM_NAME, {"payment_id": payment_id})

    def reclaim(self, stream: str, group: str, consumer: str, min_idle_ms: int):
        """Claim abandoned deliveries before consuming new work."""

        claimed = self.client.xautoclaim(
            stream,
            group,
            consumer,
            min_idle_ms,
            start_id="0-0",
            count=20,
        )
        # redis-py returns (next_start_id, [(message_id, values)], deleted_ids).
        return claimed[1] if claimed else []

    def queue_lag(self, stream: str) -> int:
        return int(self.client.xlen(stream))

"""Small, dependency-light observability boundary for the Stage 1.1 service."""

from __future__ import annotations

import json
import logging
from typing import Any

from collections import defaultdict


class _MetricChild:
    def __init__(self, metric: "_Metric", label_values: tuple[str, ...]):
        self.metric = metric
        self.label_values = label_values

    def inc(self, amount: float = 1.0) -> None:
        self.metric.values[self.label_values] += amount

    def set(self, value: float) -> None:
        self.metric.values[self.label_values] = value

    def observe(self, value: float) -> None:
        self.metric.values[self.label_values] += value
        self.metric.counts[self.label_values] += 1


class _Metric:
    """Minimal Prometheus text metric, avoiding a mandatory runtime dependency."""
    registry: list["_Metric"] = []

    def __init__(self, name: str, description: str, label_names: list[str] | None = None, kind: str = "counter"):
        self.name, self.description, self.label_names, self.kind = name, description, label_names or [], kind
        self.values: defaultdict[tuple[str, ...], float] = defaultdict(float)
        self.counts: defaultdict[tuple[str, ...], int] = defaultdict(int)
        self.registry.append(self)

    def labels(self, *values: str) -> _MetricChild:
        if len(values) != len(self.label_names):
            raise ValueError(f"{self.name} expects {len(self.label_names)} labels")
        return _MetricChild(self, tuple(str(value) for value in values))

    def inc(self, amount: float = 1.0) -> None:
        self.labels().inc(amount)

    def set(self, value: float) -> None:
        self.labels().set(value)

    def observe(self, value: float) -> None:
        self.labels().observe(value)


def Counter(name: str, description: str, label_names: list[str] | None = None) -> _Metric:
    return _Metric(name, description, label_names, "counter")


def Gauge(name: str, description: str, label_names: list[str] | None = None) -> _Metric:
    return _Metric(name, description, label_names, "gauge")


def Histogram(name: str, description: str) -> _Metric:
    return _Metric(name, description, kind="histogram")


INGESTED_EVENTS = Counter("recovery_events_ingested_total", "Accepted webhook events")
DUPLICATE_EVENTS = Counter("recovery_events_duplicate_total", "Duplicate webhook events")
INVALID_EVENTS = Counter("recovery_events_invalid_total", "Rejected webhook events", ["reason"])
PROCESSED_EVENTS = Counter("recovery_events_processed_total", "Processed events")
DLQ_EVENTS = Counter("recovery_events_dlq_total", "Events sent to the DLQ")
STATE_TRANSITIONS = Counter("recovery_state_transitions_total", "Derived state transitions", ["from_state", "to_state"])
UNKNOWN_STATES = Counter("recovery_unknown_states_total", "Payments moved to UNKNOWN")
CONTRADICTIONS = Counter("recovery_contradictions_total", "Contradictory evidence", ["type"])
OUT_OF_ORDER_EVENTS = Counter("recovery_out_of_order_total", "Out-of-order event reconstructions")
LATE_EVENTS = Counter("recovery_late_events_total", "Late positive evidence", ["type"])
RECONCILIATION_ATTEMPTS = Counter("recovery_reconciliation_attempts_total", "Reconciliation attempts", ["outcome"])
RECOVERY_CASES = Counter("recovery_cases_total", "Recovery case lifecycle", ["action"])
PROCESSING_LATENCY = Histogram("recovery_event_processing_seconds", "Webhook receipt to processing latency")
QUEUE_LAG = Gauge("recovery_queue_lag", "Approximate Redis stream length", ["stream"])


def structured_log(logger: logging.Logger, name: str, **values: Any) -> None:
    """Emit stable correlation fields without serialising payloads or secrets."""

    record = {
        "event": name,
        "event_id": values.pop("event_id", None),
        "payment_id": values.pop("payment_id", None),
        "order_id": values.pop("order_id", None),
        "merchant_id": values.pop("merchant_id", None),
        "worker_id": values.pop("worker_id", None),
        "correlation_id": values.pop("correlation_id", None),
        "state_before": values.pop("state_before", None),
        "state_after": values.pop("state_after", None),
        "state_version": values.pop("state_version", None),
        **values,
    }
    logger.info(json.dumps(record, default=str, separators=(",", ":")))


def metrics_payload() -> tuple[bytes, str]:
    lines: list[str] = []
    for metric in _Metric.registry:
        lines.extend([f"# HELP {metric.name} {metric.description}", f"# TYPE {metric.name} {metric.kind}"])
        for labels, value in metric.values.items():
            suffix = "" if not metric.label_names else "{" + ",".join(
                f'{key}="{label}"' for key, label in zip(metric.label_names, labels)
            ) + "}"
            if metric.kind == "histogram":
                lines.append(f"{metric.name}_sum{suffix} {value}")
                lines.append(f"{metric.name}_count{suffix} {metric.counts[labels]}")
            else:
                lines.append(f"{metric.name}{suffix} {value}")
    return ("\n".join(lines) + "\n").encode(), "text/plain; version=0.0.4; charset=utf-8"

# Razorpay Revenue Recovery — Stage 1

This service turns Razorpay webhook observations into an auditable, rebuildable
payment state. It deliberately stops before choosing or sending a recovery action.

## What is implemented

- HMAC-SHA256 verification over the untouched webhook body, with support for secret rotation.
- Idempotent durable ingress keyed by `(source, x-razorpay-event-id)`.
- A canonical event model that keeps Razorpay payload knowledge at the edge.
- A deterministic reducer that rebuilds state from all stored evidence, ordered by
  occurrence time rather than arrival time.
- Terminal-state protection: a captured payment is never downgraded by later negative evidence.
- Anomaly recording for out-of-order and contradictory evidence.
- An idempotent `RecoveryCase` only for a currently failed payment.
- Indexed payment correlation and timelines—one payment never requires a raw-event table scan.
- Redis Streams dispatch with unique worker identities, pending-entry reclaim, and DB commit before ACK.
- `PROCESSING → UNKNOWN` timeout handling and audited Razorpay API reconciliation; a timeout itself never starts recovery.
- Dead-letter inspection/replay, Prometheus-text metrics, structured correlation logs, and liveness/readiness checks.

## Run locally

```bash
cp .env.example .env
# Set RAZORPAY_WEBHOOK_SECRETS to the secret configured in Razorpay Test mode.
docker compose up --build
```

The API is available at `http://localhost:8000`. Swagger UI is at `/docs`.

## Core endpoints

- `POST /webhooks/razorpay` — authenticates, persists, and queues an event.
- `GET /payments/{payment_id}/state` — derived state and recovery gate.
- `GET /payments/{payment_id}/timeline` — raw-evidence references plus canonical events.
- `GET /recovery-cases/{case_id}` — normalized Stage-1 output.
- `GET /health/live` / `GET /health/ready` — process and dependency/configuration health.
- `GET /metrics` — operational counters and latency/queue metrics.
- `GET /internal/dlq/{event_id}` — inspected dead-letter reason and failure history.
- `POST /internal/replay/{event_id}` — queues an already persisted event again.

Set `INTERNAL_API_TOKEN` and send it as `X-Internal-Token` for internal replay/DLQ
operations. The application refuses to start ready outside local/test environments
without this token. Reconciliation uses `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`;
an API timeout or error is audited but never changes payment truth.

## Design boundary

The database is the durable source of truth; Redis only delivers work. If Redis is
temporarily unavailable after persistence, the webhook still receives a 2xx and the
worker's database pending-event sweep resumes delivery. If PostgreSQL is unavailable,
the endpoint returns a non-2xx so Razorpay's documented retry policy redelivers the event.

Raw payloads are retained in the database for this prototype. Move `raw_payload` to
encrypted object storage and preserve a URI reference before production use.

## Scope boundary

Stage 1.1 is still payment-centric. A checkout that fails before Razorpay creates a
`payment_id` is explicitly out of scope; it requires a future `CheckoutAttempt →
PaymentAttempt → PaymentState` model rather than guessing a failed payment.

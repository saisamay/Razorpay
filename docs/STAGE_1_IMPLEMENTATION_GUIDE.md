 # Stage 1 Implementation Guide

> **Purpose:** This is the maintenance guide for the first implemented slice of
> Razorpay Revenue Recovery. Read it before changing the webhook endpoint, reducer,
> database tables, or worker. It explains both the intended design and what the code
> currently does. Where the prototype has a deliberate limitation, it is called out
> plainly rather than being presented as production-complete.

## 1. What Stage 1 is—and is not

Stage 1 answers a narrowly defined question:

> Given all evidence received for a payment attempt, what is the safest current
> payment state, and may a later stage consider recovery?

It does **not** select a recovery action, contact a customer, retry a payment, make
a revenue prediction, or diagnose a root cause with an LLM. It produces trustworthy
input for those later concerns.

The key idea is that a webhook is *evidence*, not a command. A `payment.failed`
event may be followed by `payment.authorized` or `payment.captured`; Razorpay also
documents duplicate and unordered deliveries. Therefore this service stores every
valid event, rebuilds a state from the complete evidence history, and refuses to
consider recovery when that history proves the payment was captured.

The initial state vocabulary is:

| State | Meaning | Can recovery proceed? |
| --- | --- | --- |
| `CREATED` | Payment/order context exists, but no active attempt is confirmed. | No |
| `PROCESSING` | An attempt is in progress or still awaiting proof. | No |
| `AUTHORIZED` | Funds were authorized but capture is not established. | No |
| `CAPTURED` | Capture is established. This is terminal for recovery. | No |
| `FAILED` | A failure event is the current strongest evidence. | Yes, subject to the recovery gate |
| `UNKNOWN` | Evidence is inadequate, stale, or contradictory. | No |
| `ABANDONED` | Checkout context expired without definitive outcome. | No |

`UNKNOWN` and `ABANDONED` are part of the published design but are not yet emitted
by an expiry/timeout subsystem: current code can emit `CREATED`, `PROCESSING`,
`AUTHORIZED`, `CAPTURED`, and `FAILED` from actual received event evidence. Do not
silently map an unknown outcome to `FAILED` merely to make recovery appear possible.

## 2. What was done, in order

The repository was empty. The work therefore began as a greenfield scaffold, not a
modification to an existing application.

1. **Read and compared both supplied baseline documents.** The Markdown document is
   the complete, editable design. The DOCX contains the same material in formatted
   form. Their contents were used as engineering requirements, not as authority to
   change the user’s request.
2. **Checked Razorpay’s current webhook documentation.** This confirmed three
   assumptions that must not be guessed: signatures are HMAC-SHA256 over the exact
   raw request bytes; `x-razorpay-event-id` is Razorpay’s event identity; delivery is
   at-least-once and can arrive out of order.
3. **Created the project boundary and runtime files.** `requirements.txt`,
   `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`, and `README.md`
   make the service installable and reproducible.
4. **Created the Python package.** The package is named `recovery_service`, under
   `src/`, which prevents accidental imports from the repository root and makes the
   application layout compatible with packaging later.
5. **Built ingress before business logic.** The webhook verifies authentication
   before parsing/persisting it, writes a raw event transactionally, uses a database
   uniqueness constraint for deduplication, and only then asks Redis to deliver work.
6. **Separated normalization from reduction.** `normalizer.py` is the only current
   place that knows Razorpay’s nested webhook payload shape. `state_machine.py` only
   sees our compact canonical event shape. This separation is the main protection
   against Razorpay payload details leaking through the whole codebase.
7. **Built replayable reconstruction.** The worker gathers all usable events for the
   payment and folds them in event-occurrence order. It does not trust queue arrival
   order or mutate state through a simple "last message wins" rule.
8. **Added recovery-case correction.** A case created from a failure is later marked
   ineligible if authorization or capture evidence arrives. Leaving a historical case
   eligible after a capture would be a severe correctness defect.
9. **Added focused tests and ran them.** The suite covers signatures, persistent
   deduplication, failed-to-authorized/captured correction, captured-state safety,
   out-of-order reconstruction, and case revocation. At the time this guide was
   written: `6 passed`.

## 3. Repository map

```text
Razorpay/
├── .env.example                         # safe environment-variable template
├── .gitignore                           # keeps secrets, venvs, caches out of Git
├── Dockerfile                           # API/worker image definition
├── docker-compose.yml                   # local PostgreSQL + Redis + API + worker
├── requirements.txt                     # Python runtime and test dependencies
├── README.md                            # short getting-started guide
├── docs/
│   └── STAGE_1_IMPLEMENTATION_GUIDE.md  # this detailed guide
├── src/recovery_service/
│   ├── __init__.py                      # identifies the Python package
│   ├── settings.py                      # environment configuration
│   ├── database.py                      # SQLAlchemy engine/session setup
│   ├── models.py                        # persistent tables
│   ├── schemas.py                       # validated internal API/data shapes
│   ├── normalizer.py                    # Razorpay payload → canonical event
│   ├── state_machine.py                 # pure state-reconstruction rules
│   ├── queue.py                         # Redis Streams adapter
│   ├── service.py                       # processing transaction and case lifecycle
│   ├── main.py                          # FastAPI HTTP entry point
│   └── worker.py                        # background event consumer
└── tests/
    ├── test_state_machine.py            # pure reducer scenarios
    └── test_webhook_flow.py             # persistence/signature/case scenario
```

## 4. Dependencies: why these were selected

### Runtime dependencies

| Dependency | Used for | Why it fits Stage 1 | Main alternative and trade-off |
| --- | --- | --- | --- |
| **FastAPI** | HTTP webhook/read APIs | Typed request handling, OpenAPI docs at `/docs`, lightweight startup. | Django REST Framework is more batteries-included but heavier; Flask is smaller but requires more manual validation/docs wiring. |
| **Uvicorn** | ASGI server | Runs FastAPI efficiently in a container. `standard` adds common production event-loop helpers. | Gunicorn can supervise multiple Uvicorn workers in production; it is commonly used *with* Uvicorn rather than instead of it. |
| **SQLAlchemy 2** | Database mapping/transactions | Models tables explicitly, supports PostgreSQL in production and SQLite in tests, and keeps transactional semantics visible. | Raw SQL gives maximum control but repeats mapping/transaction code; Django ORM couples the project to Django. |
| **psycopg 3** | PostgreSQL driver | Modern, maintained PostgreSQL driver; `psycopg[binary]` makes local/Docker setup easier. | `asyncpg` is excellent for fully async DB access but would require an async SQLAlchemy design; Psycopg 2 is older. |
| **Redis** | Redis Streams client | Supplies a durable work stream and consumer groups for the prototype. | Kafka/Redpanda is preferable for larger throughput/replay ecosystems, but adds operational cost that is unnecessary for this first slice. Celery is a task framework, not an event log by itself. |
| **Pydantic 2** | Canonical schemas | Validates normalized values at the boundary and serializes models consistently. | Plain dataclasses do not validate input; Marshmallow is capable but adds a separate validation style. |

### Development/test dependencies

| Dependency | Used for | Why |
| --- | --- | --- |
| **pytest** | Test runner | Concise assertions and fixtures such as `tmp_path`. |
| **httpx** | HTTP client dependency | Included for future API integration tests and FastAPI ecosystem compatibility. Current tests deliberately test the service layer directly because the installed FastAPI/Starlette test-client combination emitted a compatibility warning and hung during lifespan entry in this environment. |

### Why PostgreSQL is truth while Redis is delivery

Redis is fast and useful, but state cannot exist *only* in Redis: its configured
persistence, memory policy, operational ownership, and replay behavior differ from a
database. The implementation commits `RawEvent` to PostgreSQL first. If `XADD` to
Redis fails, `RawEvent.processing_status` remains `PENDING`; the worker’s periodic
database sweep finds it later. This is an **outbox-like recovery mechanism**, though
it is not yet a dedicated transactional-outbox table.

If PostgreSQL itself is unavailable, ingress returns a non-2xx response. Razorpay
will retry delivery; we must not claim an event was accepted when we have not made it
durable. A more advanced architecture can put a durable stream before PostgreSQL, but
then it must carefully solve equivalent deduplication and raw-evidence durability.

## 5. Runtime configuration

Copy `.env.example` to `.env`; never commit the result.

| Variable | Example | Meaning | Failure symptom |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://recovery:recovery@postgres:5432/recovery` | SQLAlchemy connection URI. | API/worker fails on startup or webhook returns server error. |
| `REDIS_URL` | `redis://redis:6379/0` | Redis Streams URI. | API stores events but returns `queued: false`; worker cannot consume. |
| `RAZORPAY_WEBHOOK_SECRETS` | `new-secret,old-secret` | One or more comma-separated webhook secrets. Supporting both values permits signature verification during secret rotation. | Every webhook gets `401 invalid webhook signature`. |
| `APP_ENVIRONMENT` | `test` | Stored alongside each event; do not mix test and live data. | Confusing/auditing-dangerous environment mixing. |
| `MAX_WEBHOOK_BYTES` | `1048576` | Maximum accepted raw body size (1 MiB). | Large request gets 413. |

The API container overrides database and Redis hosts to Docker service names, because
`localhost` inside the container would mean the container itself, not PostgreSQL or
Redis. The secret/environment variables still come from `.env`.

## 6. The full event journey

```text
Razorpay POST
  │ raw bytes + X-Razorpay-Signature + x-razorpay-event-id
  ▼
FastAPI /webhooks/razorpay
  │ size check → raw-byte HMAC check → minimal JSON/event check
  ▼
raw_events (PostgreSQL; unique source + source_event_id)
  │                         │
  │ duplicate               └── Redis XADD recovery:events
  ▼                                      │
202 accepted                              ▼
                                    worker.py
                                      │ normalize
                                      ▼
                         canonical event + all payment evidence
                                      │ sort by occurred_at
                                      ▼
                             pure state reducer / recovery gate
                                      ▼
              payment_states + recovery_cases + raw_events status
```

### Example: failure followed by a late capture

1. `evt-1 / payment.failed` is verified and saved as `PENDING`.
2. The worker converts it to a canonical event, produces `FAILED`, and opens
   `rc_<hash(payment_id:evt-1)>` with `recovery_eligible=true`.
3. Later `evt-2 / payment.captured` is verified and saved. It may arrive after the
   failure, and it may even have been created before a different queued event.
4. The worker loads *both* events, sorts by `occurred_at`, produces `CAPTURED`, and
   records `LATE_CAPTURE_AFTER_FAILURE` when appropriate.
5. The original recovery case is updated: `state=CAPTURED`,
   `recovery_eligible=false`, `eligibility_reason=PAYMENT_ALREADY_CAPTURED`.
6. Stage 2 must read the current case/state—not act on an old cache or an old
   notification—as the case is a current view of evidence.

## 7. Data model and table-level debugging

### `raw_events`

This is the evidence ledger. It contains the received Razorpay JSON and lifecycle
metadata. Important columns:

| Column | Meaning |
| --- | --- |
| `id` | Internal UUID; queue messages and replay endpoint use this value. |
| `source`, `source_event_id` | Source identity. The unique constraint on this pair implements deduplication. |
| `event_type` | Quickly indexable copy of payload `event`; not a replacement for raw evidence. |
| `raw_payload` | Original parsed JSON retained for audit/re-normalization. In production move it to encrypted object storage and retain a pointer. |
| `normalized_payload` | The canonical representation produced by the worker. |
| `processing_status` | `PENDING`, `PROCESSED`, or `DLQ`. |
| `processing_attempts`, `last_error` | Explain retried/DLQ events. |

### `payment_states`

One current derived state per `payment_id`. This is a cache/projection over events,
not a replacement for evidence. `state_version` increases when the current row is
recomputed after additional evidence. `anomalies` records observations such as
`OUT_OF_ORDER_ARRIVAL` or `NEGATIVE_EVIDENCE_AFTER_CAPTURE` without discarding them.

### `recovery_cases`

One case per `payment_id` and failure episode. The episode key is the definitive
failure event ID; `case_id` is a deterministic SHA-256-derived ID, so repeat
processing cannot manufacture an additional case. Cases are updated/revoked when
later evidence changes the reconstructed state. A row in this table is not,
by itself, permission to contact a customer: inspect `recovery_eligible`.

### `dead_letter_events`

An event moves here after five normalization failures. It is retained in `raw_events`
too, with `processing_status=DLQ`, so an operator can repair code/data and replay it.

## 8. Module and function reference

This section is intentionally literal. It describes every defined function and the
reason it exists.

### `settings.py`

**`Settings`** is an immutable dataclass. Making it `frozen=True` prevents a request
or worker from accidentally changing global configuration after startup.

**`Settings.from_environment()`** reads each environment variable and returns a
complete settings object. It splits `RAZORPAY_WEBHOOK_SECRETS` on commas so a secret
rotation can accept both old and new signatures. Default SQLite/Redis values are only
development conveniences; Docker uses PostgreSQL and a container Redis service.

### `database.py`

**`Base`** is SQLAlchemy’s declarative base. Every model inherits it, allowing
`Base.metadata.create_all(...)` to create all tables.

**`build_session_factory(settings)`** creates a SQLAlchemy engine and returns a
factory for short-lived `Session` objects. `pool_pre_ping=True` tests a pooled
database connection before use, reducing failures after a DB restart. SQLite receives
`check_same_thread=False`, required when FastAPI/worker execution uses different
threads in local tests. PostgreSQL does not use that option.

### `models.py`

**`utc_now()`** returns a timezone-aware UTC timestamp. All service-generated times
must be timezone-aware; mixing local/naive timestamps makes event ordering unreliable.

**`RawEvent`**, **`PaymentState`**, **`RecoveryCase`**, and **`DeadLetterEvent`** are
SQLAlchemy table mappings described in Section 7. They have no methods because model
objects should represent data; business decisions live in pure/service functions.

### `schemas.py`

**`FailureEvidence`** contains the safely relevant Razorpay failure details. Fields
may be absent because providers do not always send a complete failure classification.

**`CanonicalEvent`** is the provider-neutral internal schema. `extra="forbid"`
rejects unexpected fields when re-validating the normalized JSON, which catches code
drift instead of silently accepting it. `amount` is validated non-negative.

**`RecoveryGate`** is the small deterministic decision delivered to later stages.

**`StateView`** is the response model for the state API. It includes the current state,
context, anomalies, version, and gate but never exposes the full raw payload.

### `normalizer.py`

**`NormalizationError`** distinguishes data-shape problems from database/network
errors. The worker can retry/DLQ these predictably.

**`_timestamp(value, fallback)`** accepts Razorpay’s Unix-second timestamp or an ISO
8601 string. If neither parses, it uses the durable `received_at` time. This is a
fallback, not a claim that receipt time equals occurrence time; consider emitting an
anomaly for this case in a future enhancement.

**`normalize_razorpay_event(event)`** is the anti-corruption layer. It reads nested
Razorpay fields (`payload.payment.entity`), requires a non-empty payment ID, extracts
merchant/order/amount/method/error information, and returns a `CanonicalEvent`. Only
this function should need changing when Razorpay changes payload paths. At present it
requires a payment entity, so an `order.paid` variation with no included payment will
go to the DLQ; extend the normalizer only after checking a real payload contract.

### `state_machine.py`

**`Reduction`** is an immutable result of folding evidence: state, confidence,
anomalies, failure details, and the event that defines a recovery episode.

**`_CONFIDENCE`** is a current explicit policy mapping, not machine-learning output.
It makes decisions auditable. Adjust it only with product/risk agreement and tests.

**`reduce_events(events)`** is the core pure function. It sorts evidence by
`(occurred_at, received_at, event_id)`, detects if that differs from receipt order,
then applies the transition rules:

- `payment.created` / `checkout.created` leaves the state at `CREATED`.
- `payment.processing` / `payment.pending` moves it to `PROCESSING` unless a terminal
  failed/captured state has already been established.
- `payment.failed` produces `FAILED`, except after capture where it records
  `NEGATIVE_EVIDENCE_AFTER_CAPTURE` and preserves `CAPTURED`.
- `payment.authorized` produces `AUTHORIZED`; after a failure it records
  `LATE_POSITIVE_AFTER_FAILURE`; after capture it records a stale-event anomaly.
- `payment.captured` and `order.paid` produce `CAPTURED`; after failure they record
  `LATE_CAPTURE_AFTER_FAILURE`.

No network/database call occurs here. That makes the function easy to test, replay,
and reason about. Do not replace it with a numeric priority list: transitions need
context, especially around the captured terminal-state safety rule.

**`recovery_gate(reduction)`** has exactly three outcomes: currently failed with
failure evidence → eligible; captured → explicitly ineligible; everything else →
unresolved/ineligible. This is intentionally conservative.

### `queue.py`

**`STREAM_NAME`** is the single prototype input stream, `recovery:events`.

**`EventQueue.__init__(redis_url)`** constructs a synchronous Redis client. It does
not connect immediately; errors occur on a read/write call.

**`EventQueue.publish(event_id)`** calls Redis `XADD`, appending the internal raw-event
ID to the stream. It contains no business logic, making Kafka/Redpanda replacement
localized later.

### `service.py`

**`MAX_ATTEMPTS`** is five. It applies only to normalization failures at present.

**`_canonical_events(session, payment_id)`** queries non-DLQ raw events, uses an
already saved canonical payload when available, otherwise normalizes it, and returns
only events for this payment. This is what makes current state rebuildable. It is
currently a prototype implementation that scans non-DLQ events; production should add
a normalized-event/payment ID index or a separate canonical-events table.

**`_case_id(payment_id, episode_event_id)`** derives a stable ID from the payment plus
the failure event. Stable IDs make recovery-case creation idempotent across worker
retries.

**`_upsert_recovery_case(session, state, event, reduction)`** first synchronizes all
existing cases for this payment to the newly reconstructed state/gate. This is the
revocation safeguard. If the current result is an eligible failed episode, it creates
or updates that episode’s deterministic case with identity, monetary context, evidence,
timestamps, and reason.

**`_move_to_dlq(session, event, error)`** marks the raw event `DLQ` and creates or
updates its companion `DeadLetterEvent`. It does not delete evidence.

**`process_event(session, event_id)`** is the worker’s atomic unit of work. It loads
the raw event; increments attempts; normalizes it; obtains/updates the payment-state
projection; reconstructs from all evidence; synchronizes a recovery case; and marks
the raw event `PROCESSED`. A `NormalizationError` does *not* roll the transaction
back: it persists `PENDING` plus error until attempt five, then persists the DLQ
outcome. Other exceptions are intentionally re-raised for the worker to roll back and
log, because a partial state update must never be committed.

**`state_view(state)`** converts the persistent projection to the externally returned
`StateView`. It repeats the simple gate logic from the stored current state so the API
does not need to load all raw events for each read.

### `main.py`

**`_signature_is_valid(raw_body, signature, secrets)`** creates SHA-256 HMAC hex
digests using each configured secret and compares them using `hmac.compare_digest`,
which avoids timing-sensitive string comparison. It must receive untouched bytes;
parsing/re-serializing JSON changes whitespace/key representation and breaks a valid
signature.

**`lifespan(app)`** runs once at application startup. It builds settings/session
factory, creates tables for this prototype, and attaches settings/sessions/queue to
`app.state`. Production should replace `create_all` with versioned Alembic migrations.

**`healthz()`** returns a fast liveness response. It currently means the process is
alive, not that PostgreSQL and Redis have been tested. Add a separate authenticated
readiness endpoint for dependency checks if the deployment platform needs it.

**`razorpay_webhook(request)`** is the ingress transaction. In exact order it reads
raw bytes; applies size limit; validates signature; requires event ID; minimally parses
JSON; inserts a raw event; handles a unique-constraint conflict as a successful
duplicate; then attempts queue publication. It returns 202 quickly and intentionally
does not normalize/reduce synchronously. `queued=false` still means the event is safe
in PostgreSQL and will be swept later.

**`get_payment_state(payment_id, request)`** reads one `PaymentState`, converts it with
`state_view`, or returns 404.

**`get_payment_timeline(payment_id, request)`** returns canonical evidence references
in receipt order. It deliberately returns `db://raw-events/<id>` rather than raw
payloads, reducing accidental PII exposure. Improve its current full-table scan before
large-scale use.

**`get_recovery_case(case_id, request)`** retrieves the normalized Stage-1 case or 404.

**`replay_event(event_id, request)`** clears an event’s processing error, marks it
`PENDING`, and republishes it. This endpoint has **no authentication in this prototype**;
it must only be reachable from a protected internal network until an identity provider
and authorization policy are chosen.

### `worker.py`

**`_process(factory, event_id)`** opens an independent DB session per event, invokes
`process_event`, commits only on success/durable normalization outcome, and rolls back
unexpected exceptions. This prevents one bad event from corrupting another event.

**`main()`** starts the worker. It creates tables (prototype behavior), creates the
Redis consumer group if absent, then loops. Each iteration first sweeps up to 100
database `PENDING` events, then reads up to 20 stream messages, processes their IDs,
acknowledges the Redis messages, and briefly sleeps. The sweep covers an API success
where the subsequent Redis `XADD` failed.

### Test functions

Tests are executable documentation for the invariants. They should be changed only
when the intended business rule changes—not merely because an implementation has
changed.

In `test_state_machine.py`, **`event(...)`** is a fixture helper that creates a
canonical event with controllable occurrence and receipt times. The four tests use it
to prove that a failure can be eligible, late authorization removes eligibility,
capture is never downgraded by later failure, and reordering uses occurrence rather
than receipt order.

In `test_webhook_flow.py`, **`payload(event_type)`** creates a Razorpay-shaped sample
body and **`raw_event(event_id, webhook_type)`** wraps it in the persistent model.
**`test_signature_verification_uses_raw_bytes()`** proves that even one added space
invalidates an HMAC, and **`test_persisted_events_are_idempotent_and_late_capture_blocks_recovery(...)`** proves the database uniqueness constraint, projection behavior,
anomaly recording, and recovery-case revocation in one SQLite-backed transaction.

## 9. APIs and examples

### Webhook ingestion

`POST /webhooks/razorpay`

Required headers:

```text
X-Razorpay-Signature: <HMAC-SHA256 hex digest of exact request body>
x-razorpay-event-id: <unique Razorpay event ID>
Content-Type: application/json
```

Responses:

| Status | Meaning | Razorpay retry behavior desired? |
| --- | --- | --- |
| `202` + `duplicate:false` | Stored; queue publish may or may not have succeeded. | No |
| `202` + `duplicate:true` | Already stored from a previous delivery. | No |
| `401` | Secret/signature mismatch. | Investigate, do not treat as a data error. |
| `400` | Missing event-ID header. | Investigate configuration/proxy behavior. |
| `413` | Body exceeds configured safety limit. | Investigate payload/limit. |
| `422` | Invalid JSON or no top-level event name. | Investigate malformed request. |
| `5xx` | Database or unexpected service failure. | Yes: provider should retry. |

### Read state

```bash
curl http://localhost:8000/payments/pay_example/state
```

An abbreviated response:

```json
{
  "payment_id": "pay_example",
  "state": "CAPTURED",
  "state_confidence": 1.0,
  "anomalies": [{"type": "LATE_CAPTURE_AFTER_FAILURE", "event_id": "evt_2"}],
  "state_version": 2,
  "recovery_gate": {
    "recovery_eligible": false,
    "reason": "PAYMENT_ALREADY_CAPTURED",
    "state": "CAPTURED",
    "state_confidence": 1.0
  }
}
```

### Replay

`POST /internal/replay/<raw_events.id>` uses the internal UUID from `raw_events.id`,
not Razorpay’s `x-razorpay-event-id`. This distinction is intentional: the HTTP
webhook identity is source-specific, while worker/replay identity is an internal row.

## 10. Run, test, and debug

### Run with Docker

```bash
cp .env.example .env
# Edit the secret before use.
docker compose up --build
```

The API runs on port 8000. API documentation appears at `http://localhost:8000/docs`.
For real Razorpay Test-mode webhooks the URL must be publicly reachable over HTTPS;
configure the exact secret from the Razorpay Dashboard.

### Run tests

```bash
PYTHONPATH=src .venv/bin/pytest -q
```

Expected current result:

```text
6 passed
```

### Useful SQL checks

Run these inside PostgreSQL after adapting credentials/database names:

```sql
SELECT source_event_id, event_type, processing_status, processing_attempts, last_error
FROM raw_events
ORDER BY received_at DESC;

SELECT payment_id, state, state_version, anomalies, updated_at
FROM payment_states
ORDER BY updated_at DESC;

SELECT case_id, payment_id, state, recovery_eligible, eligibility_reason, last_seen_at
FROM recovery_cases
ORDER BY last_seen_at DESC;

SELECT event_id, failure_type, attempt_count, last_error, last_failed_at
FROM dead_letter_events
ORDER BY last_failed_at DESC;
```

## 11. Troubleshooting playbook

| Symptom | Inspect first | Likely cause | Safe resolution |
| --- | --- | --- | --- |
| All webhooks return 401 | `RAZORPAY_WEBHOOK_SECRETS`, reverse proxy body handling | Incorrect secret, changed secret, body parsed/reformatted before verification | Use the secret configured for that webhook; preserve raw bytes; provide old and new comma-separated secrets during rotation. |
| Duplicate customer effect | `raw_events` unique constraint and downstream Stage 2 behavior | A later stage ignored `case_id`/action idempotency | Verify `(source, source_event_id)` and use case/action-level idempotency in every later stage. Never remove the unique constraint. |
| API says `queued:false` | API logs, Redis connectivity, `raw_events.processing_status` | Redis unavailable after database commit | Do not resend manually; the event is durable. Restore Redis/worker and let the pending sweep process it. |
| Event remains `PENDING` | Worker logs, worker process, DB query | Worker stopped, unable to reach DB/Redis, or has a repeating error | Restart worker, inspect `last_error`, then replay after repair if necessary. |
| Event is `DLQ` | `dead_letter_events.last_error`, raw payload | Unsupported/malformed payload shape | Update and test only the normalizer; then set event to `PENDING` via protected replay flow. Do not edit away raw evidence. |
| Payment incorrectly looks failed after capture | Timeline and anomalies | Reducer bug or a stale cache outside Stage 1 | Check that all events exist; captured must win. Add a regression test before modifying `reduce_events`. |
| Old recovery case still eligible after capture | `recovery_cases` row and worker logs | Case synchronization did not run/commit | Reprocess the captured evidence; retain audit trail. Test the failed→captured revocation scenario. |
| Missing state/timeline | `raw_events`, `normalized_payload`, DLQ | Event was not processed or does not contain payment entity | Fix worker/normalizer; this implementation cannot reconstruct an event with no payment ID. |
| Slow timeline API | Database metrics/query plan | Current implementation scans all raw events | Add a normalized-event table/index on `payment_id`; do not expose raw payload to solve it. |
| Concurrent workers conflict | DB logs, unique violations | First projection row created simultaneously | Add PostgreSQL `INSERT ... ON CONFLICT` or retry around projection-row creation; preserve per-payment locking/optimistic versioning. |

## 12. Known prototype boundaries and recommended next work

These are not hidden defects; they are the next deliberate engineering decisions.

1. **Migrations:** replace `Base.metadata.create_all` with Alembic migrations before
   any environment holds material data. Automatic table creation cannot safely evolve
   a live schema.
2. **Concurrency:** current code requests `FOR UPDATE` on an existing payment state,
   but concurrent creation of the first `PaymentState` can race. Implement an atomic
   PostgreSQL upsert or retry-on-unique-conflict strategy and test two workers.
3. **Query scale:** `_canonical_events` and the timeline scan raw events. Add a
   canonical-event table/indexed `payment_id`, or at minimum a database expression/
   projection that makes payment evidence lookup targeted.
4. **Outbox and worker recovery:** the pending sweep is safe but inefficient. Use a
   transactional outbox table with a dispatcher, track message attempts, and reclaim
   unacknowledged Redis consumer-group messages (`XAUTOCLAIM`).
5. **Time-based states:** implement an explicit timeout/expiry reconciler for
   `UNKNOWN` and `ABANDONED`; it must never auto-convert them to `FAILED`.
6. **Raw payload protection:** encrypted object storage, immutable retention policy,
   PII redaction strategy, access audit, and a `raw_reference` URI replace inline JSON
   before production.
7. **Authorization:** protect replay, DLQ administration, state/timeline reads as
   required by merchant tenancy, and add audit records for administrative actions.
8. **Readiness/observability:** add structured fields, metrics (unknown/duplicate/DLQ/
   queue lag), tracing, and readiness checks for dependencies. The current JSON-like
   log messages are a beginning, not complete observability.
9. **Webhook contract coverage:** collect authenticated Test-mode samples for every
   subscribed event and add fixture tests. In particular verify `order.paid` payload
   shape before relying on it.
10. **Stage 2 boundary:** publish only the current normalized `RecoveryCase` with its
    eligibility flag. Stage 2 must never mutate Stage 1 tables or act from a stale
    case snapshot.

## 13. Rules for future changes

Before merging a Stage 1 change, answer these questions:

1. Can the current payment state still be rebuilt from retained evidence?
2. Does a duplicate event produce exactly the same logical result?
3. What happens if events arrive in the reverse order?
4. Can a captured payment ever become recovery eligible because of this change?
5. Does the change leak raw payload/PII into logs or another stage?
6. Is a new transition covered by a pure reducer test and a persistence-level test?
7. What occurs if the worker crashes between each database/queue step?

If any answer is unclear, keep the payment state `UNKNOWN`/blocked and extend the
tests before adding automation. The project’s value comes from being safe and
auditable under imperfect payment evidence, not from producing the earliest possible
recovery suggestion.

## 14. Source references

- Razorpay, [Validate and Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/)
- Razorpay, [Webhook Best Practices](https://razorpay.com/docs/webhooks/best-practices/)
- Razorpay, [Payments Webhook Events](https://razorpay.com/docs/webhooks/payments/)

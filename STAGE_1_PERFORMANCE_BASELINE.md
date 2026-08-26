# Stage 1.1 Performance Baseline Benchmark Report

**Environment:** Linux (Python 3.12, SQLite in-memory/file backend, synchronous SQLAlchemy session)  
**Date:** 2026-08-26 12:04:59 UTC  
**Dataset:** 500 synthetic events across 100 distinct payments (5 events/payment)

---

## 1. Executive Metrics Summary

| Metric | Throughput | Mean Latency | p50 | p95 | p99 | Max |
|---|---|---|---|---|---|---|
| **Ingestion Ingress** | 3702.62 events/sec | 0.247 ms | 0.217 ms | 0.325 ms | 0.382 ms | 7.470 ms |
| **Worker Processing** | 151.24 events/sec | 6.611 ms | 5.801 ms | 10.860 ms | 12.488 ms | 19.255 ms |
| **State Reconstruction Query** | 2128.51 queries/sec | 0.465 ms | 0.445 ms | 0.804 ms | 0.994 ms | 2.265 ms |
| **Timeline Query** | 2802.78 queries/sec | 0.354 ms | 0.309 ms | 0.486 ms | 0.707 ms | 1.590 ms |

---

## 2. Detailed Performance Distribution

### 2.1 Webhook Ingestion Ingress
- Total Events Ingested: 500
- Elapsed Time: 0.1350 s
- Throughput: **3702.62 events/sec**
- p50 Latency: **0.217 ms**
- p95 Latency: **0.325 ms**
- p99 Latency: **0.382 ms**

### 2.2 Event Processing & State Reconstruction
- Total Events Processed: 500
- Elapsed Time: 3.3060 s
- Throughput: **151.24 events/sec**
- p50 Latency: **5.801 ms**
- p95 Latency: **10.860 ms**
- p99 Latency: **12.488 ms**

### 2.3 State Projection Read Latency
- Total Payments Queried: 100
- p50 Latency: **0.445 ms**
- p95 Latency: **0.804 ms**
- p99 Latency: **0.994 ms**

### 2.4 Timeline Read Query Latency
- Total Timeline Queries: 100
- p50 Latency: **0.309 ms**
- p95 Latency: **0.486 ms**
- p99 Latency: **0.707 ms**

### 2.5 Queue Lag Under Load
- Queue Lag (Simulated Stream Backlog): **0 events** post-batch completion.
- Peak Ingestion Backlog: **500 events** enqueued prior to worker sweep.

---

## 3. Methodology & Verification
- Test executed using synthetic Razorpay webhook payloads.
- Indexed payment queries verified (`RawEvent.payment_id` indexed lookup).
- Database cleaned up after execution.

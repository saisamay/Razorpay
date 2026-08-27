# Stage 1.1 Performance Baseline Benchmark Report

**Environment:** Linux (Python 3.12, SQLite in-memory/file backend, synchronous SQLAlchemy session)  
**Date:** 2026-08-27 05:57:47 UTC  
**Dataset:** 500 synthetic events across 100 distinct payments (5 events/payment)

---

## 1. Executive Metrics Summary

| Metric | Throughput | Mean Latency | p50 | p95 | p99 | Max |
|---|---|---|---|---|---|---|
| **Ingestion Ingress** | 3091.53 events/sec | 0.300 ms | 0.215 ms | 0.545 ms | 0.704 ms | 12.105 ms |
| **Worker Processing** | 148.88 events/sec | 6.716 ms | 6.050 ms | 11.570 ms | 13.373 ms | 23.660 ms |
| **State Reconstruction Query** | 4343.56 queries/sec | 0.228 ms | 0.196 ms | 0.314 ms | 0.397 ms | 1.260 ms |
| **Timeline Query** | 2816.06 queries/sec | 0.352 ms | 0.317 ms | 0.526 ms | 0.630 ms | 1.049 ms |

---

## 2. Detailed Performance Distribution

### 2.1 Webhook Ingestion Ingress
- Total Events Ingested: 500
- Elapsed Time: 0.1617 s
- Throughput: **3091.53 events/sec**
- p50 Latency: **0.215 ms**
- p95 Latency: **0.545 ms**
- p99 Latency: **0.704 ms**

### 2.2 Event Processing & State Reconstruction
- Total Events Processed: 500
- Elapsed Time: 3.3585 s
- Throughput: **148.88 events/sec**
- p50 Latency: **6.050 ms**
- p95 Latency: **11.570 ms**
- p99 Latency: **13.373 ms**

### 2.3 State Projection Read Latency
- Total Payments Queried: 100
- p50 Latency: **0.196 ms**
- p95 Latency: **0.314 ms**
- p99 Latency: **0.397 ms**

### 2.4 Timeline Read Query Latency
- Total Timeline Queries: 100
- p50 Latency: **0.317 ms**
- p95 Latency: **0.526 ms**
- p99 Latency: **0.630 ms**

### 2.5 Queue Lag Under Load
- Queue Lag (Simulated Stream Backlog): **0 events** post-batch completion.
- Peak Ingestion Backlog: **500 events** enqueued prior to worker sweep.

---

## 3. Methodology & Verification
- Test executed using synthetic Razorpay webhook payloads.
- Indexed payment queries verified (`RawEvent.payment_id` indexed lookup).
- Database cleaned up after execution.

# Phase E0 Dashboard Handoff Inspection Report

**Status**: E0 INSPECTION COMPLETE & VERIFIED  
**Target Specification**: `Stage 2 — P1 Evaluation & Recovery Intelligence Interface` (v3.0 Final)  
**Date**: 2026-08-29 UTC  

---

## 1. Discovered Architecture & Topology

- **Frontend framework**: Vanilla HTML5 + JavaScript (ES2022) + Glassmorphic Vanilla CSS Design System (Zero external npm dependencies required; renders instantly in modern browsers).
- **Frontend entrypoint**: Mounted via FastAPI at `GET /investigation` and `GET /dashboard` in `src/recovery_service/main.py`.
- **Backend API entrypoint**: FastAPI application in `src/recovery_service/main.py`, router mounted at `/api/v2/evaluation`.
- **Authentication mechanism**: Server-side token check (`x-internal-token`) for administrative routes; environment-aware validation.
- **Authorization mechanism**: Tenant-scoped request header (`x-merchant-id`) matching authoritative `RecoveryCase.merchant_id`.
- **Tenant identification mechanism**: Server-side comparison between authenticated principal header (`x-merchant-id`) and case ownership in database (`RecoveryCase.merchant_id`). Cross-tenant access returns HTTP 403 Forbidden.
- **Database**: PostgreSQL 16 Alpine (`postgresql+psycopg://recovery:recovery@postgres:5432/recovery`), with SQLite3 for isolated unit tests.
- **Stage 2 database tables**:
  1. `stage2_cases` (Registration state machine & PK `(case_id, stage1_state_version)`)
  2. `evidence_manifests` (Canonical EvidenceManifest records)
  3. `diagnoses` (Immutable causal diagnosis records)
  4. `failure_fingerprints` (Versioned FailureDNA & Temporal features)
  5. `incident_clusters` (Cross-payment systemic degradation signals)
  6. `recovery_eligibility` (Hard compliance rules & attempt caps)
  7. `recovery_genomes` (Immutable RecoveryGenome snapshot)
  8. `decision_proposals` (Immutable DecisionProposal records)
  9. `shadow_evaluations` (Shadow mode counterfactual vs baseline records)

---

## 2. Real P1 Artifact Verification

- **`RecoveryGenome` Source**: Table `recovery_genomes` (`RecoveryGenomeRecord`). Verified real records generated via `process_p1_pipeline()`.
- **`DecisionProposal` Source**: Table `decision_proposals` (`DecisionProposalRecord`). Verified real records generated via `optimize_recovery_decision()`.
- **`ShadowEvaluation` Source**: Table `shadow_evaluations` (`ShadowEvaluationRecord`). Verified real records generated via `create_shadow_evaluation()`.
- **Existing outcome source**: `PaymentState` and `ReconciliationAttempt` records in PostgreSQL.
- **Existing GenAI source**: `src/recovery_service/stage2/genai_explainer.py` using allowlisted PII-sanitized context and OpenAI API key loaded via `Settings.from_environment()`.
- **Docker topology**: Multi-container setup in `docker-compose.yml` (`postgres`, `redis`, `api`, `worker`).
- **Environment variables**: Configured in `.env` and `Settings.from_environment()`.

---

## 3. Boundary & File Modifications

### A. Files That MUST NOT Be Modified (FROZEN)
1. `src/recovery_service/state_machine.py` (Stage 1 Reducer)
2. `src/recovery_service/models.py` (Stage 1 Models)
3. `src/recovery_service/service.py` (Stage 1 Service)
4. `src/recovery_service/stage2/diagnosis_engine.py` (P0 Deterministic Baseline)
5. `src/recovery_service/stage2/normalizer.py` (P0 Evidence Normalizer)

### B. Files To Create
1. `src/recovery_service/stage2/evaluation.py` (E1 Evaluation contracts, projection layer & value semantic builders)
2. `src/recovery_service/stage2/eval_api.py` (E3 Case-scoped read endpoint `GET /api/v2/evaluation/cases/{case_id}`)
3. `src/recovery_service/stage2/dashboard.py` (E4 Primary Payment Recovery Investigation UI HTML/JS renderer)
4. `tests/p1/test_evaluation_contracts.py` (Phase E1 unit tests for semantics & projections)
5. `tests/p1/test_eval_api.py` (Phase E3 API security & tenant isolation tests)

### C. Files To Modify
1. `src/recovery_service/main.py` (Mount evaluation router and UI endpoints)

---

**Inspection Verdict**: Phase E0 Repository Inspection Complete. Ready for Phase E1 Evaluation Contracts implementation.

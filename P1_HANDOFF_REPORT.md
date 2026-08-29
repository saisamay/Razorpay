# P1 Handoff Inspection Report: Stage 0 / P0 $\rightarrow$ P1 Integration

**Status**: INSPECTION COMPLETE & FROZEN  
**Target Specification**: `STAGE 2 — P1 BUILD SPECIFICATION` (v3.2)  
**Date**: 2026-08-28 UTC  

---

## 1. Exact P0 $\rightarrow$ P1 Data Handoff

P1 consumes frozen, immutable outputs produced by Stage 1 and Stage 2 P0 (P0-A through P0-E):

```text
RecoveryCaseContract (Stage 1.5/P0-A)
       │
       ▼
EvidenceManifest (P0-B)
       │
       ▼
DiagnosisResult (P0-C/P0-D)
       │
       ▼
FailureDNA & TemporalFeatures (P0-E)
       │
       ▼
==================================================
 P1 INTELLIGENCE PIPELINE (P1-A through P1-G)
==================================================
```

### Exact Handoff Attributes Consumed by P1:
1. `case_id`: Stable recovery episode identifier (`rc_<hash>`).
2. `stage1_state_version`: Monotonic state version (guarantees stale result protection).
3. `payment_id`: Canonical payment identifier.
4. `merchant_id`: Tenant authorization boundary.
5. `amount` & `currency`: Monetary value and currency code.
6. `diagnosis_id`, `diagnosis_class`, `confidence`, `evidence_ids`: P0 Causal deterministic diagnosis result.
7. `fingerprint_hash`, `dimensions`: Bounded PII-safe `FailureDNA` failure dimensions.
8. `temporal_features`: Timing deltas (`request_to_gateway_ms`, `gateway_to_issuer_ms`, `total_span_seconds`, `latency_regime`).

---

## 2. Exact Files, Classes & Functions Reused

### A. Stage 1 & Stage 1.5 Shared Contracts
- [models.py](file:///home/samay/projects/Razorpay/src/recovery_service/models.py): `RecoveryCase`, `PaymentState`, `RawEvent`, `Base`
- [database.py](file:///home/samay/projects/Razorpay/src/recovery_service/database.py): `Base`, `build_session_factory`, `ensure_schema`
- [queue.py](file:///home/samay/projects/Razorpay/src/recovery_service/queue.py): `EventQueue`, `CASES_STREAM_NAME` (`"recovery:cases"`)
- [settings.py](file:///home/samay/projects/Razorpay/src/recovery_service/settings.py): `Settings`

### B. Stage 2 P0 Modules
- [stage2/models.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/models.py): `Stage2Case`, `EvidenceManifestRecord`, `DiagnosisRecord`, `FailureFingerprintRecord`
- [stage2/schemas.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/schemas.py): `RecoveryCaseContract`, `EvidenceManifest`, `DiagnosisResult`, `FailureDNA`, `TemporalFeatures`
- [stage2/normalizer.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/normalizer.py): `normalize_evidence()`, `compute_provenance_hash()`
- [stage2/diagnosis_engine.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/diagnosis_engine.py): `evaluate_diagnosis()`, `DiagnosisClasses`
- [stage2/failure_dna.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/failure_dna.py): `compute_failure_dna()`, `compute_temporal_features()`
- [stage2/consumer.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/consumer.py): `register_stage2_case()`, `process_evidence_manifest()`, `process_diagnosis()`, `process_failure_fingerprint()`

---

## 3. Infrastructure & Dependency Mapping

- **PostgreSQL**: PostgreSQL 16 Alpine (`postgresql+psycopg://recovery:recovery@postgres:5432/recovery`). Authoritative source of truth for P0 and P1 tables.
- **Redis**: Redis 7 Alpine (`redis://redis:6379/0`). Stream delivery mechanism (`recovery:cases`).
- **Docker Setup**: Multi-container setup in [docker-compose.yml](file:///home/samay/projects/Razorpay/docker-compose.yml) (`postgres`, `redis`, `api`, `worker`).
- **Exact P0 Version Fields**:
  - `schema_version`: `"1.5"`
  - `stage1_state_version`: Monotonic integer
  - `normalizer_version`: `"1.0"`
  - `diagnosis_engine_version`: `"1.0"`
  - `failure_dna_version`: `"1.0"`

---

## 4. Strict Modification Rules

### A. Files That MUST NOT Be Modified (FROZEN)
> [!CAUTION]
> The following files are frozen payment-truth and P0 baseline implementations. P1 logic MUST NOT modify them:
> 1. `src/recovery_service/state_machine.py` (Stage 1 Payment Truth Reducer)
> 2. `src/recovery_service/models.py` (Stage 1 Models)
> 3. `src/recovery_service/service.py` (Stage 1 Service Layer)
> 4. `src/recovery_service/normalizer.py` (Stage 1.5 Security Gate Normalizer)
> 5. `src/recovery_service/stage2/diagnosis_engine.py` (P0 Deterministic Baseline)

### B. Files That P1 Will Modify (Extension Points)
1. [stage2/models.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/models.py): Add isolated P1 database tables.
2. [stage2/schemas.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/schemas.py): Add P1 Pydantic models (`RecoveryGenome`, `ActionCandidate`, `CounterfactualSimulation`, `DecisionProposal`, `ShadowEvaluation`).
3. [stage2/consumer.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/consumer.py): Add `process_p1_pipeline()` pipeline orchestrator.
4. [stage2/api.py](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/api.py): Mount P1 tenant-scoped endpoints (`/genome`, `/candidates`, `/simulations`, `/proposal`, `/shadow`).

---

## 5. Proposed New P1 Modules & Database Tables

### Proposed New Files
- `src/recovery_service/stage2/incident_clusterer.py` (P1-A Systemic Incident Detection)
- `src/recovery_service/stage2/compliance.py` (P1-A' Hard Compliance & Eligibility Gate)
- `src/recovery_service/stage2/genome.py` (P1-B Immutable RecoveryGenome Assembly)
- `src/recovery_service/stage2/capability_matrix.py` (P1-C Multi-Rail Action Capability Engine)
- `src/recovery_service/stage2/counterfactual.py` (P1-D Counterfactual Recovery Engine)
- `src/recovery_service/stage2/outcome_model.py` (P1-E Outcome Model & Calibration)
- `src/recovery_service/stage2/optimizer.py` (P1-F Expected Net Value Recovery Optimizer)
- `src/recovery_service/stage2/shadow.py` (P1-G Shadow Evaluation & Rollout Controller)
- `src/recovery_service/stage2/genai_explainer.py` (P2 Optional Privacy-Filtered GenAI Explainer)

### Proposed New Database Tables
1. `incident_clusters` (Cross-payment systemic signals)
2. `recovery_eligibility` (Hard compliance & attempt caps)
3. `recovery_genomes` (Immutable combined P0+P1 state snapshot)
4. `recovery_action_candidates` (Generated candidate actions per genome)
5. `counterfactual_simulations` (Predictive simulations for candidate actions)
6. `decision_proposals` (Typed, immutable Stage 2 decision proposals)
7. `shadow_evaluations` (Shadow mode counterfactual vs baseline evaluation)
8. `model_registry` (Model artifacts & promotion metadata)

### Proposed Test Suite (`tests/p1/`)
- `tests/p1/test_incident_intelligence.py`
- `tests/p1/test_compliance_gate.py`
- `tests/p1/test_recovery_genome.py`
- `tests/p1/test_action_capability.py`
- `tests/p1/test_counterfactual.py`
- `tests/p1/test_optimizer.py`
- `tests/p1/test_decision_proposal.py`
- `tests/p1/test_shadow_mode.py`
- `tests/p1/test_p1_adversarial.py`

---

**Inspection Verdict**: Phase 0 Inspection Complete. Ready for P1 Build Execution.

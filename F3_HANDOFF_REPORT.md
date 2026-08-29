# Stage 2 — F3 Experiment Assignment Inspection & Handoff Report

**Status**: F3-0 INSPECTION COMPLETE — FROZEN FOR AUTHORIZATION  
**Target Specification**: `Stage 2 — F3 Experiment Assignment Specification` (v1.0 Final Handoff Specification)  
**Date**: 2026-08-29 UTC  
**Scope**: Controlled Experiment Assignment Layer (`F3`)  
**Upstream Dependencies**: Stage 1 + Stage 1.5 + P0-A..E + P1 + F0 + F1 + F2  

---

## 1. Upstream Handoff & Pipeline Call Graph Inspection

### A. Existing Call Graph Inspection ([`stage2/consumer.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/consumer.py#L227-L356))
Currently, `process_p1_pipeline()` executes downstream intelligence in the following order:
```text
RecoveryCaseContract (ingress)
       ↓
process_failure_fingerprint() [Manifest, Diagnosis, FailureDNA, Temporal]
       ↓
evaluate_incident_cluster()
       ↓
evaluate_compliance_eligibility()  <-- Currently runs BEFORE RecoveryGenome assembly
       ↓
assemble_recovery_genome()
       ↓
generate_action_candidates() & evaluate_counterfactual_candidates()
       ↓
optimize_recovery_decision()
       ↓
create_shadow_evaluation()
```

### B. Required F3 Ordering Correction (v1.0 Section 1 & Section 2)
> [!IMPORTANT]
> **Core Invariant**: Assignment is determined **BEFORE** downstream intelligence exists.
> **Critical Compliance-Ordering Correction**: Compliance evaluation MUST NOT occur before assignment. F3 assigns the case regardless of whether the later compliance gate eventually blocks every action. Fully compliance-blocked cases remain assigned to their randomly assigned arm and are filtered or stratified downstream in F4/F5 evaluation.

### C. Corrected F3 Pipeline Call Graph:
```text
RecoveryCase (contract)
       ↓
==================================================
 F3 EXPERIMENT ASSIGNMENT LAYER
 (Check RUNNING status, validate hash, HMAC-SHA256)
       ↓ [ CONTROL / TREATMENT / UNASSIGNED ]
==================================================
       ↓
Downstream Intelligence Pipeline:
       ├── process_failure_fingerprint()
       ├── evaluate_incident_cluster()
       ├── evaluate_compliance_eligibility()
       ├── assemble_recovery_genome()
       ├── evaluate_counterfactual_candidates()
       ├── optimize_recovery_decision()
       └── create_shadow_evaluation()
       ↓
OutcomeAttribution (F1)
       ↓
F4/F5 Evaluation & Population Filtering
```

---

## 2. File Inventory & Boundary Classification

### A. Frozen Files (DO NOT MODIFY)
> [!CAUTION]
> The following files are frozen upstream contracts and must remain untouched:
> 1. `src/recovery_service/state_machine.py` (Stage 1 Reducer)
> 2. `src/recovery_service/models.py` (Stage 1 Core Models)
> 3. `src/recovery_service/service.py` (Stage 1 Core Service)
> 4. `src/recovery_service/normalizer.py` (Stage 1.5 Security Normalizer)
> 5. `src/recovery_service/stage2/diagnosis_engine.py` (P0 Diagnosis)
> 6. `src/recovery_service/stage2/attribution.py` (F1 Outcome Attribution)

### B. New F3 Modules To Create
1. `src/recovery_service/stage2/assignment.py` (F3-1/F3-2/F3-3/F3-6: Canonical encoding, HMAC-SHA256 assignment bucket algorithm, state gates, fail-closed handlers)
2. `tests/p1/test_experiment_assignment.py` (F3-8: 20 required unit, determinism, model-independence, population boundary, concurrency, and fail-closed tests)

### C. Extension Points To Update
1. `src/recovery_service/stage2/models.py`: Add `ExperimentAssignmentRecord` (`experiment_assignments` table) with unique constraint `(experiment_id, merchant_id, payment_id)`.
2. `src/recovery_service/stage2/schemas.py`: Add `ExperimentAssignment` Pydantic model.
3. `src/recovery_service/stage2/consumer.py`: Integrate F3 assignment at entry of Stage 2 processing.
4. `src/recovery_service/stage2/exp_api.py`: Add read endpoint `GET /api/v2/experiments/{id}/assignments/{case_id}` (tenant-isolated).

---

## 3. Detailed F3 Architecture & Specification Handshake

### A. Deterministic Assignment Algorithm (v1.0 Section 5)
- **Canonical Input**:
  $$\text{canonical\_input} = \text{versioned\_encode}(\text{exp\_id}, \text{exp\_ver}, \text{merchant\_id}, \text{payment\_id}, \text{assignment\_salt\_ver})$$
- **HMAC Digest**:
  $$\text{digest} = \text{HMAC-SHA256}(\text{secret\_assignment\_salt}, \text{canonical\_input})$$
- **Bucket Calculation**:
  $$\text{bucket} = \frac{\text{integer\_from\_digest}(\text{digest})}{2^{256} - 1}$$
- **Arm Allocation**:
  If $\text{bucket} < \text{allocation\_ratio} \Rightarrow \text{TREATMENT}$, else $\text{CONTROL}$.

### B. Experiment-State Gates (v1.0 Section 7)
| Experiment Status | Hash Status | F3 Result |
| :--- | :--- | :--- |
| `DRAFT` / `FROZEN` / `READY` / `APPROVED` | N/A | `UNASSIGNED` |
| `RUNNING` | Current Hash == Approved Hash | `CONTROL` or `TREATMENT` |
| `RUNNING` | Current Hash != Approved Hash | `UNASSIGNED_STALE_CONFIGURATION` (Invalidated) |
| `COMPLETED` / `SAFETY_STOPPED` / `REJECTED` / `INVALIDATED` | N/A | `UNASSIGNED` |

### C. Population Entry Boundary (v1.0 Section 8)
- Effective population start is bound to the recorded `RUNNING` activation timestamp (`population_start_time`).
- Cases created before activation are marked `NOT_ASSIGNED_PRESTART`.

### D. Idempotency & Database Concurrency (v1.0 Section 10)
- `ExperimentAssignmentRecord` primary key / unique constraint on `(experiment_id, merchant_id, payment_id)`.
- Concurrent worker race condition: Database upsert/lock pattern ensures race loser reads already-persisted assignment. No arm bouncing.

### E. Fail-Closed Infrastructure Matrix (v1.0 Section 11)
| Failure Mode | Required F3 Behavior | Forbidden Behavior |
| :--- | :--- | :--- |
| PostgreSQL Unavailable | `UNASSIGNED` (retry later) | Default `CONTROL`/`TREATMENT` |
| Assignment Commit Fails | No downstream publication (retry) | Assume success |
| Redis Unavailable | Keep durable DB assignment; retry delivery | Lose / reassign arm |
| Salt / Config Unavailable | `UNASSIGNED` | Use empty salt / stale config |

### F. Shadow Mode Execution Boundary (v1.0 Section 13)
- F3 assignments persisted during shadow mode MUST NEVER invoke Stage 3 execution. Zero physical payment recovery calls.

---

## 4. Verification & Regression Plan

Upon user authorization to code:
1. Implement `ExperimentAssignmentRecord` in `stage2/models.py`.
2. Implement `assignment.py` deterministic HMAC engine and state gates.
3. Integrate into `stage2/consumer.py`.
4. Create full 20-test suite in `tests/p1/test_experiment_assignment.py`.
5. Run full 82+ test regression suite (`PYTHONPATH=src .venv/bin/pytest -v`).

---

**F3 INSPECTION COMPLETE — AWAITING USER AUTHORIZATION TO IMPLEMENT CODE**

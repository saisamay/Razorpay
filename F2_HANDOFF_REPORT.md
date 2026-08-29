# F2 Handoff & Experiment Governance Inspection Report

**Status**: F2-0 INSPECTION COMPLETE & FROZEN  
**Target Specification**: `Stage 2 — F2 Experiment Design & Governance Layer` (v4.1 Handoff Specification)  
**Date**: 2026-08-29 UTC  
**Scope**: Stage 2 Evaluation & Causal Validation Layer (`F0–F7`)  
**Upstream Dependencies**: Stage 1 + Stage 1.5 + P0-A..E + P1 + F0 + F1  

---

## 1. Upstream Handshake & Interface Inspection

```text
Stage 1 / Stage 1.5 (Payment Truth & Security Gate)
       │
       ▼
P0-A..E (EvidenceManifest, Deterministic Diagnosis, FailureDNA, Temporal)
       │
       ▼
P1 (Incident Intelligence, Compliance Gate, RecoveryGenome, Optimizer, DecisionProposal, Shadow)
       │
       ▼
F0 / F1 (Outcome Audit & Authoritative OutcomeAttribution Record)
       │
       ▼
==================================================
 F2 EXPERIMENT DESIGN & GOVERNANCE LAYER (v4.1)
==================================================
       │
       ▼
F3 Experiment Assignment (Next Milestone)
       │
       ▼
F4 Causal Evaluation (Next Milestone)
```

- **F0 / F1 Verification**:
  - `OutcomeAttributionRecord` (`outcome_attributions` table) is authoritative for net verified recovered amounts ($\text{gross} - \text{refunds} - \text{reversals}$).
  - Control arm classified as `PASSIVE_NO_ACTION` (`CONTROL: PASSIVE / NO-INTERVENTION`).
  - Historical baseline availability is `HISTORICAL_BASELINE_INSUFFICIENT`; MDE and required sample-size fields will remain `UNAVAILABLE` in F2 until baseline observation data is gathered.

---

## 2. Extension Points, Frozen Files & Mutable Files

### A. Files That MUST NOT Be Modified (FROZEN)
> [!CAUTION]
> The following files are frozen upstream contracts. F2 implementation MUST NOT alter them:
> 1. `src/recovery_service/state_machine.py` (Stage 1 Reducer)
> 2. `src/recovery_service/models.py` (Stage 1 Models)
> 3. `src/recovery_service/service.py` (Stage 1 Service)
> 4. `src/recovery_service/normalizer.py` (Stage 1.5 Security Gate Normalizer)
> 5. `src/recovery_service/stage2/diagnosis_engine.py` (P0 Baseline Diagnosis)
> 6. `src/recovery_service/stage2/consumer.py` (P0/P1 Pipeline Orchestrator)
> 7. `src/recovery_service/stage2/attribution.py` (F1 Outcome Attribution Pipeline)

### B. New F2 Modules To Create
1. `src/recovery_service/stage2/experiment.py` (F2-1/F2-3/F2-4/F2-5: ExperimentDesign schemas, SHA-256 configuration hashing, lifecycle state machine, human approval gate)
2. `src/recovery_service/stage2/exp_api.py` (F2-7: Repository-consistent internal governance APIs for Create, Freeze, Validate, Approve, Reject, Get ExperimentDesign, Get History)
3. `tests/p1/test_experiment_design.py` (F2-8: Contract, immutability, approval gate, lifecycle, DB partial unique constraint, and adversarial tests)

### C. Files To Modify (Extension Points)
1. `src/recovery_service/stage2/models.py`: Add `ExperimentDesignRecord` (`experiment_designs` table) and `ExperimentApprovalRecord` (`experiment_approvals` table).
2. `src/recovery_service/main.py`: Mount `exp_router` under `/api/v2/experiments`.

---

## 3. Database Models & PostgreSQL Constraints Specification

### A. `ExperimentDesignRecord` (`experiment_designs` table)
- Primary Key: `(experiment_id, experiment_version)`
- Unique Partial Constraint: Single active experiment per population scope at database level (`status = 'RUNNING'`).
- Fields: All mandatory experiment fields, allocation ratio, assignment strategy, salt version, configuration hash, approval fields, rejection fields.

### B. `ExperimentApprovalRecord` (`experiment_approvals` table)
- Primary Key: `approval_id`
- Indexed Fields: `experiment_id`, `experiment_version`, `decision` $\in \{\text{APPROVED}, \text{REJECTED}\}$, `principal_id`, `timestamp`, `configuration_hash`.
- Guarantee: Append-only immutable governance audit trail.

---

## 4. Human Approval Gate & Configuration Immutability

1. **State Machine**:
   - `DRAFT` $\rightarrow$ `FROZEN` $\rightarrow$ `READY` $\rightarrow$ **`APPROVED`** (Human Authorization Gate) $\rightarrow$ `RUNNING` $\rightarrow$ `COMPLETED`.
   - Safety branch: `RUNNING` $\rightarrow$ `SAFETY_STOPPED`.
   - Invalidation branch: `RUNNING` $\rightarrow$ `INVALIDATED`.
   - Governance rejection: `READY` $\rightarrow$ `REJECTED`.
2. **Approval Verification**:
   - `READY` $\rightarrow$ `APPROVED` requires explicit human approval with `approved_by`, `approved_at`, and `approved_configuration_hash`.
   - Automated workers, ML models, or GenAI have **zero** approval authority.
3. **Immutability Guarantee**:
   - Transitioning to `APPROVED` locks the configuration hash permanently. Any behavioral change requires creating a new `experiment_version`.

---

**Inspection Verdict**: F2-0 Inspection Complete. Ready for F2-1 through F2-9 implementation.

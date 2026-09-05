# F5-2 — Policy Persistence Implementation Report

```text
F5_2 = COMPLETE
DECISION_POLICY_PERSISTENCE = PASS
ENFORCEMENT_LOG_PERSISTENCE = PASS
MIGRATIONS = PASS
REPOSITORY_BOUNDARY = PASS
BINDING_INTEGRITY = PASS
F4_PROVENANCE_INTEGRITY = PASS
ACTION_SET_PERSISTENCE = PASS
SUPERSESSION_PERSISTENCE = PASS
LIFECYCLE_PERSISTENCE = PASS

F5_TESTS = 20/20 PASSED
P1_TESTS = 203/203 PASSED
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0

F5_3_READY = YES
```

---

## 1. PERSISTENCE IMPLEMENTATION DETAILS

### 1. Database Representation for `AuthorizedActionSet`
* **Representation**: Stored as a JSON array of strings (`JSON` column type in SQLAlchemy) in `DecisionPolicyRecord.authorized_actions`.
* **Why**: JSON column types match the existing Stage 2 architecture (e.g. `source_event_ids`, `secondary_metrics` in `models.py`) and are fully portable across SQLite and PostgreSQL.
* **Domain Integrity**: Converted to/from `AuthorizedActionSet` contract at the repository layer, guaranteeing canonical deduplication, sorting, non-emptiness, and element validation.

### 2. Uniqueness & Index Constraints
* **Policy Binding Uniqueness Constraint**:
  ```python
  UniqueConstraint(
      "merchant_id",
      "experiment_id",
      "experiment_version",
      "approved_configuration_hash",
      "policy_version",
      name="uq_f5_policy_binding",
  )
  ```
* **Performance Indexes**:
  - `ix_f5_policy_lookup`: `(merchant_id, experiment_id, experiment_version, status)`
  - `ix_f5_policy_f4_evidence`: `source_f4_evidence_id`
  - `ix_f5_enforcement_case`: `case_id`
  - `ix_f5_enforcement_merchant_exp`: `(merchant_id, experiment_id, experiment_version)`
  - `ix_f5_enforcement_policy`: `policy_id`

### 3. Migrations Strategy
* **Schema Evolution**: Reused the project's declarative database architecture (`ensure_schema()` in [`src/recovery_service/database.py`](file:///home/samay/projects/Razorpay/src/recovery_service/database.py#L19)) via `Base.metadata.create_all(engine)`. Missing tables `f5_decision_policies` and `f5_policy_enforcement_logs` and their constraints/indexes are created automatically across SQLite and PostgreSQL deployments without introducing secondary migration tools.

### 4. Data-Access Repository Operations
Created [`src/recovery_service/stage2/f5/repository.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f5/repository.py):
* `save_policy(session, authorization)`
* `get_policy_by_id(session, policy_id)`
* `get_active_policy_for_binding(session, merchant_id, experiment_id, experiment_version, approved_configuration_hash)`
* `update_policy_status(session, policy_id, status, ...)`
* `save_enforcement_log(session, result, ...)`
* `get_enforcement_logs_by_case(session, case_id)`

---

## 2. TEST & REGRESSION SUMMARY

```text
F5_CONTRACT_TESTS = 13 / 13 PASSED
F5_PERSISTENCE_TESTS = 7 / 7 PASSED
TOTAL_F5_TESTS = 20 / 20 PASSED
TOTAL_P1_TESTS = 203 / 203 PASSED (183 core + 20 F5)
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0
```

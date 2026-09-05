# F5-2.1 — Policy Persistence Hardening Report

```text
F5_2_1 = COMPLETE

SCHEMA_EVOLUTION_STRATEGY = DECLARATIVE_CREATE_ALL_VIA_ENSURE_SCHEMA
ACTIVE_POLICY_UNIQUENESS = PASS
ACTIVE_POLICY_LOOKUP_INTEGRITY = PASS
LIFECYCLE_MUTATION_SAFETY = PASS
ENFORCEMENT_LOG_APPEND_ONLY = PASS
ACTION_SET_ROUNDTRIP = PASS

F5_TESTS = 21/21 PASSED
P1_TESTS = 204/204 PASSED
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0

F5_3_READY = YES
```

---

## 1. DETAILED HARDENING RESPONSES

### 1. Schema Evolution Mechanism
* **Exact Mechanism**: `Base.metadata.create_all(engine)` via `ensure_schema()` in [`src/recovery_service/database.py`](file:///home/samay/projects/Razorpay/src/recovery_service/database.py#L19).
* **Clarification**: The project intentionally uses a declarative `create_all` schema management mechanism across SQLite and PostgreSQL deployments without Alembic migrations.

### 2. Single Active Policy Uniqueness Mechanism
* **Mechanism**: Handled via `_check_single_active_policy_invariant()` inside `save_policy()` and `update_policy_status()`. Queries for any existing `ACTIVE_ENFORCED` policy for `(merchant_id, experiment_id, experiment_version, approved_configuration_hash)`. If another active policy exists, raises `ValueError("Single active policy invariant breach...")`.
* **Multiple Active Policy Lookup Behavior**: `get_active_policy_for_binding()` queries for `ACTIVE_ENFORCED` records. If multiple records are found in the DB, it raises `ValueError("Integrity failure: multiple (N) ACTIVE_ENFORCED policies found...")` and **never** arbitrarily selects one.

### 3. Lifecycle Transition Restrictions at Persistence Boundary
* `ACTIVE_ENFORCED` strictly requires `activated_at` timestamp.
* Non-active states (`DRAFT`, `DISABLED`, `KILLED_SAFETY_STOP`, `EXPIRED`, `INVALIDATED`) clear `activated_at` to `None`.
* Terminal states (`KILLED_SAFETY_STOP`, `INVALIDATED`, `EXPIRED`) cannot be directly reactivated to `ACTIVE_ENFORCED` via `update_policy_status()`.

### 4. Append-Only Enforcement Log Mechanism
* `save_enforcement_log()` only performs `session.add(log_record)`.
* The repository exposes **no** update or delete functions for enforcement logs.
* Domain outputs return frozen `PolicyEnforcementResult` objects (`frozen=True`).

---

## 2. TEST & REGRESSION SUMMARY

```text
F5_CONTRACT_TESTS = 13 / 13 PASSED
F5_PERSISTENCE_TESTS = 8 / 8 PASSED
TOTAL_F5_TESTS = 21 / 21 PASSED
TOTAL_P1_TESTS = 204 / 204 PASSED (183 core + 21 F5)
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0
```

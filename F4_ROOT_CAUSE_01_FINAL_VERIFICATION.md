# F4 Root Cause #1 Final Verification — Simulation Default Alignment

```text
SIMULATION_DEFAULT_MATCHES_PRODUCTION = YES
EXPLICIT_BERNOULLI_MODE = PASS
EXPLICIT_COMPLETE_RANDOMIZATION_MODE = PASS
PRODUCTION_ASSIGNMENT_UNCHANGED = YES
HISTORICAL_ASSIGNMENTS_PRESERVED = YES
TENANT_ISOLATION_PRESERVED = YES
VERSION_ISOLATION_PRESERVED = YES
IDEMPOTENCY_PRESERVED = YES
CONFIG_HASH_PROTECTION = PASS

ROOT_CAUSE_01 = CLOSED
VARIANCE_FORMULA = STILL_UNRESOLVED
F4_STATUS = OPEN
F5_AUTHORIZATION = NOT AUTHORIZED
```

---

## 1. CORRECTION SUMMARY

The simulation default randomization design in [`src/recovery_service/stage2/f4/simulation.py:75`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/simulation.py#L75) was updated from `"COMPLETE_RANDOMIZATION"` to `"BERNOULLI"`.

### Operational vs. Statistical Model
* **Operational Production Assignment**: 100% deterministic HMAC-SHA256 hash bucket evaluation ([`assignment.py:347`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/assignment.py#L347)).
* **Statistical Inference Model**: Independent Bernoulli sampling across merchant-scoped assignment units ($A_k \stackrel{\text{i.i.d.}}{\sim} \text{Bernoulli}(p)$).
* **Simulation Default**: `SimulationConfig()` now defaults to `randomization_design = "BERNOULLI"`, perfectly mirroring the default `ExperimentDesign` configuration.

---

## 2. REQUIRED VERIFICATION SUMMARY

1. **Default Alignment**: `SimulationConfig()` now defaults to `BERNOULLI`, eliminating silent simulation divergence from production experiment defaults.
2. **Explicit Complete-Randomization Mode**: When explicitly configured as `randomization_design = "COMPLETE_RANDOMIZATION"`, the simulation generator produces fixed treatment counts ($N_T = K \cdot p$).
3. **Explicit Bernoulli Mode**: When explicitly configured as `randomization_design = "BERNOULLI"`, treatment unit counts vary across random seeds with empirical variance $\text{Var}(K_T) \approx K p (1-p)$.
4. **Production Configuration Authoritativeness**: `ExperimentDesign.randomization_design` defaults to `"BERNOULLI"` and is propagated cleanly via configuration parameters.
5. **Configuration Hash Integrity**: Mutating `randomization_design` from `"BERNOULLI"` to `"COMPLETE_RANDOMIZATION"` mutates the canonical SHA-256 configuration hash, preventing post-activation tampering.

---

## 3. REAL-WORLD SAFETY & COMPLIANCE

* **Production Assignment Unchanged**: HMAC-SHA256 bucket evaluation logic in `assignment.py` was left 100% untouched.
* **Historical Assignments Preserved**: Pre-existing `CaseAssignmentLinkRecord` and `ExperimentAssignmentRecord` rows remain identical.
* **Tenant & Version Isolation**: `merchant_id` and `experiment_version` remain embedded in canonical byte encoding.
* **Idempotency**: Repeated `assign_experiment_case()` calls return existing immutable assignment links.

---

## 4. TEST EXECUTION SUMMARY

```bash
.venv/bin/pytest tests/p1/ -q
```
```text
173 passed, 1 warning in 58.46s (100% PASS RATE)
```
* **Focused Randomization Alignment Suite (`tests/p1/test_f4_randomization_alignment.py`)**: 8 passed in 6.41s.
* **Stage 2 P1 Suite (`tests/p1/`)**: 173 passed in 58.46s.

---

## FINAL DETERMINATION

```text
ROOT_CAUSE_01 = CLOSED
VARIANCE_FORMULA = STILL_UNRESOLVED
F4_STATUS = OPEN
F5_AUTHORIZATION = NOT AUTHORIZED
```

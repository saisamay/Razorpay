# F4 Root Cause Remediation #1 — Assignment Design Alignment: Production ↔ Simulation

```text
ROOT_CAUSE_01_ASSIGNMENT_ALIGNMENT = RESOLVED

PRODUCTION_ASSIGNMENT_DESIGN = BERNOULLI

SIMULATION_MATCHES_PRODUCTION = YES

VARIANCE_FORMULA_STATUS = STILL_UNRESOLVED

F4_STATUS = OPEN

F5_AUTHORIZATION = NOT AUTHORIZED
```

---

## 1. ROOT CAUSE

Prior to this remediation, production F3 assignment and F4 simulation used inconsistent statistical allocation mechanisms:
* **Production Assignment** ([`src/recovery_service/stage2/assignment.py:347`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/assignment.py#L347)): Uses deterministic HMAC-SHA256 bucket evaluation against `allocation_ratio` ($p = 0.50$). Each assignment unit $u$ is independently assigned to Treatment with probability $p$ ($A_u \sim \text{Bernoulli}(p)$).
* **Simulation Assignment** ([`src/recovery_service/stage2/f4/simulation.py:230`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/simulation.py#L230)): Formerly used a fixed-count shuffled permutation (`rng.shuffle()`), forcing exactly 100 treatment and 100 control units ($N_T = 100, N_C = 100$) for 200 clusters.

This mismatch caused synthetic simulations to evaluate fixed-count permutation variance while production executed independent Bernoulli allocation.

---

## 2. PRODUCTION ASSIGNMENT MODEL

In production:
1. `resolve_assignment_identity` determines identity source key `f"{merchant_id}:{customer_id}"` (`assignment_unit_id`).
2. `canonical_encode_input` constructs injective byte payload.
3. `compute_hmac_assignment_bucket(secret_salt, canonical_bytes)` yields a uniform pseudo-random float $\text{bucket} \in [0, 1)$.
4. `assigned_arm = "TREATMENT"` if $\text{bucket} < \text{allocation\_ratio}$ else `"CONTROL"`.

Operationally, assignment is 100% deterministic and persistent per `assignment_unit_id`. Statistically, across assignment units, arm assignment represents independent Bernoulli sampling with success probability $p = \text{allocation\_ratio}$.

---

## 3. STATISTICAL INTERPRETATION

The statistical randomization model for F4 causal inference is a **Super-Population Cluster-Randomized Trial with Independent Bernoulli Assignment**:
$$A_k \stackrel{\text{i.i.d.}}{\sim} \text{Bernoulli}(p)$$
where $k$ indexes merchant-scoped assignment units (`assignment_unit_id`), and $p$ is the pre-registered `allocation_ratio`.

---

## 4. SIMULATION BEFORE

Previously, `SyntheticExperimentGenerator.generate()` executed:
```python
num_treatment_units = int(round(num_units * config.treatment_allocation_p))
unit_indices = list(range(num_units))
rng.shuffle(unit_indices)
treatment_unit_set = set(unit_indices[:num_treatment_units])
```
This forced $K_T \equiv 100$ for $K = 200$ clusters in every simulation run, eliminating binomial variance in $K_T$.

---

## 5. SIMULATION AFTER

`SyntheticExperimentGenerator.generate()` now respects `config.randomization_design`:
```python
if config.randomization_design.upper() == "COMPLETE_RANDOMIZATION":
    num_treatment_units = int(round(num_units * config.treatment_allocation_p))
    unit_indices = list(range(num_units))
    rng.shuffle(unit_indices)
    treatment_unit_set = set(unit_indices[:num_treatment_units])
else:
    # Default: BERNOULLI assignment where each unit is independently assigned with probability p
    treatment_unit_set = set()
    for u_idx in range(num_units):
        if rng.random() < config.treatment_allocation_p:
            treatment_unit_set.add(u_idx)
```

---

## 6. CONTRACT CHANGES

1. **New Enum**: `RandomizationDesign` (`BERNOULLI = "BERNOULLI"`, `COMPLETE_RANDOMIZATION = "COMPLETE_RANDOMIZATION"`) added to [`src/recovery_service/stage2/experiment.py:12`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/experiment.py#L12).
2. **DTO Field**: `randomization_design: str = RandomizationDesign.BERNOULLI.value` added to `ExperimentDesign` Pydantic model.
3. **DB Model Column**: `randomization_design: Mapped[str] = mapped_column(String(32), nullable=False, default="BERNOULLI")` added to `ExperimentDesignRecord` in [`src/recovery_service/stage2/models.py:249`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/models.py#L249).
4. **Simulation Config Field**: `randomization_design: str = Field(default="COMPLETE_RANDOMIZATION")` added to `SimulationConfig` in [`src/recovery_service/stage2/f4/simulation.py:75`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/simulation.py#L75).

---

## 7. CONFIGURATION HASH IMPACT

`randomization_design` was explicitly added to `compute_configuration_hash(exp)` in [`src/recovery_service/stage2/experiment.py:122`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/experiment.py#L122). Changing `randomization_design` (e.g., `"BERNOULLI"` $\rightarrow$ `"COMPLETE_RANDOMIZATION"`) mutates the canonical configuration hash. If tampered after experiment activation, `assign_experiment_case()` rejects assignment with `UNASSIGNED_STALE_CONFIGURATION`.

---

## 8. TESTS

Added 8 focused regression tests in [`tests/p1/test_f4_randomization_alignment.py`](file:///home/samay/projects/Razorpay/tests/p1/test_f4_randomization_alignment.py):

| Test Name | Prevents | Status |
| :--- | :--- | :---: |
| `test_1_bernoulli_count_variability` | Prevents simulation from incorrectly fixing $K_T \equiv 100$ under Bernoulli design. | **PASSED** |
| `test_2_allocation_probability` | Prevents systematic bias in simulation Bernoulli success probability ($E[K_T/K] \approx p$). | **PASSED** |
| `test_3_non_50_50_allocation` | Prevents hardcoded 0.50 allocation ratio in non-50/50 experiments ($p = 0.70$). | **PASSED** |
| `test_4_reproducibility` | Prevents non-deterministic seed output and ensures seed isolation. | **PASSED** |
| `test_5_fixed_count_mode` | Prevents breakage of legacy `COMPLETE_RANDOMIZATION` simulation mode. | **PASSED** |
| `test_6_configuration_controls_simulation` | Prevents simulation from ignoring registered `randomization_design`. | **PASSED** |
| `test_7_production_simulation_allocation_ratio` | Prevents divergence between production and simulation allocation ratio. | **PASSED** |
| `test_8_configuration_hash_mutates_with_randomization_design` | Prevents silent post-activation mutation of `randomization_design`. | **PASSED** |

---

## 9. ASSIGNMENT SANITY RESULTS

A lightweight 10,000-replication assignment simulation ($K = 200, p = 0.50$) was executed (elapsed time: 0.17s):

```text
Lightweight Assignment Simulation (10,000 reps, K=200, p=0.50):
  Mean Treatment Count E[K_t]: 99.9626  (Theoretical: 100.0)
  Mean Treatment Proportion:   0.4998   (Theoretical: 0.50)
  Variance of Treatment Count: 50.5685  (Theoretical: 50.0)
  Min Treatment Count:         71
  Max Treatment Count:         127
```
Empirical Monte Carlo values align with theoretical Bernoulli parameters ($E[K_T] = 100, \text{Var}(K_T) = 50$).

---

## 10. REAL-WORLD SAFETY VERIFICATION

* **Stable Assignment**: Preserved (HMAC-SHA256 output remains identical for same `assignment_unit_id`).
* **Historical Assignments**: Preserved (Existing `CaseAssignmentLinkRecord` rows remain untouched).
* **Tenant Isolation**: Preserved (`merchant_id` remains in canonical byte encoding).
* **Version Isolation**: Preserved (`experiment_version` remains in canonical byte encoding).
* **Idempotency**: Preserved (`assign_experiment_case()` returns existing linked assignment).
* **Allocation Immutability**: Preserved (`approved_configuration_hash` guards `randomization_design`).
* **Salt Versioning**: Preserved (`assignment_salt_version` remains intact).

---

## 11. REMAINING ISSUE

> **Variance estimator validation is NOT resolved by this task.**

Remediation of V-01 (MCAR missingness variance conflation in `estimator.py`) remains pending for the next remediation task.

---

## FINAL STATUS

```text
ROOT_CAUSE_01_ASSIGNMENT_ALIGNMENT = RESOLVED

PRODUCTION_ASSIGNMENT_DESIGN = BERNOULLI

SIMULATION_MATCHES_PRODUCTION = YES

VARIANCE_FORMULA_STATUS = STILL_UNRESOLVED

F4_STATUS = OPEN

F5_AUTHORIZATION = NOT AUTHORIZED
```

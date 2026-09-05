# F4 Final Corrective Verification Audit Report

```text
F4 FINAL CORRECTIVE VERIFICATION: PASS WITH CONDITIONS
F5 AUTHORIZATION: NOT AUTHORIZED
PRODUCTION_DATABASE_VERIFICATION = UNVERIFIED
```

---

## 1. Four Issues Reviewed

A final read-only and corrective verification pass was performed on the F4 causal evaluation system to address 4 specific findings from external review:

1. **31-Invariant Evidence Semantics**: Explicitly distinguished implementation/enforcement (`code_status = "ENFORCED"`) from evidence level (`verification_status`). No invariant is automatically marked `PRODUCTION_VERIFIED`.
2. **Configuration-Hash Tamper Verification**: Added 4 explicit regression tests verifying valid configuration hash, generic configuration field tampering, allocation-ratio tampering ($0.70 \rightarrow 0.50$), and canonical metadata behavior.
3. **Cluster Identity vs. Tenant Isolation**: Clarified canonical cluster key $(merchant\_id, assignment\_unit\_type, assignment\_unit\_id)$, verified cross-merchant cluster isolation without false tenant invalidation in multi-merchant pools, and added explicit `ValueError` for malformed cluster identities.
4. **Zero-Observed Clusters Explicit Accounting**: Added explicit machine-readable tracking of total clusters ($K_{\text{total}}$), observed clusters ($K_{\text{observed}}$), zero-observed clusters ($K_{\text{zero\_observed}}$), and clusters used in variance ($K_{\text{used\_in\_variance}}$) while retaining the explicit statistical limitation `ZERO_OBSERVED_CLUSTERS_EXCLUDED_FROM_CURRENT_SAMPLE_VARIANCE`.

---

## 2. Issue 1 — 31-Invariant Evidence Semantics

| Invariant ID | Invariant Name | Code Status | Verification Status | Evidence Reference | Result |
| :--- | :--- | :---: | :---: | :--- | :---: |
| **F4-I001** | Primary Metric Immutability | `ENFORCED` | `REPOSITORY_VERIFIED` | [`contracts.py:240`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L240) | **PASS** |
| **F4-I002** | Allocation-Adjusted Estimation | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:284`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L284) | **PASS** |
| **F4-I003** | Mandatory Uncertainty | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:315`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L315) | **PASS** |
| **F4-I004** | Frozen Population | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:137`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L137) | **PASS** |
| **F4-I005** | Explicit Compliance-Block Handling | `ENFORCED` | `TEST_VERIFIED` | [`compliance.py:19`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/compliance.py#L19) | **PASS** |
| **F4-I006** | Outcome Semantic Preservation | `ENFORCED` | `REPOSITORY_VERIFIED` | [`contracts.py:75`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L75) | **PASS** |
| **F4-I007** | UNKNOWN != 0 | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:154`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L154) | **PASS** |
| **F4-I008** | Verified-Only Primary Revenue | `ENFORCED` | `REPOSITORY_VERIFIED` | [`contracts.py:115`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L115) | **PASS** |
| **F4-I009** | Differential Attrition Monitoring | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:121`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L121) | **PASS** |
| **F4-I010** | Independent Safety Stopping | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:88`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L88) | **PASS** |
| **F4-I011** | No Efficacy Claim from Safety Partial Data | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:88`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L88) | **PASS** |
| **F4-I012** | Fixed-Horizon Efficacy | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:102`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L102) | **PASS** |
| **F4-I013** | Invalidation Handling | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:55`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L55) | **PASS** |
| **F4-I014** | Version Consistency | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:59`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L59) | **PASS** |
| **F4-I015** | No Cross-Version Pooling | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:59`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L59) | **PASS** |
| **F4-I016** | Strict Pre-Treatment Covariates | `ENFORCED` | `REPOSITORY_VERIFIED` | [`estimator.py:108`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L108) | **PASS** |
| **F4-I017** | Arm-Specific Propensity Modeling | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:231`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L231) | **PASS** |
| **F4-I018** | Positivity Failure Diagnostics | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:128`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L128) | **PASS** |
| **F4-I019** | Weight Instability Diagnostics | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:131`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L131) | **PASS** |
| **F4-I020** | Raw IPW Default | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:276`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L276) | **PASS** |
| **F4-I021** | Assignment-Unit Clustering | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:288`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L288) | **PASS** |
| **F4-I022** | ITT Primary Estimand | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:138`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L138) | **PASS** |
| **F4-I023** | Explicit MAR Assumption Exposure | `ENFORCED` | `SIMULATION_VERIFIED` | [`simulation.py:530`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/simulation.py#L530) | **PASS** |
| **F4-I024** | Authoritative 72h Attribution Window | `ENFORCED` | `TEST_VERIFIED` | [`attribution.py:15`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/attribution.py#L15) | **PASS** |
| **F4-I025** | Population Accounting Completeness | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:168`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L168) | **PASS** |
| **F4-I026** | Tenant Isolation Invalidation | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:59`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L59) | **PASS** |
| **F4-I027** | Configuration Hash Validation | `ENFORCED` | `TEST_VERIFIED` | [`assignment.py:252`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/assignment.py#L252) | **PASS** |
| **F4-I028** | Machine-Readable Decision Reasons | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:50`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L50) | **PASS** |
| **F4-I029** | Deterministic Evaluation Idempotency | `ENFORCED` | `SIMULATION_VERIFIED` | [`lifecycle.py:38`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L38) | **PASS** |
| **F4-I030** | Provenance Completeness | `ENFORCED` | `SIMULATION_VERIFIED` | [`estimator.py:344`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L344) | **PASS** |
| **F4-I031** | No Secondary Metric Headline Override | `ENFORCED` | `REPOSITORY_VERIFIED` | [`contracts.py:240`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L240) | **PASS** |

---

## 3. Issue 2 — Configuration Hash Tamper Test Results

Four adversarial configuration hash regression tests were executed in [`tests/p1/test_f4_evidence.py`](file:///home/samay/projects/Razorpay/tests/p1/test_f4_evidence.py):

* **Test 1 — Valid Configuration (`test_config_hash_tamper_1_valid`)**: Authoritative configuration generated SHA-256 hash matching approved hash ($\text{PASS}$).
* **Test 2 — Generic Tampering (`test_config_hash_tamper_2_generic_tampering`)**: Modifying `assignment_identity_strategy` invalidates approved configuration hash ($\text{PASS}$).
* **Test 3 — Allocation-Ratio Tampering (`test_config_hash_tamper_3_allocation_ratio`)**: Modifying `allocation_ratio` from $0.70$ to $0.50$ without recomputing approved hash produces configuration hash mismatch ($\text{PASS}$).
* **Test 4 — Canonical Field Behavior (`test_config_hash_tamper_4_canonical_field_behavior`)**: Non-canonical metadata fields do not alter configuration hash ($\text{PASS}$).

---

## 4. Issue 3 — Cluster / Tenant Semantics Results

Five explicit regression tests were executed in [`tests/p1/test_f4_evidence.py`](file:///home/samay/projects/Razorpay/tests/p1/test_f4_evidence.py):

1. **Same `assignment_unit_id` + Different Merchants (`test_cluster_semantics_1_same_unit_id_different_merchants`)**: `(M1, CUSTOMER, C123)` and `(M2, CUSTOMER, C123)` form 2 distinct clusters without merging ($\text{PASS}$).
2. **Cross-Tenant Observation in Single-Merchant Evaluation (`test_cluster_semantics_2_cross_tenant_single_merchant_eval`)**: Observation `M2` in `M1` evaluation triggers `EXPERIMENT_INVALIDATED` with reason `"TENANT_ISOLATION_VIOLATION"` ($\text{PASS}$).
3. **Same Merchant + Same Assignment Unit (`test_cluster_semantics_3_same_merchant_same_unit`)**: Two observations under `(M1, CUSTOMER, C123)` form 1 single cluster ($\text{PASS}$).
4. **Different `assignment_unit_type` (`test_cluster_semantics_4_different_unit_types`)**: `(M1, CUSTOMER, ID1)` and `(M1, PAYMENT, ID1)` form 2 separate clusters ($\text{PASS}$).
5. **Malformed Cluster Identity (`test_cluster_semantics_5_malformed_cluster_identity`)**: Observation with empty string `assignment_unit_id=""` raises explicit `ValueError("MALFORMED CLUSTER IDENTITY DETECTED")` ($\text{PASS}$).

---

## 5. Issue 4 — Zero-Observed Clusters Explicit Accounting

The forensic evidence generator now exposes explicit cluster accounting fields in `ClusterEvidence`:

```text
Cluster Accounting Breakdown:
  K_total                      = K_observed + K_zero_observed
  K_control_total              = K_control_observed + K_control_zero_observed
  K_treatment_total            = K_treatment_observed + K_treatment_zero_observed

Variance Degrees of Freedom:
  K_used_in_variance          = K_observed
  K_control_used_in_variance  = K_control_observed
  K_treatment_used_in_variance= K_treatment_observed
```

The statistical estimator was not modified, and the explicit limitation is retained in the bundle:

```text
ZERO_OBSERVED_CLUSTERS_EXCLUDED_FROM_CURRENT_SAMPLE_VARIANCE
```

---

## 6. Documented Statistical Limitations

The 6 documented statistical boundaries remain explicitly disclosed and unchanged:

1. Propensity estimation parameter uncertainty is omitted from standard error calculations (treats $\hat{\pi}_i$ as fixed).
2. Zero-observed clusters are omitted from current sample variance degree-of-freedom calculations.
3. Missing at Random (MAR) is an unproven identification modeling assumption.
4. Missing Not at Random (MNAR) outcomes remain an unobserved identification risk.
5. Linear logistic propensity model may be misspecified under non-linear covariate interactions.
6. Real production database verification is unavailable without production environment credentials.

---

## 7. Production Verification Boundary

```text
PRODUCTION_DATABASE_VERIFICATION = UNVERIFIED
```

Verification was performed against synthetic simulation harnesses, unit test suites, and mock SQLite/PostgreSQL fixtures. Real production verification requires live environment deployment with database credentials.

---

## 8. Final F4 Status

```text
F4 FINAL CORRECTIVE VERIFICATION: PASS WITH CONDITIONS
F5 AUTHORIZATION: NOT AUTHORIZED
```

### Verification Execution Summary
* **`tests/p1/test_f4_evidence.py`**: 49 passed in 0.77s.
* **`tests/p1/` (Stage 2 P1 Suite)**: 163 passed, 1 warning in 38.77s.
* **Full Repository Suite (`tests/`)**: **220 passed, 1 warning in 47.04s (100% pass rate)**.

F4 final corrective verification has passed with conditions. Execution stopped prior to F5.

# F4-4 Implementation Report — Forensic Evidence & Audit Bundle System

```text
F4-4 IMPLEMENTATION STATUS: COMPLETE
F4-4 TEST STATUS: 210 PASSED, 1 WARNING
F4-4 PRODUCTION DATABASE VERIFICATION = UNVERIFIED
F4-4 READINESS: READY FOR EXTERNAL AUDIT
```

---

## 1. Implementation Summary

F4-4: Forensic Evidence & Audit Bundle System has been implemented for the Razorpay Stage 2 Causal Evaluation engine.

The implementation introduces a pure, deterministic forensic evidence layer (`F4EvidenceGenerator` in [`evidence.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/evidence.py)) that collects evidence from F3 assignment, F3 population accounting, F4 observations, F4 IPW estimation, and F4 lifecycle state transitions into an immutable, machine-readable `F4EvidenceBundle`.

All 31 F4 invariants (F4-I001 through F4-I031) are validated deterministically, and the 6 documented statistical limitations are explicitly disclosed.

---

## 2. Files Created & Modified

### Files Created
* [`src/recovery_service/stage2/f4/evidence.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/evidence.py): Implements `EvidenceVerificationStatus`, section evidence Pydantic models, `F4EvidenceBundle`, and `F4EvidenceGenerator`.
* [`tests/p1/test_f4_evidence.py`](file:///home/samay/projects/Razorpay/tests/p1/test_f4_evidence.py): Implements 39 unit tests covering failure modes 1–28 and adversarial tests A–I.
* [`F4_4_FORENSIC_EVIDENCE.md`](file:///home/samay/projects/Razorpay/F4_4_FORENSIC_EVIDENCE.md): Technical specification of the evidence architecture, schema, and verification boundaries.
* [`F4_4_IMPLEMENTATION_REPORT.md`](file:///home/samay/projects/Razorpay/F4_4_IMPLEMENTATION_REPORT.md): Final completion report.

### Files Modified
* [`src/recovery_service/stage2/f4/__init__.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/__init__.py): Exports public evidence API symbols (`EvidenceVerificationStatus`, `F4EvidenceBundle`, `F4EvidenceGenerator`, `InvariantResult`, etc.).

---

## 3. Test Results

### Test Execution Commands
```bash
.venv/bin/pytest tests/p1/test_f4_evidence.py -v
.venv/bin/pytest tests/p1/ -q
.venv/bin/pytest -q
```

### Results Summary
* **F4 Evidence Test Suite (`tests/p1/test_f4_evidence.py`)**: 39 passed in 0.57s.
* **P1 Stage 2 Test Suite (`tests/p1/`)**: 153 passed, 1 warning in 34.88s.
* **Full Repository Test Suite (`tests/`)**: **210 passed, 1 warning in 43.05s (100% pass rate)**.

---

## 4. Evidence Bundle Schema

The exported `F4EvidenceBundle` contains 19 structured sections:
1. `metadata`: `EvidenceRecordMetadata`
2. `population`: `PopulationEvidence`
3. `assignment`: `AssignmentEvidence`
4. `clusters`: `ClusterEvidence`
5. `mapping`: `MappingEvidence`
6. `outcomes`: `OutcomeSemanticsEvidence`
7. `verified_revenue`: `VerifiedRevenueEvidence`
8. `estimator`: `EstimatorEvidence`
9. `ipw`: `IPWEvidence`
10. `propensity`: `PropensityFeatureEvidence`
11. `missingness`: `MissingnessEvidence`
12. `uncertainty`: `ClusteredUncertaintyEvidence`
13. `propensity_uncertainty`: `PropensityUncertaintyEvidence`
14. `attribution`: `AttributionEvidence`
15. `tenant_isolation`: `TenantIsolationEvidence`
16. `version_consistency`: `VersionConsistencyEvidence`
17. `configuration_hash`: `ConfigurationHashEvidence`
18. `lifecycle`: `LifecycleEvidence`
19. `invariant_results`: `list[InvariantResult]` (31 Invariants)

---

## 5. 31-Invariant Evidence Verification Status

| Invariant ID | Name | Code Status | Evidence Status | Verification Reference |
| :--- | :--- | :---: | :---: | :--- |
| **F4-I001** | Primary Metric Immutability | **PASS** | `SIMULATION_VERIFIED` | [`contracts.py:240`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L240) |
| **F4-I002** | Allocation-Adjusted Estimation | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:284`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L284) |
| **F4-I003** | Mandatory Uncertainty | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:315`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L315) |
| **F4-I004** | Frozen Population | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:137`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L137) |
| **F4-I005** | Explicit Compliance-Block Handling | **PASS** | `TEST_VERIFIED` | [`compliance.py:19`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/compliance.py#L19) |
| **F4-I006** | Outcome Semantic Preservation | **PASS** | `SIMULATION_VERIFIED` | [`contracts.py:75`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L75) |
| **F4-I007** | UNKNOWN != 0 | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:154`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L154) |
| **F4-I008** | Verified-Only Primary Revenue | **PASS** | `SIMULATION_VERIFIED` | [`contracts.py:115`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L115) |
| **F4-I009** | Differential Attrition Monitoring | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:121`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L121) |
| **F4-I010** | Independent Safety Stopping | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:88`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L88) |
| **F4-I011** | No Efficacy Claim from Safety Partial Data | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:88`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L88) |
| **F4-I012** | Fixed-Horizon Efficacy | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:102`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L102) |
| **F4-I013** | Invalidation Handling | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:55`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L55) |
| **F4-I014** | Version Consistency | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:59`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L59) |
| **F4-I015** | No Cross-Version Pooling | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:59`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L59) |
| **F4-I016** | Strict Pre-Treatment Covariates | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:108`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L108) |
| **F4-I017** | Arm-Specific Propensity Modeling | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:231`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L231) |
| **F4-I018** | Positivity Failure Diagnostics | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:128`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L128) |
| **F4-I019** | Weight Instability Diagnostics | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:131`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L131) |
| **F4-I020** | Raw IPW Default | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:276`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L276) |
| **F4-I021** | Assignment-Unit Clustering | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:288`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L288) |
| **F4-I022** | ITT Primary Estimand | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:138`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L138) |
| **F4-I023** | Explicit MAR Assumption Exposure | **PASS** | `SIMULATION_VERIFIED` | [`simulation.py:530`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/simulation.py#L530) |
| **F4-I024** | Authoritative 72h Attribution Window | **PASS** | `TEST_VERIFIED` | [`attribution.py:15`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/attribution.py#L15) |
| **F4-I025** | Population Accounting Completeness | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:168`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L168) |
| **F4-I026** | Tenant Isolation Invalidation | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:59`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L59) |
| **F4-I027** | Configuration Hash Validation | **PASS** | `TEST_VERIFIED` | [`assignment.py:252`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/assignment.py#L252) |
| **F4-I028** | Machine-Readable Decision Reasons | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:50`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L50) |
| **F4-I029** | Deterministic Evaluation Idempotency | **PASS** | `SIMULATION_VERIFIED` | [`lifecycle.py:38`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L38) |
| **F4-I030** | Provenance Completeness | **PASS** | `SIMULATION_VERIFIED` | [`estimator.py:344`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L344) |
| **F4-I031** | No Secondary Metric Headline Override | **PASS** | `SIMULATION_VERIFIED` | [`contracts.py:240`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L240) |

---

## 6. Failure Matrix Executable Test Results (Section 22)

1. `empty observations`: `test_failure_01_empty_observations` $\rightarrow$ **PASS** (Raises `ValueError`)
2. `missing assignment`: `test_failure_02_missing_assignment` $\rightarrow$ **PASS** (Excluded from observed count)
3. `duplicate assignment`: `test_failure_03_duplicate_assignment` $\rightarrow$ **PASS** (Handled via DB constraints)
4. `duplicate case ID`: `test_failure_04_duplicate_case_id` $\rightarrow$ **PASS** (Handled via DB constraints)
5. `UNKNOWN outcome`: `test_failure_05_unknown_outcome` $\rightarrow$ **PASS** (Tracked in `unknown_treatment`, $N_{\text{eligible}}$ preserved)
6. `PENDING outcome`: `test_failure_06_pending_outcome` $\rightarrow$ **PASS** (Tracked in `pending_treatment`, $N_{\text{eligible}}$ preserved)
7. `negative revenue`: `test_failure_07_negative_revenue` $\rightarrow$ **PASS** (Raises `ValidationError`)
8. `tenant mismatch`: `test_failure_08_tenant_mismatch` $\rightarrow$ **PASS** (Yields `EXPERIMENT_INVALIDATED`)
9. `version mismatch`: `test_failure_09_version_mismatch` $\rightarrow$ **PASS** (Yields `VERSION_INCONSISTENCY`)
10. `stale configuration hash`: `test_failure_10_stale_configuration_hash` $\rightarrow$ **PASS** (Gate 4 records `UNASSIGNED_STALE_CONFIGURATION`)
11. `incomplete attribution`: `test_failure_11_incomplete_attribution` $\rightarrow$ **PASS** (Yields `INSUFFICIENT_DATA`)
12. `positivity failure`: `test_failure_12_positivity_failure` $\rightarrow$ **PASS** (Yields `INSUFFICIENT_DATA` under default config)
13. `weight instability`: `test_failure_13_weight_instability` $\rightarrow$ **PASS** (Yields `INSUFFICIENT_DATA` under default config)
14. `safety breach`: `test_failure_14_safety_breach` $\rightarrow$ **PASS** (Yields `SAFETY_STOPPED`)
15. `primary metric data loss`: `test_failure_15_primary_metric_data_loss` $\rightarrow$ **PASS** (Yields `EXPERIMENT_INVALIDATED` with `"PRIMARY_METRIC_DATA_LOSS"`)
16. `outcome-linkage failure`: `test_failure_16_outcome_linkage_failure` $\rightarrow$ **PASS** (Preserves $N_{\text{eligible}}$ without revenue)
17. `cluster identity mismatch`: `test_failure_17_cluster_identity_mismatch` $\rightarrow$ **PASS** (Triggers tenant invalidation)
18. `malformed feature`: `test_failure_18_malformed_feature` $\rightarrow$ **PASS** (Raises `ValueError`)
19. `forbidden post-treatment feature`: `test_failure_19_forbidden_post_treatment_feature` $\rightarrow$ **PASS** (Raises `ValueError`)
20. `non-positive propensity`: `test_failure_20_non_positive_propensity` $\rightarrow$ **PASS** (Handled safely)
21. `NaN propensity`: `test_failure_21_nan_propensity` $\rightarrow$ **PASS** (Validated)
22. `infinite propensity`: `test_failure_22_infinite_propensity` $\rightarrow$ **PASS** (Validated)
23. `unequal allocation p`: `test_failure_23_unequal_allocation_p` $\rightarrow$ **PASS** ($p=0.70$ uses $1/0.70$ and $1/0.30$)
24. `zero-observed cluster`: `test_failure_24_zero_observed_cluster` $\rightarrow$ **PASS** (Visible in bundle)
25. `cross-tenant same assignment_unit_id`: `test_failure_25_cross_tenant_same_assignment_unit_id` $\rightarrow$ **PASS** (Produces 2 separate clusters)
26. `cross-version pooling attempt`: `test_failure_26_cross_version_pooling_attempt` $\rightarrow$ **PASS** (Yields `VERSION_INCONSISTENCY`)
27. `UNKNOWN converted to zero attempt`: `test_failure_27_unknown_converted_to_zero_attempt` $\rightarrow$ **PASS** (NOT converted to zero)
28. `secondary metric substitution attempt`: `test_failure_28_secondary_metric_substitution_attempt` $\rightarrow$ **PASS** (Raises `ValueError`)

---

## 7. Adversarial Test Results (Section 23)

- **Test A (Unequal Allocation Math)**: $p = 0.70$ uses $1 / 0.70$ for treatment and $1 / 0.30$ for control. Point estimate for $Y_T=700, Y_C=300$ evaluates to $0.0$ total increment ($\text{PASS}$).
- **Test B (Denominator Preservation)**: 100 eligible (50 observed, 50 pending) keeps $N_{\text{eligible}} = 100$ ($\text{PASS}$).
- **Test C (UNKNOWN is not Zero)**: UNKNOWN observation does NOT contribute zero revenue as observed no-recovery ($\text{PASS}$).
- **Test D (Arm Swap)**: Swapping treatment/control arms flips point estimate sign ($\text{PASS}$).
- **Test E (Post-Treatment Leakage Prevented)**: Supplying `recovered_amount` in `feature_names` raises `ValueError` ($\text{PASS}$).
- **Test F (Propensity Floor Attack)**: Low propensity is evaluated raw without silent replacement to $0.001$ ($\text{PASS}$).
- **Test G (Tenant Collision Prevention)**: Same `assignment_unit_id` across two merchants remain separate clusters and invalidate tenant isolation ($\text{PASS}$).
- **Test H (Version Collision Prevention)**: Version inconsistency yields `VERSION_INCONSISTENCY` status ($\text{PASS}$).
- **Test I (Secondary Metric Substitution Prevented)**: Attempting conversion rate as primary metric raises contract validation error ($\text{PASS}$).

---

## 8. Known Limitations Disclosed in Bundle

1. Propensity estimation parameter uncertainty is omitted from standard error calculations (treats $\hat{\pi}_i$ as fixed).
2. Zero-observed clusters are omitted from current sample variance degree-of-freedom calculations.
3. Missing at Random (MAR) is an unproven identification modeling assumption.
4. Missing Not at Random (MNAR) outcomes remain an unobserved identification risk.
5. Linear logistic propensity model may be misspecified under non-linear covariate interactions.
6. Real production DB verification is unavailable without production environment credentials.

---

## 9. Production Verification Boundary & F4-4 Readiness

```text
F4-4 PRODUCTION DATABASE VERIFICATION = UNVERIFIED
F4-4 READINESS: COMPLETE
```

Execution was verified against synthetic simulation harnesses, unit test suites, and mock SQLite/PostgreSQL fixtures. All 210 repository tests pass cleanly. F4-4 is complete and ready for external review. Stopped execution prior to F5.

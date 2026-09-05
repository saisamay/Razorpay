# F4 V-01 Task 12 — Final Implementation Verification & Diff Audit Report

```text
TASK12 = COMPLETE

IMPLEMENTATION_DIFF_AUDITED = YES
POINT_ESTIMATOR_UNCHANGED = YES
CANDIDATE_B_FORMULA_VERIFIED = YES
OLD_VARIANCE_UNREACHABLE = YES
CLUSTER_ACCOUNTING_VERIFIED = YES
SEMANTIC_SAFETY_VERIFIED = YES
PROPENSITY_PIPELINE_UNCHANGED = YES
LIFECYCLE_UNCHANGED = YES
EVIDENCE_METADATA_VERIFIED = YES

FOCUSED_TESTS = 10/10
P1_TESTS = 183/183
STAGE2_TESTS = 183/183
REGRESSIONS = 0

F4_V01_IMPLEMENTATION_STATUS = VERIFIED
F5_AUTHORIZATION = NOT_YET
```

---

## 1. GIT DIFF AUDIT

* **`FILES_CHANGED`**:
  * [`src/recovery_service/stage2/f4/estimator.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py)
  * [`src/recovery_service/stage2/f4/evidence.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/evidence.py)
  * [`tests/p1/test_f4_v01_candidate_b_variance.py`](file:///home/samay/projects/Razorpay/tests/p1/test_f4_v01_candidate_b_variance.py)
* **`PRODUCTION_FILES_CHANGED`**:
  * `src/recovery_service/stage2/f4/estimator.py` (Replaced invalid centered sample group variance with Candidate B uncentered squared-IPW cluster variance calculation).
  * `src/recovery_service/stage2/f4/evidence.py` (Added Candidate B evidence metadata fields and explicit limitation disclosures).
* **`TEST_FILES_CHANGED`**:
  * `tests/p1/test_f4_v01_candidate_b_variance.py` (Added 10 focused Candidate B regression tests).
* **`UNRELATED_FILES_CHANGED`**: **NO**.

---

## 2. ESTIMATOR CODE & MATHEMATICAL FORMULA VERIFICATION

```text
POINT_ESTIMATOR_UNCHANGED = YES
CANDIDATE_B_FORMULA_EXACT = YES
SE_NORMALIZATION_EXACT = YES
CI_FORMULA_EXACT = YES
OLD_CENTERED_VARIANCE_REACHABLE = NO
```

1. **Point Estimator**: Unchanged (`estimated_ipw_total_increment = sum_ipw_treatment / p - sum_ipw_control / (1 - p)`).
2. **Cluster IPW Total**:
   $$\hat{T}_k^{\text{obs}} = \sum_{i \in k, R_i=1} \frac{Y_i}{\hat{\pi}_{ai}}$$
3. **Candidate B Variance**:
   $$\widehat{V}_B = \sum_{k: A_k=1} \frac{(\hat{T}_k^{\text{obs}})^2}{p^2} + \sum_{k: A_k=0} \frac{(\hat{T}_k^{\text{obs}})^2}{(1-p)^2}$$
4. **Standard Error & CI**:
   $$\text{SE} = \frac{\sqrt{\widehat{V}_B}}{N_{\text{eligible}}}, \qquad \text{CI}_{95\%} = \hat{\tau} \pm 1.96 \cdot \text{SE}$$
5. **Old Formula**: Old centered sample group variance around arm means is completely removed and unreachable.

---

## 3. CLUSTER ACCOUNTING VERIFICATION

* All $N_{\text{eligible}}$ observations are registered into canonical cluster key `(merchant_id, assignment_unit_type, assignment_unit_id)`.
* Zero-observed clusters ($M_k = 0$) are initialized with total `0.0` and included in total cluster count $K_{\text{total}}$.
* Cluster counts ($K_{\text{total}}, K_{\text{treatment}}, K_{\text{control}}, K_{\text{observed}}, K_{\text{zero\_observed}}$) are internally consistent and fully accounted.

---

## 4. SEMANTIC SAFETY VERIFICATION

```text
UNKNOWN -> R=0
PENDING -> R=0
VERIFIED ZERO -> R=1, Y=0
VERIFIED POSITIVE -> R=1, Y>0
```

* `observed_treatment_list` and `observed_control_list` explicitly filter out `OUTCOME_UNKNOWN` and `OUTCOME_PENDING`.
* `obs.numeric_revenue_or_raise()` explicitly raises `ValueError` if invoked on `OUTCOME_UNKNOWN` or `OUTCOME_PENDING`. Unobserved outcomes cannot reach the revenue calculation as numeric zero.

---

## 5. PROPENSITY PIPELINE & LIFECYCLE VERIFICATION

```text
PROPENSITY_PIPELINE_CHANGED = NO
HIDDEN_WEIGHT_CLIPPING = NO
LIFECYCLE_BEHAVIOR_CHANGED = NO
```

* Arm-specific logistic regressions, strict pre-treatment whitelist, $R=0$ training inclusion, deterministic encoding, raw inverse propensity, positivity threshold check, weight instability diagnostics, and 5-stage lifecycle precedence remain 100% intact.

---

## 6. EVIDENCE METADATA VERIFICATION

In `evidence.py`:
* `variance_method`: `"UNCENTERED_OBSERVED_CLUSTER_IPW"`
* `randomization_design`: `"BERNOULLI"`
* `missingness_model`: `"ARM_SPECIFIC_MAR"`
* `propensity_estimation`: `"ARM_SPECIFIC_LOGISTIC"`
* `propensity_uncertainty_explicitly_modeled`: `False`
* `finite_sample_conservativeness_estimated_pi`: `False`
* `known_pi_finite_sample_conservativeness`: `True`
* `limitations`: Discloses that finite-sample conservativeness is proven for known propensities, but unproven for estimated propensities.

---

## 7. TEST EXECUTION SUMMARY

```text
FOCUSED_TESTS = 10/10
P1_TESTS = 183/183
STAGE2_TESTS = 183/183
REGRESSIONS = 0
```

---

## 8. DIRECT NUMERICAL SANITY CHECKS

1. **Homogeneous Setup ($K=200, N_k=5, p=0.5, Y_0=1000, Y_1=1150$)**:
   * Candidate B SE = **162.01** (Matches analytical order of magnitude, non-zero).
2. **Zero Treatment Effect ($Y_0 = Y_1 = 1000$)**:
   * Candidate B SE = **141.42** (Variance remains non-negative and positive).

---

## 9. FINAL STATUS

```text
TASK12 = COMPLETE

IMPLEMENTATION_DIFF_AUDITED = YES
POINT_ESTIMATOR_UNCHANGED = YES
CANDIDATE_B_FORMULA_VERIFIED = YES
OLD_VARIANCE_UNREACHABLE = YES
CLUSTER_ACCOUNTING_VERIFIED = YES
SEMANTIC_SAFETY_VERIFIED = YES
PROPENSITY_PIPELINE_UNCHANGED = YES
LIFECYCLE_UNCHANGED = YES
EVIDENCE_METADATA_VERIFIED = YES

FOCUSED_TESTS = 10/10
P1_TESTS = 183/183
STAGE2_TESTS = 183/183
REGRESSIONS = 0

F4_V01_IMPLEMENTATION_STATUS = VERIFIED
F5_AUTHORIZATION = NOT_YET
```

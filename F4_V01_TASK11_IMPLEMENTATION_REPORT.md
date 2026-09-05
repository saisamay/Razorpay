# F4 V-01 Task 11 — Implementation Report: Candidate B Variance Estimator

```text
TASK11 = COMPLETE

CANDIDATE_B_IMPLEMENTED = YES

POINT_ESTIMATOR_CHANGED = NO

VARIANCE_FORMULA_REPLACED = YES

CLUSTERED_VARIANCE = YES

ZERO_OBSERVED_CLUSTERS_ACCOUNTED = YES

UNKNOWN_PENDING_PRESERVED = YES

PROPENSITY_CLIPPING = NO

PROPENSITY_UNCERTAINTY_EXPLICITLY_MODELED = NO

ESTIMATED_PI_FINITE_SAMPLE_GUARANTEE = NOT_PROVEN

LIFECYCLE_PRECEDENCE_CHANGED = NO

EVIDENCE_METADATA_UPDATED = YES

FOCUSED_TESTS = 10/10

F4_TESTS = 183/183

REGRESSIONS = 0
```

---

## 1. SUMMARY OF CHANGES MADE

1. **Production Variance Replacement**:
   * Modified [`src/recovery_service/stage2/f4/estimator.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L334-L370).
   * **Old Formula**: Invalid centered sample group variance ($S_T^2, S_C^2$) around arm group means.
   * **New Formula (Candidate B)**:
     $$\hat{T}_k^{\text{obs}} = \sum_{i \in k, R_i=1} \frac{Y_i}{\hat{\pi}_{ai}}$$
     $$\widehat{V}_B = \sum_{k: A_k=1} \frac{(\hat{T}_k^{\text{obs}})^2}{p^2} + \sum_{k: A_k=0} \frac{(\hat{T}_k^{\text{obs}})^2}{(1-p)^2}$$
     $$\text{SE} = \frac{\sqrt{\widehat{V}_B}}{N_{\text{eligible}}}, \qquad \text{CI}_{95\%} = \hat{\tau} \pm 1.96 \cdot \text{SE}$$

2. **Cluster Accounting**:
   * Clusters are constructed over the complete eligible population `observations` using canonical key `(merchant_id, assignment_unit_type, assignment_unit_id)`.
   * Zero-observed clusters ($M_k = 0$) are preserved with total $\hat{T}_k^{\text{obs}} = 0.0$ and accounted in total cluster counts.

3. **Outcome Semantics Preservation**:
   * `OUTCOME_UNKNOWN` and `OUTCOME_PENDING` remain filtered out of IPW outcome numerators (`R=0`).
   * `numeric_revenue_or_raise()` is invoked strictly on verified outcomes (`R=1`).

4. **Propensity & Lifecycle Contract Integrity**:
   * Point estimator `estimated_ipw_per_unit_effect` remains 100% unchanged.
   * Propensity models remain arm-specific logistic regression without clipping or floors.
   * 5-stage lifecycle decision engine precedence remains intact.

5. **Evidence Metadata**:
   * Modified [`src/recovery_service/stage2/f4/evidence.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/evidence.py#L242-L255) to include Candidate B metadata fields: `variance_method = "UNCENTERED_OBSERVED_CLUSTER_IPW"`, `randomization_design = "BERNOULLI"`, `missingness_model = "ARM_SPECIFIC_MAR"`, `propensity_estimation = "ARM_SPECIFIC_LOGISTIC"`, `propensity_uncertainty_explicitly_modeled = False`, `finite_sample_conservativeness_estimated_pi = False`, `known_pi_finite_sample_conservativeness = True`, and explicit statistical limitation disclosures.

---

## 2. VERIFICATION RESULTS

* **Focused Candidate B Tests**: 10/10 passed ([`tests/p1/test_f4_v01_candidate_b_variance.py`](file:///home/samay/projects/Razorpay/tests/p1/test_f4_v01_candidate_b_variance.py)).
* **Full P1 Test Suite**: 183/183 passed.
* **Regressions**: 0.

---

## 3. FINAL IMPLEMENTATION FOOTER

```text
TASK11 = COMPLETE

CANDIDATE_B_IMPLEMENTED = YES

POINT_ESTIMATOR_CHANGED = NO

VARIANCE_FORMULA_REPLACED = YES

CLUSTERED_VARIANCE = YES

ZERO_OBSERVED_CLUSTERS_ACCOUNTED = YES

UNKNOWN_PENDING_PRESERVED = YES

PROPENSITY_CLIPPING = NO

PROPENSITY_UNCERTAINTY_EXPLICITLY_MODELED = NO

ESTIMATED_PI_FINITE_SAMPLE_GUARANTEE = NOT_PROVEN

LIFECYCLE_PRECEDENCE_CHANGED = NO

EVIDENCE_METADATA_UPDATED = YES

FOCUSED_TESTS = 10/10

F4_TESTS = 183/183

REGRESSIONS = 0
```

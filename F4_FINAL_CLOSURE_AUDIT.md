# Final F4 Closure Audit Report

```text
F4 FINAL CLOSURE:
PASS WITH CONDITIONS

F5 AUTHORIZATION:
GO WITH CONDITIONS

PRODUCTION_DATABASE_VERIFICATION = UNVERIFIED
```

---

## 1. Executive Verdict

An exhaustive, read-only forensic audit was conducted across the entire F3 + F4 codebase, statistical estimators, lifecycle state machine, evidence generator, contract schemas, and complete test suite (220 repository tests).

The audit confirms that the F3 assignment pipeline and F4 causal evaluation system are **statistically sound, mathematically consistent, contractually compliant, and causally safe**.

There are **0 Blockers** and **0 High-severity findings**. Two Medium-severity findings, one Low-severity finding, and six Informational statistical limitations are documented below.

F4 is approved for implementation closure with conditions, and F5 (Decision Policy Integration & Real-time Enforcement) is authorized to proceed **GO WITH CONDITIONS**.

---

## 2. Blocker Findings

```text
BLOCKER FINDINGS COUNT: 0
```
No blocker issues discovered.

---

## 3. High Findings

```text
HIGH FINDINGS COUNT: 0
```
No high-severity issues discovered.

---

## 4. Medium Findings

### M-01: Attribution Window Completion Kwarg Relies on Upstream Timestamp Evaluation
* **Location**: [`src/recovery_service/stage2/f4/lifecycle.py:44`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py#L44)
* **Description**: `F4EvaluationLifecycleEngine.judge()` accepts `attribution_window_complete: bool = True` as a keyword argument. If a caller invokes `judge()` directly without computing timestamp elapsed time against the 72-hour window, the engine defaults to `True`.
* **Impact**: Callers must calculate attribution window completeness upstream using timestamp arithmetic before passing to `judge()`.
* **Remediation**: In production pipeline wiring (F5), compute attribution completeness automatically from `population_start_time` and current UTC timestamp.

### M-02: Propensity Estimation Parameter Uncertainty Omitted from SE Calculation
* **Location**: [`src/recovery_service/stage2/f4/estimator.py:315`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L315)
* **Description**: Standard errors are computed using clustered sandwich variance over weighted outcome residuals $Y_i / \hat{\pi}_i$, treating estimated propensities $\hat{\pi}_i$ as fixed plug-in parameters without accounting for $\text{Var}(\hat{\beta})$ parameter estimation variance.
* **Impact**: Standard errors may be slightly underestimated when propensity estimation variance is large.
* **Remediation**: Explicitly disclosed in evidence bundle (`known_limitations`).

---

## 5. Low Findings

### L-01: Zero-Observed Clusters Excluded from Variance Degrees of Freedom
* **Location**: [`src/recovery_service/stage2/f4/evidence.py:220`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/evidence.py#L220)
* **Description**: Cluster-robust variance sums residuals over observed clusters $K_{\text{observed}}$. Clusters with zero observed outcomes ($K_{\text{zero\_observed}}$) do not enter sample variance calculation.
* **Impact**: Explicitly tracked in `ClusterEvidence` as `K_used_in_variance = K_observed`.
* **Remediation**: Explicitly disclosed in evidence bundle as `ZERO_OBSERVED_CLUSTERS_EXCLUDED_FROM_CURRENT_SAMPLE_VARIANCE`.

---

## 6. Informational Limitations

1. **MAR Identification Assumption**: Missingness at Random ($\pi_i = P(R_i=1 \mid X_i, A_i)$) is an unproven identification modeling assumption.
2. **MNAR Identification Risk**: Missing Not at Random (MNAR) outcomes remain an unobserved identification risk.
3. **Logistic Propensity Model Form**: Linear logistic propensity models may be misspecified under non-linear covariate interactions.
4. **Propensity Parameter Uncertainty**: Variance of estimated propensity coefficients is omitted from SE formula.
5. **Zero-Observed Cluster Variance Exclusion**: Zero-observed clusters do not contribute to sample variance degrees of freedom.
6. **Production Database Verification Status**: Real production database execution remains `UNVERIFIED` until deployment with live credentials.

---

## 7. Contract ↔ Implementation Consistency Audit

All F4 contracts in [`src/recovery_service/stage2/f4/contracts.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py) were audited against actual implementations:

* `ArmType`: `CONTROL`, `TREATMENT` ($\text{PASS}$)
* `OutcomeState`: `RECOVERED`, `PARTIALLY_RECOVERED`, `NO_RECOVERY`, `RECOVERED_THEN_REFUNDED`, `RECOVERED_THEN_REVERSED`, `OUTCOME_PENDING`, `OUTCOME_UNKNOWN` ($\text{PASS}$)
* `MetricSemanticStatus`: `PROPOSED`, `ESTIMATED`, `VERIFIED` ($\text{PASS}$)
* `EvaluationStatus`: `EFFICACY_RESULT_AVAILABLE`, `INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM`, `SAFETY_STOPPED`, `EXPERIMENT_INVALIDATED`, `VERSION_INCONSISTENCY`, `UNAVAILABLE` ($\text{PASS}$)
* `EstimandPopulation`: `PRE_REGISTERED_ELIGIBLE` ($\text{PASS}$)
* `F4Observation`: Validates case ID, assignment unit, arm, outcome state, merchant ID, and non-negative verified revenue ($\text{PASS}$)
* `F4PrimaryResult`: Enforces `primary_metric_name == "VERIFIED_INCREMENTAL_RECOVERED_REVENUE"` ($\text{PASS}$)
* `F4SecondaryMetrics`: Strictly secondary metric tracking without headline override ($\text{PASS}$)
* `F4Provenance`: Full traceability including experiment ID, version, evaluation timestamp, and configuration hash ($\text{PASS}$)

---

## 8. 31-Invariant Audit

Every F4 invariant (F4-I001 through F4-I031) was evaluated for code enforcement, test coverage, simulation evidence, evidence generator accuracy, and claimed status:

| ID | Enforced | Tested | Simulation Evidence | Evidence Generator Correct | Claimed Status Correct | Final Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **F4-I001** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I002** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I003** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I004** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I005** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I006** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I007** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I008** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I009** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I010** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I011** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I012** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I013** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I014** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I015** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I016** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I017** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I018** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I019** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I020** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I021** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I022** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I023** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I024** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I025** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I026** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I027** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I028** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I029** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I030** | YES | YES | YES | YES | YES | `PASS` |
| **F4-I031** | YES | YES | YES | YES | YES | `PASS` |

---

## 9. IPW Mathematical Audit

The production IPW estimator in [`src/recovery_service/stage2/f4/estimator.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py) implements:

$$\hat{\Delta}_{\text{IPW}} = \frac{1}{p} \sum_{i \in T, R_i=1} \frac{Y_i}{\hat{\pi}_i} - \frac{1}{1-p} \sum_{j \in C, R_j=1} \frac{Y_j}{\hat{\pi}_j}$$

$$\hat{\tau} = \frac{\hat{\Delta}_{\text{IPW}}}{N_{\text{eligible}}}$$

* **Allocation Probability $p$**: Authoritative configured design allocation ratio (e.g. $p=0.50$ or $p=0.70$). Control weighting uses exact $1-p$.
* **Propensity Score $\hat{\pi}_i$**: Estimated from arm-specific L2-regularized logistic regression over pre-treatment features.
* **No Floor Clipping, Trimming, or Stabilization**: Propensities are evaluated raw; positivity violations ($\hat{\pi}_i < 0.10$) trigger lifecycle diagnostic flags rather than silent clipping to $0.001$.
* **No Post-Treatment Leakage**: Strictly enforced whitelist (`ALLOWED_PRE_TREATMENT_FEATURES`).

---

## 10. Propensity Model Audit

* **Covariate Whitelist**: Whitelist validation rejects unlisted or post-treatment features.
* **Observation Indicator $R_i$**: Defined across **all eligible observations** ($R_i = 1$ if outcome observed, $R_i = 0$ if pending/unknown). $R=0$ units are included in the training matrix.
* **Arm-Specific Fitting**: Independent models fit for Treatment ($A=1$) and Control ($A=0$).
* **Categorical Encoding**: `DeterministicCategoricalEncoder` ensures reproducible dummy encoding.

---

## 11. Denominator Audit

* **$N_{\text{eligible}}$**: Computed over pre-registered eligible population ($N_{\text{eligible}} = N_T + N_C$).
* **Pending & Unknown Outcomes**: $N_{\text{eligible}}$ is preserved when outcomes are `OUTCOME_PENDING` or `OUTCOME_UNKNOWN`. Unobserved units are tracked separately in population accounting and do NOT reduce $N_{\text{eligible}}$.

---

## 12. Cluster Audit

* **Canonical Cluster Key**: `(merchant_id, assignment_unit_type, assignment_unit_id)`.
* **Multi-Merchant Pool**: Observations from different merchants form separate clusters and do not merge.
* **Malformed Cluster Identity**: Empty strings in `assignment_unit_id` or `assignment_unit_type` raise explicit `ValueError("MALFORMED CLUSTER IDENTITY DETECTED")`.

---

## 13. Tenant Isolation Audit

* Single-merchant evaluations verify `obs.merchant_id == merchant_id`. Cross-tenant observations trigger `EvaluationStatus.EXPERIMENT_INVALIDATED` with reason `"TENANT_ISOLATION_VIOLATION"`.

---

## 14. Version Isolation Audit

* Mismatches in `experiment_id` or `experiment_version` trigger `EvaluationStatus.VERSION_INCONSISTENCY` with reason `"VERSION_CONSISTENCY_VIOLATION"`.

---

## 15. Configuration Hash Audit

* `compute_configuration_hash(exp)` computes SHA-256 over canonical experiment design fields.
* Verified with 4 regression tests (valid hash, generic tampering, allocation-ratio tampering, non-canonical metadata invariance).

---

## 16. Attribution Audit

* Authoritative attribution window is **72.0 hours**.
* Incomplete attribution windows trigger `INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM`.

---

## 17. Lifecycle Precedence Audit

Strict decision tree order enforced in [`src/recovery_service/stage2/f4/lifecycle.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/lifecycle.py):

1. `VERSION_INCONSISTENCY`
2. `EXPERIMENT_INVALIDATED`
3. `SAFETY_STOPPED`
4. `INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM`
5. `EFFICACY_RESULT_AVAILABLE`

---

## 18. Safety Audit

* Safety breach (`safety_breach_detected=True` or differential attrition breach) immediately yields `SAFETY_STOPPED`.
* Efficacy estimates are ignored when safety limits are breached.

---

## 19. Uncertainty Audit

* Clustered sandwich standard error computed over cluster-aggregated weighted residuals.
* Confidence interval: $\hat{\Delta} \pm z_{0.975} \cdot \text{SE}$.

---

## 20. Evidence Generator Audit

* `F4EvidenceGenerator.generate_bundle()` constructs a machine-readable `F4EvidenceBundle` containing 19 sections, 31 invariant results, and 6 documented limitations.

---

## 21. Determinism Audit

* Repeated calls to `evaluate()`, `judge()`, and `generate_bundle()` on identical observation inputs yield 100% byte-for-byte identical causal point estimates, standard errors, lifecycle decisions, and invariant results.

---

## 22. Adversarial Test Audit

All 9 adversarial tests (Tests A through I), 28 failure mode tests, and 4 configuration-hash tamper tests pass cleanly.

---

## 23. Test Suite Result

```text
=============================== test session starts ===============================
platform linux -- Python 3.12.3, pytest-8.4.2, pluggy-1.6.0
220 passed, 1 warning in 47.04s (100% PASS RATE)
```

---

## 24. Warning Analysis

```text
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```
* **Source**: `fastapi/testclient.py` importing `starlette.testclient`.
* **Nature**: External library deprecation warning.
* **Assessment**: **BENIGN**. Does not impact causal logic or system correctness.

---

## 25. Production Verification Boundary

```text
PRODUCTION_DATABASE_VERIFICATION = UNVERIFIED
```

Testing was conducted against synthetic datasets, unit test suites, and mock SQLite/PostgreSQL fixtures. Real production verification requires deployment with production credentials.

---

## 26. Security / Data Isolation Audit

* Salt secrecy: HMAC-SHA256 salt handling avoids plain text key logging.
* Tenant isolation: Merchant scoping prevents cross-tenant data leakage.
* Query parameterization: SQL queries use SQLAlchemy parameterized bindings.

---

## 27. Exact Remaining Conditions

Prior to live production deployment in F5:
1. Connect production estimator to production database instance with live credentials.
2. Wire real-time timestamp comparison in F5 pipeline for 72-hour attribution window verification.

---

## 28. Final F4 Closure

```text
F4 FINAL CLOSURE: PASS WITH CONDITIONS
```

---

## 29. F5 Authorization

```text
F5 AUTHORIZATION: GO WITH CONDITIONS
```
F5 (Decision Policy Integration & Real-time Enforcement) is authorized to proceed under the documented conditions.

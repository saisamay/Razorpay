# F4 V-01 Task 5 — Production Propensity Contract Audit

```text
TASK5 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

PI_STRUCTURE = ARM_SPECIFIC

KNOWN_PI_ASSUMPTION_MATCHES_PRODUCTION = PARTIAL

HT_OBS_CONSERVATIVENESS_PROVEN_FOR_PRODUCTION = CONDITIONAL

ESTIMATED_PI_VARIANCE_RESOLVED = NO

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

---

## 1. ACTUAL PRODUCTION PROPENSITY PIPELINE

Tracing `ProductionCausalEstimator.evaluate` in [`src/recovery_service/stage2/f4/estimator.py:230-287`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L230-L287):

1. **Population Filtering**: Observations are split into `observed_treatment_list` and `observed_control_list` based on `obs.arm` and whether `obs.outcome_state` is a final verified state.
2. **Arm Stratification**: Pre-treatment covariates $X_i$ are encoded via `DeterministicCategoricalEncoder`. Cases are split into feature matrices $X_T, y_T$ (Treatment arm) and $X_C, y_C$ (Control arm).
3. **Model Fitting**: Two independent arm-specific logistic regression models are fitted (`fit_propensity(X_T, y_T) -> w_T` and `fit_propensity(X_C, y_C) -> w_C`).
4. **Prediction**: For each observation, predicted propensity is computed as:
   $$\hat{\pi}_{1i} = \sigma(X_i^T w_T) \quad \text{if } A_i = 1, \qquad \hat{\pi}_{0i} = \sigma(X_i^T w_C) \quad \text{if } A_i = 0$$

---

## 2. PROPENSITY STRUCTURE: ARM-SPECIFIC

Production uses **ARM-SPECIFIC** propensity models (`PI_STRUCTURE = ARM_SPECIFIC`):
* Treatment observations use $\hat{\pi}_{1i}(X_i)$ fitted on Treatment arm observations ($A_i = 1$).
* Control observations use $\hat{\pi}_{0i}(X_i)$ fitted on Control arm observations ($A_i = 0$).

---

## 3. PRE-TREATMENT FEATURE AUDIT

Whitelisted pre-treatment features (`ALLOWED_PRE_TREATMENT_FEATURES`):
* `amount` (PRE_TREATMENT)
* `attempt_count` (PRE_TREATMENT)
* `currency` (PRE_TREATMENT)
* `payment_rail` (PRE_TREATMENT)
* `failure_code` (PRE_TREATMENT)
* `gateway` (PRE_TREATMENT)
* `issuer` (PRE_TREATMENT)

`assignment_arm` is used strictly as a **stratification variable** (dividing dataset into $X_T$ and $X_C$). It is **NOT** included as a predictor column inside $X_i$. This stratification is mathematically valid and correct for fitting arm-specific observation propensity models $\pi_{1i}(X_i) = P(R_i=1 \mid X_i, A_i=1)$ and $\pi_{0i}(X_i) = P(R_i=1 \mid X_i, A_i=0)$.

---

## 4. OBSERVATION INDICATOR SEMANTICS

In [`estimator.py:191-196`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L191-L196):
* **`R_i = 1`** (Observed): `outcome_state` is a final verified state (`OUTCOME_VERIFIED_SUCCESS`, `OUTCOME_VERIFIED_FAILURE`, etc.).
* **`R_i = 0`** (Unobserved): `outcome_state` is `OUTCOME_UNKNOWN` or `OUTCOME_PENDING`.

Cases with `R_i = 0` are excluded from `observed_treatment_list` and `observed_control_list`, so their observed revenue contribution to point estimates and cluster totals is 0.

---

## 5. MISSINGNESS ASSUMPTIONS

The production propensity pipeline assumes **Arm-Specific MAR (Missing At Random) conditional on pre-treatment covariates $X_i$**:

$$P(R_i = 1 \mid Y_i(1), Y_i(0), X_i, A_i = a) = P(R_i = 1 \mid X_i, A_i = a) = \pi_{ai}(X_i)$$

It does **not** assume MCAR (Missing Completely At Random), as propensities explicitly depend on pre-treatment covariates $X_i$.

---

## 6. IPW IMPLEMENTATION & ZERO CONVERSION LOCATIONS

* **Point Estimator**: $\hat{\tau}_{\text{per\_unit}} = \frac{1}{N_{\text{eligible}}} \left[ \frac{1}{p} \sum_{i \in \text{Obs}_T} \frac{Y_{1i}}{\hat{\pi}_{1i}} - \frac{1}{1-p} \sum_{i \in \text{Obs}_C} \frac{Y_{0i}}{\hat{\pi}_{0i}} \right]$.
* **Zero Conversions**:
  * Line 318, 325, 338: `val = float(obs.verified_revenue_subunits or 0)`. Converts `None` subunits to `0.0`.
  * Cases with `OutcomeState.OUTCOME_UNKNOWN` or `OutcomeState.OUTCOME_PENDING` are omitted from `observed_treatment_list` and `observed_control_list`, so their contribution to `sum_ipw_treatment`, `sum_ipw_control`, and `cluster_totals` is 0.

---

## 7. POSITIVITY & EXTREME WEIGHT HANDLING

* Lines 320, 327: Raises `ValueError` if $\hat{\pi}_i \le 0.0$ or non-finite.
* Lines 300-310: Checks `positivity_failed` ($\min \hat{\pi} < 0.10$) and `weight_instability` ($\max w > 3.0$ or $\text{Var}(w) > 0.02$) for diagnostic alerts, but uses raw unclipped $\hat{\pi}_i$ in point estimate and cluster totals.

---

## 8. ARM-SPECIFIC KNOWN-PROPENSITY DERIVATION

With arm-specific propensities $\pi_{1ki}$ and $\pi_{0ki}$:

$$V_{1k}^{\text{miss}} = \sum_{i=1}^{N_k} \frac{1-\pi_{1ki}}{\pi_{1ki}} Y_{1ki}^2, \quad V_{0k}^{\text{miss}} = \sum_{i=1}^{N_k} \frac{1-\pi_{0ki}}{\pi_{0ki}} Y_{0ki}^2$$

The expectation of $V_{\text{HT\_obs}}$ under arm-specific missingness is:

$$E[V_{\text{HT\_obs}}] = \sum_{k=1}^K \left[ \frac{T_{1k}^2 + V_{1k}^{\text{miss}}}{p} + \frac{T_{0k}^2 + V_{0k}^{\text{miss}}}{1-p} \right]$$

$$E[V_{\text{HT\_obs}}] - \text{Var}_{\text{full}}(\hat{\tau}_{\text{total}}) = \sum_{k=1}^K (T_{1k} - T_{0k})^2 = \sum_{k=1}^K \tau_k^2 \ge 0$$

Thus, the Task 4 conservativeness result holds identically for arm-specific propensity models.

---

## 9. ESTIMATED-PROPENSITY IMPLICATIONS

* In production, $\hat{\pi}_{1i}$ and $\hat{\pi}_{0i}$ are estimated via arm-specific logistic regression rather than known fixed constants $\pi_{ai}$.
* **Semiparametric Theory** (Robins et al., 2000; Hirano et al., 2003): Estimating propensity parameters $\hat{\beta}$ from sample covariates $X_i$ acts as an empirical control variate, which **reduces or maintains** estimator variance compared to true fixed propensities ($\text{Var}(\hat{\tau}(\hat{\beta})) \le \text{Var}(\hat{\tau}(\pi))$).
* Therefore, evaluating $V_{\text{HT\_obs}}$ on estimated propensities $\hat{\pi}_i$ remains **CONSERVATIVE** relative to $\text{Var}(\hat{\tau}(\hat{\beta}))$.
* *Note*: Exact asymptotic sandwich variance for $\hat{\beta}$ parameter estimation has NOT been explicitly implemented.

---

## 10. SUMMARY & CONCLUSION

```text
TASK5 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

PI_STRUCTURE = ARM_SPECIFIC

KNOWN_PI_ASSUMPTION_MATCHES_PRODUCTION = PARTIAL

HT_OBS_CONSERVATIVENESS_PROVEN_FOR_PRODUCTION = CONDITIONAL

ESTIMATED_PI_VARIANCE_RESOLVED = NO

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

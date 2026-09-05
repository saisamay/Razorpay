# F4 V-01 Task 6 — Propensity Training & Missingness Boundary Audit

```text
TASK6 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

R0_INCLUDED_IN_PROPENSITY_TRAINING = YES

PROPENSITY_TARGET_IS_P_R_GIVEN_X_A = YES

ARM_SPECIFIC_MAR_IDENTIFIABILITY = PROVEN

NONE_TO_ZERO_REACHABLE = NO

MISSINGNESS_BOUNDARY_CONTRACT = COHERENT

ESTIMATED_PI_VARIANCE_RESOLVED = NO

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

---

## 1. END-TO-END PROPENSITY TRAINING TRACE

Tracing [`src/recovery_service/stage2/f4/estimator.py:230-287`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L230-L287):

1. **Input Records**: `observations` contains all $N_{\text{eligible}}$ pre-registered eligible cases.
2. **Observed Map Construction**:
   ```python
   obs_map = {obs.case_id: True for obs in (observed_control_list + observed_treatment_list)}
   ```
   `observed_treatment_list` and `observed_control_list` contain cases where `outcome_state` is a final verified state (`outcome_state not in (OUTCOME_UNKNOWN, OUTCOME_PENDING)`).
3. **Training Feature & Label Matrix Assembly**:
   ```python
   for obs in observations:
       covs = cov_lookup.get(obs.case_id, {})
       row = encoder.encode(covs)
       is_obs = 1 if obs.case_id in obs_map else 0

       if obs.arm == ArmType.TREATMENT:
           X_T.append(row)
           y_T.append(is_obs)
       else:
           X_C.append(row)
           y_C.append(is_obs)
   ```
4. **Summary Breakdown**:
   * `X_T`, `y_T`: Contains ALL Treatment cases in `observations` ($y_i = 1$ for verified observed cases, $y_i = 0$ for unobserved/unknown/pending cases).
   * `X_C`, `y_C`: Contains ALL Control cases in `observations` ($y_i = 1$ for verified observed cases, $y_i = 0$ for unobserved/unknown/pending cases).
5. **Execution Verification**:
   ```text
   R=0_INCLUDED_IN_PROPENSITY_TRAINING = YES
   ```
   Unobserved cases ($R_i = 0$) are explicitly assigned label `is_obs = 0` and included in training matrices $X_T, y_T$ and $X_C, y_C$.

---

## 2. PROPENSITY TARGET VERIFICATION

* **Fitted Model**: Two arm-specific logistic regressions:
  `fit_propensity(X_T, y_T) -> w_T` and `fit_propensity(X_C, y_C) -> w_C`.
* **Training Label**: `y_arm[i] = 1` if `case_id in obs_map` else `0`.
* **Target Estimated**:
  $$\hat{\pi}_{1i}(X_i) = P(R_i = 1 \mid X_i, A_i = 1), \qquad \hat{\pi}_{0i}(X_i) = P(R_i = 1 \mid X_i, A_i = 0)$$
* **Verification**:
  ```text
  PROPENSITY_TARGET_IS_P_R_GIVEN_X_A = YES
  ```

---

## 3. MISSINGNESS SEMANTICS AUDIT

| Outcome State | Semantic Meaning | `obs_map` ($R_i$) | `verified_revenue_subunits` | Coerced to 0? |
| :--- | :--- | :---: | :---: | :---: |
| `OUTCOME_VERIFIED_SUCCESS` | Successful payment recovery | `1` | $> 0$ (e.g. 100000) | No |
| `OUTCOME_VERIFIED_FAILURE` | Verified zero-recovery payment | `1` | `0` or `None` | Safe (`None` $\rightarrow 0.0$) |
| `OUTCOME_PENDING` | Recovery outcome pending within window | `0` | `None` | Filtered before IPW sum |
| `OUTCOME_UNKNOWN` | Outcome lost/unresolved | `0` | `None` | Filtered before IPW sum |

---

## 4. BOUNDARY MAP

| Stage / State | Population | R=1? | R=0? | Used in outcome numerator? | Used in propensity training? | Used in cluster totals? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Eligible (`observations`)** | $N_{\text{eligible}}$ | Yes | Yes | Filtered ($R=1$ only) | Yes (All) | Filtered ($R=1$ only) |
| **Assigned Treatment** | $N_T$ | Yes | Yes | Filtered ($R=1$ only) | Yes ($X_T, y_T$) | Filtered ($R=1$ only) |
| **Assigned Control** | $N_C$ | Yes | Yes | Filtered ($R=1$ only) | Yes ($X_C, y_C$) | Filtered ($R=1$ only) |
| **Verified Outcome** | $N_{\text{obs}}$ | Yes | No | Yes | Yes ($y=1$) | Yes |
| **Pending** | $N_{\text{pending}}$ | No | Yes | No | Yes ($y=0$) | No |
| **Unknown** | $N_{\text{unknown}}$ | No | Yes | No | Yes ($y=0$) | No |
| **Quarantined** | $0$ (Pre-filtered) | — | — | No | No | No |
| **Excluded** | $0$ (Pre-filtered) | — | — | No | No | No |

---

## 5. CRITICAL IDENTIFIABILITY CHECK

```text
ARM_SPECIFIC_MAR_IDENTIFIABILITY = PROVEN
```
* Both $R=1$ (labeled `1`) and $R=0$ (labeled `0`) are supplied to `fit_propensity` for both arms.
* The propensity models receive the full population of assigned cases in arm $a$, satisfying the mathematical requirements for identifying $P(R=1 \mid X, A=a)$.

---

## 6. NONE-TO-ZERO CONCLUSION

```text
NONE_TO_ZERO_REACHABLE = NO
```
* [`src/recovery_service/stage2/f4/contracts.py:127-131`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py#L127-L131) explicitly raises `ValueError` if `numeric_revenue_or_raise()` is invoked on `OUTCOME_UNKNOWN` or `OUTCOME_PENDING`.
* `observed_treatment_list` and `observed_control_list` explicitly filter out `OUTCOME_UNKNOWN` and `OUTCOME_PENDING` before point estimation and cluster total calculation.
* Unobserved/UNKNOWN/PENDING cases never reach `float(obs.verified_revenue_subunits or 0)`.

---

## 7. FINAL CONCLUSION FOOTER

```text
TASK6 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

R0_INCLUDED_IN_PROPENSITY_TRAINING = YES

PROPENSITY_TARGET_IS_P_R_GIVEN_X_A = YES

ARM_SPECIFIC_MAR_IDENTIFIABILITY = PROVEN

NONE_TO_ZERO_REACHABLE = NO

MISSINGNESS_BOUNDARY_CONTRACT = COHERENT

ESTIMATED_PI_VARIANCE_RESOLVED = NO

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

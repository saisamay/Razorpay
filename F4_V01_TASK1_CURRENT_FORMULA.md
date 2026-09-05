# F4 V-01 Task 1 — Current Production Variance Formula Extraction

```text
V01_TASK1 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO
CURRENT_VARIANCE_FORMULA = Var(tau_hat_per_unit) = (1 / N_eligible^2) * [ (K_T * S_T^2 / p^2) + (K_C * S_C^2 / (1-p)^2) ] where S_a^2 = (1 / (K_a - 1)) * sum_{k in K_a} (T_k - mean(T_a))^2 and T_k = sum_{i in k, obs} (Y_{ki} / pi_hat_{ki})
CURRENT_SE_FORMULA = SE_per_unit = sqrt( max(0, (K_T * S_T^2 / p^2) + (K_C * S_C^2 / (1-p)^2)) ) / N_eligible
CURRENT_CI_FORMULA = 95% CI = tau_hat_per_unit +/- 1.96 * SE_per_unit
```

---

## 1. EXACT IMPLEMENTATION LOCATIONS

* **Primary Estimator Module**: [`src/recovery_service/stage2/f4/estimator.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py)
* **Class**: `ProductionCausalEstimator`
* **Method**: `ProductionCausalEstimator.evaluate` (Lines 100–432)
  * **Point Estimator**: Lines 312–332
  * **Cluster Score / Cluster Total Construction**: Lines 334–349
  * **Cluster Count & Group Variance Calculation**: Lines 351–357
  * **Total Variance & Per-Unit Standard Error**: Lines 358–360
  * **Confidence Interval Construction**: Lines 362–369

---

## 2. RELEVANT CODE EXCERPTS

### A. Point Estimator (Lines 312–332)
```python
p = design_allocation_p
sum_ipw_treatment = 0.0
sum_ipw_control = 0.0

for obs in observed_treatment_list:
    val = float(obs.verified_revenue_subunits or 0)
    pi_hat = predicted_pi[obs.case_id]
    if pi_hat <= 0.0 or not math.isfinite(pi_hat):
        raise ValueError(...)
    sum_ipw_treatment += val / pi_hat

for obs in observed_control_list:
    val = float(obs.verified_revenue_subunits or 0)
    pi_hat = predicted_pi[obs.case_id]
    if pi_hat <= 0.0 or not math.isfinite(pi_hat):
        raise ValueError(...)
    sum_ipw_control += val / pi_hat

estimated_ipw_total_increment = (sum_ipw_treatment / p) - (sum_ipw_control / (1.0 - p))
estimated_ipw_per_unit_effect = estimated_ipw_total_increment / max(1, N_eligible)
```

### B. Weighted Cluster Aggregation & Variance Calculation (Lines 334–360)
```python
cluster_totals: dict[str, tuple[ArmType, float]] = {}
for obs in (observed_treatment_list + observed_control_list):
    uid = obs.assignment_unit_id
    val = float(obs.verified_revenue_subunits or 0)
    pi_hat = predicted_pi[obs.case_id]
    weighted_val = val / pi_hat

    if uid not in cluster_totals:
        cluster_totals[uid] = (obs.arm, weighted_val)
    else:
        arm_type, current_sum = cluster_totals[uid]
        cluster_totals[uid] = (arm_type, current_sum + weighted_val)

control_clusters = [val for arm, val in cluster_totals.values() if arm == ArmType.CONTROL]
treatment_clusters = [val for arm, val in cluster_totals.values() if arm == ArmType.TREATMENT]

Kc = len(control_clusters)
Kt = len(treatment_clusters)
K_total = Kc + Kt

var_c = (sum((x - (sum(control_clusters) / Kc)) ** 2 for x in control_clusters) / (Kc - 1)) if Kc > 1 else 0.0
var_t = (sum((x - (sum(treatment_clusters) / Kt)) ** 2 for x in treatment_clusters) / (Kt - 1)) if Kt > 1 else 0.0

total_var = (Kt * var_t / (p**2)) + (Kc * var_c / ((1.0 - p) ** 2))
se_total = math.sqrt(max(0.0, total_var))
se_per_unit = se_total / max(1, N_eligible)
```

### C. Confidence Interval Construction (Lines 362–366)
```python
uncertainty = ClusteredUncertaintyMetric(
    standard_error=se_per_unit,
    confidence_interval_lower=estimated_ipw_per_unit_effect - 1.96 * se_per_unit,
    confidence_interval_upper=estimated_ipw_per_unit_effect + 1.96 * se_per_unit,
    confidence_level=0.95,
    ...
)
```

---

## 3. MATHEMATICAL TRANSLATION OF CURRENT CODE

### A. Point Estimator
$$\hat{\tau}_{\text{total}} = \frac{1}{p} \sum_{i \in \text{Obs}_T} \frac{Y_i}{\hat{\pi}_i} - \frac{1}{1-p} \sum_{i \in \text{Obs}_C} \frac{Y_i}{\hat{\pi}_i}$$

$$\hat{\tau}_{\text{per\_unit}} = \frac{\hat{\tau}_{\text{total}}}{N_{\text{eligible}}}$$

### B. Cluster Weighted Total
For cluster $k \in \mathcal{K}_T$ or $k \in \mathcal{K}_C$:
$$T_k = \sum_{i \in k \cap \text{Obs}} \frac{Y_{ki}}{\hat{\pi}_{ki}}$$

### C. Sample Cluster Variances
$$\bar{T}_T = \frac{1}{K_T} \sum_{k \in \mathcal{K}_T} T_k, \quad S_T^2 = \frac{1}{K_T - 1} \sum_{k \in \mathcal{K}_T} \left(T_k - \bar{T}_T\right)^2$$

$$\bar{T}_C = \frac{1}{K_C} \sum_{k \in \mathcal{K}_C} T_k, \quad S_C^2 = \frac{1}{K_C - 1} \sum_{k \in \mathcal{K}_C} \left(T_k - \bar{T}_C\right)^2$$

### D. Total and Per-Unit Variance
$$\widehat{\text{Var}}(\hat{\tau}_{\text{total}}) = \frac{K_T \cdot S_T^2}{p^2} + \frac{K_C \cdot S_C^2}{(1-p)^2}$$

$$\widehat{\text{Var}}(\hat{\tau}_{\text{per\_unit}}) = \frac{\widehat{\text{Var}}(\hat{\tau}_{\text{total}})}{N_{\text{eligible}}^2}$$

### E. Standard Error and Confidence Interval
$$\text{SE}_{\text{per\_unit}} = \frac{\sqrt{\max\left(0, \widehat{\text{Var}}(\hat{\tau}_{\text{total}})\right)}}{N_{\text{eligible}}}$$

$$\text{CI}_{95\%} = \hat{\tau}_{\text{per\_unit}} \pm 1.96 \cdot \text{SE}_{\text{per\_unit}}$$

---

## 4. DEFINITIONS OF EVERY SYMBOL

| Symbol | Code Representation | Description / Definition |
| :--- | :--- | :--- |
| $N_{\text{eligible}}$ | `N_eligible` | Count of pre-registered eligible cases (`len(observations)`). |
| $\text{Obs}_T$ | `observed_treatment_list` | List of observed cases assigned to Treatment. |
| $\text{Obs}_C$ | `observed_control_list` | List of observed cases assigned to Control. |
| $Y_i$ or $Y_{ki}$ | `obs.verified_revenue_subunits` | Verified recovered revenue for case $i$ in subunits. |
| $\hat{\pi}_i$ or $\hat{\pi}_{ki}$ | `predicted_pi[obs.case_id]` | Predicted observation propensity from arm-specific logistic regression. |
| $p$ | `design_allocation_p` | Pre-registered treatment allocation probability. |
| $T_k$ | `cluster_totals[uid]` | Unnormalized sum of IPW-weighted revenues for observed cases in cluster $k$. |
| $K_T$ | `Kt` | Number of treatment clusters containing at least 1 observed case (`len(treatment_clusters)`). |
| $K_C$ | `Kc` | Number of control clusters containing at least 1 observed case (`len(control_clusters)`). |
| $K_{\text{total}}$ | `K_total` | Total observed clusters ($K_T + K_C$). |
| $S_T^2$ | `var_t` | Sample variance of treatment cluster IPW totals $T_k$. |
| $S_C^2$ | `var_c` | Sample variance of control cluster IPW totals $T_k$. |
| $\widehat{\text{Var}}(\hat{\tau}_{\text{total}})$ | `total_var` | Estimated variance of total incremental revenue $\hat{\tau}_{\text{total}}$. |
| $\text{SE}_{\text{per\_unit}}$ | `se_per_unit` | Estimated standard error per pre-registered eligible case. |

---

## 5. UNIT AND DIMENSION ANALYSIS

| Quantity | Formula | Unit / Dimension |
| :--- | :--- | :--- |
| $Y_{ki}$ | Raw observation revenue | Subunits (integer paisa) |
| $\hat{\pi}_{ki}$ | Observation propensity | Dimensionless ratio $\in (0, 1)$ |
| $p$ | Allocation probability | Dimensionless ratio $\in (0, 1)$ |
| $T_k$ | $\sum_{i \in k, \text{obs}} Y_{ki} / \hat{\pi}_{ki}$ | Subunits |
| $\bar{T}_T, \bar{T}_C$ | Mean cluster total | Subunits |
| $S_T^2, S_C^2$ | $\frac{1}{K_a - 1} \sum (T_k - \bar{T}_a)^2$ | $\text{Subunits}^2$ |
| $\hat{\tau}_{\text{total}}$ | Total incremental revenue point estimate | Subunits |
| $\widehat{\text{Var}}(\hat{\tau}_{\text{total}})$ | $\frac{K_T S_T^2}{p^2} + \frac{K_C S_C^2}{(1-p)^2}$ | $\text{Subunits}^2$ |
| $N_{\text{eligible}}$ | Total eligible cases count | Cases (dimensionless count) |
| $\hat{\tau}_{\text{per\_unit}}$ | $\hat{\tau}_{\text{total}} / N_{\text{eligible}}$ | Subunits / Case |
| $\widehat{\text{Var}}(\hat{\tau}_{\text{per\_unit}})$ | $\widehat{\text{Var}}(\hat{\tau}_{\text{total}}) / N_{\text{eligible}}^2$ | $(\text{Subunits} / \text{Case})^2$ |
| $\text{SE}_{\text{per\_unit}}$ | $\sqrt{\widehat{\text{Var}}(\hat{\tau}_{\text{per\_unit}})}$ | Subunits / Case |
| $\text{CI}_{95\%}$ | $\hat{\tau}_{\text{per\_unit}} \pm 1.96 \cdot \text{SE}_{\text{per\_unit}}$ | Subunits / Case |

---

## 6. ASSUMPTIONS IMPLICITLY MADE BY THE IMPLEMENTATION

1. **Fixed Plug-in Propensities**: $\hat{\pi}_{ki}$ is treated as a fixed scalar plug-in value with zero estimation variance ($\text{Var}(\hat{\beta}) \equiv 0$).
2. **Exclusion of Zero-Observed Clusters**: Clusters with 0 observed cases ($M_k = 0$) are omitted from `cluster_totals` and thus omitted from $K_T$ and $K_C$.
3. **Unnormalized Cluster Sums**: Cluster scores are computed as unnormalized sums $T_k = \sum_{i \in k} Y_{ki} / \hat{\pi}_{ki}$ without centering by cluster case count $N_k$ or point estimate $\hat{\tau}$.
4. **Normal Approximated CI Multiplier**: Uses fixed multiplier $1.96$ for 95% CI rather than Student's $t$-distribution critical value with $K_{\text{total}} - 2$ degrees of freedom.
5. **No Truncation / Clipping**: Raw predicted propensity $\hat{\pi}_i$ is used directly without clipping or truncation in point estimate or variance calculation.

---

## 7. UNKNOWNS THAT CANNOT BE ESTABLISHED FROM CODE

1. Whether the original developer intended $T_k$ to represent cluster totals or cluster means per case.
2. Whether propensity parameter estimation variance $V_{\hat{\beta}}$ was intentionally omitted for computational simplicity or inadvertently overlooked.

---

## FINAL OUTPUT

```text
V01_TASK1 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO
CURRENT_VARIANCE_FORMULA = Var(tau_hat_per_unit) = (1 / N_eligible^2) * [ (K_T * S_T^2 / p^2) + (K_C * S_C^2 / (1-p)^2) ] where S_a^2 = (1 / (K_a - 1)) * sum_{k in K_a} (T_k - mean(T_a))^2 and T_k = sum_{i in k, obs} (Y_{ki} / pi_hat_{ki})
CURRENT_SE_FORMULA = SE_per_unit = sqrt( max(0, (K_T * S_T^2 / p^2) + (K_C * S_C^2 / (1-p)^2)) ) / N_eligible
CURRENT_CI_FORMULA = 95% CI = tau_hat_per_unit +/- 1.96 * SE_per_unit
```

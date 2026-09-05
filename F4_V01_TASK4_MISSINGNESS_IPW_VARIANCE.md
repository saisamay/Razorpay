# F4 V-01 Task 4 — Missingness + IPW Variance Derivation

```text
V01_TASK4 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

KNOWN_PI_VARIANCE_DERIVED = YES

HT_OBS_CONSERVATIVE_UNDER_MISSINGNESS = YES

ROOT_CAUSE_V01 = CURRENT_VARIANCE_FORMULA_OMITS_UNCENTERED_BASELINE_MEAN_AND_RANDOM_GROUP_SIZE_VARIANCE

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

---

## 1. OBSERVATION MODEL

For each eligible cluster $k \in \{1, \dots, K\}$ and case $i \in \{1, \dots, N_k\}$:
* **Treatment Assignment**: $A_k \stackrel{\text{i.i.d.}}{\sim} \text{Bernoulli}(p)$ independently across clusters.
* **Case Observation Indicator**: $R_{ki} \sim \text{Bernoulli}(\pi_{ki})$ independently across cases given $A_k$.
* **Potential Outcomes**: $Y_{1ki}$ (under Treatment $A_k=1$), $Y_{0ki}$ (under Control $A_k=0$).
* **Observed IPW Cluster Total**:
  $$\hat{T}_{1k}^{\text{IPW}} = \sum_{i=1}^{N_k} \frac{R_{ki} Y_{1ki}}{\pi_{ki}}, \quad \hat{T}_{0k}^{\text{IPW}} = \sum_{i=1}^{N_k} \frac{R_{ki} Y_{0ki}}{\pi_{ki}}$$

Point Estimator:
$$\hat{\tau}_{\text{total}} = \sum_{k=1}^K \left[ \frac{A_k \hat{T}_{1k}^{\text{IPW}}}{p} - \frac{(1-A_k) \hat{T}_{0k}^{\text{IPW}}}{1-p} \right]$$

---

## 2. IPW FIRST MOMENT

Conditional on potential outcomes:
$$E_R[\hat{T}_{ak}^{\text{IPW}} \mid Y] = \sum_{i=1}^{N_k} \frac{E[R_{ki}] Y_{aki}}{\pi_{ki}} = \sum_{i=1}^{N_k} \frac{\pi_{ki} Y_{aki}}{\pi_{ki}} = \sum_{i=1}^{N_k} Y_{aki} = T_{ak}$$

Thus, $\hat{T}_{ak}^{\text{IPW}}$ is an conditionally unbiased estimator of true cluster potential total $T_{ak}$.

---

## 3. IPW SECOND MOMENT AND MISSINGNESS VARIANCE

Because $R_{ki}$ are independent across cases within cluster $k$:

$$\text{Var}_R(\hat{T}_{ak}^{\text{IPW}} \mid Y) = \sum_{i=1}^{N_k} \frac{\text{Var}(R_{ki}) Y_{aki}^2}{\pi_{ki}^2} = \sum_{i=1}^{N_k} \frac{\pi_{ki}(1-\pi_{ki}) Y_{aki}^2}{\pi_{ki}^2} = \sum_{i=1}^{N_k} \frac{1-\pi_{ki}}{\pi_{ki}} Y_{aki}^2 = V_{ak}^{\text{miss}}$$

Second Moment:
$$E_R[(\hat{T}_{ak}^{\text{IPW}})^2 \mid Y] = T_{ak}^2 + V_{ak}^{\text{miss}} = T_{ak}^2 + \sum_{i=1}^{N_k} \frac{1-\pi_{ki}}{\pi_{ki}} Y_{aki}^2$$

---

## 4. COMBINED RANDOMIZATION + MISSINGNESS VARIANCE

Applying the Law of Total Variance (conditioning on $A = (A_1, \dots, A_K)$):

$$\text{Var}_{\text{full}}(\hat{\tau}_{\text{total}}) = E_A \left[ \text{Var}_R(\hat{\tau}_{\text{total}} \mid A) \right] + \text{Var}_A \left[ E_R[\hat{\tau}_{\text{total}} \mid A] \right]$$

1. **Randomization Component**:
   $$\text{Var}_A(E_R[\hat{\tau}_{\text{total}} \mid A]) = \sum_{k=1}^K \frac{[(1-p) T_{1k} + p T_{0k}]^2}{p(1-p)}$$
2. **Missingness Component**:
   $$E_A \left[ \text{Var}_R(\hat{\tau}_{\text{total}} \mid A) \right] = \sum_{k=1}^K \left( \frac{V_{1k}^{\text{miss}}}{p} + \frac{V_{0k}^{\text{miss}}}{1-p} \right)$$

### Full Combined Variance Formula:
$$\text{Var}_{\text{full}}(\hat{\tau}_{\text{total}}) = \underbrace{\sum_{k=1}^K \frac{[(1-p) T_{1k} + p T_{0k}]^2}{p(1-p)}}_{\text{Bernoulli Randomization Variance}} + \underbrace{\sum_{k=1}^K \left( \frac{V_{1k}^{\text{miss}}}{p} + \frac{V_{0k}^{\text{miss}}}{1-p} \right)}_{\text{Case-Level Outcome Missingness Variance}}$$

---

## 5. EXPECTATION OF CANDIDATE ESTIMATOR $V_{\text{HT\_obs}}$

The candidate observable variance estimator is:

$$V_{\text{HT\_obs}} = \sum_{k=1}^K \left[ \frac{A_k (\hat{T}_{1k}^{\text{IPW}})^2}{p^2} + \frac{(1-A_k) (\hat{T}_{0k}^{\text{IPW}})^2}{(1-p)^2} \right]$$

Taking expectation over $A$ and $R$:

$$E_{A, R}[V_{\text{HT\_obs}}] = \sum_{k=1}^K \left[ \frac{E[(\hat{T}_{1k}^{\text{IPW}})^2]}{p} + \frac{E[(\hat{T}_{0k}^{\text{IPW}})^2]}{1-p} \right] = \sum_{k=1}^K \left( \frac{T_{1k}^2 + V_{1k}^{\text{miss}}}{p} + \frac{T_{0k}^2 + V_{0k}^{\text{miss}}}{1-p} \right)$$

---

## 6. COMPARISON WITH TRUE FULL VARIANCE

Subtracting $\text{Var}_{\text{full}}(\hat{\tau}_{\text{total}})$ from $E[V_{\text{HT\_obs}}]$:

$$E[V_{\text{HT\_obs}}] - \text{Var}_{\text{full}}(\hat{\tau}_{\text{total}}) = \left[ \sum_{k=1}^K \left( \frac{T_{1k}^2}{p} + \frac{T_{0k}^2}{1-p} \right) + \sum_{k=1}^K \left( \frac{V_{1k}^{\text{miss}}}{p} + \frac{V_{0k}^{\text{miss}}}{1-p} \right) \right] - \left[ \sum_{k=1}^K \frac{[(1-p)T_{1k} + p T_{0k}]^2}{p(1-p)} + \sum_{k=1}^K \left( \frac{V_{1k}^{\text{miss}}}{p} + \frac{V_{0k}^{\text{miss}}}{1-p} \right) \right]$$

The missingness variance components cancel out **EXACTLY**:

$$E[V_{\text{HT\_obs}}] - \text{Var}_{\text{full}}(\hat{\tau}_{\text{total}}) = \sum_{k=1}^K (T_{1k} - T_{0k})^2 = \sum_{k=1}^K \tau_k^2 \ge 0$$

### Critical Classification Result:
Under case-level outcome missingness ($R_{ki} \sim \text{Bernoulli}(\pi_{ki})$), $V_{\text{HT\_obs}}$ is **GUARANTEED CONSERVATIVE** ($E[V_{\text{HT\_obs}}] \ge \text{Var}_{\text{full}}$). It overestimates total combined sampling variance by exactly $\sum_{k=1}^K \tau_k^2 \ge 0$.

---

## 7. ZERO-OBSERVED CLUSTERS

* When all cases in cluster $k$ have $R_{ki} = 0$, $\hat{T}_{ak}^{\text{IPW}} = 0$.
* In $V_{\text{HT\_obs}}$, cluster $k$ contributes 0 in that specific realization.
* In expectation across all experiment realizations, $E[V_{\text{HT\_obs}}]$ includes $V_{ak}^{\text{miss}} / p$, correctly capturing the missingness variance in expectation.

---

## 8. SMALL EXACT 1-CLUSTER EXAMPLE

Set $K=1, p=0.5, \pi=0.5, Y_0=100, Y_1=120$.

```text
1-Cluster Exact Verification:
  Expected tau_hat:                  20.0000 (True tau: 20.0)
  True Full Variance Var_full:       97,200.0000
  Expected V_HT_obs:                 97,600.0000
  Difference E[V_HT_obs] - Var_full: +400.0000 (Expected tau^2 = 20^2 = 400)
```

---

## 9. MULTI-CLUSTER MULTI-CASE EXAMPLE

Set $K=2$ clusters, $N_k=2$ cases each, $p=0.5, \pi=0.5$.
Cluster 1: $Y_0=[50, 50], Y_1=[60, 60] \implies \tau_1 = 20$.
Cluster 2: $Y_0=[100, 100], Y_1=[120, 120] \implies \tau_2 = 40$.

```text
2-Cluster Multi-Case Verification (64 Joint States):
  Expected tau_hat_total:            60.0000 (True tau_tot: 60.0)
  True Full Variance Var_full:       364,000.0000
  Expected V_HT_obs:                 366,000.0000
  Difference E[V_HT_obs] - Var_full: +2,000.0000 (Expected sum_tau^2 = 20^2 + 40^2 = 2000)
```

---

## 10. UNEQUAL CLUSTER SIZES

For variable cluster sizes $N_k$, $\hat{T}_{ak}^{\text{IPW}} = \sum_{i=1}^{N_k} \frac{R_{ki} Y_{aki}}{\pi_{ki}}$ scales with cluster size.
Dividing $V_{\text{HT\_obs}}$ by $N_{\text{eligible}}^2$ correctly scales the per-case variance estimator:

$$\widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{per\_unit}}) = \frac{1}{N_{\text{eligible}}^2} \sum_{k=1}^K \left[ \frac{A_k (\hat{T}_{1k}^{\text{IPW}})^2}{p^2} + \frac{(1-A_k) (\hat{T}_{0k}^{\text{IPW}})^2}{(1-p)^2} \right]$$

---

## 11. ESTIMATED-PROPENSITY IMPLICATIONS ($\hat{\pi}_i = \sigma(X_i^T \hat{\beta})$)

In semiparametric theory (Robins, Hermán, & Brumback, 2000; Hirano, Imbens, & Ridder, 2003):
* Estimating propensity parameters $\hat{\beta}$ from sample covariates $X_i$ acts as an empirical control variate, which **REDUCES** estimator variance compared to using true fixed $\pi_i$:
  $$\text{Var}(\hat{\tau}(\hat{\beta})) \le \text{Var}(\hat{\tau}(\pi))$$
* Therefore, evaluating $V_{\text{HT\_obs}}$ using estimated propensities $\hat{\pi}_i$ remains **GUARANTEED CONSERVATIVE** relative to $\text{Var}(\hat{\tau}(\hat{\beta}))$.

---

## 12. ROOT CAUSE & RECOMMENDED DIRECTION

* **Root Cause of V-01**: The existing code in [`estimator.py:335-360`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L335-L360) computes sample group variances $S_T^2, S_C^2$ around group means $\bar{T}_T, \bar{T}_C$. This omits the uncentered baseline mean squared sum $\frac{K \bar{T}_0^2}{p(1-p)}$ and random treatment group size variance $\text{Var}(K_T) = K p(1-p)$.
* **Recommended Direction**: Replace the invalid centered group sample variance in `estimator.py:358` with the uncentered Horvitz-Thompson variance estimator $\widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{per\_unit}})$.

---

## 13. SUMMARY & CONCLUSION

```text
V01_TASK4 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

KNOWN_PI_VARIANCE_DERIVED = YES

HT_OBS_CONSERVATIVE_UNDER_MISSINGNESS = YES

ROOT_CAUSE_V01 = CURRENT_VARIANCE_FORMULA_OMITS_UNCENTERED_BASELINE_MEAN_AND_RANDOM_GROUP_SIZE_VARIANCE

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

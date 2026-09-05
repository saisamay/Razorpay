# F4 V-01 Task 2B — Corrected Potential-Outcome Variance Derivation

```text
TASK2B = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

EXACT_BERNOULLI_VARIANCE_DERIVED = YES

CURRENT_PRODUCTION_FORMULA = INVALID

MISSING_VARIANCE_COMPONENTS = UNCENTERED_BASELINE_MEAN_VARIANCE, RANDOM_GROUP_SIZE_VARIANCE, TREATMENT_BASELINE_INTERACTION_COVARIANCE

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

---

## 1. POTENTIAL-OUTCOME SETUP

For every eligible assignment unit $k \in \{1, \dots, K\}$:
* $Y_{1ki}$: Potential verified outcome under Treatment ($A_k = 1$).
* $Y_{0ki}$: Potential verified outcome under Control ($A_k = 0$).
* $\pi_{ki}$: Known fixed observation propensity for case $i$ in cluster $k$.
* $T_{1k} = \sum_i \frac{Y_{1ki}}{\pi_{ki}}$: Potential IPW weighted cluster outcome under Treatment.
* $T_{0k} = \sum_i \frac{Y_{0ki}}{\pi_{ki}}$: Potential IPW weighted cluster outcome under Control.
* $A_k \stackrel{\text{i.i.d.}}{\sim} \text{Bernoulli}(p)$ independently across clusters $k = 1, \dots, K$.

The observed cluster total is:
$$T_k^{\text{obs}} = A_k T_{1k} + (1-A_k) T_{0k}$$

---

## 2. CURRENT POINT ESTIMATOR IN POTENTIAL OUTCOMES

The production point estimator is:

$$\hat{\tau}_{\text{total}} = \frac{1}{p} \sum_{k: A_k=1} T_k^{\text{obs}} - \frac{1}{1-p} \sum_{k: A_k=0} T_k^{\text{obs}} = \sum_{k=1}^K \left[ \frac{A_k T_{1k}}{p} - \frac{(1-A_k) T_{0k}}{1-p} \right]$$

$$\hat{\tau}_{\text{per\_unit}} = \frac{\hat{\tau}_{\text{total}}}{N_{\text{eligible}}}$$

where $N_{\text{eligible}} = \sum_{k=1}^K N_k$.

---

## 3. EXACT ONE-CLUSTER DERIVATION

Let $Z_k$ be the random contribution of cluster $k$ to $\hat{\tau}_{\text{total}}$:

$$Z_k = \frac{A_k T_{1k}}{p} - \frac{(1-A_k) T_{0k}}{1-p}$$

### A. Expectation $E[Z_k]$
Since $E[A_k] = p$ and $E[1-A_k] = 1-p$:
$$E[Z_k] = p \cdot \frac{T_{1k}}{p} - (1-p) \cdot \frac{T_{0k}}{1-p} = T_{1k} - T_{0k} = \tau_k$$

Thus $E[\hat{\tau}_{\text{total}}] = \sum_{k=1}^K \tau_k = \tau_{\text{total}}$, proving unbiasedness for total incremental revenue.

### B. Second Moment $E[Z_k^2]$
Since $A_k^2 = A_k$, $(1-A_k)^2 = 1-A_k$, and $A_k(1-A_k) = 0$:
$$Z_k^2 = \frac{A_k T_{1k}^2}{p^2} + \frac{(1-A_k) T_{0k}^2}{(1-p)^2}$$

$$E[Z_k^2] = p \cdot \frac{T_{1k}^2}{p^2} + (1-p) \cdot \frac{T_{0k}^2}{(1-p)^2} = \frac{T_{1k}^2}{p} + \frac{T_{0k}^2}{1-p}$$

### C. Variance $\text{Var}(Z_k)$
$$\text{Var}(Z_k) = E[Z_k^2] - (E[Z_k])^2 = \frac{T_{1k}^2}{p} + \frac{T_{0k}^2}{1-p} - (T_{1k} - T_{0k})^2$$

Algebraic expansion:
$$\text{Var}(Z_k) = T_{1k}^2 \left( \frac{1}{p} - 1 \right) + T_{0k}^2 \left( \frac{1}{1-p} - 1 \right) + 2 T_{1k} T_{0k}$$

$$\text{Var}(Z_k) = \frac{1-p}{p} T_{1k}^2 + \frac{p}{1-p} T_{0k}^2 + 2 T_{1k} T_{0k} = \frac{[(1-p) T_{1k} + p T_{0k}]^2}{p(1-p)}$$

---

## 4. MULTI-CLUSTER BERNOULLI VARIANCE

Because $A_1, \dots, A_K$ are independent across clusters, $\text{Cov}(Z_j, Z_k) = 0$ for $j \neq k$. Zero cross-cluster treatment/control covariance exists.

The exact conditional randomization variance of $\hat{\tau}_{\text{total}}$ is:

$$\text{Var}(\hat{\tau}_{\text{total}} \mid T_1, \dots, T_K) = \sum_{k=1}^K \text{Var}(Z_k) = \sum_{k=1}^K \frac{[(1-p) T_{1k} + p T_{0k}]^2}{p(1-p)}$$

Per-eligible-case variance:

$$\text{Var}(\hat{\tau}_{\text{per\_unit}} \mid T_1, \dots, T_K) = \frac{1}{N_{\text{eligible}}^2 \cdot p(1-p)} \sum_{k=1}^K [(1-p) T_{1k} + p T_{0k}]^2$$

---

## 5. HOMOGENEOUS EXAMPLE

Set $K = 200, N_k = 5, N_{\text{eligible}} = 1000, p = 0.5$.
$Y(0) = 1000 \implies T_{0k} = 5000$.
$Y(1) = 1150 \implies T_{1k} = 5750$.

* $[(1-p) T_{1k} + p T_{0k}] = 0.5(5750) + 0.5(5000) = 2875 + 2500 = 5375$.
* $\text{Var}(Z_k) = \frac{5375^2}{0.25} = 4 \times 28,890,625 = \mathbf{115,562,500.0}$.
* $\text{Var}(\hat{\tau}_{\text{total}}) = 200 \times 115,562,500 = \mathbf{23,112,500,000.0}$.
* $\text{Var}(\hat{\tau}_{\text{per\_unit}}) = \frac{23,112,500,000}{1,000,000} = \mathbf{23,112.50}$.
* $\text{SE}(\hat{\tau}_{\text{per\_unit}}) = \sqrt{23112.50} = \mathbf{152.028}$.

---

## 6. CONSTANT TREATMENT EFFECT

Suppose $T_{1k} - T_{0k} = \tau_0$ (constant treatment effect across all clusters), but baseline levels $T_{0k}$ vary across clusters.

$$\text{Var}(Z_k) = \frac{[(1-p) (T_{0k} + \tau_0) + p T_{0k}]^2}{p(1-p)} = \frac{[T_{0k} + (1-p) \tau_0]^2}{p(1-p)}$$

**Conclusion**: Randomization variance is **NON-ZERO** even under a constant treatment effect. This occurs because under Bernoulli assignment, the number of treatment clusters $K_T \sim \text{Binom}(K, p)$ is random, causing the Horvitz-Thompson sum to fluctuate proportionally to baseline outcome level $T_{0k}$.

---

## 7. EXACT VARIANCE DECOMPOSITION

Substituting $T_{1k} = T_{0k} + \tau_k$ into $\text{Var}(Z_k)$:

$$\text{Var}(Z_k) = \frac{T_{0k}^2}{p(1-p)} + \frac{2 T_{0k} \tau_k}{p} + \frac{(1-p) \tau_k^2}{p}$$

Summing over all $K$ clusters:

$$\text{Var}(\hat{\tau}_{\text{total}}) = \underbrace{\frac{1}{p(1-p)} \sum_{k=1}^K T_{0k}^2}_{\text{Baseline Outcome Level Component}} + \underbrace{\frac{2}{p} \sum_{k=1}^K T_{0k} \tau_k}_{\text{Baseline-Effect Interaction}} + \underbrace{\frac{1-p}{p} \sum_{k=1}^K \tau_k^2}_{\text{Treatment Effect Variance}}$$

---

## 8. COMPARISON TO CURRENT PRODUCTION FORMULA

The current production formula $\widehat{\text{Var}}_{\text{prod}}(\hat{\tau}_{\text{total}}) = \frac{K_T S_T^2}{p^2} + \frac{K_C S_C^2}{(1-p)^2}$ calculates:

$$S_T^2 \approx \frac{1}{K-1} \sum (T_{1k} - \bar{T}_1)^2, \quad S_C^2 \approx \frac{1}{K-1} \sum (T_{0k} - \bar{T}_0)^2$$

### Missing Terms in Production Formula:
1. **Uncentered Baseline Mean Variance**: Missing $\frac{K \bar{T}_0^2}{p(1-p)}$ (the uncentered baseline outcome magnitude).
2. **Random Group Size Variance**: Missing variance generated by Binomial treatment count $K_T \sim \text{Binom}(K, p)$.
3. **Treatment-Baseline Interaction Covariance**: Missing $2 \bar{T}_0 \bar{\tau} / p$.

**Special Conditions for Validity**: The production formula would be valid under Bernoulli assignment **ONLY IF** population baseline mean $\bar{T}_0 \equiv 0$ AND $\bar{T}_1 \equiv 0$. In financial recovery services where baseline revenue $\bar{Y} \approx ₹1,000$, $\bar{T}_0 \gg 0$, making the current production formula **`INVALID`**.

---

## 9. COMPLETE RANDOMIZATION COMPARISON

Under **Complete Randomization** where $K_T \equiv K p$ is fixed:
* Any constant shift $C$ in baseline outcomes cancels out: $\frac{K_T C}{p} - \frac{K_C C}{1-p} = K C - K C \equiv 0$.
* Neyman's exact variance under Complete Randomization is:
  $$\text{Var}_{\text{CR}}(\hat{\tau}_{\text{total}}) = \frac{K}{p} S_1^2 + \frac{K}{1-p} S_0^2 - K S_{\tau}^2$$
* Under Complete Randomization, the production formula $\frac{K S_1^2}{p} + \frac{K S_0^2}{1-p}$ matches Neyman's conservative upper bound. Under Bernoulli assignment, it fails because $K_T$ is random and baseline mean $\bar{T}_0$ does not cancel.

---

## 10. ZERO-OBSERVED CLUSTERS

* For a cluster $k$ with 0 observed outcomes ($M_k = 0$), $T_k^{\text{obs}} = 0$.
* In the point estimator, $T_k^{\text{obs}} = 0$ contributes 0 to $\hat{\tau}_{\text{total}}$.
* Conditional on potential outcomes $(T_{1k}, T_{0k})$, if a cluster has zero potential outcome $T_{1k}=0, T_{0k}=0$, its randomization variance contribution $\text{Var}(Z_k)$ is 0.

---

## 11. UNEQUAL CLUSTER SIZES

* $\hat{\tau}_{\text{total}} / N$ targets the weighted per-eligible-case incremental revenue $\tau_{\text{per\_unit}} = \frac{\sum (T_{1k} - T_{0k})}{\sum N_k}$.
* Unweighted cluster assignment causes larger clusters ($N_k \gg 1$) to contribute quadratically larger variance ($T_{1k}^2 \propto N_k^2$).

---

## 12. CRITICAL DISTINCTIONS

1. **Design-Based Randomization Variance**: Derived here as $\sum \frac{[(1-p) T_{1k} + p T_{0k}]^2}{p(1-p)}$ conditional on potential outcomes.
2. **Outcome Missingness Variance**: Additional variance introduced by case-level missingness $R_i \sim \text{Bernoulli}(\pi_i)$.
3. **Propensity Estimation Variance**: Variance from estimating $\hat{\beta}$ in logistic regression.
4. **Feasible Sample Estimator**: Feasible variance formula constructed strictly from observed data $A_k, T_k^{\text{obs}}, \hat{\pi}_i$.

---

## 13. SUMMARY & CONCLUSION

```text
TASK2B = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

EXACT_BERNOULLI_VARIANCE_DERIVED = YES

CURRENT_PRODUCTION_FORMULA = INVALID

MISSING_VARIANCE_COMPONENTS = UNCENTERED_BASELINE_MEAN_VARIANCE, RANDOM_GROUP_SIZE_VARIANCE, TREATMENT_BASELINE_INTERACTION_COVARIANCE

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

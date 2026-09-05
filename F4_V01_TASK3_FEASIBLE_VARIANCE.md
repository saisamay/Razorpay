# F4 V-01 Task 3 — Feasible Observable Variance Estimator

```text
V01_TASK3 = COMPLETE

PRODUCTION_CODE_MODIFIED = NO

FEASIBLE_VARIANCE_ESTIMATOR_IDENTIFIED = YES

DESIGN_UNBIASED = IMPOSSIBLE

CONSISTENT = YES

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

---

## 1. PROBLEM DEFINITION

Under the pre-registered Razorpay recovery experiment design:
* $A_k \stackrel{\text{i.i.d.}}{\sim} \text{Bernoulli}(p)$ independently across $K$ assignment units.
* Potential outcomes $(T_{1k}, T_{0k})$ are never jointly observable for any cluster $k$ (Fundamental Problem of Causal Inference).
* For each cluster $k$, we observe only $A_k \in \{0, 1\}$ and $T_k^{\text{obs}} = A_k T_{1k} + (1-A_k) T_{0k}$.

The objective is to identify a **valid, feasible variance estimator** constructed strictly from observed data $(A_k, T_k^{\text{obs}}, p, N_k)$ without relying on unobservable potential outcome cross-products.

---

## 2. EXACT THEORETICAL VARIANCE TARGET

Conditional on potential outcomes $(T_{1k}, T_{0k})$, Task 2B established the exact Bernoulli randomization variance of $\hat{\tau}_{\text{total}}$:

$$\text{Var}(\hat{\tau}_{\text{total}} \mid T_{1}, T_{0}) = \sum_{k=1}^K \frac{[(1-p) T_{1k} + p T_{0k}]^2}{p(1-p)}$$

Expanding the numerator:

$$\text{Var}(\hat{\tau}_{\text{total}}) = \sum_{k=1}^K \left[ \frac{(1-p) T_{1k}^2}{p} + \frac{p T_{0k}^2}{1-p} + 2 T_{1k} T_{0k} \right] = \sum_{k=1}^K \left( \frac{T_{1k}^2}{p} + \frac{T_{0k}^2}{1-p} \right) - \sum_{k=1}^K (T_{1k} - T_{0k})^2$$

---

## 3. OBSERVABLE-DATA LIMITATION

Because $A_k (1-A_k) \equiv 0$ for every cluster $k$, the cross-product term $T_{1k} T_{0k}$ is **never observable**.

**Fundamental Identification Result**:
Exact design-unbiased estimation of the finite-population Bernoulli randomization variance is **IMPOSSIBLE** from a single realization of an experiment without making uncheckable structural assumptions about $T_{1k} T_{0k}$.

Therefore, any feasible variance estimator must target an **EXACT CONSERVATIVE UPPER BOUND** ($E[\widehat{\text{Var}}] \ge \text{Var}_{\text{true}}$).

---

## 4. CANDIDATE VARIANCE ESTIMATORS ANALYZED

### Candidate 1: Uncentered Horvitz-Thompson Observed Total Variance ($\widehat{\text{Var}}_{\text{HT\_obs}}$)
Define:
$$\widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{total}}) = \sum_{k=1}^K \left[ \frac{A_k (T_k^{\text{obs}})^2}{p^2} + \frac{(1-A_k) (T_k^{\text{obs}})^2}{(1-p)^2} \right]$$

#### Expectation:
$$E \left[ \widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{total}}) \right] = \sum_{k=1}^K \left[ p \cdot \frac{T_{1k}^2}{p^2} + (1-p) \cdot \frac{T_{0k}^2}{(1-p)^2} \right] = \sum_{k=1}^K \left( \frac{T_{1k}^2}{p} + \frac{T_{0k}^2}{1-p} \right)$$

Comparing with exact Bernoulli variance:
$$E \left[ \widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{total}}) \right] - \text{Var}(\hat{\tau}_{\text{total}}) = \sum_{k=1}^K (T_{1k} - T_{0k})^2 = \sum_{k=1}^K \tau_k^2 \ge 0$$

* **Design Unbiasedness**: Impossible for exact variance, but **GUARANTEED CONSERVATIVE** ($E[\widehat{\text{Var}}] \ge \text{Var}$).
* **Consistency**: Consistent estimator for upper bound of Bernoulli randomization variance.
* **Special Case**: When cluster treatment effects $\tau_k = 0$ (or small relative to baseline revenue), $\widehat{\text{Var}}_{\text{HT\_obs}}$ is **EXACTLY UNBIASED**.

---

### Candidate 2: Current Production Formula (Neyman Sample Group Variance)
$$\widehat{\text{Var}}_{\text{prod}}(\hat{\tau}_{\text{total}}) = \frac{K_T S_T^2}{p^2} + \frac{K_C S_C^2}{(1-p)^2}$$

* **Evaluation**: **INVALID** under Bernoulli assignment.
* **Reason**: Subtracts sample group means $\bar{T}_T, \bar{T}_C$, completely omitting the uncentered baseline squared sum $\frac{K \bar{T}_0^2}{p(1-p)}$ and random group size variance $\text{Var}(K_T) = K p(1-p)$. Underestimates true sampling variance by factors of $4.5\times$ to $\infty$.

---

## 5. MATHEMATICAL DERIVATION OF FEASIBLE ESTIMATOR

On the per-eligible-case scale ($\hat{\tau}_{\text{per\_unit}} = \hat{\tau}_{\text{total}} / N_{\text{eligible}}$):

$$\widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{per\_unit}}) = \frac{1}{N_{\text{eligible}}^2} \sum_{k=1}^K \left[ \frac{A_k (T_k^{\text{obs}})^2}{p^2} + \frac{(1-A_k) (T_k^{\text{obs}})^2}{(1-p)^2} \right]$$

$$\text{SE}_{\text{HT\_obs}}(\hat{\tau}_{\text{per\_unit}}) = \sqrt{\widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{per\_unit}})}$$

---

## 6. BERNOULLI-SPECIFIC ANALYSIS

Under independent Bernoulli assignment ($A_k \sim \text{Bernoulli}(p)$):
* $K_T \sim \text{Binom}(K, p)$ fluctuates across experiment realizations.
* Fluctuations in $K_T$ inject variance proportional to uncentered baseline cluster total $(T_k^{\text{obs}})^2$.
* $\widehat{\text{Var}}_{\text{HT\_obs}}$ directly captures this binomial treatment count variance by summing uncentered weighted squared outcomes $(T_k^{\text{obs}} / p)^2$.

---

## 7. UNEQUAL CLUSTER SIZES

* $T_k^{\text{obs}} = \sum_{i \in k, \text{obs}} \frac{Y_{ki}}{\hat{\pi}_{ki}}$ scales with cluster size $N_k$.
* Dividing the total variance by $N_{\text{eligible}}^2 = (\sum_{k=1}^K N_k)^2$ correctly weights each cluster's contribution proportional to $N_k^2$, correctly preserving variance scaling for variable cluster sizes.

---

## 8. ZERO-OBSERVED CLUSTERS

* For a cluster $k$ with 0 observed outcomes ($M_k = 0$), $T_k^{\text{obs}} = 0$.
* In $\widehat{\text{Var}}_{\text{HT\_obs}}$, a zero-observed cluster contributes $(0)^2 = 0$ to total variance.
* All $K$ eligible assignment units remain in the summation index $k = 1, \dots, K$.

---

## 9. KNOWN-$\pi$ vs ESTIMATED-$\hat{\pi}$ IMPLICATIONS

* **Layer 1 (Known $\pi_i$)**: $\widehat{\text{Var}}_{\text{HT\_obs}}$ provides a conservative upper bound for true propensities $\pi_i$.
* **Layer 2 (Estimated $\hat{\pi}_i$)**: In semiparametric efficiency theory (Robins, Hermán, & Brumback, 2000), using estimated propensities $\hat{\pi}_i(\hat{\beta})$ from logistic regression **reduces or maintains** estimator variance compared to true propensities ($\text{Var}(\hat{\tau}(\hat{\beta})) \le \text{Var}(\hat{\tau}(\pi))$). Therefore, $\widehat{\text{Var}}_{\text{HT\_obs}}$ using $\hat{\pi}_i$ remains a **CONSERVATIVE** variance estimator for the estimated-propensity IPW point estimator.

---

## 10. SMALL EXHAUSTIVE EXAMPLE ($K=4$)

Set $K = 4, p = 0.5, N_{\text{eligible}} = 4$ with $T_0 = [10, 20, 30, 40], T_1 = [15, 30, 45, 60]$.

```text
K=4 Numerical Verification:
  True Bernoulli Var(tau_hat_total): 18,750.0000
  True Bernoulli Var(tau_hat_per_unit): 1,171.8750
  Sum of tau_k^2:                    750.0000
  Mean HT_obs Var(tau_hat_total):    19,500.0000
  Mean HT_obs Var(tau_hat_per_unit): 1,218.7500
  Bias E[HT_obs] - True_Var:         +750.0000  (Guaranteed Conservative)
```

---

## 11. HOMOGENEOUS EXAMPLE ($K=200$)

Set $K = 200, N_k = 5, N_{\text{eligible}} = 1000, p = 0.5, Y(0)=1000, Y(1)=1150$.

```text
K=200 Homogeneous Example Verification:
  True Bernoulli SE(per_unit): 152.0280
  HT_obs SE(per_unit):         152.3975
  Ratio HT_obs / True:         1.0024   (Overestimates SE by only +0.24%)
```

---

## 12. RECOMMENDED FEASIBLE ESTIMATOR

The recommended feasible variance estimator for F4 Bernoulli IPW point estimation is:

$$\widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{per\_unit}}) = \frac{1}{N_{\text{eligible}}^2} \sum_{k=1}^K \left[ \frac{A_k (T_k^{\text{obs}})^2}{p^2} + \frac{(1-A_k) (T_k^{\text{obs}})^2}{(1-p)^2} \right]$$

$$\text{SE}_{\text{per\_unit}} = \sqrt{\widehat{\text{Var}}_{\text{HT\_obs}}(\hat{\tau}_{\text{per\_unit}})}$$

---

## 13. SUMMARY & CONCLUSION

```text
V01_TASK3 = COMPLETE

PRODUCTION_CODE_MODIFIED = NO

FEASIBLE_VARIANCE_ESTIMATOR_IDENTIFIED = YES

DESIGN_UNBIASED = IMPOSSIBLE

CONSISTENT = YES

IMPLEMENTATION_CHANGE_AUTHORIZED = NO
```

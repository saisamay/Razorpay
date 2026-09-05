# F4 V-01 Task 2 — First-Principles Variance Derivation

```text
V01_TASK2 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

CURRENT_VARIANCE_FORMULA_CLASSIFICATION = INVALID

ROOT_CAUSE_IDENTIFIED = YES
```

---

## 1. MATHEMATICAL SETUP

Let $K$ be the total number of pre-registered eligible assignment units (clusters).
For each assignment unit $k \in \{1, \dots, K\}$:
* $N_k \ge 1$ is the number of eligible cases in cluster $k$.
* $T_k = \sum_{i \in k, \text{obs}} \frac{Y_{ki}}{\hat{\pi}_{ki}}$ is the fixed unnormalized IPW weighted revenue total for observed cases in cluster $k$.
* In this derivation, we treat $T_k$ as fixed constants (given potential outcomes and fixed propensities $\hat{\pi}_i = \pi_i$).

**Randomization Model**:
$$A_k \stackrel{\text{i.i.d.}}{\sim} \text{Bernoulli}(p), \quad \text{independently for } k = 1, \dots, K$$
where $p = \text{design\_allocation\_p} \in (0, 1)$.

---

## 2. CURRENT POINT ESTIMATOR

The current production point estimator is:

$$\hat{\tau}_{\text{total}} = \frac{1}{p} \sum_{k: A_k=1} T_k - \frac{1}{1-p} \sum_{k: A_k=0} T_k = \sum_{k=1}^K \left[ \frac{A_k T_k}{p} - \frac{(1-A_k) T_k}{1-p} \right]$$

$$\hat{\tau}_{\text{per\_unit}} = \frac{\hat{\tau}_{\text{total}}}{N_{\text{eligible}}}$$

where $N_{\text{eligible}} = \sum_{k=1}^K N_k$.

---

## 3. FIRST-PRINCIPLES BERNOULLI DERIVATION

Let $Z_k$ be the random contribution of assignment unit $k$ to $\hat{\tau}_{\text{total}}$:

$$Z_k = \frac{A_k T_k}{p} - \frac{(1-A_k) T_k}{1-p}$$

Simplifying $Z_k$ algebraically:

$$Z_k = T_k \left[ \frac{A_k(1-p) - (1-A_k)p}{p(1-p)} \right] = T_k \left[ \frac{A_k - p}{p(1-p)} \right]$$

### Expectation of $Z_k$ and $\hat{\tau}_{\text{total}}$:
Since $E[A_k] = p$:

$$E[Z_k] = T_k \left[ \frac{p - p}{p(1-p)} \right] = 0$$

$$E[\hat{\tau}_{\text{total}} \mid T_1, \dots, T_K] = \sum_{k=1}^K E[Z_k] = 0$$

### Variance of $Z_k$:
Since $\text{Var}(A_k) = p(1-p)$:

$$\text{Var}(Z_k) = T_k^2 \cdot \frac{\text{Var}(A_k)}{p^2 (1-p)^2} = T_k^2 \cdot \frac{p(1-p)}{p^2 (1-p)^2} = \frac{T_k^2}{p(1-p)}$$

---

## 4. EXACT RANDOMIZATION VARIANCE

Because $A_1, \dots, A_K$ are mutually independent under Bernoulli assignment, $Z_1, \dots, Z_K$ are independent random variables.

Therefore, the exact conditional randomization variance of $\hat{\tau}_{\text{total}}$ is:

$$\text{Var}(\hat{\tau}_{\text{total}} \mid T_1, \dots, T_K) = \sum_{k=1}^K \text{Var}(Z_k) = \frac{1}{p(1-p)} \sum_{k=1}^K T_k^2$$

On the per-eligible-case scale:

$$\text{Var}(\hat{\tau}_{\text{per\_unit}} \mid T_1, \dots, T_K) = \frac{1}{N_{\text{eligible}}^2 \cdot p(1-p)} \sum_{k=1}^K T_k^2$$

---

## 5. CURRENT PRODUCTION VARIANCE COMPARISON

The current production formula is:

$$\widehat{\text{Var}}_{\text{prod}}(\hat{\tau}_{\text{total}}) = \frac{K_T \cdot S_T^2}{p^2} + \frac{K_C \cdot S_C^2}{(1-p)^2}$$

where:
$$S_T^2 = \frac{1}{K_T - 1} \sum_{k: A_k=1} (T_k - \bar{T}_T)^2, \quad S_C^2 = \frac{1}{K_C - 1} \sum_{k: A_k=0} (T_k - \bar{T}_C)^2$$

### Why the Current Production Formula Fails Under Bernoulli Assignment:
1. **Subtracts Group Means $\bar{T}_T, \bar{T}_C$**: $S_T^2$ and $S_C^2$ measure deviations around group sample means. They omit the squared baseline outcome level $\bar{T}^2$.
2. **Ignores Randomness of $K_T$**: Under independent Bernoulli assignment, treatment count $K_T \sim \text{Binomial}(K, p)$ is random. Every unit added to or subtracted from treatment shifts the Horvitz-Thompson total by $T_k / p$.
3. **Severe Anti-Conservatism**: When baseline outcome levels are non-zero ($\bar{T} \gg 0$), $S_T^2$ and $S_C^2$ remain small, causing the production formula to severely underestimate true Bernoulli sampling variance (by $4.5\times$ in small examples and infinite factors in homogeneous examples).

---

## 6. $K_T$ AND $K_C$ RANDOMNESS

Under independent Bernoulli assignment:
* $K_T = \sum_{k=1}^K A_k \sim \text{Binomial}(K, p)$
* $E[K_T] = K p, \quad \text{Var}(K_T) = K p(1-p)$
* $K_C = K - K_T \sim \text{Binomial}(K, 1-p)$

Because $K_T$ is a random variable, $\hat{\tau}_{\text{total}} = \frac{1}{p} \sum_{A_k=1} T_k - \frac{1}{1-p} \sum_{A_k=0} T_k$ contains variance contributed directly by the fluctuation of $K_T$ scaled by average baseline cluster outcome $\bar{T}$.

---

## 7. TREATMENT/CONTROL COVARIANCE

Under independent Bernoulli assignment:
$$\text{Cov}(A_j, A_k) = 0 \quad \text{for } j \neq k$$

Because assignments are independent, there is zero cross-cluster covariance ($\text{Cov}(Z_j, Z_k) = 0$). The total variance is simply the sum of individual cluster variances $\sum_{k=1}^K \text{Var}(Z_k)$.

---

## 8. $K=4$ EXHAUSTIVE NUMERICAL EXAMPLE

Set $K = 4, p = 0.5, N_{\text{eligible}} = 4$ with cluster totals $T = [10, 20, 30, 40]$.

### Exact Theoretical Variance:
$$\text{Var}(\hat{\tau}_{\text{total}}) = \frac{1}{0.5 \times 0.5} (10^2 + 20^2 + 30^2 + 40^2) = 4 \times (100 + 400 + 900 + 1600) = \mathbf{12,000.0}$$
$$\text{Var}(\hat{\tau}_{\text{per\_unit}}) = \frac{12,000.0}{4^2} = \mathbf{750.0}$$

### Exhaustive Enumeration over all $2^4 = 16$ Assignments:
* **Defined Production Variance Assignments**: Defined for only **6 / 16** assignments (where $K_T = 2, K_C = 2$). Undefined or 0 for the other 10 assignments ($K_T = 0, 1, 3, 4$).
* **Mean Production Variance (where defined)**:
  $$\text{Mean } \widehat{\text{Var}}_{\text{prod}}(\hat{\tau}_{\text{total}}) = \mathbf{2,666.67} \quad (\widehat{\text{Var}}_{\text{prod}}(\hat{\tau}_{\text{per\_unit}}) = \mathbf{166.67})$$
* **Comparison**: The production formula underestimates exact Bernoulli variance ($166.67$ vs $750.0$) by **$4.5\times$**, proving severe anti-conservatism.

---

## 9. $K=200$ HOMOGENEOUS CLUSTER ANALYTICAL EXAMPLE

Set $K = 200, N_k = 5, N_{\text{eligible}} = 1000, p = 0.5$.
Baseline outcomes: $Y(0) = 1000, Y(1) = 1150$.
Zero missingness ($\pi_i = 1$).

* Control cluster totals: $T_k(0) = 5 \times 1000 = 5000$.
* Treatment cluster totals: $T_k(1) = 5 \times 1150 = 5750$.

### Exact Randomization Calculation:
* $Z_k = 5750 / 0.5 = 11500$ if $A_k = 1$, and $Z_k = -5000 / 0.5 = -10000$ if $A_k = 0$.
* $E[Z_k] = 0.5(11500) + 0.5(-10000) = 750$.
* $\text{Var}(Z_k) = 0.5(11500 - 750)^2 + 0.5(-10000 - 750)^2 = 10750^2 = 115,562,500$.
* Exact $\text{Var}(\hat{\tau}_{\text{total}}) = 200 \times 115,562,500 = \mathbf{23,112,500,000.0}$.
* Exact $\text{SE}(\hat{\tau}_{\text{per\_unit}}) = \frac{\sqrt{23,112,500,000}}{1000} = \mathbf{152.028}$.

### Current Production Formula:
* Since all control clusters have identical $T_k = 5000$, $S_C^2 \equiv 0$.
* Since all treatment clusters have identical $T_k = 5750$, $S_T^2 \equiv 0$.
* Current production formula reports: $\text{total\_var} = 0 \implies \text{SE}_{\text{prod}} = \mathbf{0.0000}$.
* **Result**: Production formula claims 0 uncertainty ($\text{SE} = 0$) when actual sampling $\text{SE} = 152.03$.

---

## 10. UNEQUAL CLUSTER SIZES

When cluster sizes $N_k$ vary:
* The current unweighted point estimator $\hat{\tau}_{\text{total}} = \frac{1}{p} \sum_{T} T_k - \frac{1}{1-p} \sum_{C} T_k$ computes total population revenue increment.
* Dividing by $N_{\text{eligible}} = \sum_{k=1}^K N_k$ estimates **incremental revenue per eligible case**.
* However, because $T_k$ scales linearly with cluster size $N_k$, larger clusters introduce quadratically larger variance ($T_k^2 \propto N_k^2$). Uncentered $T_k^2$ summation amplifies baseline variance for large clusters.

---

## 11. ZERO-OBSERVED CLUSTERS

For a cluster $k$ with 0 observed outcomes ($M_k = 0$):
* **Point Estimator Contribution**: $T_k = 0$. In $\hat{\tau}_{\text{total}}$, $T_k = 0$ contributes 0 revenue.
* **Randomization Variance Contribution**: In the true Bernoulli variance $\frac{1}{p(1-p)} \sum T_k^2$, a cluster with $T_k = 0$ contributes $0^2 = 0$.
* **Degrees of Freedom**: In cluster count accounting, $k$ is still a valid pre-registered assignment unit ($A_k \in \{0, 1\}$). Omitting $M_k = 0$ clusters from $K_{\text{total}}$ artificially inflates sample variance estimators that divide by $K_T - 1$ or $K_C - 1$.

---

## 12. BERNOULLI VS COMPLETE RANDOMIZATION

| Randomization Design | Treatment Count $K_T$ | Baseline Mean $\bar{U}$ Effect | Variance Formula |
| :--- | :--- | :--- | :--- |
| **Independent Bernoulli** | Random ($K_T \sim \text{Binom}(K, p)$) | Appears in variance ($\sum T_k^2 / (p(1-p))$) | Depends on un-centered $T_k^2$ |
| **Complete Randomization** | Fixed ($K_T \equiv K p$) | Drops out ($\sum A_k \bar{U} = K_T \bar{U}$) | Neyman formula: $\frac{K S_T^2}{p} + \frac{K S_C^2}{1-p}$ |

### Match to Production Formula:
* Under **Bernoulli Assignment**, the current production formula is **INVALID** (severely underestimates variance when $\bar{T} \neq 0$).
* Under **Complete Randomization** (fixed $K_T = K p$), the current production formula $\frac{K_T S_T^2}{p^2} + \frac{K_C S_C^2}{(1-p)^2}$ matches the conservative Neyman variance estimator $\frac{K S_T^2}{p} + \frac{K S_C^2}{1-p}$.

---

## 13. EXACT CLASSIFICATION OF CURRENT VARIANCE FORMULA

The current production variance formula $\widehat{\text{Var}}_{\text{prod}}(\hat{\tau}_{\text{total}}) = \frac{K_T S_T^2}{p^2} + \frac{K_C S_C^2}{(1-p)^2}$ is:

$$\mathbf{INVALID}$$

under the registered independent Bernoulli assignment design.

---

## 14. WHAT REMAINS UNRESOLVED

1. **Outcome Missingness Variance (MCAR / MAR)**: This derivation assumed $\pi_i$ fixed and 100% observation. Task 3 must incorporate case-level missingness variance $R_i \sim \text{Bernoulli}(\pi_i)$.
2. **Cluster Centering ($U_k = T_k - N_k \hat{\tau}$)**: How to construct centered cluster scores $U_k$ that remove baseline cluster outcome variance under Bernoulli assignment.
3. **Propensity Parameter Variance ($V_{\hat{\beta}}$)**: Incorporating variance of estimated coefficients $\hat{\beta}$ from logistic regression.

---

## FINAL OUTPUT

```text
V01_TASK2 = COMPLETE
PRODUCTION_CODE_MODIFIED = NO

CURRENT_VARIANCE_FORMULA_CLASSIFICATION = INVALID

ROOT_CAUSE_IDENTIFIED = YES
```

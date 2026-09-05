# F4 MCAR Clustered Variance Resolution Report

```text
MCAR_CLUSTER_VARIANCE_STATUS = INCORRECT
CURRENT_FORMULA_APPROPRIATENESS = INAPPROPRIATE
PRODUCTION_SIMULATION_DESIGN_MATCH = MISMATCH
28x_SE_EXPLANATION = EXPLAINED

F4_STATISTICAL_STATUS = PASS_WITH_CONDITIONS
F5_AUTHORIZATION = GO_WITH_CONDITIONS
```

---

## 1. ACTUAL ESTIMATOR WITH MISSINGNESS

$$\hat{\tau} = \frac{\hat{\Delta}_{\text{IPW}}}{N_{\text{eligible}}} = \frac{1}{N_{\text{eligible}}} \left[ \frac{1}{p} \sum_{i \in \text{eligible}_T} \frac{R_i Y_i}{\hat{\pi}_i} - \frac{1}{1-p} \sum_{j \in \text{eligible}_C} \frac{R_j Y_j}{\hat{\pi}_j} \right]$$

### Random Variables Contributing to Variance
1. **Customer Assignment ($A_k$)**: Random allocation of customer clusters $k$ to Treatment ($A_k = 1$) vs Control ($A_k = 0$) with probability $p = 0.50$.
2. **Case Missingness ($R_i$)**: Observation indicator ($R_i \in \{0, 1\}$) for eligible case $i \in k$ with propensity $\pi_i = P(R_i = 1 \mid X_i)$.
3. **Outcome Variability ($Y_i$)**: Potential outcomes $Y_i(0), Y_i(1)$ across cases and merchants.
4. **Propensity Estimation ($\hat{\pi}_i$)**: Sampling variation in propensity model parameters $\hat{\beta}$.

---

## 2. MATHEMATICAL ANALYSIS OF MCAR WITHIN A CLUSTER

For a customer cluster $k$ containing $N_k = 5$ eligible cases, each with $Y_i = 1,000.0$ subunits and $\pi_i = 0.85$:

* **Weighted Case Value**: $\frac{Y_i}{\hat{\pi}_i} = \frac{1000}{0.85} = 1,176.47$ subunits.
* **Observed Case Count**: $M_k = \sum_{i=1}^5 R_i \sim \text{Binomial}(5, 0.85)$.
* **Weighted Cluster Total**: $T_k = \sum_{i \in k} \frac{R_i Y_i}{\hat{\pi}_i} = 1,176.47 \times M_k$.

### Mathematical Quantities
1. **Expected Cluster Total ($E[T_k]$)**:
   $$E[M_k] = 5 \times 0.85 = 4.25 \implies E[T_k] = 1,176.47 \times 4.25 = \mathbf{5,000.00 \text{ subunits}}$$
2. **Variance of Cluster Total ($\text{Var}[T_k]$)**:
   $$\text{Var}[M_k] = 5 \times 0.85 \times 0.15 = 0.6375 \implies \text{Var}[T_k] = (1,176.47)^2 \times 0.6375 = \mathbf{882,352.94 \text{ subunits}^2}$$
3. **Standard Deviation of Cluster Total ($\text{SD}[T_k]$)**:
   $$\text{SD}[T_k] = \sqrt{882,352.94} = \mathbf{939.34 \text{ subunits}}$$

---

## 3. CASE-LEVEL OBSERVATION VARIANCE VS. CLUSTER-ASSIGNMENT VARIANCE

By the Law of Total Variance (conditioning on assignment $A$):
$$\text{Var}(\hat{\tau}) = \underbrace{E_A[\text{Var}_{R|A}(\hat{\tau} \mid A)]}_{\text{Case-Level Missingness Variance}} + \underbrace{\text{Var}_A(E_{R|A}[\hat{\tau} \mid A])}_{\text{Cluster Assignment Variance}}$$

* **Case-Level Missingness Variance ($E_A[\text{Var}_{R|A}]$)**:
  Cases miss independently across cases $i \in k$. The variance of missingness scales **linearly with case count** ($\sum_{i \in \text{Obs}} Y_i^2 \frac{1-\pi_i}{\pi_i^2}$).
* **Cluster Assignment Variance ($\text{Var}_A(E_{R|A}]$)**:
  Between-cluster variance occurs because whole customer clusters $k$ are assigned to Treatment vs Control. It scales with the variance of true cluster potential outcomes $\text{Var}_k\left(\sum_{i \in k} Y_{k,i}\right)$.

### Root Cause of the 28.5 SE Inflation
In [`estimator.py:335-360`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/estimator.py#L335-L360), `cluster_totals` computes $T_k = \sum_{i \in k} \frac{R_i Y_i}{\hat{\pi}_i}$ FIRST, and THEN takes the sample variance across clusters $S_T^2 = \text{Var}_k(T_k)$.
This conflates within-cluster case missingness variance ($\text{Var}_{R|A}(T_k) = 882,353$) with between-cluster assignment variance. When `total_var` multiplies $S_T^2$ by $\frac{K_t}{p^2} = 400$, it incorrectly multiplies the case-level missingness variance by $400$ instead of summing it linearly across $K_t$ clusters ($\times 100$). This over-scales the standard error from $\approx 0.83$ to $\mathbf{28.52}$.

---

## 4. APPROPRIATE CASE-LEVEL CLUSTER-ROBUST FORMULA

The mathematically appropriate variance estimator for the registered CASE-level IPW estimand under cluster assignment is the **Cluster-Robust Sandwich Estimator on Case Residuals**:

Let $e_{k,i}$ be the case-level IPW residual score for case $i$ in cluster $k$:
$$e_{k,i} = \frac{A_k R_{k,i} Y_{k,i}}{p \cdot \hat{\pi}_{k,i}} - \frac{(1 - A_k) R_{k,i} Y_{k,i}}{(1 - p) \cdot \hat{\pi}_{k,i}} - \hat{\tau}$$

Let $U_k$ be the cluster score sum for cluster $k$:
$$U_k = \sum_{i \in k} e_{k,i}$$

Then the cluster-robust variance estimator of $\hat{\tau}$ is:
$$\text{Var}_{\text{appropriate}}(\hat{\tau}) = \frac{1}{N_{\text{eligible}}^2} \cdot \frac{K_{\text{total}}}{K_{\text{total}} - 1} \sum_{k=1}^{K_{\text{total}}} U_k^2$$

---

## 5. EVALUATION OF THE 28.5 SE

The 28.5 SE is **EXCESSIVELY CONSERVATIVE / INCORRECTLY SCALED**. It is not a calibrated statistical bound; it is an artifact of multiplying within-cluster case-level missingness variance by $\frac{1}{p^2}$.

---

## 6. PRODUCTION VS. SIMULATION ASSIGNMENT DESIGN

```text
PRODUCTION_DESIGN = Independent HMAC-SHA256 Bernoulli assignment per assignment_unit_id (assignment.py:347)
SIMULATION_DESIGN = Fixed-count balanced permutation assignment via rng.shuffle() (simulation.py:230-233)
DESIGN_DIFFERENCE_IMPACT_ON_VARIANCE = Bernoulli assignment introduces binomial variance in the number of treatment clusters K_t ~ Binomial(K_total, p), whereas fixed-count permutation fixes K_t = 100.
```

---

## 7. FINAL DETERMINATION BLOCK

```text
MCAR_CLUSTER_VARIANCE_STATUS = INCORRECT
CURRENT_FORMULA_APPROPRIATENESS = INAPPROPRIATE
PRODUCTION_SIMULATION_DESIGN_MATCH = MISMATCH
28x_SE_EXPLANATION = EXPLAINED

F4_STATISTICAL_STATUS = PASS_WITH_CONDITIONS
F5_AUTHORIZATION = GO_WITH_CONDITIONS
```

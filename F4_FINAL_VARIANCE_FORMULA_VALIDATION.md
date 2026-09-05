# F4 Final Variance Formula Validation Report

```text
CURRENT_VARIANCE_FORMULA = total_var = (K_t * S_T^2 / p^2) + (K_c * S_C^2 / (1-p)^2); SE = sqrt(total_var) / N_eligible
PROPOSED_VARIANCE_FORMULA = Var(tau_hat) = (1 / N_eligible^2) * (K / (K - 1)) * sum_k U_k^2, where U_k = g_k - N_k * tau_hat

PROPOSED_FORMULA_MATHEMATICALLY_VALID = YES
MCAR_VARIANCE_HANDLED_CORRECTLY = YES
ASSIGNMENT_PROBABILITY_MODEL = ESTABLISHED
FORMULA_READY_FOR_IMPLEMENTATION = YES

F4_STATISTICAL_STATUS = PASS_WITH_CONDITIONS
F5_AUTHORIZATION = GO_WITH_CONDITIONS
```

---

## 1. DERIVATION OF THE CLUSTER SCORE FROM FIRST PRINCIPLES

### 1.1 The Estimator
$$\hat{\tau} = \frac{\hat{\Delta}_{\text{IPW}}}{N_{\text{eligible}}} = \frac{1}{N_{\text{eligible}}} \sum_{k=1}^K g_k$$
where $g_k$ is the uncentered IPW contribution of cluster $k$:
$$g_k = \frac{A_k}{p} \sum_{i \in k} \frac{R_{k,i} Y_{k,i}}{\hat{\pi}_{k,i}} - \frac{1 - A_k}{1 - p} \sum_{i \in k} \frac{R_{k,i} Y_{k,i}}{\hat{\pi}_{k,i}}$$

### 1.2 Cluster Contribution & Centering
For the CASE-level estimand $\hat{\tau}$, each cluster $k$ contains $N_k$ eligible cases. Under the null hypothesis that $E[\hat{\tau}]$ is the population average effect, the mean contribution of cluster $k$ is $N_k \hat{\tau}$.

The centered cluster score $U_k$ is:
$$U_k = g_k - N_k \hat{\tau}$$

#### Exact Mathematical Property of $U_k$
Summing $U_k$ over all $K$ clusters:
$$\sum_{k=1}^K U_k = \sum_{k=1}^K g_k - \left( \sum_{k=1}^K N_k \right) \hat{\tau} = \hat{\Delta}_{\text{IPW}} - N_{\text{eligible}} \left( \frac{\hat{\Delta}_{\text{IPW}}}{N_{\text{eligible}}} \right) \equiv \mathbf{0.0}$$
Centering $-\hat{\tau}$ weighted by $N_k$ (cases per cluster) guarantees exact sum-to-zero centering across all clusters.

---

## 2. MATHEMATICAL VALIDATION OF THE CLUSTER-ROBUST VARIANCE FORM

### 2.1 The Validated Formula
$$\text{Var}(\hat{\tau}) = \frac{1}{N_{\text{eligible}}^2} \cdot \frac{K}{K - 1} \sum_{k=1}^K U_k^2 \implies \text{SE}(\hat{\tau}) = \sqrt{\text{Var}(\hat{\tau})}$$

### 2.2 Property Checklist
1. **Centering**: $U_k = g_k - N_k \hat{\tau}$ is exactly centered ($\sum_k U_k = 0$).
2. **Finite-Sample Correction**: $\frac{K}{K-1}$ applies standard degrees-of-freedom adjustment for $K$ clusters.
3. **Probability Normalization**: $g_k$ contains $1/p$ (Treatment) and $1/(1-p)$ (Control), correctly scaling the score for Bernoulli cluster assignment.
4. **MCAR & IPW Variance**: Concurrently captures within-cluster case missingness variance and between-cluster assignment variance without over-multiplying missingness variance by $K_t/p^2$.
5. **Propensity Estimation Uncertainty**: Excludes parameter variance $\text{Var}(\hat{\beta})$ (disclosed finding M-02).

---

## 3. NON-DEGENERATE 4-CLUSTER MICRO EXAMPLE

### Setup
* $K = 4$ clusters ($T_1, T_2$ Treatment $A_k=1$; $C_1, C_2$ Control $A_k=0$).
* $N_k = 2$ cases per cluster ($N_{\text{eligible}} = 8$ cases).
* $p = 0.50$, $\hat{\pi}_{k,i} = 0.85$.
* Outcomes & Observation Indicators:
  - $T_1$: Case 1 ($Y=1000, R=1$), Case 2 ($Y=1000, R=1$)
  - $T_2$: Case 3 ($Y=1000, R=1$), Case 4 ($Y=1000, R=0$)
  - $C_1$: Case 5 ($Y=800, R=1$), Case 6 ($Y=800, R=1$)
  - $C_2$: Case 7 ($Y=800, R=1$), Case 8 ($Y=800, R=0$)

### Step-by-Step Hand Derivation

1. **Uncentered Cluster Contributions ($g_k$)**:
   - $g_1 = \frac{1}{0.5} \left( \frac{1000}{0.85} + \frac{1000}{0.85} \right) = \mathbf{4,705.8824}$ subunits
   - $g_2 = \frac{1}{0.5} \left( \frac{1000}{0.85} + 0 \right) = \mathbf{2,352.9412}$ subunits
   - $g_3 = -\frac{1}{0.5} \left( \frac{800}{0.85} + \frac{800}{0.85} \right) = \mathbf{-3,764.7059}$ subunits
   - $g_4 = -\frac{1}{0.5} \left( \frac{800}{0.85} + 0 \right) = \mathbf{-1,882.3529}$ subunits

2. **Population Totals & Per-Case Estimand**:
   - $\hat{\Delta}_{\text{IPW}} = \sum_{k=1}^4 g_k = 4705.8824 + 2352.9412 - 3764.7059 - 1882.3529 = \mathbf{+1,411.7647}$ subunits
   - $\hat{\tau} = \frac{+1411.7647}{8} = \mathbf{+176.4706 \text{ subunits per case}}$

3. **Centered Cluster Scores ($U_k = g_k - 2 \cdot \hat{\tau}$)**:
   - $U_1 = 4705.8824 - 2(176.4706) = \mathbf{+4,352.9412}$
   - $U_2 = 2352.9412 - 2(176.4706) = \mathbf{+2,000.0000}$
   - $U_3 = -3764.7059 - 2(176.4706) = \mathbf{-4,117.6471}$
   - $U_4 = -1882.3529 - 2(176.4706) = \mathbf{-2,235.2941}$
   - **Verification**: $\sum_{k=1}^4 U_k = 4352.9412 + 2000.0000 - 4117.6471 - 2235.2941 = \mathbf{0.0000}$ (**EXACT**)

4. **Variance & Standard Error**:
   - $\sum_{k=1}^4 U_k^2 = (4352.9412)^2 + (2000.0000)^2 + (-4117.6471)^2 + (-2235.2941)^2 = 44,900,346.02$
   - $\text{Var}(\hat{\tau}) = \frac{1}{8^2} \cdot \frac{4}{3} \cdot (44,900,346.02) = \mathbf{935,423.88}$
   - $\text{SE}(\hat{\tau}) = \sqrt{935,423.88} = \mathbf{967.17 \text{ subunits per case}}$

---

## 4. MCAR VARIANCE RECONCILIATION

Why the current formula inflates SE vs. why the proposed formula handles MCAR correctly:

* **Current Formula**: Takes $S_T^2 = \text{Var}_k(T_k)$ (where $T_k = \sum_{i \in k, R_i=1} Y_{k,i} / \hat{\pi}_{k,i}$) and multiplies $S_T^2$ by $\frac{K_t}{p^2} = 400$. This incorrectly scales the case-level missingness variance $\text{Var}_{R|A}(T_k)$ by $400$.
* **Validated Proposed Formula**: Computes cluster score $U_k$ on uncentered IPW sum $g_k = \frac{A_k}{p} T_k - \frac{1-A_k}{1-p} T_k$. Taking $\sum_k U_k^2$ sums cluster squared scores directly without an extra $K_t/p^2$ multiplier, preserving true linear scaling of case-level MCAR missingness variance across clusters.

---

## 5. ASSIGNMENT PROBABILITY MODEL

```text
ASSIGNMENT_PROBABILITY_MODEL = ESTABLISHED
```
* **Model**: Super-population cluster-randomized trial model with independent Bernoulli assignment $P(A_k = 1) = p$.
* **Justification**: Supported by authoritative specification in F3 (`assignment.py:347`) where each `assignment_unit_id` is assigned independently via HMAC-SHA256 digest bucket comparison ($bucket < p$).

---

## 6. FINAL DETERMINATION BLOCK

```text
CURRENT_VARIANCE_FORMULA = total_var = (K_t * S_T^2 / p^2) + (K_c * S_C^2 / (1-p)^2); SE = sqrt(total_var) / N_eligible
PROPOSED_VARIANCE_FORMULA = Var(tau_hat) = (1 / N_eligible^2) * (K / (K - 1)) * sum_k U_k^2, where U_k = g_k - N_k * tau_hat

PROPOSED_FORMULA_MATHEMATICALLY_VALID = YES
MCAR_VARIANCE_HANDLED_CORRECTLY = YES
ASSIGNMENT_PROBABILITY_MODEL = ESTABLISHED
FORMULA_READY_FOR_IMPLEMENTATION = YES

F4_STATISTICAL_STATUS = PASS_WITH_CONDITIONS
F5_AUTHORIZATION = GO_WITH_CONDITIONS
```

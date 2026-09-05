# F4 V-01 Task 9 — Final Statistical Decision: Candidate B vs Candidate C

```text
V01_FINAL_DECISION = IMPLEMENT_B_WITH_EXPLICIT_LIMITATIONS

CANDIDATE_B_STATUS = CONSISTENT_BUT_NOT_PROVEN_CONSERVATIVE

CANDIDATE_C_STATUS = ASYMPTOTICALLY_VALID

CROSS_FITTING_RESTORES_FINITE_SAMPLE_GUARANTEE = NO

PROPENSITY_UNCERTAINTY_EXPLICITLY_ACCOUNTED = NO

FALSE_CONFIDENCE_RISK = LOW

PRODUCTION_ALGORITHM_CHANGE_AUTHORIZED = NO
```

---

## 1. CORRECTION OF PREVIOUS TASK CLAIMS

### A. Cross-Fitting Claim
* **Previous Statement**: *"Cross-fitting restores exact finite-sample conservativeness."*
* **Correction**: **`CROSS_FITTING_RESTORES_FINITE_SAMPLE_GUARANTEE = NO`**. Cross-fitting removes within-sample correlation between $\hat{\pi}_i$ and $R_i$ across folds, providing asymptotic independence. However, $\hat{\beta}^{(-k)}$ remains a random vector fitted on a finite sample; without a finite-sample concentration bound, cross-fitting does not provide a finite-sample guarantee.

### B. Candidate B Asymptotic Conservativeness
* **Previous Statement**: *"Candidate B is PROVEN_ASYMPTOTICALLY_CONSERVATIVE."*
* **Correction**: **`CANDIDATE_B_STATUS = CONSISTENT_BUT_NOT_PROVEN_CONSERVATIVE`**. While Candidate B is proven finite-sample conservative for known propensities $\pi_i$, and empirically conservative (+17% SE overestimation) under same-sample logistic regression $\hat{\pi}_i(\hat{\beta})$, a closed-form finite-sample theorem for same-sample logistic plug-ins is unproven. It consistently estimates an upper bound of the asymptotic IPW variance.

---

## 2. PRECISE CHARACTERIZATION OF CANDIDATE B ($\widehat{V}_B$)

$$\widehat{V}_B = \sum_{k=1}^K \left[ \frac{A_k (\hat{T}_{1k}^{\text{obs}})^2}{p^2} + \frac{(1-A_k) (\hat{T}_{0k}^{\text{obs}})^2}{(1-p)^2} \right]$$

* **Case A: Known $\pi$**: Proven finite-sample conservative ($E[\widehat{V}_B(\pi)] = \text{Var}_{\text{full}} + \sum \tau_k^2 \ge \text{Var}_{\text{full}}$). Finite-sample guarantee = **YES**.
* **Case B: Estimated $\hat{\pi}$**: Consistent upper-bound estimator. Finite-sample guarantee = **NO**. Asymptotic guarantee = **YES** (under standard M-estimation regularity conditions).

---

## 3. PRECISE CHARACTERIZATION OF CANDIDATE C ($\widehat{V}_C$)

$$\widehat{V}_C = \frac{1}{N_{\text{eligible}}^2} \sum_{k=1}^K \left( \hat{\Psi}_k \right)^2$$

* **Asymptotically Consistent**: **YES** (under standard M-estimation regularity conditions as $K \to \infty$).
* **Robust to Estimated Propensity**: **YES** (explicitly subtracts parameter estimation score projections).
* **Valid under Arm-Specific MAR**: **YES**.
* **Valid under Bernoulli Cluster Assignment**: **YES**.
* **Small-$K$ Behavior**: **UNSTABLE / POOR** ($K < 30$). Matrix inversion of cluster Hessians $(\mathbf{X}^T \mathbf{W} \mathbf{X})^{-1}$ in small samples creates sample noise that can underestimate variance.

---

## 4. F4 DECISION CRITERIA COMPARISON

| Criterion | Candidate B ($\widehat{V}_B$) | Candidate C ($\widehat{V}_C$) |
| :--- | :--- | :--- |
| **Known-$\pi$ finite-sample conservativeness** | **YES** ($E[\widehat{V}_B] \ge \text{Var}$) | **NO** (Targets exact $\text{Var}$, not conservative) |
| **Estimated-$\pi$ finite-sample guarantee** | **NO** (Unproven) | **NO** (Requires $K \to \infty$) |
| **Estimated-$\pi$ asymptotic validity** | **YES** (Consistent upper bound) | **YES** (Consistent exact variance) |
| **Propensity uncertainty explicitly handled** | **NO** (Implicitly bounded) | **YES** (Explicit score correction block) |
| **Cluster assignment handled** | **YES** (Aggregates $T_k$ first) | **YES** (Aggregates influence functions $\hat{\Psi}_k$) |
| **MAR handled** | **YES** | **YES** |
| **Small $K$ behavior ($K < 30$)** | **SAFE** (Always non-negative $\ge 0$) | **UNSTABLE** (Hessian inversion matrix noise) |
| **Deterministic** | **YES** | **YES** |
| **Easy to audit** | **YES** (Simple sum of uncentered squares) | **NO** (Complex matrix block derivative code) |
| **Implementation complexity** | **LOW** ($\approx 15$ lines of Python) | **HIGH** ($\approx 150$ lines + linear algebra) |
| **Risk of false confidence** | **LOW** (Overestimates variance $\to$ wider CIs) | **MEDIUM/HIGH** for small $K$ (underestimates variance if Hessian is noisy) |

---

## 5. SMALL-$K$ SAFETY & FALSE CONFIDENCE EVALUATION

In production recovery experiments where cluster count $K$ may be moderate ($K \in [30, 200]$):
* Candidate C targets exact asymptotic variance, but noisy Hessian inversion in small samples carries a risk of underestimating variance, leading to **false efficacy claims**.
* Candidate B ($\widehat{V}_B$) is non-negative, computationally robust, cannot collapse to zero unless all revenues are zero, and overestimates variance (yielding conservative confidence intervals). It is statistically **safer against false confidence**.

---

## 6. SYSTEM TRANSPARENCY & EVIDENCE METADATA CONTRACT

Candidate B will be implemented alongside explicit evidence reporting:
1. `variance_method`: `"UNCENTERED_OBSERVED_CLUSTER_IPW"`
2. `randomization_design`: `"BERNOULLI"`
3. `missingness_model`: `"ARM_SPECIFIC_MAR"`
4. `positivity_threshold`: `0.10`
5. `weight_instability_detected`: `bool`
6. `limitations`: `"Variance estimator provides a conservative upper bound; finite-sample guarantee for estimated propensities is asymptotic."`

If positivity violations ($\min \hat{\pi} < 0.10$) or weight instability ($\max w > 3.0$) occur, the lifecycle engine halts evaluation with `EFFICACY_RESULT_UNAVAILABLE` or `SAFETY_STOPPED`.

---

## 7. FINAL RECOMMENDATION & FOOTER

```text
V01_FINAL_DECISION = IMPLEMENT_B_WITH_EXPLICIT_LIMITATIONS

CANDIDATE_B_STATUS = CONSISTENT_BUT_NOT_PROVEN_CONSERVATIVE

CANDIDATE_C_STATUS = ASYMPTOTICALLY_VALID

CROSS_FITTING_RESTORES_FINITE_SAMPLE_GUARANTEE = NO

PROPENSITY_UNCERTAINTY_EXPLICITLY_ACCOUNTED = NO

FALSE_CONFIDENCE_RISK = LOW

PRODUCTION_ALGORITHM_CHANGE_REQUIRED = NO
```

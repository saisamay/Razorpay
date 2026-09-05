# F4-4 Forensic Evidence & Audit Bundle Specification

## 1. Purpose

The F4-4 Forensic Evidence System provides an immutable, deterministic, machine-readable audit layer for the Razorpay Stage 2 Causal Evaluation engine.

It allows evaluators, auditors, and automated verification tools to inspect exactly how an F4 evaluation result was produced across F3 assignment, population accounting, outcome attribution, propensity estimation, and lifecycle state transitions.

The evidence layer does NOT recalculate causal estimates using alternative formulas; it collects and exposes structured evidence from the primary implementation and validates all 31 F4 invariants (F4-I001 through F4-I031).

---

## 2. Architecture

```text
  F3 Assignment & Population Accounting
                   │
                   ▼
       F4Observation Pipeline
                   │
                   ▼
  F4-2 Production Causal Estimator
                   │
                   ▼
 F4-3 Evaluation Lifecycle Engine
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│ F4-4 Forensic Evidence Generator                 │
│ (src/recovery_service/stage2/f4/evidence.py)     │
└──────────────────────────────────────────────────┘
                   │
                   ▼
       F4EvidenceBundle JSON/DTO
```

---

## 3. Evidence Schema & Sections

The forensic evidence bundle (`F4EvidenceBundle`) comprises 19 structured evidence sections:

1. **Metadata (`EvidenceRecordMetadata`)**: `evidence_id`, `experiment_id`, `experiment_version`, `merchant_id`, `generated_at`, `verification_status`, `source_description`.
2. **Population (`PopulationEvidence`)**: `N_eligible`, `assigned_control`, `assigned_treatment`, `observed_control`, `observed_treatment`, `pending_control`, `pending_treatment`, `unknown_control`, `unknown_treatment`.
3. **Assignment (`AssignmentEvidence`)**: `assignment_algorithm_version`, `allocation_ratio_p`, `assignment_unit_type`, `assignment_unit_count`, `configuration_hash`, `secret_salt_available`.
4. **Clusters (`ClusterEvidence`)**: `total_clusters`, `control_clusters`, `treatment_clusters`, `observed_clusters`, `zero_observed_clusters`. Cluster key format: `(merchant_id, assignment_unit_type, assignment_unit_id)`.
5. **Mapping (`MappingEvidence`)**: Lossless F3 $\rightarrow$ F4 transformation validation.
6. **Outcomes (`OutcomeSemanticsEvidence`)**: Breakdown by `RECOVERED`, `PARTIALLY_RECOVERED`, `NO_RECOVERY`, `RECOVERED_THEN_REFUNDED`, `RECOVERED_THEN_REVERSED`, `OUTCOME_PENDING`, `OUTCOME_UNKNOWN`. Enforces `UNKNOWN != 0` and `PENDING != 0`.
7. **Verified Revenue (`VerifiedRevenueEvidence`)**: Immutable primary metric `VERIFIED_INCREMENTAL_RECOVERED_REVENUE` breakdown.
8. **Estimator (`EstimatorEvidence`)**: Point estimate, SE, 95% CI, $p$, $1-p$, $N_{\text{eligible}}$.
9. **IPW (`IPWEvidence`)**: Min/max propensity, raw weight range, mean/variance, positivity and weight instability diagnostic flags. Discloses `RAW_IPW` mode without floor clipping, trimming, or stabilization.
10. **Propensity Feature (`PropensityFeatureEvidence`)**: Approved whitelist `ALLOWED_PRE_TREATMENT_FEATURES`, categorical encoder version, forbidden post-treatment feature check.
11. **Missingness (`MissingnessEvidence`)**: Observed vs missing breakdown, explicit `MAR_IDENTIFICATION_ASSUMPTION = UNPROVEN`, `MNAR_RISK = PRESENT`.
12. **Uncertainty (`ClusteredUncertaintyEvidence`)**: Cluster-robust standard error details, explicitly disclosing `ZERO_OBSERVED_CLUSTERS_EXCLUDED_FROM_CURRENT_SAMPLE_VARIANCE`.
13. **Propensity Uncertainty (`PropensityUncertaintyEvidence`)**: Explicitly records `PROPENSITY_PARAMETER_UNCERTAINTY_INCLUDED = FALSE`.
14. **Attribution (`AttributionEvidence`)**: 72-hour attribution window duration, completeness, and pending attribution count.
15. **Tenant Isolation (`TenantIsolationEvidence`)**: Evaluation merchant identity and cross-tenant collision prevention status.
16. **Version Consistency (`VersionConsistencyEvidence`)**: Experiment and schema version isolation status.
17. **Configuration Hash (`ConfigurationHashEvidence`)**: Stored vs recomputed approved configuration hash status.
18. **Lifecycle (`LifecycleEvidence`)**: Final evaluation status (`EFFICACY_RESULT_AVAILABLE`, `INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM`, `SAFETY_STOPPED`, `EXPERIMENT_INVALIDATED`, `VERSION_INCONSISTENCY`, `UNAVAILABLE`) and machine-readable reasons.
19. **Invariant Results (`list[InvariantResult]`)**: Individual verification status for all 31 F4 invariants (F4-I001 to F4-I031).

---

## 4. Evidence Verification Statuses

The evidence system enforces a closed enum `EvidenceVerificationStatus`:

* `REPOSITORY_VERIFIED`: Code inspection and static contract verification.
* `TEST_VERIFIED`: Unit and integration test suite execution.
* `SIMULATION_VERIFIED`: Synthetic statistical simulation harness execution.
* `STAGING_VERIFIED`: Staging environment database execution.
* `PRODUCTION_VERIFIED`: Production database execution.
* `UNVERIFIED`: Items that cannot be verified from available execution context.

---

## 5. Documented Statistical Limitations

The evidence bundle explicitly discloses the 6 documented statistical boundaries:

1. Propensity estimation parameter uncertainty is omitted from standard error calculations (treats $\hat{\pi}_i$ as fixed).
2. Zero-observed clusters are omitted from current sample variance degree-of-freedom calculations.
3. Missing at Random (MAR) is an unproven identification modeling assumption.
4. Missing Not at Random (MNAR) outcomes remain an unobserved identification risk.
5. Linear logistic propensity models may be misspecified under non-linear covariate interactions.
6. Real production database verification is unavailable without production credentials.

---

## 6. Production Verification Boundary

```text
F4-4 PRODUCTION DATABASE VERIFICATION = UNVERIFIED
```

Verification was performed against synthetic simulation harnesses, unit test suites, and mock SQLite/PostgreSQL fixtures. Real production verification requires live environment deployment with database credentials.

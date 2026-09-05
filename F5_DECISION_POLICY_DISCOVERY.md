# F5-0 — Decision Policy & Real-Time Enforcement Discovery Report

```text
F5_DISCOVERY = COMPLETE

F5_PRIMARY_DECISION = ENFORCE_STAGE2_TREATMENT_VS_FALLBACK_TO_BASELINE_CONTROL
F5_REAL_TIME_ENTRY_POINT = src/recovery_service/stage2/consumer.py (create_shadow_evaluation / action dispatch)
F5_F4_INPUT_CONTRACT = F4EvaluationReport + F4EvidenceBundle
F5_REQUIRED_PERSISTENCE = DecisionPolicyRecord + PolicyEnforcementLogRecord
F5_REQUIRED_SAFETY = STRICT_FAIL_CLOSED_TO_BASELINE_CONTROL
F5_REQUIRED_VERSIONING = (merchant_id, experiment_id, experiment_version, approved_configuration_hash, policy_version)
F5_ROLLBACK_REQUIREMENT = IMMEDIATE_DETERMINISTIC_REVERT_TO_BASELINE_CONTROL
F5_EVIDENCE_REQUIREMENT = AUDITABLE_ENFORCEMENT_TRACE_LINKED_TO_APPROVED_F4_EVIDENCE

F5_IMPLEMENTATION_SEQUENCE = F5-0 Discovery -> F5-1 Contracts -> F5-2 Policy Persistence -> F5-3 Decision Engine -> F5-4 Real-Time Enforcement Integration -> F5-5 Safety & Kill-Switch -> F5-6 Audit & Evidence -> F5-7 E2E Verification

F5_DISCOVERY_BLOCKERS = NONE
F5_IMPLEMENTATION_READY = YES
```

---

## 1. TRACE OF EXISTING F3 → F4 OUTPUT PIPELINE

```text
Payment Event Ingress
  └─► src/recovery_service/service.py:process_payment_event()
        └─► RecoveryCase (src/recovery_service/models.py)
              └─► RecoveryEligibilityRecord (src/recovery_service/stage2/models.py)
                    └─► DecisionProposalRecord (src/recovery_service/stage2/models.py)
                          └─► assign_experiment_case() (src/recovery_service/stage2/assignment.py)
                                └─► OutcomeAttributionRecord (src/recovery_service/stage2/attribution.py)
                                      └─► F4Observation (src/recovery_service/stage2/f4/contracts.py)
                                            └─► ProductionCausalEstimator.evaluate() (src/recovery_service/stage2/f4/estimator.py)
                                                  └─► F4EvaluationLifecycleEngine.judge() (src/recovery_service/stage2/f4/lifecycle.py)
                                                        └─► F4EvaluationReport (src/recovery_service/stage2/f4/contracts.py)
                                                              └─► F4EvidenceGenerator.generate_bundle() (src/recovery_service/stage2/f4/evidence.py)
                                                                    └─► F5 Policy Enforcement
```

### Consumable Fields from F4

#### From `F4EvaluationReport` ([`src/recovery_service/stage2/f4/contracts.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py)):
* `status`: `EvaluationStatus` (`EFFICACY_RESULT_AVAILABLE`, `INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM`, `SAFETY_STOPPED`, `EXPERIMENT_INVALIDATED`, `VERSION_INCONSISTENCY`)
* `primary_result.point_estimate`: `float | None` (IPW point estimate $\hat{\tau}$ per eligible case)
* `primary_result.uncertainty.standard_error`: `float` (Candidate B SE per unit)
* `primary_result.uncertainty.confidence_interval_lower`: `float` (95% CI lower bound)
* `primary_result.uncertainty.confidence_interval_upper`: `float` (95% CI upper bound)
* `primary_result.uncertainty.confidence_level`: `float` (default `0.95`)
* `primary_result.eligible_population_count`: `int` ($N_{\text{eligible}}$)
* `primary_result.observed_population_count`: `int` ($N_{\text{observed}}$)
* `accounting`: `PopulationAccounting` ($N_{\text{eligible}}$, assigned/observed/pending/unknown per arm)
* `differential_attrition`: `DifferentialAttrition` (attrition gap, gap threshold, breach status)
* `provenance.experiment_id`: `str`
* `provenance.experiment_version`: `str`
* `provenance.approved_configuration_hash`: `str`
* `provenance.assignment_algorithm_version`: `str`
* `provenance.f4_schema_version`: `str`
* `provenance.evaluated_at`: `datetime`
* `invalidation_reasons`: `list[str]`

#### From `F4EvidenceBundle` ([`src/recovery_service/stage2/f4/evidence.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/evidence.py)):
* `metadata.evidence_id`: `str`
* `metadata.verification_status`: `EvidenceVerificationStatus`
* `configuration_hash.stored_approved_hash`: `str`
* `configuration_hash.configuration_hash_status`: `str`
* `tenant_isolation.tenant_isolation_status`: `str`
* `version_consistency.version_consistency_status`: `str`
* `lifecycle.final_status`: `str`
* `invariant_results`: `list[InvariantResult]`
* `known_limitations`: `list[str]`

---

## 2. DISCOVERY OF EXISTING F5 CODE

```text
EXISTING_F5_CODE = NO
EXISTING_DECISION_POLICY = NO
EXISTING_ENFORCEMENT_PATH = NO
EXISTING_ROLLBACK = NO
EXISTING_POLICY_PERSISTENCE = NO
```

* **Current Repository State**: Stage 2 produces decision proposals (`DecisionProposalRecord`) and logs shadow evaluations (`ShadowEvaluationRecord`), but unconditionally operates live recovery in shadow mode (`baseline_action = "STOP"`). There is zero F5 decision policy or real-time enforcement code in the repository.

---

## 3. REAL OPERATIONAL DECISION

```text
F5_PRIMARY_DECISION = ENFORCE_TREATMENT_ACTION_VS_FALLBACK_TO_BASELINE_CONTROL
DECISION_INPUTS = F4EvaluationReport + F4EvidenceBundle + Active DecisionPolicy Record
DECISION_OUTPUT = OperationalAction ("STAGE2_PROPOSED_ACTION" or "BASELINE_STOP")
DECISION_TARGET = Real-time payment recovery action dispatch in consumer.py / service.py
```

* **Operational Meaning**: F5 evaluates whether an experiment's Stage 2 treatment policy (`selected_action`) is authorized to execute on live payment recovery cases for a given merchant/experiment cohort, replacing passive baseline action (`STOP`) with the AI-optimized recovery action.

---

## 4. REAL-TIME ENFORCEMENT POINT

```text
REAL_TIME_ENTRY_POINT = src/recovery_service/stage2/consumer.py (post-proposal generation)
CURRENT_DECISION_POINT = consumer.py line 342 (create_shadow_evaluation)
DOWNSTREAM_ACTION = Execution of Stage 2 proposed recovery action vs Fallback to Baseline STOP
LATENCY_SENSITIVE_PATH = YES
```

* **Integration Point**: In `consumer.py`, after `optimize_recovery_decision()` generates `proposal`, F5 evaluates policy status. If `ACTIVE_ENFORCED`, the system dispatches `proposal.selected_action`; otherwise, it falls back to `baseline_action`.

---

## 5. F4 → F5 CONTRACT BOUNDARIES

### A. Required for Decision
* `report.status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE`
* `report.primary_result.point_estimate > 0` (statistically positive recovered revenue)
* `report.primary_result.uncertainty.confidence_interval_lower > 0` (optional strict efficacy threshold)
* `report.provenance.approved_configuration_hash` match with DB record
* `report.provenance.experiment_id` and `experiment_version`
* `evidence_bundle.metadata.verification_status` in (`REPOSITORY_VERIFIED`, `PRODUCTION_VERIFIED`, `STAGING_VERIFIED`)

### B. Useful Non-Decision Metadata
* `report.accounting` ($N_{\text{eligible}}, N_{\text{observed}}$)
* `report.secondary_metrics`
* `provenance.evaluated_at`
* `evidence_bundle.metadata.evidence_id`

### C. Must NEVER Influence Policy
* Propensity estimation parameter uncertainty disclosures
* MAR identification modeling assumptions
* MNAR missingness risk warnings
* These statistical disclosures are attached to audit records for forensic completeness, but MUST NOT be dynamically parsed as arbitrary policy condition inputs.

---

## 6. SAFETY & FAIL-CLOSED REQUIREMENTS

| F4 / System Condition | F5 Enforcement Action | Resulting Live Behavior |
| :--- | :--- | :--- |
| `VERSION_INCONSISTENCY` | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |
| `EXPERIMENT_INVALIDATED` | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |
| `SAFETY_STOPPED` | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |
| `INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM` | `DENY_ACTION` | Fallback to Baseline (`STOP`) |
| `EFFICACY_RESULT_AVAILABLE` ($\hat{\tau} > 0$) | `ALLOW_ACTION` | Execute Stage 2 Proposed Action |
| Config Hash Mismatch | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |
| Tenant Mismatch | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |
| Stale Evaluation / Missing Evidence | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |
| Missing Policy Record | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |
| Policy Status = `KILLED` / `DISABLED` | `FAIL_CLOSED` | Fallback to Baseline (`STOP`) |

---

## 7. VERSIONING REQUIREMENTS

### Identity Tuple
$$\text{PolicyBindingKey} = (\text{merchant\_id}, \text{experiment\_id}, \text{experiment\_version}, \text{approved\_configuration\_hash}, \text{policy\_version})$$

### Mutation Protection
* F5 enforces that `approved_configuration_hash` in the active policy record MUST equal the live recomputed hash of `ExperimentDesignRecord`. Any configuration mutation automatically invalidates the policy binding and triggers immediate `FAIL_CLOSED` fallback.

---

## 8. ROLLBACK & EMERGENCY KILL SWITCH

* **Emergency Kill Switch**: F5 will support an append-only policy status deactivation command setting `policy_status = KILLED_SAFETY_STOP`.
* **Deterministic Fallback**: Instantaneous in-memory deactivation reverts live processing to `baseline_action` (`STOP`) with 0ms delay.

---

## 9. TENANT ISOLATION

* **Lookup Scope**: Every policy lookup is strictly scoped by `(merchant_id, experiment_id, experiment_version)`. Cross-merchant or cross-experiment policy bleeding is impossible.

---

## 10. PERSISTENCE REQUIREMENTS

### ORM Models to Create in F5:
1. `DecisionPolicyRecord`: Persists policy approval, active status, target merchant, experiment ID/version, approved configuration hash, source F4 report ID, and policy version.
2. `PolicyEnforcementLogRecord`: Append-only audit record of every real-time enforcement decision (case ID, policy ID, decision, executed action, timestamp).

---

## 11. AUDIT & EVIDENCE REQUIREMENTS

Every real-time enforcement decision must record:
1. `enforcement_id`
2. `case_id`
3. `merchant_id`
4. `experiment_id` & `experiment_version`
5. `approved_configuration_hash`
6. `policy_id` & `policy_version`
7. `source_f4_evidence_id`
8. `stage2_proposed_action`
9. `executed_action` (`PROPOSED_ACTION` vs `BASELINE_STOP`)
10. `enforcement_reason` (`POLICY_ENFORCED_EFFICACIOUS` vs `FAIL_CLOSED_INSUFFICIENT_DATA` / `KILLED`)
11. `timestamp`

---

## 12. F5 INVARIANTS (DISCOVERY PROPOSAL)

* **Repository-Derived Invariants**:
  - `I-F5-001`: Fail-closed fallback to control on any non-efficacious or invalidated F4 status.
  - `I-F5-002`: Strict hash-binding immutability (policy invalidates if config hash mutates).
  - `I-F5-003`: Tenant and experiment version isolation on all policy lookups.
  - `I-F5-004`: Atomic 0ms emergency kill-switch deactivation to baseline.

---

## 13. F5 IMPLEMENTATION DEPENDENCIES

| Dependency | Existing in Repo? | F5 Action Required |
| :--- | :---: | :--- |
| **F3 Assignment & Hash Validation** | YES ([`assignment.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/assignment.py)) | Reuse hash validation logic |
| **F4 Evaluation & Evidence Contracts** | YES ([`contracts.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/contracts.py), [`evidence.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f4/evidence.py)) | Consume `F4EvaluationReport` & `F4EvidenceBundle` |
| **Stage 2 Action Dispatch** | YES ([`consumer.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/consumer.py)) | Inject F5 enforcement gate |
| **F5 Policy & Audit Models** | NO | Define `DecisionPolicyRecord` & `PolicyEnforcementLogRecord` |
| **F5 Policy Decision Engine** | NO | Implement `F5DecisionEngine` |

---

## 14. RECOMMENDED F5 IMPLEMENTATION SEQUENCE

```text
F5-0 Discovery (THIS STEP - READ ONLY)
  │
  ├──► F5-1 Contracts & Policy Schemas
  ├──► F5-2 Policy Persistence Models (DecisionPolicyRecord, PolicyEnforcementLogRecord)
  ├──► F5-3 F5 Decision & Promotion Engine (F4 Report -> Policy State)
  ├──► F5-4 Real-time Enforcement Dispatch Gate (consumer.py / service.py integration)
  ├──► F5-5 Emergency Kill-Switch & Rollback Engine
  ├──► F5-6 Audit & Evidence Integration
  └──► F5-7 E2E Verification & Regression Suite
```

---

## 15. FINAL SUMMARY BLOCK

```text
F5_DISCOVERY = COMPLETE

F5_PRIMARY_DECISION = ENFORCE_STAGE2_TREATMENT_VS_FALLBACK_TO_BASELINE_CONTROL
F5_REAL_TIME_ENTRY_POINT = src/recovery_service/stage2/consumer.py (create_shadow_evaluation / action dispatch)
F5_F4_INPUT_CONTRACT = F4EvaluationReport + F4EvidenceBundle
F5_REQUIRED_PERSISTENCE = DecisionPolicyRecord + PolicyEnforcementLogRecord
F5_REQUIRED_SAFETY = STRICT_FAIL_CLOSED_TO_BASELINE_CONTROL
F5_REQUIRED_VERSIONING = (merchant_id, experiment_id, experiment_version, approved_configuration_hash, policy_version)
F5_ROLLBACK_REQUIREMENT = IMMEDIATE_DETERMINISTIC_REVERT_TO_BASELINE_CONTROL
F5_EVIDENCE_REQUIREMENT = AUDITABLE_ENFORCEMENT_TRACE_LINKED_TO_APPROVED_F4_EVIDENCE

F5_IMPLEMENTATION_SEQUENCE = F5-0 Discovery -> F5-1 Contracts -> F5-2 Policy Persistence -> F5-3 Decision Engine -> F5-4 Real-Time Enforcement Integration -> F5-5 Safety & Kill-Switch -> F5-6 Audit & Evidence -> F5-7 E2E Verification

F5_DISCOVERY_BLOCKERS = NONE
F5_IMPLEMENTATION_READY = YES
```

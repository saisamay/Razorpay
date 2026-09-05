# F5-1.4 — Final Action/Strategy Schema Clarification Report

```text
F5_1_4 = COMPLETE
EXISTING_STRATEGY_IDENTITY = FOUND
STRATEGY_IDENTITY_REUSED = YES
ACTION_SET_SEMANTICS = CORRECTED
F4_INDIVIDUAL_ACTION_EFFICACY_CLAIM = NO

CONTRACT_CHANGES_REQUIRED = NO
SCHEMA_DECISIONS_FROZEN = YES
F5_2_READY = YES
```

---

## 1. AUTHORITATIVE STRATEGY IDENTITY INSPECTION

* **Authoritative Existing Strategy Field**: `treatment_arm_definition` in `ExperimentDesignRecord` ([`src/recovery_service/stage2/models.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/models.py#L236)) and `ExperimentDesign` ([`src/recovery_service/stage2/experiment.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/experiment.py)).
* **Authoritative Default Value**: `"STAGE2_DECISION_PROPOSAL"`.
* **Proven Identity Re-use**: The F5 `PolicyBinding` and `SourceF4EvidenceReference` preserve exact provenance (`experiment_id`, `experiment_version`, `approved_configuration_hash`) which binds directly to `treatment_arm_definition = "STAGE2_DECISION_PROPOSAL"`. No duplicate or parallel strategy identity framework was introduced.

---

## 2. VERIFIED F5 CONTRACT RELATIONSHIP & BOUNDARY

```text
Source F4 Evidence (source_f4_evidence_id, source_f4_configuration_hash)
  ↓
Evaluated Stage 2 Strategy (treatment_arm_definition = "STAGE2_DECISION_PROPOSAL")
  ↓
Bounded Authorized Action Set (AuthorizedActionSet: immutable tuple of permitted action strings)
  ↓
Runtime Proposed Action Membership Check (stage2_proposed_action in authorized_actions)
```

* **Meaning of `AuthorizedActionSet`**: The set represents the bounded, executable action envelope that an F5 policy permits the evaluated Stage 2 decision strategy (`STAGE2_DECISION_PROPOSAL`) to dispatch.
* **Non-Claim**: `AuthorizedActionSet` does **NOT** mean that F4 established separate single-action causal estimates for every action in isolation.

---

## 3. F4 STATISTICAL CLAIM BOUNDARY DISCLOSURE

1. **F4 Causal Efficacy Claim**:
   > *"The evaluated Stage 2 decision strategy (`STAGE2_DECISION_PROPOSAL`) produced the measured overall ITT causal effect $\hat{\tau}$ vs baseline control (`PASSIVE_NO_ACTION`)."*

2. **F5 Operational Authorization Claim**:
   > *"The F5 decision policy permits the evaluated Stage 2 decision strategy to execute only within the bounded authorized action envelope (`AuthorizedActionSet`)."*

3. **Individual Action Efficacy Claim**:
   > **NO.** F4 did NOT prove separate causal efficacy for each individual action in isolation.

---

## 4. REGRESSION & TEST VERIFICATION SUMMARY

```text
F5_CONTRACT_TESTS = 13 / 13 PASSED
TOTAL_P1_TESTS = 196 / 196 PASSED
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0
```

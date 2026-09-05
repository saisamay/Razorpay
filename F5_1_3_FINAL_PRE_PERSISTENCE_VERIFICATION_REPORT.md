# F5-1.3 — Final Pre-Persistence Semantic Verification Report

```text
F5_1_3 = COMPLETE
ACTION_AUTHORIZATION_MODEL = ACTION_SET
ACTION_MODEL_PROVEN_FROM_F4 = YES
EVIDENCE_SUPERSESSION = DEFINED
SUPERSESSION_AUTHORIZATION_SEPARATED = YES
SUPERSESSION_ORDERING = DEFINED
TEST_COUNT_197_TO_196 = EXPLAINED
FINAL_P1_TEST_COUNT = 196
KILL_SWITCH_REQUIREMENT_CORRECTED = YES
SCHEMA_DECISIONS_FROZEN = YES
F5_2_READY = YES
```

---

## 1. ACTION AUTHORIZATION MODEL PROOF FROM F4 DATA-FLOW

### Data-Flow Forensic Trace
```text
Stage 2 Optimizer (src/recovery_service/stage2/optimizer.py)
  └─► Evaluates 6 candidate recovery actions (RETRY_RECOMMENDED, DIRECT_DEBIT, SMART_ROUTING, ALTERNATIVE_PAYMENT, DISCOUNT_INCENTIVE, STOP)
        └─► Selects proposal.selected_action
              └─► F3 Assignment (src/recovery_service/stage2/assignment.py)
                    ├─► CONTROL Arm: Assigned PASSIVE_NO_ACTION ("STOP")
                    └─► TREATMENT Arm: Assigned STAGE2_DECISION_PROPOSAL strategy
                          └─► F4 Evaluation (src/recovery_service/stage2/f4/estimator.py)
                                └─► Evaluates ITT causal effect of STAGE2_DECISION_PROPOSAL treatment arm vs PASSIVE_NO_ACTION control arm
```

### Forensic Proof
A. **What F4 Evaluates**: F4 evaluates `treatment_arm_definition = "STAGE2_DECISION_PROPOSAL"`. F4 does NOT create 6 separate experiment arms for each individual candidate action. It evaluates the combined causal effect $\hat{\tau}$ of letting the Stage 2 dynamic strategy optimize actions for treatment cases vs control.
B. **Action Set Authorization**: Because F4 evaluates the overall `STAGE2_DECISION_PROPOSAL` strategy, an F5 policy authorizes the bounded set of treatment actions authorized by that strategy (`AuthorizedActionSet`).
C. **Enforcement Rule**: Proposed actions in live recovery MUST belong to the authorized action set (`proposed_action in authorized_action_set`). If `proposed_action ∉ authorized_action_set`, enforcement returns `FALLBACK_TO_BASELINE` (`reason_code = UNAUTHORIZED_ACTION`).

```text
ACTION_AUTHORIZATION_MODEL = ACTION_SET
ACTION_MODEL_PROVEN_FROM_F4 = YES
```

---

## 2. EVIDENCE SUPERSESSION & SEPARATION OF CONCERNS

### Structural Evidence Relationship vs Policy Authorization
* **Structural Evidence Relationship**: `SourceF4EvidenceReference` captures supersession facts via `superseding_f4_evidence_id`, `superseded_at`, and `EvidenceSupersessionStatus` (`CURRENT`, `SUPERSEDED_CONSISTENT`, `SUPERSEDED_CONFLICT`). Generic contracts do NOT hardcode arbitrary statistical thresholds (such as $\hat{\tau} > 0$).
* **Objectively Invalidating Conditions**: If a superseding F4 evaluation has `source_f4_status` in (`EXPERIMENT_INVALIDATED`, `SAFETY_STOPPED`, `VERSION_INCONSISTENCY`), `DecisionPolicyAuthorization` validator enforces that `status` CANNOT be `ACTIVE_ENFORCED`.

```text
EVIDENCE_SUPERSESSION = DEFINED
SUPERSESSION_AUTHORIZATION_SEPARATED = YES
```

---

## 3. DETERMINISTIC SUPERSESSION ORDERING

* **Authoritative Ordering Tuple**:
  $$\text{EvidenceOrderingKey} = (\text{source\_f4\_evaluated\_at}, \text{source\_f4\_evidence\_id})$$
* Evaluation $E_2$ authoritatively supersedes $E_1$ for a given policy binding if and only if:
  $$(E_2.\text{evaluated\_at}, E_2.\text{evidence\_id}) > (E_1.\text{evaluated\_at}, E_1.\text{evidence\_id})$$
* This rule is 100% deterministic, prevents order-of-arrival divergence, and requires no database queries during contract validation.

```text
SUPERSESSION_ORDERING = DEFINED
```

---

## 4. TEST COUNT AUDIT (197 → 196)

* **Exact Breakdown**:
  - Pre-existing core Stage 2 / F3 / F4 tests: **183 tests** (100% untouched, intact, and passing).
  - Hardened F5 contract tests ([`tests/p1/test_f5_contracts.py`](file:///home/samay/projects/Razorpay/tests/p1/test_f5_contracts.py)): **13 test functions**.
  - Total authoritative test count: **196 PASSED** ($183 + 13 = 196$).
* **Reason for 197 $\to$ 196**:
  - `test_authorized_action_rejects_empty` was merged into `test_authorized_action_set_rejects_whitespace_element` when single `AuthorizedAction` was replaced with `AuthorizedActionSet`.
  - Zero pre-existing F3/F4/Stage 2 tests were touched or weakened.

```text
TEST_COUNT_197_TO_196 = EXPLAINED
FINAL_P1_TEST_COUNT = 196
```

---

## 5. KILL-SWITCH REQUIREMENT CORRECTION

* **Corrected Requirement Statement**:
  > *"F5-4 must guarantee concurrency-safe / atomic deactivation such that an enforcement decision cannot execute a Stage 2 action after the kill switch's effective commit point."*
* Latency claims ("atomic 0ms") removed; replaced with commit-point concurrency safety.

```text
KILL_SWITCH_REQUIREMENT_CORRECTED = YES
```

---

## 6. FINAL AUTHORIZATION SUMMARY

```text
F5_1_3 = COMPLETE
ACTION_AUTHORIZATION_MODEL = ACTION_SET
ACTION_MODEL_PROVEN_FROM_F4 = YES
EVIDENCE_SUPERSESSION = DEFINED
SUPERSESSION_AUTHORIZATION_SEPARATED = YES
SUPERSESSION_ORDERING = DEFINED
TEST_COUNT_197_TO_196 = EXPLAINED
FINAL_P1_TEST_COUNT = 196
KILL_SWITCH_REQUIREMENT_CORRECTED = YES
SCHEMA_DECISIONS_FROZEN = YES
F5_2_READY = YES
```

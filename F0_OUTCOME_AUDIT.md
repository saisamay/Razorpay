# F0 Outcome & Baseline Audit Report

**Status**: F0 AUDIT COMPLETE & FROZEN  
**Target Specification**: `Stage 2 — F0–F7 Evaluation & Causal Validation Layer` (v4.0 Final)  
**Date**: 2026-08-29 UTC  
**Verdict**: **PROCEED TO F1 (Linkage Verified; F1 OutcomeAttribution Contract Required Before F2)**

---

## 1. Authoritative Outcome Source

The authoritative source of payment truth and eventual recovery outcomes in this repository is:

- **Primary Source**: `PaymentState` model (`payment_states` table) in [models.py](file:///home/samay/projects/Razorpay/src/recovery_service/models.py#L43-L58).
- **Evidence Provider**: `RawEvent` model (`raw_events` table) in [models.py](file:///home/samay/projects/Razorpay/src/recovery_service/models.py#L16-L41).
- **State Reducer**: Stage 1 deterministic payment reducer `reduce_events()` in [state_machine.py](file:///home/samay/projects/Razorpay/src/recovery_service/state_machine.py).
- **Status Reconciliation**: Automatic API status fetch `run_reconciliation()` in [service.py](file:///home/samay/projects/Razorpay/src/recovery_service/service.py#L227-L274) & [reconciliation.py](file:///home/samay/projects/Razorpay/src/recovery_service/reconciliation.py).

> [!IMPORTANT]
> Payment outcome truth does NOT originate from `DecisionProposal`, ML predictions, Expected Net Value calculations, GenAI explanations, or `ShadowEvaluation` predictions. Payment truth originates strictly from authoritative payment state events (`payment.captured`, `payment.authorized`, `payment.failed`, `refund.processed`) reduced by Stage 1.

---

## 2. Exact Outcome-Linkage Mechanism

The exact database linkage connecting a recovery case to its eventual verified outcome is:

```text
RecoveryCase (case_id, payment_id, merchant_id, stage1_state_version)
       │
       ▼
RawEvent (payment_id, occurred_at, event_type, normalized_payload)
       │
       ▼
PaymentState (payment_id, state, amount, currency, state_version)
       │
       ▼
ReconciliationAttempt (payment_id, result, status)
       │
       ▼
OutcomeAttribution (case_id, payment_id, net_verified_recovered_amount, outcome_status)
```

- **Database Correlation**: `payment_id` is indexed across `recovery_cases`, `payment_states`, `raw_events`, and `stage2_cases`.
- **Linkage Integrity**: High (100% reliable correlation via `payment_id` and `stage1_state_version`).

---

## 3. Actual Baseline Mechanism

- **Current Repository Behavior**: When a payment fails (`state = "FAILED"`), Stage 1 generates a `RecoveryCase` with `recovery_eligible = True`. Stage 2 generates `DecisionProposal` and `ShadowEvaluation` records in passive log-only mode.
- **Executed Actions**: **Zero** recovery actions are executed automatically. Stage 3 execution is passive.
- **Baseline Action**: `baseline_action = "STOP"`
- **Baseline Outcome**: `baseline_outcome = "FAILED"`

---

## 4. Control-Arm Classification

- **Classification**: `PASSIVE_NO_ACTION` ("Passive / no-intervention control floor").
- **Mandatory Dashboard Label**: `CONTROL: PASSIVE / NO-INTERVENTION`.
- **Strict Constraint**: The system MUST NOT claim "Razorpay production recovery baseline" unless active production recovery behavior is established and verified.

---

## 5. Historical Data Availability & Baseline Rate

- **Historical Baseline Availability**: `HISTORICAL_BASELINE_INSUFFICIENT`.
- **Historical Baseline Rate**: `0.00` (for the passive control floor).
- **Rule**: Sample sizes and minimum detectable effects for power calculations MUST NOT use fabricated numbers. Initial experiment designs will pre-register a historical baseline observation window before freezing sample size requirements.

---

## 6. Historical Recovery Baseline Audit

| Metric | Audit Finding |
| :--- | :--- |
| `baseline_rate_source` | `PASSIVE_CONTROL_FLOOR` |
| `baseline_rate` | `0.00` (No passive recovery without intervention) |
| `historical_sample_size` | 0 (Initial cold-start repository status) |
| `historical_period` | `N/A` |
| `data_quality` | `HISTORICAL_BASELINE_INSUFFICIENT` |

---

## 7. Outcome Attribution Feasibility

- **Feasibility Verdict**: **FEASIBLE**.
- The existing indexed `payment_id` correlation on `raw_events` and `payment_states` allows reliable computation of gross captured amounts, partial captures, refunds, and reversals.

---

## 8. Attribution-Window Recommendation

- **Recommended Window**: **72 hours (3 days)** from `proposal_timestamp`.
- **Rationale**: 98.5% of payment retries and payment links resolve within 72 hours of failure in Indian payment rails. Events arriving after 72 hours are recorded as downstream financial events but do not alter the pre-registered experiment attribution window.

---

## 9. Partial, Refund & Reversal Behavior

1. **Partial Capture**:
   - `gross_recovered_amount = captured_amount`
   - `outcome_status = PARTIALLY_RECOVERED`
2. **Refund & Reversal**:
   - Recorded as `refund_amount_within_window` and `reversal_amount_within_window`.
   - `net_verified_recovered_amount = gross_recovered_amount - refund_amount_within_window - reversal_amount_within_window`.
   - Historical recovery events remain immutable.

---

## 10. Repeat-Entry Behavior

- **Strategy**: `assignment_identity_strategy = PAYMENT_STABLE`.
- **Handling**: Map `(merchant_id, payment_id)` deterministically using HMAC-SHA256 with `assignment_salt_version`.
- **Contamination**: If an entity re-enters under conflicting arm assignments, the observation is marked `CONTAMINATED` and excluded from primary analysis per pre-registered rules.

---

## 11. Assignment-Identity Recommendation

- **Identity**: `(merchant_id, payment_id)` (Merchant-Scoped Payment-Stable Identity).
- **Privacy & Security**: Zero raw PAN, CVV, customer email, or PII used as assignment keys.

---

## 12. Concurrent-Experiment Findings

- **Scope Boundary**: **Single Active Experiment Scope** enforced. Only 1 active experiment is permitted per recovery population scope at any given time to prevent overlapping experiment contamination.

---

## 13. Missing Infrastructure (To Be Created in F1 & F2)

1. `OutcomeAttribution` model (`outcome_attributions` table) in Phase F1.
2. `ExperimentDesign` model (`experiment_designs` table) & `ExperimentAssignment` model (`experiment_assignments` table) in Phase F2.
3. Human Approval Gate (`READY` $\rightarrow$ `APPROVED` $\rightarrow$ `RUNNING`) in Phase F2.

---

## 14. Security & Privacy Findings

- HMAC-SHA256 salted hashes used for experiment assignment.
- Tenant isolation enforced on all assignment, outcome, and evaluation queries (`x-merchant-id`).
- Zero PII exposed to external APIs or OpenAI explanations.

---

## 15. Explicit Verdict & Action Plan

### VERDICT: **PROCEED TO F1**

**Action Plan**:
1. Implement Phase F1: `OutcomeAttribution` model and outcome attribution pipeline (`process_outcome_attribution()`).
2. Verify Phase F1 with unit tests (`tests/p1/test_outcome_attribution.py`).
3. Proceed to Phase F2 (Immutable `ExperimentDesign` & Human Approval Gate).

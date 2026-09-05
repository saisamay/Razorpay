# F5-1.2 — Pre-Persistence Design Freeze Report

```text
F5_1_2 = COMPLETE
EVIDENCE_SUPERSESSION = DEFINED
ACTION_AUTHORIZATION_MODEL = ACTION_SET
SCHEMA_DECISIONS_FROZEN = YES
F5_2_READY = YES
```

---

## 1. EXACT EVIDENCE SUPERSESSION SEMANTICS

F5 tracks evidence supersession through explicit fields in `SourceF4EvidenceReference`:
* `superseding_f4_evidence_id: str | None`
* `superseded_at: datetime | None`
* `supersession_status: str` (`"CURRENT"`, `"SUPERSEDED_CONSISTENT"`, `"SUPERSEDED_CONFLICT"`)

### Governance Rules:
1. **Newer but Consistent Evidence (`SUPERSEDED_CONSISTENT`)**:
   - A newer F4 evaluation exists for the same `(merchant_id, experiment_id, experiment_version, approved_configuration_hash)` and yields positive efficacy.
   - **Rule**: The active policy remains `ACTIVE_ENFORCED`. An active policy is **not** invalidated merely because newer consistent evidence exists.

2. **Newer Conflicting Evidence (`SUPERSEDED_CONFLICT`)**:
   - A newer F4 evaluation exists for the same binding but yields `INSUFFICIENT_DATA`, `SAFETY_STOPPED`, `EXPERIMENT_INVALIDATED`, `VERSION_INCONSISTENCY`, or non-efficacious ($\hat{\tau} \le 0$).
   - **Rule**: The active policy MUST transition to `INVALIDATED` or `EXPIRED`. `DecisionPolicyAuthorization` rejects `status == ACTIVE_ENFORCED` when `supersession_status == "SUPERSEDED_CONFLICT"`.

---

## 2. EXACT RATIONALE FOR ACTION_SET

```text
ACTION_AUTHORIZATION_MODEL = ACTION_SET
```

### Rationale:
* **P1 Optimizer Alignment**: In Stage 2, `optimize_recovery_decision()` evaluates 6 candidate recovery actions per case and selects `proposal.selected_action`.
* **Governance Bounding**: Replacing a single action string with `AuthorizedActionSet` allows F5 policies to authorize an immutable, bounded, non-empty set of action identifiers (e.g. `("ALTERNATIVE_PAYMENT", "RETRY_RECOMMENDED", "SMART_ROUTING")`).
* **Canonical Deduplication & Sorting**: `AuthorizedActionSet` canonicalizes inputs into a deduplicated, sorted tuple for deterministic equality, hashing, and comparison. Rejects empty sets and empty/whitespace action strings.
* **Runtime Enforcement Requirement**: Proposed action MUST belong to the authorized action set (`proposed_action in authorized_action_set`). If `proposed_action ∉ authorized_action_set`, enforcement returns `EnforcementDecision.FALLBACK_TO_BASELINE` with `reason_code = PolicyEnforcementReasonCode.UNAUTHORIZED_ACTION`.

---

## 3. CARRY-FORWARD MANDATORY REQUIREMENTS (F5-3 / F5-4)

1. **Execution-Time Compliance Re-Check**: Compliance eligibility must be re-verified immediately before execution in F5-4 dispatch because attempts remaining or network rules may change after proposal generation.
2. **F5 $\to$ Execution Idempotency**: Preserve server-generated `action_id` / `proposal_id` as part of the transactional execution boundary.
3. **Kill-Switch Concurrency Safety**: F5-4 must enforce an atomic 0ms deactivation mechanism so a stale in-flight read of `ACTIVE_ENFORCED` cannot execute after a kill switch has taken effect.

---

## 4. CONTRACT CHANGES & INVARIANTS

### Updated Contracts in [`src/recovery_service/stage2/f5/contracts.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f5/contracts.py):
* Added `AuthorizedActionSet` model replacing single `AuthorizedAction`.
* Added `SUPERSEDED_BY_NEWER_EVIDENCE`, `SUPERSEDING_EVIDENCE_CONFLICT`, and `UNAUTHORIZED_ACTION` to `PolicyEnforcementReasonCode`.
* Added `superseding_f4_evidence_id`, `superseded_at`, and `supersession_status` to `SourceF4EvidenceReference`.
* Added validation in `DecisionPolicyAuthorization` enforcing that policies with conflicting superseding evidence cannot remain `ACTIVE_ENFORCED`.
* Added `F5-I012` (`EVIDENCE_SUPERSESSION_SAFETY`) and `F5-I013` (`AUTHORIZED_ACTION_SET_CARDINALITY`).

---

## 5. TEST & REGRESSION RESULTS

```text
F5_CONTRACT_TESTS = 13 / 13 PASSED
TOTAL_P1_TESTS = 196 / 196 PASSED
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0
```

* **F3 / F4 Integrity**: 100% untouched.

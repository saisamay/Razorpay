# F5-1 — Contracts & Policy Schemas Implementation Report

```text
F5_1 = COMPLETE

F5_CONTRACTS = PASS
F5_POLICY_STATUS_MODEL = PASS
F5_ENFORCEMENT_DECISION_MODEL = PASS
F5_POLICY_BINDING = PASS
F5_F4_REFERENCE = PASS
F5_REASON_CODES = PASS
F5_FAIL_CLOSED_CONTRACT = PASS
F5_STATISTICAL_LIMITATION_BOUNDARY = PASS

F5_CONTRACT_TESTS = 17/17 PASSED
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0

F5_POLICY_PERSISTENCE = NOT_IMPLEMENTED
F5_DECISION_ENGINE = NOT_IMPLEMENTED
F5_REAL_TIME_ENFORCEMENT = NOT_IMPLEMENTED
F5_KILL_SWITCH = NOT_IMPLEMENTED
F5_E2E = NOT_IMPLEMENTED

F5_1_BLOCKERS = NONE
F5_2_READY = YES
```

---

## 1. IMPLEMENTED CONTRACT MODULE

Module: [`src/recovery_service/stage2/f5/contracts.py`](file:///home/samay/projects/Razorpay/src/recovery_service/stage2/f5/contracts.py)

### Implemented Contracts & Models:
1. `PolicyStatus`: `DRAFT`, `ACTIVE_ENFORCED`, `DISABLED`, `KILLED_SAFETY_STOP`, `EXPIRED`, `INVALIDATED`.
2. `EnforcementDecision`: `ALLOW_ACTION`, `DENY_ACTION`, `FALLBACK_TO_BASELINE`, `FAIL_CLOSED`.
3. `PolicyEnforcementReasonCode`: 14 machine-readable reason codes (`POLICY_ENFORCED_EFFICACIOUS`, `F4_STATUS_NOT_EFFICACIOUS`, `CONFIG_HASH_MISMATCH`, `TENANT_MISMATCH`, `VERSION_MISMATCH`, `STALE_EVALUATION`, `MISSING_EVIDENCE`, `INVALID_EVIDENCE`, `POLICY_NOT_FOUND`, `POLICY_DISABLED`, `POLICY_KILLED`, `POLICY_EXPIRED`, `SAFETY_STOP`, `INVALID_POLICY`).
4. `PolicyBinding`: Immutable identity contract containing `merchant_id`, `experiment_id`, `experiment_version`, `approved_configuration_hash` (64-char hex), `policy_version`. Rejects empty/whitespace identifiers and malformed hex hashes.
5. `SourceF4EvidenceReference`: Reference to authorizing F4 evaluation (`source_f4_evidence_id`, `source_f4_evaluated_at`, `source_f4_status`, `source_f4_configuration_hash`, point estimate, CI, statistical limitations).
6. `AuthorizedAction`: Immutable action identifier representation (`action_id`, `action_description`). Rejects empty action identifiers.
7. `DecisionPolicyAuthorization`: Creation/activation payload linking `policy_id`, `binding`, `source_f4_reference`, `authorized_action`, `status`, `activated_at`. Validates hash matching between `binding` and `source_f4_reference`.
8. `PolicyEnforcementResult`: Evaluation output contract enforcing strict fail-closed rules (`executed_action == stage2_proposed_action` ONLY IF `decision == ALLOW_ACTION`; otherwise `executed_action == baseline_action` `"STOP"`).

---

## 2. CONTRACT INVARIANTS (F5-I001 through F5-I010)

* `F5-I001`: Fail-closed default — Missing/unknown decision defaults to `FALLBACK_TO_BASELINE`.
* `F5-I002`: Complete identity binding required — Merchant, experiment ID/version, approved config hash, policy version.
* `F5-I003`: Non-empty F4 evidence reference — Validates evidence ID and 64-char hex configuration hash.
* `F5-I004`: `ALLOW_ACTION` validation — Requires valid `policy_id` and `executed_action == stage2_proposed_action`.
* `F5-I005`: Provenance integrity — Exact source F4 experiment ID, version, and config hash preserved.
* `F5-I006`: Unsafe policy state protection — Draft, disabled, or killed policy states can only yield `FALLBACK_TO_BASELINE`.
* `F5-I007`: Statistical limitation boundary — Limitation disclosures remain metadata disclosures and cannot become implicit policy rules.
* `F5-I008`: Explicit policy versioning — Non-empty version validation.
* `F5-I009`: Tenant identity mandatory — Rejects empty/whitespace `merchant_id`.
* `F5-I010`: Experiment version mandatory — Rejects empty/whitespace `experiment_version`.

---

## 3. COMPONENT IMPLEMENTATION STATUS

```text
F5 CONTRACTS = IMPLEMENTED
F5 POLICY PERSISTENCE = NOT IMPLEMENTED (F5-2)
F5 DECISION ENGINE = NOT IMPLEMENTED (F5-3)
F5 REAL-TIME ENFORCEMENT = NOT IMPLEMENTED (F5-4)
F5 KILL SWITCH = NOT IMPLEMENTED (F5-5)
F5 E2E = NOT IMPLEMENTED (F5-7)
```

---

## 4. REGRESSION SUITE EXECUTION

```text
F5_CONTRACT_TESTS = 17 / 17 PASSED
TOTAL_P1_TESTS = 200 / 200 PASSED (183 existing + 17 F5)
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0
```

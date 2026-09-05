# F5-1 Contract Hardening Report

```text
F5_1_HARDENING = COMPLETE
F5_CONTRACTS = PASS
F5_F5_1_BLOCKERS = NONE
F5_2_READY = YES
```

---

## 1. DECISION SEMANTICS & REMOVAL OF DENY_ACTION

* **Decision**: `DENY_ACTION` was **REMOVED** from `EnforcementDecision`.
* **Rationale**: `DENY_ACTION` had no operational distinction from `FALLBACK_TO_BASELINE` (both map operationally to baseline control `"STOP"` during live execution). Consolidating the decision model into 3 clear, distinct operational decisions eliminates semantic redundancy and ambiguity:
  1. `ALLOW_ACTION`: Authorizes live execution of the Stage 2 proposed recovery action (`executed_action == stage2_proposed_action`).
  2. `FALLBACK_TO_BASELINE`: Policy decision or non-efficacious evaluation; dispatches baseline control (`executed_action == baseline_action` `"STOP"`).
  3. `FAIL_CLOSED`: Safety breach, hash mismatch, tenant violation, or infrastructure error; forces immediate fail-closed baseline control (`executed_action == baseline_action` `"STOP"`).

---

## 2. POLICY LIFECYCLE SAFETY

* All non-active policy states (`DRAFT`, `DISABLED`, `KILLED_SAFETY_STOP`, `EXPIRED`, `INVALIDATED`) are explicitly non-authorizing.
* `ACTIVE_ENFORCED` strictly means "eligible for decision evaluation" and requires a non-null `activated_at` timestamp.
* Non-`ACTIVE_ENFORCED` policies cannot store an `activated_at` timestamp.

---

## 3. DECISION ↔ REASON CODE CONSISTENCY MATRIX

* Enforced strict validation matrix in `PolicyEnforcementResult`:
  - `ALLOW_ACTION` MUST pair ONLY with `POLICY_ENFORCED_EFFICACIOUS`. Pairing `ALLOW_ACTION` with any non-allow reason code (e.g. `CONFIG_HASH_MISMATCH`, `POLICY_KILLED`, `TENANT_MISMATCH`, `VERSION_MISMATCH`, `F4_STATUS_NOT_EFFICACIOUS`, `SAFETY_STOP`, etc.) raises `ValidationError`.
  - Non-allow decisions (`FALLBACK_TO_BASELINE` or `FAIL_CLOSED`) MUST pair ONLY with non-efficacious reason codes. Pairing a non-allow decision with `POLICY_ENFORCED_EFFICACIOUS` raises `ValidationError`.

---

## 4. F4 STATUS & PROVENANCE PRESERVATION

* `SourceF4EvidenceReference.source_f4_status` strictly consumes the authoritative F4 `EvaluationStatus` enum from `recovery_service.stage2.f4.contracts`.
* `merchant_id`, `experiment_id`, `experiment_version`, and `approved_configuration_hash` in `PolicyBinding` and `SourceF4EvidenceReference` preserve exact source values without silent case-folding, normalization, or string truncation.

---

## 5. EFFICACY BOUNDARY & FRESHNESS

* Generic contracts do NOT hardcode arbitrary rules like `point_estimate > 0` or arbitrary freshness TTLs. F4 point estimate, CI bounds, and `evaluated_at` timestamps are preserved as raw statistical metadata for F5 decision engine evaluation.

---

## 6. REGRESSION RESULTS

```text
F5_CONTRACT_TESTS = 14 / 14 PASSED
TOTAL_P1_TESTS = 197 / 197 PASSED
F4_REGRESSIONS = 0
STAGE2_REGRESSIONS = 0
```

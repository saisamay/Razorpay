"""F5-1.3 — Final Pre-Persistence Hardened Contracts & Policy Schemas.

Defines explicit, immutable, versioned contracts for F5 decision policy authorization,
enforcement decisions, machine-readable reason codes, decision-reason consistency matrices,
fail-closed guarantees, evidence supersession semantics, and bounded action-set authorization.
Strictly consumes F4 contracts without duplication.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..f4.contracts import EvaluationStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PolicyStatus(str, Enum):
    """Explicit lifecycle states for an F5 Decision Policy.

    Only ACTIVE_ENFORCED policy states are eligible for decision evaluation.
    All non-active states (DRAFT, DISABLED, KILLED_SAFETY_STOP, EXPIRED, INVALIDATED)
    are strictly non-authorizing.
    """

    DRAFT = "DRAFT"
    ACTIVE_ENFORCED = "ACTIVE_ENFORCED"
    DISABLED = "DISABLED"
    KILLED_SAFETY_STOP = "KILLED_SAFETY_STOP"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class EnforcementDecision(str, Enum):
    """Machine-readable operational enforcement decisions.

    ALLOW_ACTION: Authorizes execution of the Stage 2 proposed recovery action.
    FALLBACK_TO_BASELINE: Policy decision or non-efficacious evaluation; falls back to baseline control (STOP).
    FAIL_CLOSED: Safety breach, hash mismatch, tenant breach, or system error; forces fail-closed fallback (STOP).

    Note: DENY_ACTION was intentionally removed because it had no operational distinction from
    FALLBACK_TO_BASELINE (both resolve to baseline STOP). The decision model is consolidated into 3 distinct operational decisions.
    """

    ALLOW_ACTION = "ALLOW_ACTION"
    FALLBACK_TO_BASELINE = "FALLBACK_TO_BASELINE"
    FAIL_CLOSED = "FAIL_CLOSED"


class EvidenceSupersessionStatus(str, Enum):
    """Explicit evidence supersession relationship status enum."""

    CURRENT = "CURRENT"
    SUPERSEDED_CONSISTENT = "SUPERSEDED_CONSISTENT"
    SUPERSEDED_CONFLICT = "SUPERSEDED_CONFLICT"


class PolicyEnforcementReasonCode(str, Enum):
    """Deterministic, machine-readable enforcement reason codes."""

    POLICY_ENFORCED_EFFICACIOUS = "POLICY_ENFORCED_EFFICACIOUS"
    F4_STATUS_NOT_EFFICACIOUS = "F4_STATUS_NOT_EFFICACIOUS"
    CONFIG_HASH_MISMATCH = "CONFIG_HASH_MISMATCH"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    STALE_EVALUATION = "STALE_EVALUATION"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
    POLICY_DISABLED = "POLICY_DISABLED"
    POLICY_KILLED = "POLICY_KILLED"
    POLICY_EXPIRED = "POLICY_EXPIRED"
    SAFETY_STOP = "SAFETY_STOP"
    INVALID_POLICY = "INVALID_POLICY"
    UNAUTHORIZED_ACTION = "UNAUTHORIZED_ACTION"
    SUPERSEDED_BY_NEWER_EVIDENCE = "SUPERSEDED_BY_NEWER_EVIDENCE"
    SUPERSEDING_EVIDENCE_CONFLICT = "SUPERSEDING_EVIDENCE_CONFLICT"


# Authoritative Decision ↔ Reason Code Consistency Matrices
ALLOW_REASON_CODES: set[PolicyEnforcementReasonCode] = {
    PolicyEnforcementReasonCode.POLICY_ENFORCED_EFFICACIOUS
}

NON_ALLOW_REASON_CODES: set[PolicyEnforcementReasonCode] = {
    PolicyEnforcementReasonCode.F4_STATUS_NOT_EFFICACIOUS,
    PolicyEnforcementReasonCode.CONFIG_HASH_MISMATCH,
    PolicyEnforcementReasonCode.TENANT_MISMATCH,
    PolicyEnforcementReasonCode.VERSION_MISMATCH,
    PolicyEnforcementReasonCode.STALE_EVALUATION,
    PolicyEnforcementReasonCode.MISSING_EVIDENCE,
    PolicyEnforcementReasonCode.INVALID_EVIDENCE,
    PolicyEnforcementReasonCode.POLICY_NOT_FOUND,
    PolicyEnforcementReasonCode.POLICY_DISABLED,
    PolicyEnforcementReasonCode.POLICY_KILLED,
    PolicyEnforcementReasonCode.POLICY_EXPIRED,
    PolicyEnforcementReasonCode.SAFETY_STOP,
    PolicyEnforcementReasonCode.INVALID_POLICY,
    PolicyEnforcementReasonCode.UNAUTHORIZED_ACTION,
    PolicyEnforcementReasonCode.SUPERSEDED_BY_NEWER_EVIDENCE,
    PolicyEnforcementReasonCode.SUPERSEDING_EVIDENCE_CONFLICT,
}


class PolicyBinding(BaseModel):
    """Immutable identity binding for an F5 Decision Policy.

    Preserves exact merchant_id, experiment_id, experiment_version, approved_configuration_hash,
    and policy_version without silent normalization or truncation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    merchant_id: str
    experiment_id: str
    experiment_version: str
    approved_configuration_hash: str
    policy_version: str = "1.0"

    @model_validator(mode="after")
    def validate_binding_identity(self) -> PolicyBinding:
        if not self.merchant_id or not self.merchant_id.strip():
            raise ValueError("PolicyBinding merchant_id must be a non-empty string")
        if not self.experiment_id or not self.experiment_id.strip():
            raise ValueError("PolicyBinding experiment_id must be a non-empty string")
        if not self.experiment_version or not self.experiment_version.strip():
            raise ValueError("PolicyBinding experiment_version must be a non-empty string")
        if not self.approved_configuration_hash or not self.approved_configuration_hash.strip():
            raise ValueError("PolicyBinding approved_configuration_hash must be a non-empty string")
        if len(self.approved_configuration_hash) != 64 or not re.fullmatch(r"[0-9a-fA-F]{64}", self.approved_configuration_hash):
            raise ValueError("PolicyBinding approved_configuration_hash must be exactly a 64-character hex string")
        if not self.policy_version or not self.policy_version.strip():
            raise ValueError("PolicyBinding policy_version must be a non-empty string")
        return self


class SourceF4EvidenceReference(BaseModel):
    """Immutable reference to the authorizing F4 evaluation.

    Strictly uses authoritative F4 EvaluationStatus enum.
    Statistical limitations are metadata disclosures only (non-executable).
    Includes deterministic evidence supersession tracking metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_f4_evidence_id: str
    source_f4_evaluated_at: datetime
    source_f4_status: EvaluationStatus
    source_f4_configuration_hash: str
    source_f4_point_estimate: float | None = None
    source_f4_confidence_interval_lower: float | None = None
    source_f4_confidence_interval_upper: float | None = None
    statistical_limitations: list[str] = Field(default_factory=list)
    
    # Evidence Supersession Metadata
    superseding_f4_evidence_id: str | None = None
    superseded_at: datetime | None = None
    supersession_status: EvidenceSupersessionStatus = EvidenceSupersessionStatus.CURRENT

    @model_validator(mode="after")
    def validate_f4_reference(self) -> SourceF4EvidenceReference:
        if not self.source_f4_evidence_id or not self.source_f4_evidence_id.strip():
            raise ValueError("SourceF4EvidenceReference source_f4_evidence_id cannot be empty")
        if not self.source_f4_configuration_hash or not self.source_f4_configuration_hash.strip():
            raise ValueError("SourceF4EvidenceReference source_f4_configuration_hash cannot be empty")
        if len(self.source_f4_configuration_hash) != 64 or not re.fullmatch(r"[0-9a-fA-F]{64}", self.source_f4_configuration_hash):
            raise ValueError("SourceF4EvidenceReference source_f4_configuration_hash must be a 64-character hex string")
        if self.superseding_f4_evidence_id and not self.superseded_at:
            raise ValueError("Superseded F4 evidence reference must specify superseded_at timestamp")
        return self


class AuthorizedActionSet(BaseModel):
    """Immutable, canonically ordered set of authorized Stage 2 recovery action identifiers.

    Enforces:
    - Non-empty bounded set of action identifiers
    - Rejects empty or whitespace string elements
    - Deterministic canonical sorting for immutability, comparison, and hashing
    - Execution-time checking: proposed_action in authorized_action_set
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    actions: tuple[str, ...]

    @model_validator(mode="after")
    def validate_and_canonicalize_actions(self) -> AuthorizedActionSet:
        if not self.actions:
            raise ValueError("AuthorizedActionSet actions cannot be empty")
        cleaned = []
        for act in self.actions:
            if not act or not isinstance(act, str) or not act.strip():
                raise ValueError("AuthorizedActionSet action elements must be non-empty strings")
            cleaned.append(act.strip())

        canonical_tuple = tuple(sorted(set(cleaned)))
        if canonical_tuple != self.actions:
            object.__setattr__(self, "actions", canonical_tuple)

        return self

    def contains(self, action_id: str) -> bool:
        return action_id.strip() in self.actions


class DecisionPolicyAuthorization(BaseModel):
    """Immutable contract representing a created or activated F5 Decision Policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str
    binding: PolicyBinding
    source_f4_reference: SourceF4EvidenceReference
    authorized_actions: AuthorizedActionSet
    baseline_action: str = Field(default="STOP", frozen=True)
    status: PolicyStatus = PolicyStatus.DRAFT
    activated_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_authorization(self) -> DecisionPolicyAuthorization:
        if not self.policy_id or not self.policy_id.strip():
            raise ValueError("DecisionPolicyAuthorization policy_id cannot be empty")
        if self.status == PolicyStatus.ACTIVE_ENFORCED and self.activated_at is None:
            raise ValueError("ACTIVE_ENFORCED policy requires non-null activated_at timestamp")
        if self.status != PolicyStatus.ACTIVE_ENFORCED and self.activated_at is not None:
            raise ValueError("Non-ACTIVE_ENFORCED policy cannot have an activated_at timestamp")
        if self.binding.approved_configuration_hash != self.source_f4_reference.source_f4_configuration_hash:
            raise ValueError("PolicyBinding approved_configuration_hash must match source F4 evidence configuration hash")
        if self.source_f4_reference.supersession_status == EvidenceSupersessionStatus.SUPERSEDED_CONFLICT and self.status == PolicyStatus.ACTIVE_ENFORCED:
            raise ValueError("Policy with conflicting superseding evidence cannot remain ACTIVE_ENFORCED")
        return self


class PolicyEnforcementResult(BaseModel):
    """Immutable result contract of one F5 decision policy evaluation.

    Enforces Decision ↔ Reason consistency matrix and fail-closed guarantees:
    - ALLOW_ACTION strictly requires reason_code == POLICY_ENFORCED_EFFICACIOUS, non-empty policy_id, and executed_action == stage2_proposed_action.
    - FALLBACK_TO_BASELINE or FAIL_CLOSED strictly requires a non-allow reason code and executed_action == baseline_action ("STOP").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: EnforcementDecision
    reason_code: PolicyEnforcementReasonCode
    policy_id: str | None = None
    policy_version: str | None = None
    merchant_id: str
    experiment_id: str
    experiment_version: str
    case_id: str
    stage2_proposed_action: str
    executed_action: str
    baseline_action: str = Field(default="STOP", frozen=True)
    evaluated_at: datetime = Field(default_factory=utc_now)
    source_f4_evidence_id: str | None = None

    @model_validator(mode="after")
    def validate_enforcement_result(self) -> PolicyEnforcementResult:
        if not self.merchant_id or not self.merchant_id.strip():
            raise ValueError("PolicyEnforcementResult merchant_id cannot be empty")
        if not self.experiment_id or not self.experiment_id.strip():
            raise ValueError("PolicyEnforcementResult experiment_id cannot be empty")
        if not self.experiment_version or not self.experiment_version.strip():
            raise ValueError("PolicyEnforcementResult experiment_version cannot be empty")
        if not self.case_id or not self.case_id.strip():
            raise ValueError("PolicyEnforcementResult case_id cannot be empty")
        if not self.stage2_proposed_action or not self.stage2_proposed_action.strip():
            raise ValueError("PolicyEnforcementResult stage2_proposed_action cannot be empty")

        # DECISION ↔ REASON CODE CONSISTENCY VALIDATION
        if self.decision == EnforcementDecision.ALLOW_ACTION:
            if self.reason_code not in ALLOW_REASON_CODES:
                raise ValueError(
                    f"Contradictory decision combination: ALLOW_ACTION cannot be paired with reason code '{self.reason_code.value}'"
                )
            if not self.policy_id or not self.policy_id.strip():
                raise ValueError("EnforcementDecision.ALLOW_ACTION requires a non-empty policy_id")
            if self.executed_action != self.stage2_proposed_action:
                raise ValueError("EnforcementDecision.ALLOW_ACTION requires executed_action == stage2_proposed_action")
        else:
            if self.reason_code in ALLOW_REASON_CODES:
                raise ValueError(
                    f"Contradictory decision combination: Non-ALLOW decision '{self.decision.value}' cannot be paired with '{self.reason_code.value}'"
                )
            if self.executed_action != self.baseline_action:
                raise ValueError(
                    f"Non-ALLOW decision ({self.decision.value}) strictly requires executed_action "
                    f"to equal baseline_action ('{self.baseline_action}'), got '{self.executed_action}'"
                )

        return self


class F5ContractInvariant(BaseModel):
    """Explicit statement of an F5 Contract Invariant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invariant_id: str
    name: str
    description: str
    status: str = "CONTRACT_ENFORCED"


F5_CONTRACT_INVARIANTS = [
    F5ContractInvariant(
        invariant_id="F5-I001",
        name="FAIL_CLOSED_NO_MISSING_ALLOW",
        description="Missing/unknown decision cannot produce ALLOW_ACTION; must default to FALLBACK_TO_BASELINE.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I002",
        name="COMPLETE_POLICY_BINDING_REQUIRED",
        description="Policy binding strictly requires non-empty merchant_id, experiment_id, experiment_version, approved_configuration_hash, and policy_version.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I003",
        name="NON_EMPTY_F4_EVIDENCE_REFERENCE",
        description="A policy cannot reference an empty or corrupt F4 evidence identifier or configuration hash.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I004",
        name="ALLOW_ACTION_REQUIRES_AUTHORIZED_ACTION",
        description="An enforcement result cannot claim ALLOW_ACTION without executed_action matching stage2_proposed_action, a valid policy_id, and POLICY_ENFORCED_EFFICACIOUS reason code.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I005",
        name="F4_PROVENANCE_INTEGRITY_PRESERVED",
        description="F5 policy contracts preserve exact source F4 experiment ID, experiment version, and configuration hash without silent normalization.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I006",
        name="UNSAFE_POLICY_STATE_FORCES_BASELINE",
        description="Invalid, disabled, draft, expired, or killed policy states can only yield FALLBACK_TO_BASELINE or FAIL_CLOSED, never ALLOW_ACTION.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I007",
        name="LIMITATION_DISCLOSURES_NON_EXECUTEABLE",
        description="Statistical limitation disclosures remain metadata disclosures and cannot become implicit policy rules.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I008",
        name="EXPLICIT_POLICY_VERSIONING",
        description="Policy versions are explicit, non-empty, and validated.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I009",
        name="TENANT_IDENTITY_MANDATORY",
        description="Merchant identity is mandatory and cannot be empty or whitespace.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I010",
        name="EXPERIMENT_VERSION_MANDATORY",
        description="Experiment version is mandatory and cannot be empty or whitespace.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I011",
        name="DECISION_REASON_CONSISTENCY",
        description="Enforcement result enforces strict consistency between decision and reason codes, blocking invalid combinations such as ALLOW_ACTION + CONFIG_HASH_MISMATCH.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I012",
        name="EVIDENCE_SUPERSESSION_SAFETY",
        description="A policy superseded by conflicting F4 evidence cannot remain ACTIVE_ENFORCED; it must transition to INVALIDATED or EXPIRED.",
    ),
    F5ContractInvariant(
        invariant_id="F5-I013",
        name="AUTHORIZED_ACTION_SET_CARDINALITY",
        description="Authorized actions represent an immutable, canonically sorted, non-empty set of bounded action identifiers.",
    ),
]


class PolicyKillResult(BaseModel):
    """Authoritative result of F5 emergency kill switch operation (F5-5)."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(..., description="Unique policy identifier")
    merchant_id: str = Field(..., description="Merchant tenant identifier")
    experiment_id: str = Field(..., description="Experiment identifier")
    experiment_version: str = Field(..., description="Experiment version")
    previous_status: PolicyStatus = Field(..., description="Previous policy status before kill switch")
    new_status: PolicyStatus = Field(..., description="New policy status after kill switch (KILLED_SAFETY_STOP)")
    kill_effective_at: datetime = Field(..., description="Timestamp when kill transition committed")
    idempotent: bool = Field(..., description="True if policy was already killed")
    policy_version: str = Field("1.0", description="Policy version string")


class EnforcementEvidenceBundle(BaseModel):
    """Authoritative forensic reconstruction of an F5 Stage 2 enforcement event (F5-6)."""

    model_config = ConfigDict(frozen=True)

    enforcement_id: str = Field(..., description="Unique enforcement audit log identifier")
    proposal_id: str | None = Field(None, description="Linked Stage 2 proposal identifier")
    case_id: str = Field(..., description="Linked recovery case identifier")
    merchant_id: str = Field(..., description="Merchant tenant identifier")
    experiment_id: str = Field(..., description="Experiment identifier")
    experiment_version: str = Field(..., description="Experiment version string")
    approved_configuration_hash: str = Field(..., description="64-character hex configuration hash")

    policy_id: str | None = Field(None, description="Policy identifier if authorized/evaluated")
    policy_version: str | None = Field(None, description="Policy version string")

    source_f4_evidence_id: str | None = Field(None, description="Authoritative F4 evidence identifier")
    source_f4_configuration_hash: str | None = Field(None, description="F4 configuration hash")

    stage2_proposed_action: str = Field(..., description="Action proposed by Stage 2 proposal engine")
    executed_action: str = Field(..., description="Action actually executed (proposed action or STOP)")
    baseline_action: str = Field("STOP", description="Baseline fallback action (STOP)")

    decision: EnforcementDecision = Field(..., description="Authoritative F5 enforcement decision")
    reason_code: PolicyEnforcementReasonCode = Field(..., description="Machine-readable decision reason code")
    evaluated_at: datetime = Field(..., description="Decision timestamp")

    execution_status: str | None = Field(None, description="Stage2Case status at/after enforcement")
    policy_status_at_decision: str | None = Field(None, description="Policy lifecycle status when decision was evaluated")
    policy_killed: bool = Field(False, description="True if the associated policy was subsequently or currently killed")
    kill_audit_summary: dict[str, Any] | None = Field(None, description="Summary metadata of emergency policy kill if applicable")



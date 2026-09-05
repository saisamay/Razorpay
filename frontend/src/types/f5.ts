export type PolicyStatus = 
  | 'DRAFT'
  | 'ACTIVE_ENFORCED'
  | 'DISABLED'
  | 'KILLED_SAFETY_STOP'
  | 'EXPIRED'
  | 'INVALIDATED';

export type EnforcementDecision = 
  | 'ALLOW_ACTION'
  | 'FALLBACK_TO_BASELINE'
  | 'FAIL_CLOSED';

export type PolicyEnforcementReasonCode =
  | 'POLICY_ENFORCED_EFFICACIOUS'
  | 'F4_STATUS_NOT_EFFICACIOUS'
  | 'CONFIG_HASH_MISMATCH'
  | 'TENANT_MISMATCH'
  | 'VERSION_MISMATCH'
  | 'STALE_EVALUATION'
  | 'MISSING_EVIDENCE'
  | 'INVALID_EVIDENCE'
  | 'POLICY_NOT_FOUND'
  | 'POLICY_DISABLED'
  | 'POLICY_KILLED'
  | 'POLICY_EXPIRED'
  | 'SAFETY_STOP'
  | 'INVALID_POLICY'
  | 'UNAUTHORIZED_ACTION'
  | 'SUPERSEDED_BY_NEWER_EVIDENCE'
  | 'SUPERSEDING_EVIDENCE_CONFLICT';

export interface KillPolicyPayload {
  merchant_id: string;
  experiment_id: string;
  experiment_version?: string;
  approved_configuration_hash: string;
  operator_id?: string | null;
  reason?: string | null;
}

export interface PolicyKillResult {
  policy_id: string;
  merchant_id: string;
  experiment_id: string;
  experiment_version: string;
  previous_status: PolicyStatus | string;
  new_status: PolicyStatus | string;
  kill_effective_at: string;
  idempotent: boolean;
  policy_version: string;
}

export interface EnforcementEvidenceBundle {
  enforcement_id: string;
  proposal_id?: string | null;
  case_id: string;
  merchant_id: string;
  experiment_id: string;
  experiment_version: string;
  approved_configuration_hash: string;
  policy_id?: string | null;
  policy_version?: string | null;
  source_f4_evidence_id?: string | null;
  source_f4_configuration_hash?: string | null;
  stage2_proposed_action: string;
  executed_action: string;
  baseline_action: string;
  decision: EnforcementDecision | string;
  reason_code: PolicyEnforcementReasonCode | string;
  evaluated_at: string;
  execution_status?: string | null;
  policy_status_at_decision?: string | null;
  policy_killed: boolean;
  kill_audit_summary?: Record<string, any> | null;
}

export interface F5ContractInvariant {
  invariant_id: string;
  name: string;
  description: string;
  status: string;
}

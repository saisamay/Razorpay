import { apiRequest } from './api';
import { EnforcementEvidenceBundle, KillPolicyPayload, PolicyKillResult } from '../types/f5';

export async function getEnforcementEvidence(
  enforcementId: string,
  merchantId?: string,
  internalToken?: string
): Promise<EnforcementEvidenceBundle> {
  return apiRequest<EnforcementEvidenceBundle>(`/api/v2/policies/enforcement/${enforcementId}/evidence`, {
    merchantId,
    internalToken,
  });
}

export async function executePolicyKill(
  policyId: string,
  payload: KillPolicyPayload,
  internalToken?: string
): Promise<PolicyKillResult> {
  return apiRequest<PolicyKillResult>(`/api/v2/policies/${policyId}/kill`, {
    method: 'POST',
    internalToken,
    body: JSON.stringify(payload),
  });
}

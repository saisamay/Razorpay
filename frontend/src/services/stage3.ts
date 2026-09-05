import { apiRequest } from './api';
import { RecoveryAttempt, Escalation } from '../types/stage3';

export type { Escalation };

export interface EscalationDetailResponse {
  escalation: Escalation & {
    resolution_notes?: string | null;
  };
  orchestration?: {
    orchestration_id?: string | null;
    current_attempt_number: number;
    max_attempts: number;
    episode_status: string;
    selected_action?: string | null;
    total_net_recovered_amount: number;
    stopping_reason?: string | null;
  };
  case?: {
    amount?: number | null;
    currency?: string;
    state?: string;
    recovery_eligible?: boolean;
  };
}

export async function getCaseAttempts(caseId: string, merchantId?: string): Promise<RecoveryAttempt[]> {
  return apiRequest<RecoveryAttempt[]>(`/api/v3/cases/${caseId}/attempts`, {
    merchantId,
  });
}

export async function listEscalations(
  merchantId?: string,
  statusFilter?: string,
  limit: number = 50,
  offset: number = 0
): Promise<Escalation[]> {
  return apiRequest<Escalation[]>('/api/v3/escalations', {
    merchantId,
    params: {
      merchant_id: merchantId,
      status_filter: statusFilter,
      limit,
      offset,
    },
  });
}

export async function getEscalationDetail(
  escalationId: string,
  merchantId?: string
): Promise<EscalationDetailResponse> {
  return apiRequest<EscalationDetailResponse>(`/api/v3/escalations/${escalationId}`, {
    merchantId,
  });
}

export async function resolveEscalation(
  escalationId: string,
  payload: { resolution_action: string; operator_id: string; notes?: string },
  merchantId?: string
): Promise<any> {
  return apiRequest(`/api/v3/escalations/${escalationId}/resolve`, {
    method: 'POST',
    merchantId,
    body: JSON.stringify(payload),
  });
}

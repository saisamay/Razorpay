import { apiRequest } from './api';
import { RecoveryCaseListResponse } from '../types/cases';

export interface ListCasesParams {
  merchantId?: string;
  status?: string;
  recoveryEligible?: boolean;
  minAmount?: number;
  maxAmount?: number;
  limit?: number;
  offset?: number;
}

export async function listRecoveryCases(params: ListCasesParams = {}): Promise<RecoveryCaseListResponse> {
  return apiRequest<RecoveryCaseListResponse>('/api/v2/cases', {
    merchantId: params.merchantId,
    params: {
      merchant_id: params.merchantId,
      status: params.status,
      recovery_eligible: params.recoveryEligible,
      min_amount: params.minAmount,
      max_amount: params.maxAmount,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function getCaseDiagnosis(caseId: string, merchantId?: string): Promise<any> {
  return apiRequest(`/api/v2/cases/${caseId}/diagnosis`, { merchantId });
}

export async function getCaseGenome(caseId: string, merchantId?: string): Promise<any> {
  return apiRequest(`/api/v2/cases/${caseId}/genome`, { merchantId });
}

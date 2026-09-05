import { apiRequest } from './api';
import { CaseEvaluationProjection, F4Report } from '../types/evaluation';

export async function getCaseEvaluationProjection(
  caseId: string,
  merchantId?: string
): Promise<CaseEvaluationProjection> {
  return apiRequest<CaseEvaluationProjection>(`/api/v2/evaluation/cases/${caseId}`, {
    merchantId,
  });
}

export async function getF4Report(
  merchantId?: string,
  experimentId?: string,
  experimentVersion?: string
): Promise<F4Report> {
  return apiRequest<F4Report>('/api/v2/evaluation/f4-report', {
    merchantId,
    params: {
      merchant_id: merchantId,
      experiment_id: experimentId,
      experiment_version: experimentVersion,
    },
  });
}

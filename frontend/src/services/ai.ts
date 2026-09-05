import { apiRequest } from './api';
import { CaseAIReasoningProjection } from '../types/ai';

export async function getCaseAIReasoning(
  caseId: string,
  merchantId?: string
): Promise<CaseAIReasoningProjection> {
  return apiRequest<CaseAIReasoningProjection>(`/api/v2/evaluation/cases/${caseId}/ai-reasoning`, {
    merchantId,
    params: { merchant_id: merchantId },
  });
}

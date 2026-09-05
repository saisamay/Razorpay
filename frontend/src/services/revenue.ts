import { apiRequest } from './api';
import { RevenueSummary } from '../types/revenue';

export async function fetchRevenueSummary(
  merchantId?: string,
  windowStart?: string,
  windowEnd?: string
): Promise<RevenueSummary> {
  return apiRequest<RevenueSummary>('/api/v2/evaluation/revenue-summary', {
    merchantId,
    params: {
      merchant_id: merchantId,
      window_start: windowStart,
      window_end: windowEnd,
    },
  });
}

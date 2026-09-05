export interface CaseAIReasoningProjection {
  case_id: string;
  merchant_id: string;
  overall_confidence: number;
  reasoning_chain: Array<{
    step: string;
    finding: string;
    evidence_reference: string;
    confidence: number;
  }>;
  summary: string;
  generated_at: string;
}

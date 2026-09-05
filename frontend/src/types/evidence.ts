export type LineageNodeStatus = 
  | 'OBSERVED'
  | 'AVAILABLE'
  | 'EVALUATED'
  | 'ALLOW'
  | 'STOP'
  | 'EXECUTED'
  | 'NOT_AVAILABLE'
  | 'NOT_ESTABLISHED'
  | 'NOT_APPLICABLE';

export interface EvidenceLineageNode {
  step: number;
  title: string;
  subtitle: string;
  status: LineageNodeStatus;
  id?: string | null;
  timestamp?: string | null;
  details?: Record<string, any> | null;
  link?: string | null;
}

export interface CaseLineageSummary {
  case_id: string;
  merchant_id: string;
  payment_id?: string | null;
  amount_inr?: number | null;
  first_seen_at?: string | null;
  state?: string | null;
  recovery_eligible?: boolean | null;
  nodes: EvidenceLineageNode[];
}

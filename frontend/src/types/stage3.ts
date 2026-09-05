export interface RecoveryAttempt {
  attempt_id: string;
  orchestration_id: string;
  case_id: string;
  merchant_id: string;
  attempt_number: number;
  proposed_action: string;
  executed_action: string;
  proposal_id: string;
  enforcement_id: string;
  enforcement_decision: string;
  outcome_status: string;
  net_recovered_amount: number;
  status: string;
  started_at: string;
  completed_at?: string | null;
}

export interface Escalation {
  escalation_id: string;
  orchestration_id: string;
  case_id: string;
  merchant_id: string;
  reason_code: string;
  severity: string;
  status: 'OPEN' | 'RESOLVED' | 'TIMED_OUT';
  triggered_at: string;
  assigned_operator?: string | null;
  resolution_action?: string | null;
  resolved_at?: string | null;
}

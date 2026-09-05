export interface RecoveryCase {
  case_id: string;
  payment_id: string;
  recovery_episode_id?: string | null;
  merchant_id: string;
  order_id?: string | null;
  amount: number;
  currency: string;
  state: string;
  state_confidence?: number | null;
  recovery_eligible: boolean;
  eligibility_reason?: string | null;
  schema_version: string;
  stage1_state_version: number;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
}

export interface RecoveryCaseListResponse {
  items: RecoveryCase[];
  limit: number;
  offset: number;
  total: number;
}

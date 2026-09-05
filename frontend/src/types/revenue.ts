export interface CaseBreakdownItem {
  case_id: string;
  amount_inr: number;
  recovery_eligible: boolean;
  outcome_status: string;
  net_verified_recovered_inr: number;
}

export interface RevenueSummary {
  case_count?: number;
  revenue_at_risk_paise?: number;
  eligible_revenue_paise?: number;
  revenue_at_risk_inr: number;
  eligible_revenue_inr: number;
  gross_recovered_inr: number;
  net_verified_recovered_inr: number;
  unrecovered_revenue_inr: number;
  recovery_rate: number;
  cases_breakdown: CaseBreakdownItem[];
  incremental_recovered_revenue_inr?: number | null;
  baseline_recovery_rate?: number | null;
  f4_eval_status?: string | null;
}

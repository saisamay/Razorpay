export interface MetricValue {
  value: any;
  value_semantics: 'OBSERVED' | 'PREDICTED' | 'VERIFIED' | 'COUNTERFACTUAL' | 'EVALUATED' | 'GOVERNED';
  source_type: string;
  source_version: string;
}

export interface F4Report {
  report_id?: string;
  merchant_id?: string;
  experiment_id?: string;
  experiment_version?: string;
  status: string; // e.g. "NOT_AVAILABLE", "SUCCESS", "INVALID"
  positivity_status?: string | null;
  reason?: string | null;
  estimand_population?: string | null;
  allocation_proportion_p?: number | null;
  eligible_population_count?: number | null;
  observed_control_count?: number | null;
  observed_treatment_count?: number | null;
  point_estimate_paise_per_unit?: number | null;
  incremental_recovered_revenue_paise?: number | null;
  counterfactual_control_revenue_paise?: number | null;
  standard_error?: number | null;
  confidence_interval_lower?: number | null;
  confidence_interval_upper?: number | null;
  invalidation_reasons?: string[];
  raw_report_json?: Record<string, any> | null;
  evaluated_at?: string | null;
}

export interface CaseEvaluationProjection {
  case_id: string;
  merchant_id: string;
  payment_id: string;
  order_id?: string | null;
  amount: MetricValue;
  currency: string;
  payment_rail: string;
  state: MetricValue;
  state_version: number;
  recovery_eligible: MetricValue;
  evidence_manifest?: Record<string, any> | null;
  diagnosis?: Record<string, any> | null;
  failure_dna?: Record<string, any> | null;
  temporal_features?: Record<string, any> | null;
  incident?: Record<string, any> | null;
  compliance?: Record<string, any> | null;
  genome?: Record<string, any> | null;
  action_capability_matrix?: Array<Record<string, any>>;
  counterfactual_simulations?: Array<Record<string, any>>;
  decision_proposal?: Record<string, any> | null;
  shadow_evaluation?: Record<string, any> | null;
  genai_explanation?: Record<string, any> | null;
  data_quality?: Record<string, boolean>;
  provenance?: Record<string, any>;
}

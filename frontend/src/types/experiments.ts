export interface Experiment {
  experiment_id: string;
  experiment_version: string;
  allocation_ratio: number;
  status: 'DRAFT' | 'FROZEN' | 'READY' | 'APPROVED' | 'REJECTED' | 'RUNNING' | 'TERMINATED';
  approved_configuration_hash?: string | null;
  created_at?: string;
  approved_at?: string | null;
  approved_by?: string | null;
  rejected_at?: string | null;
  rejected_by?: string | null;
  rejection_reason?: string | null;
}

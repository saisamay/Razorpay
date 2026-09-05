import React from 'react';
import { RevenueSummary } from '../../types/revenue';
import { KpiCard } from '../common/KpiCard';
import { StatusBadge } from '../common/StatusBadge';

export interface CausalImpactSectionProps {
  data: RevenueSummary;
}

export const CausalImpactSection: React.FC<CausalImpactSectionProps> = ({ data }) => {
  const isIncrementalAvailable =
    data.incremental_recovered_revenue_inr !== null &&
    data.incremental_recovered_revenue_inr !== undefined;

  const isBaselineAvailable =
    data.baseline_recovery_rate !== null &&
    data.baseline_recovery_rate !== undefined;

  return (
    <section style={{ marginBottom: '2rem' }}>
      <div
        style={{
          background: 'rgba(139, 92, 246, 0.08)',
          border: '1px solid rgba(139, 92, 246, 0.25)',
          borderRadius: 'var(--radius-lg)',
          padding: '1.5rem',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff' }}>F4 Causal Impact & Counterfactuals</h2>
              <StatusBadge
                status={data.f4_eval_status || 'NOT_AVAILABLE'}
                label={isIncrementalAvailable ? 'CAUSAL EVALUATED' : 'NOT ESTABLISHED'}
              />
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Rigorous causal estimation comparing algorithm treatment vs. control baseline
            </p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1.25rem' }}>
          <KpiCard
            title="Baseline Recovery Rate"
            value={isBaselineAvailable ? (data.baseline_recovery_rate! * 100) : null}
            type="percent"
            isNotAvailable={!isBaselineAvailable}
            notAvailableReason="F4 control arm baseline required"
            subtext="Counterfactual control recovery rate"
            accentColor="#cbd5e1"
            badge="CONTROL BASELINE"
          />

          <KpiCard
            title="Incremental Recovered Revenue"
            value={isIncrementalAvailable ? data.incremental_recovered_revenue_inr : null}
            type="currency"
            isNotAvailable={!isIncrementalAvailable}
            notAvailableReason="Requires active F4 experiment report"
            subtext="Causal lift above baseline control"
            accentColor="var(--accent-purple)"
            badge="CAUSAL LIFT"
          />
        </div>
      </div>
    </section>
  );
};

import React from 'react';
import { RevenueSummary } from '../../types/revenue';
import { KpiCard } from '../common/KpiCard';

export interface FinancialImpactSectionProps {
  data: RevenueSummary;
}

export const FinancialImpactSection: React.FC<FinancialImpactSectionProps> = ({ data }) => {
  return (
    <section style={{ marginBottom: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>Financial Impact Summary</h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Deterministic revenue economics & Stage 3 verified net recovery totals
          </p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.25rem' }}>
        <KpiCard
          title="Revenue at Risk"
          value={data.revenue_at_risk_inr}
          type="currency"
          subtext="Total failed payment volume"
          accentColor="var(--accent-amber)"
          badge="FAILED VOLUME"
        />
        <KpiCard
          title="Eligible Revenue"
          value={data.eligible_revenue_inr}
          type="currency"
          subtext="Compliant volume for recovery"
          accentColor="var(--accent-blue)"
          badge="ELIGIBLE"
        />
        <KpiCard
          title="Gross Recovered"
          value={data.gross_recovered_inr}
          type="currency"
          subtext="Total gross payments recovered"
          accentColor="#cbd5e1"
        />
        <KpiCard
          title="Net Verified Recovered"
          value={data.net_verified_recovered_inr}
          type="currency"
          subtext="Stage 3 verified net revenue"
          accentColor="var(--accent-green)"
          badge="VERIFIED NET"
        />
        <KpiCard
          title="Unrecovered Revenue"
          value={data.unrecovered_revenue_inr}
          type="currency"
          subtext="Remaining unrecovered loss"
          accentColor="var(--accent-red)"
        />
        <KpiCard
          title="Recovery Rate"
          value={data.recovery_rate * 100}
          type="percent"
          subtext="Net verified / Eligible volume"
          accentColor="var(--accent-purple)"
        />
      </div>
    </section>
  );
};

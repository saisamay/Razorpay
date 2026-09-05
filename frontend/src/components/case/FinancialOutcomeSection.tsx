import React from 'react';
import { formatINR } from '../common/KpiCard';
import { StatusBadge } from '../common/StatusBadge';

export interface FinancialOutcomeSectionProps {
  amount: number;
  currency: string;
  state: string;
  recoveryEligible: boolean;
  eligibilityReason?: string | null;
  paymentId: string;
  orderId?: string | null;
  paymentRail?: string;
  stateVersion?: number;
}

export const FinancialOutcomeSection: React.FC<FinancialOutcomeSectionProps> = ({
  amount,
  currency,
  state,
  recoveryEligible,
  eligibilityReason,
  paymentId,
  orderId,
  paymentRail = 'CARD',
  stateVersion = 1,
}) => {
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.25rem',
        marginBottom: '1.5rem',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>Financial & Payment Context</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Stage 1 payment state machine metadata and recovery gate validation
          </p>
        </div>
        <StatusBadge status={recoveryEligible ? 'RECOVERY ELIGIBLE' : 'RECOVERY BLOCKED'} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Payment Amount</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
            {formatINR(amount)} <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{currency}</span>
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Payment State</div>
          <div style={{ marginTop: '0.35rem' }}>
            <StatusBadge status={state} />
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>State Version: v{stateVersion}</div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Payment Rail</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--accent-blue)', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
            {paymentRail.toUpperCase()}
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Payment ID</div>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-main)', fontFamily: 'var(--font-mono)', marginTop: '0.35rem', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {paymentId}
          </div>
          {orderId && <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>Order: {orderId}</div>}
        </div>
      </div>

      {eligibilityReason && (
        <div style={{ marginTop: '1rem', padding: '0.65rem 0.85rem', background: 'rgba(255, 255, 255, 0.03)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          <strong style={{ color: 'var(--text-main)' }}>Eligibility Reason:</strong> {eligibilityReason}
        </div>
      )}
    </div>
  );
};

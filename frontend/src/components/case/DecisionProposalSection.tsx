import React from 'react';
import { formatINR } from '../common/KpiCard';
import { StatusBadge } from '../common/StatusBadge';

export interface DecisionProposalSectionProps {
  proposal?: Record<string, any> | null;
  actionCapabilityMatrix?: Array<Record<string, any>> | null;
  shadowEval?: Record<string, any> | null;
}

export const DecisionProposalSection: React.FC<DecisionProposalSectionProps> = ({
  proposal,
  actionCapabilityMatrix,
  shadowEval,
}) => {
  if (!proposal && (!actionCapabilityMatrix || actionCapabilityMatrix.length === 0)) {
    return (
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', marginBottom: '1.5rem', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
        No decision proposal recorded for this case.
      </div>
    );
  }

  const selectedAction = proposal?.selected_action || shadowEval?.stage2_proposed_action || 'STOP';
  const successProb = proposal?.predicted_success_probability !== undefined ? Math.round(proposal.predicted_success_probability * 100) : null;
  const expectedNetVal = proposal?.expected_net_value !== undefined ? proposal.expected_net_value : null;
  const ci = proposal?.confidence_interval;

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
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>Stage 2 DecisionProposal & Action Matrix</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Authoritative algorithmic intervention proposal and expected financial yield
          </p>
        </div>
        <StatusBadge status="PROPOSAL SELECTED" variant="purple" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1.25rem' }}>
        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Selected Action</div>
          <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--accent-purple)', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
            {selectedAction}
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Predicted P(Success)</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--accent-blue)', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
            {successProb !== null ? `${successProb}%` : 'N/A'}
          </div>
          {ci && Array.isArray(ci) && (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.2rem', fontFamily: 'var(--font-mono)' }}>
              CI: [{(ci[0] * 100).toFixed(0)}% - {(ci[1] * 100).toFixed(0)}%]
            </div>
          )}
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Expected Net Value</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--accent-green)', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
            {expectedNetVal !== null ? formatINR(expectedNetVal) : 'N/A'}
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Optimizer Version</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginTop: '0.3rem' }}>
            v{proposal?.optimizer_version || '1.0'}
          </div>
        </div>
      </div>

      {actionCapabilityMatrix && actionCapabilityMatrix.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem', textTransform: 'uppercase' }}>
            Action Capability Matrix & Compliance Gate
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-strong)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.5rem' }}>Action</th>
                  <th style={{ padding: '0.5rem' }}>Capability</th>
                  <th style={{ padding: '0.5rem' }}>Compliance</th>
                  <th style={{ padding: '0.5rem' }}>Final Status</th>
                </tr>
              </thead>
              <tbody>
                {actionCapabilityMatrix.map((item, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '0.5rem', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{item.action}</td>
                    <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>{item.capability}</td>
                    <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>{item.compliance}</td>
                    <td style={{ padding: '0.5rem' }}>
                      <StatusBadge status={item.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

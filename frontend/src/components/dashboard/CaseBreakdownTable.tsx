import React from 'react';
import { CaseBreakdownItem } from '../../types/revenue';
import { formatINR } from '../common/KpiCard';
import { StatusBadge } from '../common/StatusBadge';

export interface CaseBreakdownTableProps {
  cases: CaseBreakdownItem[];
  onSelectCase?: (caseId: string) => void;
}

export const CaseBreakdownTable: React.FC<CaseBreakdownTableProps> = ({ cases, onSelectCase }) => {
  if (!cases || cases.length === 0) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          padding: '2rem',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.875rem',
        }}
      >
        No active recovery case breakdown data available for this merchant scope.
      </div>
    );
  }

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.25rem',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>Case-Level Revenue Traceability</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Breakdown of failed payment cases and verified net recovery status
          </p>
        </div>
        <StatusBadge status={`${cases.length} CASES`} variant="blue" />
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border-strong)', color: 'var(--text-muted)' }}>
              <th style={{ padding: '0.75rem 0.5rem', fontWeight: 600 }}>Case ID</th>
              <th style={{ padding: '0.75rem 0.5rem', fontWeight: 600 }}>Amount</th>
              <th style={{ padding: '0.75rem 0.5rem', fontWeight: 600 }}>Eligible</th>
              <th style={{ padding: '0.75rem 0.5rem', fontWeight: 600 }}>Outcome</th>
              <th style={{ padding: '0.75rem 0.5rem', fontWeight: 600 }}>Net Verified</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr
                key={c.case_id}
                onClick={() => onSelectCase && onSelectCase(c.case_id)}
                style={{
                  borderBottom: '1px solid var(--border-subtle)',
                  cursor: onSelectCase ? 'pointer' : 'default',
                  transition: 'background 0.15s ease',
                }}
              >
                <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--accent-blue)' }}>
                  {c.case_id}
                </td>
                <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'var(--font-mono)' }}>
                  {formatINR(c.amount_inr)}
                </td>
                <td style={{ padding: '0.75rem 0.5rem' }}>
                  <StatusBadge
                    status={c.recovery_eligible ? 'ELIGIBLE' : 'BLOCKED'}
                    variant={c.recovery_eligible ? 'green' : 'red'}
                  />
                </td>
                <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-secondary)' }}>
                  {c.outcome_status}
                </td>
                <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--accent-green)' }}>
                  {formatINR(c.net_verified_recovered_inr)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

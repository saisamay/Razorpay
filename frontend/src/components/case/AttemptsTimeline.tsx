import React from 'react';
import { RecoveryAttempt } from '../../types/stage3';
import { formatINR } from '../common/KpiCard';
import { StatusBadge } from '../common/StatusBadge';

export interface AttemptsTimelineProps {
  attempts?: RecoveryAttempt[] | null;
  stoppingReason?: string | null;
  loading?: boolean;
  error?: string | null;
}

export const AttemptsTimeline: React.FC<AttemptsTimelineProps> = ({
  attempts,
  stoppingReason,
  loading,
  error,
}) => {
  if (loading) {
    return (
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', marginBottom: '1.5rem' }}>
        <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', marginBottom: '0.75rem' }}>Stage 3 Recovery Attempt Execution Timeline</div>
        <div className="animate-pulse" style={{ height: '140px', background: 'var(--bg-dark-700)', borderRadius: 'var(--radius-md)' }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', marginBottom: '1.5rem', color: '#f87171' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#ef4444' }}>Recovery Attempt Timeline Unavailable</h3>
        <p style={{ fontSize: '0.85rem', marginTop: '0.25rem' }}>{error}</p>
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
        marginBottom: '1.5rem',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>Stage 3 Recovery Attempt Execution Timeline</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Auditable physical recovery execution history, F5 governance enforcement, and outcome reconciliation
          </p>
        </div>
        <StatusBadge status={attempts ? `${attempts.length} ATTEMPTS` : '0 ATTEMPTS'} variant="blue" />
      </div>

      {stoppingReason && (
        <div
          style={{
            background: 'rgba(245, 158, 11, 0.12)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '0.85rem 1rem',
            marginBottom: '1.25rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <span style={{ fontSize: '1.1rem' }}>🛑</span>
          <div>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--accent-amber)' }}>
              Recovery Episode Stopped
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-main)', fontFamily: 'var(--font-mono)' }}>
              Reason: {stoppingReason}
            </div>
          </div>
        </div>
      )}

      {!attempts || attempts.length === 0 ? (
        <div
          style={{
            background: 'var(--bg-dark-900)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '2rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.875rem',
          }}
        >
          No Stage 3 recovery attempts executed yet. Payment is in passive shadow evaluation mode or awaiting orchestration dispatch.
        </div>
      ) : (
        <div style={{ position: 'relative', paddingLeft: '1.5rem' }}>
          {/* Timeline bar line */}
          <div
            style={{
              position: 'absolute',
              top: '0.5rem',
              bottom: '0.5rem',
              left: '0.45rem',
              width: '2px',
              background: 'var(--border-strong)',
            }}
          />

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {attempts.map((att, idx) => (
              <div key={att.attempt_id || idx} style={{ position: 'relative' }}>
                {/* Bullet node */}
                <div
                  style={{
                    position: 'absolute',
                    left: '-1.45rem',
                    top: '0.25rem',
                    width: '10px',
                    height: '10px',
                    borderRadius: '50%',
                    background: att.outcome_status === 'RECOVERED' ? 'var(--accent-green)' : att.status === 'FAILED' ? 'var(--accent-red)' : 'var(--accent-blue)',
                    boxShadow: '0 0 8px rgba(59, 130, 246, 0.5)',
                  }}
                />

                <div
                  style={{
                    background: 'var(--bg-dark-900)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    padding: '1rem',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.65rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                      <span style={{ fontSize: '0.9rem', fontWeight: 700, color: '#fff' }}>
                        Attempt #{att.attempt_number}
                      </span>
                      <StatusBadge status={att.outcome_status || att.status || 'EXECUTED'} />
                    </div>

                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      Started: {new Date(att.started_at).toLocaleString()}
                    </span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem', fontSize: '0.8rem', marginBottom: '0.65rem' }}>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Proposed Action: </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--accent-purple)' }}>{att.proposed_action}</span>
                    </div>

                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Executed Action: </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--accent-blue)' }}>{att.executed_action}</span>
                    </div>

                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>F5 Enforcement: </span>
                      <StatusBadge status={att.enforcement_decision || 'ALLOWED'} />
                    </div>

                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Net Recovered: </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: att.net_recovered_amount > 0 ? 'var(--accent-green)' : 'var(--text-main)' }}>
                        {formatINR(att.net_recovered_amount || 0)}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '1rem', fontSize: '0.7rem', color: 'var(--text-muted)', borderTop: '1px solid rgba(255,255,255,0.03)', paddingTop: '0.4rem', fontFamily: 'var(--font-mono)' }}>
                    <span>Attempt ID: {att.attempt_id}</span>
                    {att.enforcement_id && <span>Enforcement ID: {att.enforcement_id}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

import React from 'react';
import { StatusBadge } from '../common/StatusBadge';

export interface DiagnosisSectionProps {
  diagnosis?: {
    diagnosis_id?: string;
    diagnosis_class?: string;
    score?: number;
    confidence?: number;
    engine_version?: string;
    status?: string;
    evidence_ids?: string[];
    contradiction_ids?: string[];
    competing_hypotheses?: Array<{ hypothesis: string; score: number }>;
  } | null;
  loading?: boolean;
  error?: string | null;
}

export const DiagnosisSection: React.FC<DiagnosisSectionProps> = ({ diagnosis, loading, error }) => {
  if (loading) {
    return (
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', marginBottom: '1.5rem' }}>
        <div className="animate-pulse" style={{ height: '140px', background: 'var(--bg-dark-700)', borderRadius: 'var(--radius-md)' }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', marginBottom: '1.5rem', color: '#f87171' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#ef4444' }}>Failure Diagnosis Unavailable</h3>
        <p style={{ fontSize: '0.85rem', marginTop: '0.25rem' }}>{error}</p>
      </div>
    );
  }

  if (!diagnosis) {
    return (
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', marginBottom: '1.5rem', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
        No active failure diagnosis recorded for this case.
      </div>
    );
  }

  const confidencePct = Math.round((diagnosis.confidence || 0) * 100);

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
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>Failure Diagnosis</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Stage 2 deterministic causal classification and confidence evaluation
          </p>
        </div>
        <StatusBadge status={diagnosis.status || 'CURRENT'} variant="blue" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1rem' }}>
        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Primary Classification</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--accent-blue)', marginTop: '0.2rem' }}>
            {diagnosis.diagnosis_class || 'UNKNOWN'}
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Diagnosis Confidence</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.2rem' }}>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--accent-green)', fontFamily: 'var(--font-mono)' }}>
              {confidencePct}%
            </div>
            <div style={{ flex: 1, height: '6px', background: 'var(--bg-dark-700)', borderRadius: '3px', overflow: 'hidden' }}>
              <div style={{ width: `${confidencePct}%`, height: '100%', background: 'var(--accent-green)' }} />
            </div>
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Engine Version</div>
          <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-main)', fontFamily: 'var(--font-mono)', marginTop: '0.35rem' }}>
            v{diagnosis.engine_version || '1.0'}
          </div>
        </div>
      </div>

      {diagnosis.evidence_ids && diagnosis.evidence_ids.length > 0 && (
        <div style={{ marginTop: '0.75rem' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem', textTransform: 'uppercase' }}>
            Supporting Evidence IDs ({diagnosis.evidence_ids.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
            {diagnosis.evidence_ids.map((evId) => (
              <span
                key={evId}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.725rem',
                  background: 'var(--bg-dark-900)',
                  border: '1px solid var(--border-subtle)',
                  padding: '0.2rem 0.5rem',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-secondary)',
                }}
              >
                {evId}
              </span>
            ))}
          </div>
        </div>
      )}

      {diagnosis.competing_hypotheses && diagnosis.competing_hypotheses.length > 0 && (
        <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem', textTransform: 'uppercase' }}>
            Competing Hypotheses
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            {diagnosis.competing_hypotheses.map((h, idx) => (
              <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                <span>{h.hypothesis}</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-main)' }}>{(h.score * 100).toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

import React from 'react';
import { StatusBadge } from '../common/StatusBadge';

export interface GenomeSectionProps {
  genome?: {
    genome_id?: string;
    schema_version?: string;
    p0_source?: Record<string, any> | null;
    p1_source?: Record<string, any> | null;
    provenance?: Record<string, any> | null;
    assembled_at?: string | null;
  } | null;
  failureDna?: Record<string, any> | null;
  loading?: boolean;
}

export const GenomeSection: React.FC<GenomeSectionProps> = ({ genome, failureDna, loading }) => {
  if (loading) {
    return (
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', marginBottom: '1.5rem' }}>
        <div className="animate-pulse" style={{ height: '120px', background: 'var(--bg-dark-700)', borderRadius: 'var(--radius-md)' }} />
      </div>
    );
  }

  const p0 = genome?.p0_source || {};
  const dna = failureDna || p0;

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
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>Failure DNA & RecoveryGenome</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Recognizable failure pattern dimensions and immutable state snapshot
          </p>
        </div>
        <StatusBadge status="STABILITY GENOME" variant="purple" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1rem' }}>
        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Genome ID</div>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-purple)', fontFamily: 'var(--font-mono)', marginTop: '0.25rem' }}>
            {genome?.genome_id || 'N/A'}
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Fingerprint Hash</div>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-main)', fontFamily: 'var(--font-mono)', marginTop: '0.25rem' }}>
            {(p0.failure_dna_fingerprint || dna.fingerprint || 'N/A').substring(0, 20)}...
          </div>
        </div>

        <div style={{ background: 'var(--bg-dark-900)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Schema Version</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginTop: '0.25rem' }}>
            v{genome?.schema_version || '1.0'}
          </div>
        </div>
      </div>

      {Object.keys(dna).length > 0 && (
        <div style={{ background: 'rgba(0, 0, 0, 0.2)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem', textTransform: 'uppercase' }}>
            Fingerprint Dimension Features
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.5rem', fontSize: '0.8rem' }}>
            {Object.entries(dna).slice(0, 8).map(([key, val]) => (
              <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                <span style={{ color: 'var(--text-muted)' }}>{key}:</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-main)', fontWeight: 500 }}>
                  {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

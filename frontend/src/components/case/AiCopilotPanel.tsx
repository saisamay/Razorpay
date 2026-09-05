import React from 'react';
import { CaseAIReasoningProjection } from '../../types/ai';
import { StatusBadge } from '../common/StatusBadge';

export interface AiCopilotPanelProps {
  data?: CaseAIReasoningProjection | null;
  loading?: boolean;
  error?: string | null;
}

export const AiCopilotPanel: React.FC<AiCopilotPanelProps> = ({ data, loading, error }) => {
  if (loading) {
    return (
      <div style={{ background: 'rgba(139, 92, 246, 0.08)', border: '1px solid rgba(139, 92, 246, 0.25)', borderRadius: 'var(--radius-lg)', padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--accent-purple)', marginBottom: '0.75rem' }}>AI Recovery Reasoning</div>
        <div className="animate-pulse" style={{ height: '120px', background: 'var(--bg-dark-700)', borderRadius: 'var(--radius-md)' }} />
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.25)',
          borderRadius: 'var(--radius-lg)',
          padding: '1.25rem',
          marginBottom: '1.5rem',
          color: '#f87171',
        }}
      >
        <div style={{ fontWeight: 600, fontSize: '1rem', color: '#ef4444', marginBottom: '0.25rem' }}>AI Copilot Reasoning Unavailable</div>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-main)' }}>{error}</div>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const confidencePct = Math.round((data.overall_confidence || 0) * 100);

  return (
    <div
      style={{
        background: 'linear-gradient(135deg, rgba(139, 92, 246, 0.12) 0%, rgba(59, 130, 246, 0.08) 100%)',
        border: '1px solid rgba(139, 92, 246, 0.35)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
        marginBottom: '1.5rem',
        boxShadow: '0 8px 32px -4px rgba(139, 92, 246, 0.15)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #8b5cf6 0%, #3b82f6 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontWeight: 800,
              fontSize: '0.85rem',
            }}
          >
            AI
          </div>
          <div>
            <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff' }}>AI Recovery Reasoning</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Evidence-Grounded Forensic Copilot & Intervention Explanation
            </p>
          </div>
        </div>

        <StatusBadge status={`${confidencePct}% CONFIDENCE`} variant="purple" />
      </div>

      {data.summary && (
        <div
          style={{
            background: 'rgba(18, 24, 38, 0.85)',
            border: '1px solid rgba(139, 92, 246, 0.25)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            marginBottom: '1.25rem',
            fontSize: '0.925rem',
            lineHeight: 1.6,
            color: '#e2e8f0',
          }}
        >
          <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-purple)', textTransform: 'uppercase', marginBottom: '0.35rem', letterSpacing: '0.05em' }}>
            Forensic Copilot Summary
          </div>
          "{data.summary}"
        </div>
      )}

      {data.reasoning_chain && data.reasoning_chain.length > 0 && (
        <div>
          <div style={{ fontSize: '0.775rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.65rem', letterSpacing: '0.05em' }}>
            Step-by-Step Evidence Grounding Chain
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            {data.reasoning_chain.map((step, idx) => (
              <div
                key={idx}
                style={{
                  background: 'rgba(18, 24, 38, 0.6)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.85rem 1rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.35rem',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-blue)' }}>
                    Step {step.step || idx + 1}
                  </span>
                  <span style={{ fontSize: '0.725rem', color: 'var(--accent-green)', fontFamily: 'var(--font-mono)' }}>
                    {Math.round((step.confidence || 0) * 100)}% Confidence
                  </span>
                </div>
                <div style={{ fontSize: '0.875rem', color: 'var(--text-main)' }}>{step.finding}</div>
                {step.evidence_reference && (
                  <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
                    Evidence Ref: <span style={{ color: 'var(--accent-purple)' }}>{step.evidence_reference}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div
        style={{
          marginTop: '1.25rem',
          paddingTop: '0.85rem',
          borderTop: '1px solid rgba(139, 92, 246, 0.2)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '0.75rem',
          color: 'var(--text-muted)',
        }}
      >
        <span>
          <strong style={{ color: 'var(--text-secondary)' }}>Governance Note:</strong> AI recommends and explains. F5 governance controls execution.
        </span>
        {data.generated_at && (
          <span style={{ fontFamily: 'var(--font-mono)' }}>Generated: {new Date(data.generated_at).toLocaleTimeString()}</span>
        )}
      </div>
    </div>
  );
};

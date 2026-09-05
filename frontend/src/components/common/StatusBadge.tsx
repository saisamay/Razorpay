import React from 'react';

export interface StatusBadgeProps {
  status: string;
  variant?: 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'gray';
  label?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, variant, label }) => {
  const normalized = status.toUpperCase();

  let resolvedVariant = variant;
  if (!resolvedVariant) {
    if (['ELIGIBLE', 'VERIFIED', 'SUCCESS', 'RUNNING', 'APPROVED'].includes(normalized)) {
      resolvedVariant = 'green';
    } else if (['BLOCKED', 'FAILED', 'REJECTED', 'KILLED'].includes(normalized)) {
      resolvedVariant = 'red';
    } else if (['NOT_AVAILABLE', 'PENDING', 'DRAFT', 'OPEN'].includes(normalized)) {
      resolvedVariant = 'amber';
    } else if (['SHADOW', 'PROPOSED'].includes(normalized)) {
      resolvedVariant = 'purple';
    } else if (['OBSERVED', 'INFO'].includes(normalized)) {
      resolvedVariant = 'blue';
    } else {
      resolvedVariant = 'gray';
    }
  }

  const styles: Record<string, React.CSSProperties> = {
    green: { background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', border: '1px solid rgba(16, 185, 129, 0.3)' },
    red: { background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.3)' },
    amber: { background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)' },
    blue: { background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6', border: '1px solid rgba(59, 130, 246, 0.3)' },
    purple: { background: 'rgba(139, 92, 246, 0.15)', color: '#8b5cf6', border: '1px solid rgba(139, 92, 246, 0.3)' },
    gray: { background: 'rgba(156, 163, 175, 0.15)', color: '#9ca3af', border: '1px solid rgba(156, 163, 175, 0.3)' },
  };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '0.15rem 0.55rem',
        borderRadius: '9999px',
        fontSize: '0.725rem',
        fontWeight: 600,
        letterSpacing: '0.02em',
        textTransform: 'uppercase',
        ...styles[resolvedVariant],
      }}
    >
      {label || status}
    </span>
  );
};

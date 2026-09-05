import React from 'react';

export interface EmptyStateProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, description, icon }) => {
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        padding: '3rem 1.5rem',
        textAlign: 'center',
        color: 'var(--text-secondary)',
      }}
    >
      {icon && <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'center' }}>{icon}</div>}
      <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.5rem' }}>{title}</div>
      <div style={{ fontSize: '0.875rem', maxWidth: '400px', margin: '0 auto' }}>{description}</div>
    </div>
  );
};

import React from 'react';

export interface ErrorAlertProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({
  title = 'Unable to Load Data',
  message,
  onRetry,
}) => {
  return (
    <div
      style={{
        background: 'rgba(239, 68, 68, 0.1)',
        border: '1px solid rgba(239, 68, 68, 0.3)',
        borderRadius: 'var(--radius-md)',
        padding: '1.25rem',
        color: '#f87171',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
        margin: '1rem 0',
      }}
    >
      <div style={{ fontWeight: 600, fontSize: '1rem', color: '#ef4444' }}>{title}</div>
      <div style={{ fontSize: '0.875rem', color: 'var(--text-main)' }}>{message}</div>
      {onRetry && (
        <div>
          <button
            onClick={onRetry}
            style={{
              background: '#ef4444',
              color: '#fff',
              border: 'none',
              padding: '0.4rem 1rem',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
            }}
          >
            Retry Request
          </button>
        </div>
      )}
    </div>
  );
};

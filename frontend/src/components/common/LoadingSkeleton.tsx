import React from 'react';

export const LoadingSkeleton: React.FC<{ height?: string; width?: string }> = ({ height = '100px', width = '100%' }) => {
  return (
    <div
      className="animate-pulse"
      style={{
        height,
        width,
        background: 'var(--bg-dark-700)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)',
      }}
    />
  );
};

export const DashboardSkeleton: React.FC = () => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <LoadingSkeleton key={i} height="120px" />
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        <LoadingSkeleton height="280px" />
        <LoadingSkeleton height="280px" />
      </div>
    </div>
  );
};

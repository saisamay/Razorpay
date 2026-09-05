import React from 'react';
import { StatusBadge } from './StatusBadge';

export interface KpiCardProps {
  title: string;
  value?: number | string | null;
  type?: 'currency' | 'percent' | 'number' | 'text';
  subtext?: string;
  isNotAvailable?: boolean;
  notAvailableReason?: string;
  badge?: string;
  accentColor?: string;
}

export const formatINR = (val: number): string => {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(val);
};

export const KpiCard: React.FC<KpiCardProps> = ({
  title,
  value,
  type = 'currency',
  subtext,
  isNotAvailable = false,
  notAvailableReason = 'F4 parameter required',
  badge,
  accentColor = 'var(--text-main)',
}) => {
  const renderValue = () => {
    if (isNotAvailable || value === null || value === undefined) {
      return (
        <div style={{ margin: '0.4rem 0' }}>
          <span
            style={{
              fontSize: '1.05rem',
              fontWeight: 600,
              color: 'var(--accent-amber)',
              background: 'rgba(245, 158, 11, 0.12)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              padding: '0.2rem 0.6rem',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            Not Established
          </span>
        </div>
      );
    }

    if (typeof value === 'string') {
      return <div style={{ fontSize: '1.5rem', fontWeight: 700, color: accentColor, fontFamily: 'var(--font-mono)' }}>{value}</div>;
    }

    if (type === 'currency') {
      return <div style={{ fontSize: '1.5rem', fontWeight: 700, color: accentColor, fontFamily: 'var(--font-mono)' }}>{formatINR(value)}</div>;
    }

    if (type === 'percent') {
      return <div style={{ fontSize: '1.5rem', fontWeight: 700, color: accentColor, fontFamily: 'var(--font-mono)' }}>{value.toFixed(1)}%</div>;
    }

    return <div style={{ fontSize: '1.5rem', fontWeight: 700, color: accentColor, fontFamily: 'var(--font-mono)' }}>{value.toLocaleString('en-IN')}</div>;
  };

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        boxShadow: 'var(--shadow-card)',
        transition: 'transform 0.15s ease, border-color 0.15s ease',
      }}
    >
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
            {title}
          </span>
          {badge && <StatusBadge status={badge} />}
        </div>
        {renderValue()}
      </div>
      <div style={{ fontSize: '0.75rem', color: isNotAvailable ? 'var(--accent-amber)' : 'var(--text-muted)', marginTop: '0.5rem' }}>
        {isNotAvailable ? notAvailableReason : subtext}
      </div>
    </div>
  );
};

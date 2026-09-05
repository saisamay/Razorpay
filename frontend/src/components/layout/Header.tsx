import React from 'react';
import { StatusBadge } from '../common/StatusBadge';

export interface HeaderProps {
  merchantId: string;
  onMerchantIdChange: (newId: string) => void;
}

export const Header: React.FC<HeaderProps> = ({ merchantId, onMerchantIdChange }) => {
  return (
    <header
      style={{
        height: '64px',
        background: 'var(--bg-dark-800)',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 1.5rem',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <div
            style={{
              width: '28px',
              height: '28px',
              borderRadius: '6px',
              background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 800,
              fontSize: '0.9rem',
              color: '#fff',
            }}
          >
            R
          </div>
          <span style={{ fontWeight: 700, fontSize: '1.1rem', color: '#fff', letterSpacing: '-0.01em' }}>
            Razorpay AI Revenue Recovery
          </span>
        </div>
        <StatusBadge status="SYSTEM ACTIVE" variant="green" />
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', background: 'var(--bg-dark-700)', padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)' }}>
          v2.0.0
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
            Merchant Context:
          </span>
          <input
            type="text"
            value={merchantId}
            onChange={(e) => onMerchantIdChange(e.target.value)}
            placeholder="Enter Merchant ID..."
            style={{
              background: 'var(--bg-dark-900)',
              border: '1px solid var(--border-strong)',
              color: 'var(--text-main)',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              padding: '0.35rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
              width: '180px',
              outline: 'none',
            }}
          />
        </div>
      </div>
    </header>
  );
};

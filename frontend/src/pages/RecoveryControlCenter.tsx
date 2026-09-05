import React, { useEffect, useState, useCallback } from 'react';
import { fetchRevenueSummary } from '../services/revenue';
import { RevenueSummary } from '../types/revenue';
import { FinancialImpactSection } from '../components/dashboard/FinancialImpactSection';
import { CausalImpactSection } from '../components/dashboard/CausalImpactSection';
import { CaseBreakdownTable } from '../components/dashboard/CaseBreakdownTable';
import { DashboardSkeleton } from '../components/common/LoadingSkeleton';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { EmptyState } from '../components/common/EmptyState';

export interface RecoveryControlCenterProps {
  merchantId: string;
  onNavigateToCases?: () => void;
}

export const RecoveryControlCenter: React.FC<RecoveryControlCenterProps> = ({
  merchantId,
  onNavigateToCases,
}) => {
  const [data, setData] = useState<RevenueSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const summary = await fetchRevenueSummary(merchantId);
      setData(summary);
    } catch (err: any) {
      console.error('Failed to load revenue summary:', err);
      setError(err.message || 'Unable to connect to Razorpay Revenue Recovery backend service.');
    } finally {
      setLoading(false);
    }
  }, [merchantId]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (loading) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ marginBottom: '1.5rem' }}>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff' }}>Recovery Control Center</h1>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Loading financial metrics & recovery performance...</p>
        </div>
        <DashboardSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ marginBottom: '1.5rem' }}>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff' }}>Recovery Control Center</h1>
        </div>
        <ErrorAlert
          title="Revenue Summary Service Unavailable"
          message={error}
          onRetry={loadDashboard}
        />
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        <EmptyState
          title="No Revenue Summary Available"
          description="There is no active revenue data for the specified merchant scope."
        />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', letterSpacing: '-0.02em' }}>
            Recovery Control Center
          </h1>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Real-time revenue-at-risk monitoring, verified net recovery, and causal impact evaluation
          </p>
        </div>
        <div>
          <button
            onClick={loadDashboard}
            style={{
              background: 'var(--bg-dark-700)',
              border: '1px solid var(--border-strong)',
              color: 'var(--text-main)',
              padding: '0.5rem 1rem',
              borderRadius: 'var(--radius-md)',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
            }}
          >
            ↻ Refresh Data
          </button>
        </div>
      </div>

      <FinancialImpactSection data={data} />
      <CausalImpactSection data={data} />
      <CaseBreakdownTable cases={data.cases_breakdown} onSelectCase={() => onNavigateToCases && onNavigateToCases()} />
    </div>
  );
};

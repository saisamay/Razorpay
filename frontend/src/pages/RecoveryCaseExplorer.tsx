import React, { useEffect, useState, useCallback } from 'react';
import { listRecoveryCases } from '../services/cases';
import { RecoveryCase } from '../types/cases';
import { formatINR } from '../components/common/KpiCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { EmptyState } from '../components/common/EmptyState';

export interface RecoveryCaseExplorerProps {
  merchantId: string;
  onSelectCase: (caseId: string) => void;
}

export const RecoveryCaseExplorer: React.FC<RecoveryCaseExplorerProps> = ({
  merchantId,
  onSelectCase,
}) => {
  // Cases list state
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination state
  const [limit] = useState<number>(20);
  const [offset, setOffset] = useState<number>(0);

  // Filter form state (local state before applying)
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [eligibilityFilter, setEligibilityFilter] = useState<string>('ALL');
  const [minAmountInput, setMinAmountInput] = useState<string>('');
  const [maxAmountInput, setMaxAmountInput] = useState<string>('');

  // Active query parameters state
  const [appliedFilters, setAppliedFilters] = useState<{
    status?: string;
    recoveryEligible?: boolean;
    minAmount?: number;
    maxAmount?: number;
  }>({});

  const loadCases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listRecoveryCases({
        merchantId,
        status: appliedFilters.status,
        recoveryEligible: appliedFilters.recoveryEligible,
        minAmount: appliedFilters.minAmount,
        maxAmount: appliedFilters.maxAmount,
        limit,
        offset,
      });

      setCases(res.items || []);
      setTotal(res.total || 0);
    } catch (err: any) {
      console.error('Failed to list recovery cases:', err);
      setError(err.message || 'Unable to load recovery cases from backend.');
    } finally {
      setLoading(false);
    }
  }, [merchantId, appliedFilters, limit, offset]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  const handleApplyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0); // Reset to page 1

    const newFilters: {
      status?: string;
      recoveryEligible?: boolean;
      minAmount?: number;
      maxAmount?: number;
    } = {};

    if (statusFilter !== 'ALL') {
      newFilters.status = statusFilter;
    }

    if (eligibilityFilter === 'ELIGIBLE') {
      newFilters.recoveryEligible = true;
    } else if (eligibilityFilter === 'BLOCKED') {
      newFilters.recoveryEligible = false;
    }

    if (minAmountInput.trim()) {
      const parsedMin = parseFloat(minAmountInput);
      if (!isNaN(parsedMin)) {
        newFilters.minAmount = parsedMin;
      }
    }

    if (maxAmountInput.trim()) {
      const parsedMax = parseFloat(maxAmountInput);
      if (!isNaN(parsedMax)) {
        newFilters.maxAmount = parsedMax;
      }
    }

    setAppliedFilters(newFilters);
  };

  const handleResetFilters = () => {
    setStatusFilter('ALL');
    setEligibilityFilter('ALL');
    setMinAmountInput('');
    setMaxAmountInput('');
    setOffset(0);
    setAppliedFilters({});
  };

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit) || 1;
  const startItem = total === 0 ? 0 : offset + 1;
  const endItem = Math.min(offset + limit, total);

  return (
    <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', letterSpacing: '-0.02em' }}>
            Recovery Case Explorer
          </h1>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Paginated operational case inventory, failure states, and eligibility filtering
          </p>
        </div>
        <StatusBadge status={`${total} TOTAL CASES`} variant="blue" />
      </div>

      {/* Filters Bar */}
      <form
        onSubmit={handleApplyFilters}
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          padding: '1.25rem',
          marginBottom: '1.5rem',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '0.85rem', letterSpacing: '0.05em' }}>
          Server-Side Query Filters
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', alignItems: 'end' }}>
          {/* Status Filter */}
          <div>
            <label style={{ display: 'block', fontSize: '0.775rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '0.35rem' }}>
              State Status
            </label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--bg-dark-900)',
                border: '1px solid var(--border-strong)',
                color: 'var(--text-main)',
                padding: '0.45rem 0.75rem',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.85rem',
                outline: 'none',
              }}
            >
              <option value="ALL">All States</option>
              <option value="PENDING">PENDING</option>
              <option value="IN_PROGRESS">IN_PROGRESS</option>
              <option value="RECOVERED">RECOVERED</option>
              <option value="FAILED">FAILED</option>
              <option value="ESCALATED">ESCALATED</option>
              <option value="STOPPED">STOPPED</option>
            </select>
          </div>

          {/* Eligibility Filter */}
          <div>
            <label style={{ display: 'block', fontSize: '0.775rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '0.35rem' }}>
              Recovery Eligibility
            </label>
            <select
              value={eligibilityFilter}
              onChange={(e) => setEligibilityFilter(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--bg-dark-900)',
                border: '1px solid var(--border-strong)',
                color: 'var(--text-main)',
                padding: '0.45rem 0.75rem',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.85rem',
                outline: 'none',
              }}
            >
              <option value="ALL">All Eligibility</option>
              <option value="ELIGIBLE">Eligible Only</option>
              <option value="BLOCKED">Blocked Only</option>
            </select>
          </div>

          {/* Min Amount */}
          <div>
            <label style={{ display: 'block', fontSize: '0.775rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '0.35rem' }}>
              Min Amount (₹)
            </label>
            <input
              type="number"
              placeholder="e.g. 1000"
              value={minAmountInput}
              onChange={(e) => setMinAmountInput(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--bg-dark-900)',
                border: '1px solid var(--border-strong)',
                color: 'var(--text-main)',
                fontFamily: 'var(--font-mono)',
                padding: '0.45rem 0.75rem',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.85rem',
                outline: 'none',
              }}
            />
          </div>

          {/* Max Amount */}
          <div>
            <label style={{ display: 'block', fontSize: '0.775rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '0.35rem' }}>
              Max Amount (₹)
            </label>
            <input
              type="number"
              placeholder="e.g. 50000"
              value={maxAmountInput}
              onChange={(e) => setMaxAmountInput(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--bg-dark-900)',
                border: '1px solid var(--border-strong)',
                color: 'var(--text-main)',
                fontFamily: 'var(--font-mono)',
                padding: '0.45rem 0.75rem',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.85rem',
                outline: 'none',
              }}
            />
          </div>

          {/* Action Buttons */}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="submit"
              style={{
                background: 'var(--accent-blue)',
                color: '#fff',
                border: 'none',
                padding: '0.5rem 1rem',
                borderRadius: 'var(--radius-sm)',
                fontWeight: 600,
                fontSize: '0.85rem',
                cursor: 'pointer',
                flex: 1,
              }}
            >
              Apply
            </button>
            <button
              type="button"
              onClick={handleResetFilters}
              style={{
                background: 'var(--bg-dark-700)',
                color: 'var(--text-main)',
                border: '1px solid var(--border-strong)',
                padding: '0.5rem 0.85rem',
                borderRadius: 'var(--radius-sm)',
                fontWeight: 600,
                fontSize: '0.85rem',
                cursor: 'pointer',
              }}
            >
              Reset
            </button>
          </div>
        </div>
      </form>

      {/* Loading Skeleton */}
      {loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {[1, 2, 3, 4, 5].map((i) => (
            <LoadingSkeleton key={i} height="52px" />
          ))}
        </div>
      )}

      {/* Error Alert */}
      {error && !loading && (
        <ErrorAlert title="Unable to Load Recovery Cases" message={error} onRetry={loadCases} />
      )}

      {/* Empty State */}
      {!loading && !error && cases.length === 0 && (
        <EmptyState
          title="No Recovery Cases Found"
          description="There are no recovery cases matching your selected filters for this merchant."
        />
      )}

      {/* Cases Table */}
      {!loading && !error && cases.length > 0 && (
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-lg)',
            padding: '1.25rem',
            boxShadow: 'var(--shadow-card)',
            marginBottom: '1.5rem',
          }}
        >
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-strong)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.75rem 0.75rem', fontWeight: 600 }}>Case ID</th>
                  <th style={{ padding: '0.75rem 0.75rem', fontWeight: 600 }}>Payment ID</th>
                  <th style={{ padding: '0.75rem 0.75rem', fontWeight: 600 }}>Amount</th>
                  <th style={{ padding: '0.75rem 0.75rem', fontWeight: 600 }}>State</th>
                  <th style={{ padding: '0.75rem 0.75rem', fontWeight: 600 }}>Eligibility</th>
                  <th style={{ padding: '0.75rem 0.75rem', fontWeight: 600 }}>First Seen</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => (
                  <tr
                    key={c.case_id}
                    onClick={() => onSelectCase(c.case_id)}
                    style={{
                      borderBottom: '1px solid var(--border-subtle)',
                      cursor: 'pointer',
                      transition: 'background 0.15s ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(59, 130, 246, 0.08)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <td style={{ padding: '0.75rem 0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--accent-blue)' }}>
                      {c.case_id}
                    </td>
                    <td style={{ padding: '0.75rem 0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                      {c.payment_id}
                    </td>
                    <td style={{ padding: '0.75rem 0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#fff' }}>
                      {formatINR(c.amount > 1000 ? c.amount / 100 : c.amount)}
                    </td>
                    <td style={{ padding: '0.75rem 0.75rem' }}>
                      <StatusBadge status={c.state || 'FAILED'} />
                    </td>
                    <td style={{ padding: '0.75rem 0.75rem' }}>
                      <StatusBadge
                        status={c.recovery_eligible ? 'ELIGIBLE' : 'BLOCKED'}
                        variant={c.recovery_eligible ? 'green' : 'red'}
                      />
                    </td>
                    <td style={{ padding: '0.75rem 0.75rem', color: 'var(--text-muted)', fontSize: '0.8rem', fontFamily: 'var(--font-mono)' }}>
                      {c.first_seen_at ? new Date(c.first_seen_at).toLocaleDateString() : 'N/A'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginTop: '1.25rem',
              paddingTop: '1rem',
              borderTop: '1px solid var(--border-subtle)',
              fontSize: '0.85rem',
              color: 'var(--text-secondary)',
            }}
          >
            <div>
              Showing <strong style={{ color: '#fff' }}>{startItem}–{endItem}</strong> of <strong style={{ color: '#fff' }}>{total}</strong> cases
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <button
                disabled={currentPage <= 1}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                style={{
                  background: 'var(--bg-dark-700)',
                  color: currentPage <= 1 ? 'var(--text-muted)' : 'var(--text-main)',
                  border: '1px solid var(--border-strong)',
                  padding: '0.4rem 0.85rem',
                  borderRadius: 'var(--radius-sm)',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  cursor: currentPage <= 1 ? 'not-allowed' : 'pointer',
                  opacity: currentPage <= 1 ? 0.5 : 1,
                }}
              >
                ← Previous
              </button>

              <span>
                Page <strong style={{ color: '#fff' }}>{currentPage}</strong> of <strong style={{ color: '#fff' }}>{totalPages}</strong>
              </span>

              <button
                disabled={currentPage >= totalPages}
                onClick={() => setOffset(offset + limit)}
                style={{
                  background: 'var(--bg-dark-700)',
                  color: currentPage >= totalPages ? 'var(--text-muted)' : 'var(--text-main)',
                  border: '1px solid var(--border-strong)',
                  padding: '0.4rem 0.85rem',
                  borderRadius: 'var(--radius-sm)',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  cursor: currentPage >= totalPages ? 'not-allowed' : 'pointer',
                  opacity: currentPage >= totalPages ? 0.5 : 1,
                }}
              >
                Next →
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

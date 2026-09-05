import React, { useEffect, useState, useCallback } from 'react';
import { listRecoveryCases } from '../services/cases';
import { listEscalations, resolveEscalation, Escalation } from '../services/stage3';
import { RecoveryCase } from '../types/cases';
import { KpiCard, formatINR } from '../components/common/KpiCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { DashboardSkeleton } from '../components/common/LoadingSkeleton';
import { ErrorAlert } from '../components/common/ErrorAlert';

export interface OperationsProps {
  merchantId: string;
  onSelectCase?: (caseId: string) => void;
}

export const Operations: React.FC<OperationsProps> = ({ merchantId, onSelectCase }) => {
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Selected escalation for resolution modal/panel
  const [selectedEscalation, setSelectedEscalation] = useState<Escalation | null>(null);
  const [resolutionAction, setResolutionAction] = useState<string>('RESUME_AUTOMATION');
  const [operatorId, setOperatorId] = useState<string>('op_admin_01');
  const [notes, setNotes] = useState<string>('');
  const [resolving, setResolving] = useState<boolean>(false);
  const [resolutionSuccess, setResolutionSuccess] = useState<string | null>(null);

  const loadOperationsData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [caseRes, escRes] = await Promise.all([
        listRecoveryCases({ merchantId, limit: 50 }).catch(() => ({ items: [], total: 0 })),
        listEscalations(merchantId, undefined, 50).catch(() => []),
      ]);
      setCases(caseRes.items || []);
      setEscalations(escRes || []);
    } catch (err: any) {
      console.error('Failed to load Recovery Operations data:', err);
      setError(err.message || 'Unable to connect to Stage 3 Recovery Operations API.');
    } finally {
      setLoading(false);
    }
  }, [merchantId]);

  useEffect(() => {
    loadOperationsData();
  }, [loadOperationsData]);

  const handleResolveEscalation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedEscalation) return;

    setResolving(true);
    setResolutionSuccess(null);
    try {
      await resolveEscalation(
        selectedEscalation.escalation_id,
        {
          resolution_action: resolutionAction,
          operator_id: operatorId,
          notes: notes || undefined,
        },
        merchantId
      );
      setResolutionSuccess(`Escalation ${selectedEscalation.escalation_id} resolved successfully!`);
      setSelectedEscalation(null);
      setNotes('');
      await loadOperationsData();
    } catch (err: any) {
      console.error('Resolution failed:', err);
      alert(`Resolution failed: ${err.message}`);
    } finally {
      setResolving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ marginBottom: '1.5rem' }}>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff' }}>Recovery Operations</h1>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Loading Stage 3 multi-attempt orchestrations and escalations...</p>
        </div>
        <DashboardSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ marginBottom: '1.5rem' }}>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff' }}>Recovery Operations</h1>
        </div>
        <ErrorAlert title="Stage 3 Operations Service Error" message={error} onRetry={loadOperationsData} />
      </div>
    );
  }

  const openEscalationsCount = escalations.filter((e) => e.status === 'OPEN').length;
  const resolvedEscalationsCount = escalations.filter((e) => e.status === 'RESOLVED').length;
  const eligibleCasesCount = cases.filter((c) => c.recovery_eligible).length;

  return (
    <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', letterSpacing: '-0.02em' }}>
              Recovery Operations & Orchestration
            </h1>
            <StatusBadge status="ACTIVE" label="STAGE 3 ORCHESTRATOR" />
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Stage 3 Closed-Loop Multi-Attempt Execution, Escalation Cockpit, and Stopping Rules
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', background: 'var(--bg-dark-700)', padding: '0.4rem 0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            Merchant: <strong style={{ color: '#fff' }}>{merchantId}</strong>
          </span>
          <button
            onClick={loadOperationsData}
            style={{
              background: 'var(--bg-dark-700)',
              border: '1px solid var(--border-strong)',
              color: 'var(--text-main)',
              padding: '0.5rem 1rem',
              borderRadius: 'var(--radius-md)',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ↻ Refresh Operations
          </button>
        </div>
      </div>

      {resolutionSuccess && (
        <div style={{ background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#10b981', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)', marginBottom: '1.5rem', fontSize: '0.875rem' }}>
          ✓ {resolutionSuccess}
        </div>
      )}

      {/* Operational KPI Overview Cards */}
      <section style={{ marginBottom: '2rem' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem' }}>
          <KpiCard
            title="Total Observed Cases"
            value={cases.length}
            type="number"
            subtext="Stage 1 payment recovery episodes"
            accentColor="#3b82f6"
            badge="CASE PIPELINE"
          />
          <KpiCard
            title="Recovery Eligible Cases"
            value={eligibleCasesCount}
            type="number"
            subtext="Compliant for Stage 3 retry dispatch"
            accentColor="var(--accent-emerald)"
            badge="ELIGIBLE"
          />
          <KpiCard
            title="Open Escalations"
            value={openEscalationsCount}
            type="number"
            subtext="Awaiting operator review/resolution"
            accentColor={openEscalationsCount > 0 ? "#ef4444" : "#10b981"}
            badge={openEscalationsCount > 0 ? "REQUIRES REVIEW" : "CLEARED"}
          />
          <KpiCard
            title="Resolved Escalations"
            value={resolvedEscalationsCount}
            type="number"
            subtext="Actioned by recovery operators"
            accentColor="#cbd5e1"
            badge="RESOLVED"
          />
        </div>
      </section>

      {/* Stage 3 System Lifecycle & Invariant Rules Banner */}
      <section style={{ marginBottom: '2rem' }}>
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.5rem' }}>
          <div style={{ marginBottom: '1rem' }}>
            <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff' }}>
              Stage 3 Closed-Loop Execution Invariants
            </h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Authoritative operational boundaries enforced by the Stage 3 Orchestrator
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>MAX ATTEMPTS PER CASE</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', marginTop: '0.25rem' }}>3 Attempts Max</div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>Strict upper limit on physical retries</p>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>RECOVERY ATTRIBUTION WINDOW</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', marginTop: '0.25rem' }}>72 Hours Max</div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>Max attribution window for settlement</p>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>OPERATOR ESCALATION SLA</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', marginTop: '0.25rem' }}>24 Hours SLA</div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>Max operator review resolution window</p>
            </div>
          </div>
        </div>
      </section>

      {/* Escalations Cockpit */}
      <section style={{ marginBottom: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff' }}>
            Stage 3 Recovery Escalations ({escalations.length})
          </h2>
          {openEscalationsCount > 0 && (
            <span style={{ fontSize: '0.8rem', color: '#ef4444', background: 'rgba(239, 68, 68, 0.12)', padding: '0.25rem 0.65rem', borderRadius: '9999px', border: '1px solid rgba(239, 68, 68, 0.3)', fontWeight: 600 }}>
              {openEscalationsCount} Open Action Item{openEscalationsCount === 1 ? '' : 's'}
            </span>
          )}
        </div>

        {escalations.length === 0 ? (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '2rem', textAlign: 'center' }}>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              No recovery escalations are currently logged for merchant <strong>{merchantId}</strong>.
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
              Escalations are automatically generated when attempt thresholds, systemic incident lockouts, or policy violations occur.
            </p>
          </div>
        ) : (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
                <thead>
                  <tr style={{ background: 'var(--bg-dark-700)', borderBottom: '1px solid var(--border-subtle)' }}>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Escalation ID</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Case ID</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Reason Code</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Severity</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Status</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Triggered At</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Resolution</th>
                  </tr>
                </thead>
                <tbody>
                  {escalations.map((esc) => (
                    <tr key={esc.escalation_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '0.85rem 1rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#fff' }}>
                        {esc.escalation_id}
                      </td>
                      <td style={{ padding: '0.85rem 1rem', fontFamily: 'var(--font-mono)' }}>
                        <button
                          onClick={() => onSelectCase && onSelectCase(esc.case_id)}
                          style={{ background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer', textDecoration: 'underline', padding: 0, fontFamily: 'inherit', fontWeight: 600 }}
                        >
                          {esc.case_id}
                        </button>
                      </td>
                      <td style={{ padding: '0.85rem 1rem', color: 'var(--text-main)', fontWeight: 600 }}>
                        {esc.reason_code}
                      </td>
                      <td style={{ padding: '0.85rem 1rem' }}>
                        <StatusBadge status={esc.severity} />
                      </td>
                      <td style={{ padding: '0.85rem 1rem' }}>
                        <StatusBadge status={esc.status} />
                      </td>
                      <td style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        {new Date(esc.triggered_at).toLocaleString()}
                      </td>
                      <td style={{ padding: '0.85rem 1rem' }}>
                        {esc.status === 'OPEN' ? (
                          <button
                            onClick={() => setSelectedEscalation(esc)}
                            style={{
                              background: 'var(--accent-blue)',
                              color: '#fff',
                              border: 'none',
                              padding: '0.35rem 0.75rem',
                              borderRadius: 'var(--radius-sm)',
                              fontSize: '0.775rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            Resolve...
                          </button>
                        ) : (
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                            {esc.resolution_action || 'RESOLVED'}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* Resolution Modal / Panel */}
      {selectedEscalation && (
        <section style={{ marginBottom: '2rem' }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--accent-blue)', borderRadius: 'var(--radius-lg)', padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '0.75rem' }}>
              Resolve Escalation: {selectedEscalation.escalation_id}
            </h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
              Case: <strong style={{ color: '#fff', fontFamily: 'var(--font-mono)' }}>{selectedEscalation.case_id}</strong> | Reason: <strong style={{ color: '#ef4444' }}>{selectedEscalation.reason_code}</strong>
            </p>

            <form onSubmit={handleResolveEscalation} style={{ display: 'grid', gap: '1rem', maxWidth: '600px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  Resolution Action
                </label>
                <select
                  value={resolutionAction}
                  onChange={(e) => setResolutionAction(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--bg-dark-700)',
                    border: '1px solid var(--border-strong)',
                    color: '#fff',
                    padding: '0.5rem',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '0.875rem',
                  }}
                >
                  <option value="RESUME_AUTOMATION">RESUME_AUTOMATION (Allow Stage 3 retry dispatch)</option>
                  <option value="STOP_RECOVERY">STOP_RECOVERY (Terminate recovery episode)</option>
                  <option value="CLOSE_CASE">CLOSE_CASE (Mark case as manually resolved)</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  Operator Identifier
                </label>
                <input
                  type="text"
                  value={operatorId}
                  onChange={(e) => setOperatorId(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    background: 'var(--bg-dark-700)',
                    border: '1px solid var(--border-strong)',
                    color: '#fff',
                    padding: '0.5rem',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '0.875rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  Resolution Notes
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  placeholder="Provide operator rationale..."
                  style={{
                    width: '100%',
                    background: 'var(--bg-dark-700)',
                    border: '1px solid var(--border-strong)',
                    color: '#fff',
                    padding: '0.5rem',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '0.875rem',
                  }}
                />
              </div>

              <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
                <button
                  type="submit"
                  disabled={resolving}
                  style={{
                    background: 'var(--accent-blue)',
                    color: '#fff',
                    border: 'none',
                    padding: '0.5rem 1.25rem',
                    borderRadius: 'var(--radius-md)',
                    fontWeight: 600,
                    cursor: resolving ? 'not-allowed' : 'pointer',
                  }}
                >
                  {resolving ? 'Submitting...' : 'Confirm Resolution'}
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedEscalation(null)}
                  style={{
                    background: 'var(--bg-dark-700)',
                    border: '1px solid var(--border-subtle)',
                    color: 'var(--text-secondary)',
                    padding: '0.5rem 1rem',
                    borderRadius: 'var(--radius-md)',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </section>
      )}

      {/* Active Recovery Cases Table */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', marginBottom: '1rem' }}>
          Active Recovery Cases Pipeline ({cases.length})
        </h2>

        {cases.length === 0 ? (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '2rem', textAlign: 'center' }}>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              NO ACTIVE RECOVERIES
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
              There are currently no recovery operations in progress for merchant <strong>{merchantId}</strong>.
            </p>
          </div>
        ) : (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
                <thead>
                  <tr style={{ background: 'var(--bg-dark-700)', borderBottom: '1px solid var(--border-subtle)' }}>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Case ID</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Payment ID</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Amount</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Current State</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Eligibility</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>First Seen At</th>
                    <th style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => (
                    <tr key={c.case_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '0.85rem 1rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#fff' }}>
                        {c.case_id}
                      </td>
                      <td style={{ padding: '0.85rem 1rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                        {c.payment_id}
                      </td>
                      <td style={{ padding: '0.85rem 1rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#fff' }}>
                        {formatINR(c.amount / 100)}
                      </td>
                      <td style={{ padding: '0.85rem 1rem' }}>
                        <StatusBadge status={c.state} />
                      </td>
                      <td style={{ padding: '0.85rem 1rem' }}>
                        <StatusBadge
                          status={c.recovery_eligible ? 'ELIGIBLE' : 'INELIGIBLE'}
                          label={c.recovery_eligible ? 'ELIGIBLE' : 'INELIGIBLE'}
                        />
                      </td>
                      <td style={{ padding: '0.85rem 1rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        {c.first_seen_at ? new Date(c.first_seen_at).toLocaleString() : 'N/A'}
                      </td>
                      <td style={{ padding: '0.85rem 1rem' }}>
                        <button
                          onClick={() => onSelectCase && onSelectCase(c.case_id)}
                          style={{
                            background: 'var(--bg-dark-700)',
                            border: '1px solid var(--border-strong)',
                            color: '#3b82f6',
                            padding: '0.35rem 0.75rem',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.775rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          Inspect Case →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* Stage 3 Stopping Rules Inventory Reference */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', marginBottom: '1rem' }}>
          Stage 3 Stopping Rules & Termination Reasons
        </h2>
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.5rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontWeight: 700, color: '#10b981', fontSize: '0.875rem' }}>PAYMENT_RECOVERED</div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                Payment successfully settled and reconciled in Stage 3.
              </p>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontWeight: 700, color: '#ef4444', fontSize: '0.875rem' }}>MAX_ATTEMPTS_REACHED</div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                Exhausted maximum configured attempt limit (3 attempts max).
              </p>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontWeight: 700, color: '#f59e0b', fontSize: '0.875rem' }}>RECOVERY_WINDOW_EXPIRED</div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                72-hour attribution window expired from first failure timestamp.
              </p>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontWeight: 700, color: '#ef4444', fontSize: '0.875rem' }}>F5_GOVERNANCE_DENIAL</div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                F5 Emergency Policy Kill Switch or safety rule denied execution.
              </p>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontWeight: 700, color: '#f59e0b', fontSize: '0.875rem' }}>NON_POSITIVE_EXPECTED_NET_VALUE</div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                Expected recovery net monetary value &le; execution cost.
              </p>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontWeight: 700, color: '#ef4444', fontSize: '0.875rem' }}>ACTIVE_SYSTEMIC_INCIDENT</div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                P1-A cluster signal detected active issuer/gateway downtime.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

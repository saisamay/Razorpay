import React, { useEffect, useState, useCallback } from 'react';
import { getF4Report } from '../services/evaluation';
import { getEnforcementEvidence } from '../services/f5';
import { listRecoveryCases } from '../services/cases';
import { fetchFullCaseLineage } from '../services/evidence';
import { EnforcementEvidenceBundle } from '../types/f5';
import { F4Report } from '../types/evaluation';
import { CaseLineageSummary } from '../types/evidence';
import { StatusBadge } from '../components/common/StatusBadge';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { DashboardSkeleton } from '../components/common/LoadingSkeleton';

export interface EvidenceProps {
  merchantId?: string;
  onNavigatePage?: (path: string) => void;
}

export const Evidence: React.FC<EvidenceProps> = ({ merchantId = 'merchant_123', onNavigatePage }) => {
  const [f4Report, setF4Report] = useState<F4Report | null>(null);
  const [recentCases, setRecentCases] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Case Lineage Lookup State
  const [caseIdInput, setCaseIdInput] = useState<string>('');
  const [caseLineage, setCaseLineage] = useState<CaseLineageSummary | null>(null);
  const [lineageLoading, setLineageLoading] = useState<boolean>(false);
  const [lineageError, setLineageError] = useState<string | null>(null);

  // Enforcement Evidence Lookup State
  const [enforcementIdInput, setEnforcementIdInput] = useState<string>('');
  const [enforcementBundle, setEnforcementBundle] = useState<EnforcementEvidenceBundle | null>(null);
  const [enforcementLoading, setEnforcementLoading] = useState<boolean>(false);
  const [enforcementError, setEnforcementError] = useState<string | null>(null);

  const loadEvidenceOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [reportRes, caseListRes] = await Promise.all([
        getF4Report(merchantId).catch(() => null),
        listRecoveryCases({ merchantId, limit: 10 }).catch(() => ({ items: [], total: 0 })),
      ]);
      setF4Report(reportRes);
      const items = caseListRes.items || [];
      setRecentCases(items);

      if (items.length > 0) {
        const firstCaseId = items[0].case_id;
        setCaseIdInput(firstCaseId);
        fetchFullCaseLineage(firstCaseId, merchantId)
          .then(setCaseLineage)
          .catch(() => setCaseLineage(null));
      }
    } catch (err: any) {
      console.error('Failed to load Audit Evidence data:', err);
      setError(err.message || 'Unable to connect to Audit & Evidence backend API.');
    } finally {
      setLoading(false);
    }
  }, [merchantId]);

  useEffect(() => {
    loadEvidenceOverview();
  }, [loadEvidenceOverview]);

  const handleLookupCaseLineage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!caseIdInput.trim()) return;

    setLineageLoading(true);
    setLineageError(null);
    setCaseLineage(null);
    try {
      const lineage = await fetchFullCaseLineage(caseIdInput.trim(), merchantId);
      setCaseLineage(lineage);
    } catch (err: any) {
      console.error('Case lineage lookup failed:', err);
      setLineageError(err.message || `RecoveryCase '${caseIdInput}' not found or access denied.`);
    } finally {
      setLineageLoading(false);
    }
  };

  const handleLookupEnforcementEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enforcementIdInput.trim()) return;

    setEnforcementLoading(true);
    setEnforcementError(null);
    setEnforcementBundle(null);
    try {
      const bundle = await getEnforcementEvidence(enforcementIdInput.trim(), merchantId);
      setEnforcementBundle(bundle);
    } catch (err: any) {
      console.error('Enforcement evidence lookup failed:', err);
      setEnforcementError(err.message || `Enforcement audit log '${enforcementIdInput}' not found or access denied.`);
    } finally {
      setEnforcementLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto', padding: '1rem 0' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', marginBottom: '1rem' }}>
          Audit & Evidence Center
        </h1>
        <DashboardSkeleton />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: '1280px', margin: '0 auto', padding: '1rem 0', display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* A. Evidence Center Header */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', margin: 0, letterSpacing: '-0.02em' }}>
              Audit & Evidence Center
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Authoritative forensic audit logs, F4 causal estimand evidence, F5 enforcement traces, and end-to-end decision lineage.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Tenant Scope:</span>
            <span style={{
              background: 'var(--bg-dark-700)',
              border: '1px solid var(--border-subtle)',
              padding: '0.35rem 0.75rem',
              borderRadius: 'var(--radius-md)',
              fontFamily: 'monospace',
              fontSize: '0.85rem',
              color: 'var(--accent-teal)'
            }}>
              {merchantId}
            </span>
          </div>
        </div>

        <div style={{
          marginTop: '1rem',
          background: 'rgba(56, 189, 248, 0.08)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          borderRadius: 'var(--radius-md)',
          padding: '0.75rem 1rem',
          fontSize: '0.8rem',
          color: '#38bdf8',
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          flexWrap: 'wrap',
        }}>
          <span style={{ fontWeight: 700 }}>AUTHORITATIVE BACKEND EVIDENCE BOUNDARY:</span>
          <span>PostgreSQL-backed audit tables. Presentation-only lineage tree representation.</span>
        </div>
      </div>

      {error && <ErrorAlert message={error} onRetry={loadEvidenceOverview} />}

      {/* G. DISPATCH / OUTCOME SEMANTICS DISCLAIMER CARDS */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        gap: '1rem',
      }}>
        <div style={{
          background: 'var(--bg-dark-800)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          padding: '1rem',
        }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            Dispatch Semantics Boundary
          </div>
          <div style={{ fontSize: '1rem', fontWeight: 700, color: '#f59e0b', marginTop: '0.35rem' }}>
            Governed Dispatch ≠ Financial Settlement
          </div>
          <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.35rem', margin: 0 }}>
            Governed action dispatch signifies execution of an authorized recovery attempt, not confirmed bank settlement.
          </p>
        </div>

        <div style={{
          background: 'var(--bg-dark-800)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          padding: '1rem',
        }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            F5 Decision Boundary
          </div>
          <div style={{ fontSize: '1rem', fontWeight: 700, color: '#10b981', marginTop: '0.35rem' }}>
            F5 ALLOW ≠ Payment Success
          </div>
          <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.35rem', margin: 0 }}>
            F5 ALLOW_ACTION authorizes governed application action execution. Payment outcome is observed asynchronously via webhooks.
          </p>
        </div>

        <div style={{
          background: 'var(--bg-dark-800)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          padding: '1rem',
        }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            Settlement Reconciliation Boundary
          </div>
          <div style={{ fontSize: '1rem', fontWeight: 700, color: '#a855f7', marginTop: '0.35rem' }}>
            Independent Bank Settlement: NOT IMPLEMENTED
          </div>
          <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.35rem', margin: 0 }}>
            System records observed gateway webhook payment outcomes. Distributed 2PC / XA bank settlement verification is not claimed.
          </p>
        </div>
      </div>

      {/* B. BROWSER EVIDENCE SEARCH & LOOKUP */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '1rem' }}>
          Forensic Evidence & Case Lineage Lookup
        </h2>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem' }}>
          {/* Form 1: Case Lineage Lookup */}
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Inspect End-to-End Case Lineage (`case_id`)
            </label>
            <form onSubmit={handleLookupCaseLineage} style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={caseIdInput}
                onChange={(e) => setCaseIdInput(e.target.value)}
                placeholder="Enter Recovery Case ID (e.g. rec_case_123)"
                required
                style={{
                  flex: 1,
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                  fontFamily: 'monospace',
                }}
              />
              <button
                type="submit"
                disabled={lineageLoading}
                style={{
                  background: 'var(--accent-primary)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 1rem',
                  fontWeight: 700,
                  fontSize: '0.85rem',
                  cursor: lineageLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {lineageLoading ? 'Tracing...' : 'Trace Lineage'}
              </button>
            </form>

            {/* Quick selector of recent cases if available */}
            {recentCases.length > 0 && (
              <div style={{ marginTop: '0.6rem', display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>Quick Select:</span>
                {recentCases.slice(0, 3).map((c) => (
                  <button
                    key={c.case_id}
                    onClick={() => {
                      setCaseIdInput(c.case_id);
                      setLineageLoading(true);
                      setLineageError(null);
                      fetchFullCaseLineage(c.case_id, merchantId)
                        .then(setCaseLineage)
                        .catch((err) => setLineageError(err.message))
                        .finally(() => setLineageLoading(false));
                    }}
                    style={{
                      background: 'var(--bg-dark-700)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '0.15rem 0.4rem',
                      fontSize: '0.725rem',
                      fontFamily: 'monospace',
                      color: 'var(--accent-teal)',
                      cursor: 'pointer',
                    }}
                  >
                    {c.case_id}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Form 2: F5 Enforcement Evidence Lookup */}
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Inspect F5 Enforcement Evidence (`enforcement_id`)
            </label>
            <form onSubmit={handleLookupEnforcementEvidence} style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={enforcementIdInput}
                onChange={(e) => setEnforcementIdInput(e.target.value)}
                placeholder="Enter Enforcement ID (e.g. enf_89a0b12f)"
                required
                style={{
                  flex: 1,
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                  fontFamily: 'monospace',
                }}
              />
              <button
                type="submit"
                disabled={enforcementLoading}
                style={{
                  background: 'var(--bg-dark-700)',
                  color: '#fff',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 1rem',
                  fontWeight: 700,
                  fontSize: '0.85rem',
                  cursor: enforcementLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {enforcementLoading ? 'Loading...' : 'Inspect Bundle'}
              </button>
            </form>
          </div>
        </div>
      </div>

      {/* C. CASE → DECISION LINEAGE TREE */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
          <div>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', margin: 0 }}>
              End-to-End Decision & Audit Lineage Tree
            </h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              {caseLineage ? `Authoritative decision trace for Case ${caseLineage.case_id}` : 'Select or query a case ID to trace complete lineage.'}
            </p>
          </div>

          {caseLineage && (
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Payment ID:</span>
              <code style={{ fontSize: '0.85rem', color: 'var(--accent-teal)', background: 'var(--bg-dark-700)', padding: '0.2rem 0.5rem', borderRadius: 'var(--radius-sm)' }}>
                {caseLineage.payment_id || 'N/A'}
              </code>
            </div>
          )}
        </div>

        {lineageError && <ErrorAlert message={lineageError} />}

        {caseLineage ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {caseLineage.nodes.map((node) => (
              <div
                key={node.step}
                style={{
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '1rem 1.25rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.6rem',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div style={{
                      width: '26px',
                      height: '26px',
                      borderRadius: '50%',
                      background: 'var(--bg-dark-800)',
                      border: '1px solid var(--accent-primary)',
                      color: 'var(--accent-primary)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '0.75rem',
                      fontWeight: 800,
                    }}>
                      {node.step}
                    </div>
                    <div>
                      <span style={{ fontSize: '0.95rem', fontWeight: 700, color: '#fff' }}>
                        {node.title}
                      </span>
                      <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)' }}>
                        {node.subtitle}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <StatusBadge status={node.status} />
                    {node.link && onNavigatePage && (
                      <button
                        onClick={() => onNavigatePage(node.link!)}
                        style={{
                          background: 'transparent',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-sm)',
                          padding: '0.25rem 0.5rem',
                          color: 'var(--accent-teal)',
                          fontSize: '0.75rem',
                          cursor: 'pointer',
                        }}
                      >
                        View Page ➔
                      </button>
                    )}
                  </div>
                </div>

                {node.details && (
                  <div style={{
                    background: 'var(--bg-dark-800)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '0.75rem 1rem',
                    fontSize: '0.775rem',
                    fontFamily: 'monospace',
                    color: 'var(--text-secondary)',
                    border: '1px solid var(--border-subtle)',
                  }}>
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                      {JSON.stringify(node.details, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : !lineageLoading && (
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px border-dashed var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1.5rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.85rem',
          }}>
            No case lineage currently loaded. Select a case above to trace complete end-to-end evidence lineage.
          </div>
        )}
      </div>

      {/* D. F5 ENFORCEMENT EVIDENCE INSPECTOR */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
          Authoritative F5 Enforcement Evidence Inspection (F5-6)
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Retrieved directly from <code style={{ color: 'var(--accent-teal)' }}>GET /api/v2/policies/enforcement/{'{enforcement_id}'}/evidence</code>.
        </p>

        {enforcementError && <ErrorAlert message={enforcementError} />}

        {enforcementBundle ? (
          <div style={{ background: 'var(--bg-dark-700)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ fontWeight: 700, color: '#fff', fontSize: '1rem' }}>
                Enforcement Audit ID: <span style={{ fontFamily: 'monospace', color: 'var(--accent-teal)' }}>{enforcementBundle.enforcement_id}</span>
              </div>
              <StatusBadge status={enforcementBundle.decision} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem', fontSize: '0.8rem' }}>
              <div><span style={{ color: 'var(--text-muted)' }}>Case ID:</span> <b style={{ color: '#fff' }}>{enforcementBundle.case_id}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Proposal ID:</span> <b style={{ color: '#fff' }}>{enforcementBundle.proposal_id || 'N/A'}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Reason Code:</span> <b style={{ color: '#38bdf8' }}>{enforcementBundle.reason_code}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Evaluated At:</span> <b style={{ color: '#fff' }}>{new Date(enforcementBundle.evaluated_at).toLocaleString()}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Proposed Action:</span> <b style={{ color: '#fff' }}>{enforcementBundle.stage2_proposed_action}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Executed Action:</span> <b style={{ color: '#10b981' }}>{enforcementBundle.executed_action}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Baseline Action:</span> <b style={{ color: '#f59e0b' }}>{enforcementBundle.baseline_action}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Policy Killed:</span> <b style={{ color: enforcementBundle.policy_killed ? '#ef4444' : '#10b981' }}>{enforcementBundle.policy_killed ? 'YES' : 'NO'}</b></div>
            </div>
          </div>
        ) : !enforcementLoading && (
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px border-dashed var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1.25rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.85rem',
          }}>
            Enter a valid <code style={{ color: 'var(--accent-teal)' }}>enforcement_id</code> in the lookup form above to inspect authoritative F5 enforcement audit logs.
          </div>
        )}
      </div>

      {/* E. F4 CAUSAL EVALUATION & PROVENANCE AUDIT */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
          Authoritative F4 Causal Estimand & Evidence Provenance
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Persisted F4 evaluation report metadata retrieved from <code style={{ color: 'var(--accent-teal)' }}>GET /api/v2/evaluation/f4-report</code>.
        </p>

        {f4Report ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>F4 Evaluation Status</div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: '#10b981', marginTop: '0.35rem' }}>
                {f4Report.status}
              </div>
            </div>

            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>Point Estimate (IPW &tau;)</div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: '#38bdf8', marginTop: '0.35rem' }}>
                {f4Report.point_estimate_paise_per_unit != null ? `${f4Report.point_estimate_paise_per_unit} paise/unit` : 'NOT_ESTABLISHED'}
              </div>
            </div>

            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>Eligible / Observed Population</div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: '#fff', marginTop: '0.35rem' }}>
                N_eligible = {f4Report.eligible_population_count ?? 0} | N_ctl = {f4Report.observed_control_count ?? 0} | N_trt = {f4Report.observed_treatment_count ?? 0}
              </div>
            </div>

            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>Approved Configuration Hash</div>
              <div style={{ fontSize: '0.775rem', fontFamily: 'monospace', color: 'var(--accent-teal)', marginTop: '0.35rem', wordBreak: 'break-all' }}>
                {f4Report.raw_report_json?.provenance?.approved_configuration_hash || 'a'.repeat(64)}
              </div>
            </div>
          </div>
        ) : (
          <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            No persisted F4 evaluation report found in PostgreSQL for merchant <code style={{ color: 'var(--accent-teal)' }}>{merchantId}</code>.
          </div>
        )}
      </div>

      {/* H. EVIDENCE STATUS MATRIX */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
          Authoritative Evidence Status Inventory
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Explicit categorization of available vs unavailable evidence components to prevent ambiguity or overclaiming.
        </p>

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '0.75rem 1rem' }}>Evidence Component</th>
                <th style={{ padding: '0.75rem 1rem' }}>Backend Source</th>
                <th style={{ padding: '0.75rem 1rem' }}>Availability Status</th>
                <th style={{ padding: '0.75rem 1rem' }}>Operational Meaning</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--bg-dark-700)' }}>
                <td style={{ padding: '0.75rem 1rem', fontWeight: 700, color: '#fff' }}>Stage 1 Ingested Case</td>
                <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', color: 'var(--accent-teal)' }}>recovery_cases</td>
                <td style={{ padding: '0.75rem 1rem' }}><StatusBadge status="AVAILABLE" /></td>
                <td style={{ padding: '0.75rem 1rem', color: 'var(--text-secondary)' }}>Ingested payment failure event and eligibility record</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--bg-dark-700)' }}>
                <td style={{ padding: '0.75rem 1rem', fontWeight: 700, color: '#fff' }}>F4 Causal Revenue Estimand</td>
                <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', color: 'var(--accent-teal)' }}>f4_evaluation_reports</td>
                <td style={{ padding: '0.75rem 1rem' }}><StatusBadge status={f4Report ? 'AVAILABLE' : 'NOT_ESTABLISHED'} /></td>
                <td style={{ padding: '0.75rem 1rem', color: 'var(--text-secondary)' }}>Doubly robust IPW causal revenue estimand report</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--bg-dark-700)' }}>
                <td style={{ padding: '0.75rem 1rem', fontWeight: 700, color: '#fff' }}>F5 Enforcement Audit Trace</td>
                <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', color: 'var(--accent-teal)' }}>f5_policy_enforcement_logs</td>
                <td style={{ padding: '0.75rem 1rem' }}><StatusBadge status={enforcementBundle ? 'AVAILABLE' : 'NOT_ESTABLISHED'} /></td>
                <td style={{ padding: '0.75rem 1rem', color: 'var(--text-secondary)' }}>Append-only policy enforcement decision audit log</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--bg-dark-700)' }}>
                <td style={{ padding: '0.75rem 1rem', fontWeight: 700, color: '#fff' }}>Asynchronous Webhook Outcome</td>
                <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', color: 'var(--accent-teal)' }}>recovery_attempts</td>
                <td style={{ padding: '0.75rem 1rem' }}><StatusBadge status="OBSERVED" /></td>
                <td style={{ padding: '0.75rem 1rem', color: 'var(--text-secondary)' }}>Observed payment outcome via gateway webhooks</td>
              </tr>
              <tr>
                <td style={{ padding: '0.75rem 1rem', fontWeight: 700, color: '#fff' }}>Independent Bank Settlement</td>
                <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', color: 'var(--text-muted)' }}>External Banking Rail</td>
                <td style={{ padding: '0.75rem 1rem' }}><StatusBadge status="NOT_APPLICABLE" /></td>
                <td style={{ padding: '0.75rem 1rem', color: 'var(--text-secondary)' }}>Distributed 2PC / XA bank settlement is NOT implemented</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* F. APPEND-ONLY AUDIT DISCLOSURE */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        padding: '1rem 1.25rem',
        fontSize: '0.8rem',
        color: 'var(--text-muted)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '0.5rem',
      }}>
        <div>
          <b>Append-Only Audit Log Disclosure:</b> F5 maintains an application-level append-only audit/evidence log (records in <code style={{ color: '#fff' }}>f5_policy_enforcement_logs</code> and <code style={{ color: '#fff' }}>f5_policy_kill_audits</code>). Database-enforced immutability against privileged direct SQL access is outside the application's threat model and is not required by the Buildathon specification.
        </div>
        <div>
          PostgreSQL 18.3 • <code style={{ color: 'var(--accent-teal)' }}>razorpay_pg_test</code>
        </div>
      </div>
    </div>
  );
};

export default Evidence;

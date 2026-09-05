import React, { useEffect, useState, useCallback } from 'react';
import { getF4Report } from '../services/evaluation';
import { getEnforcementEvidence, executePolicyKill } from '../services/f5';
import { listRecoveryCases } from '../services/cases';
import { getCaseAttempts } from '../services/stage3';
import { EnforcementEvidenceBundle, PolicyKillResult, KillPolicyPayload } from '../types/f5';
import { F4Report } from '../types/evaluation';
import { StatusBadge } from '../components/common/StatusBadge';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { DashboardSkeleton } from '../components/common/LoadingSkeleton';

export interface GovernanceProps {
  merchantId?: string;
}

const F5_INVARIANTS = [
  {
    id: 'F5-I001',
    name: 'FAIL_CLOSED_NO_MISSING_ALLOW',
    description: 'Missing/unknown decision cannot produce ALLOW_ACTION; strictly defaults to FALLBACK_TO_BASELINE (STOP).',
  },
  {
    id: 'F5-I002',
    name: 'COMPLETE_POLICY_BINDING_REQUIRED',
    description: 'Policy binding strictly requires merchant_id, experiment_id, experiment_version, approved_configuration_hash, and policy_version.',
  },
  {
    id: 'F5-I003',
    name: 'NON_EMPTY_F4_EVIDENCE_REFERENCE',
    description: 'A policy cannot reference an empty or corrupt F4 evidence identifier or configuration hash.',
  },
  {
    id: 'F5-I004',
    name: 'ALLOW_ACTION_REQUIRES_AUTHORIZED_ACTION',
    description: 'ALLOW_ACTION strictly requires executed_action == stage2_proposed_action, valid policy_id, and POLICY_ENFORCED_EFFICACIOUS reason.',
  },
  {
    id: 'F5-I005',
    name: 'F4_PROVENANCE_INTEGRITY_PRESERVED',
    description: 'F5 policy contracts preserve exact source F4 experiment ID, version, and configuration hash without silent normalization.',
  },
  {
    id: 'F5-I006',
    name: 'UNSAFE_POLICY_STATE_FORCES_BASELINE',
    description: 'Invalid, disabled, draft, expired, or killed policy states can only yield FALLBACK_TO_BASELINE or FAIL_CLOSED.',
  },
  {
    id: 'F5-I007',
    name: 'LIMITATION_DISCLOSURES_NON_EXECUTEABLE',
    description: 'Statistical limitation disclosures remain metadata disclosures and cannot become implicit policy rules.',
  },
  {
    id: 'F5-I008',
    name: 'EXPLICIT_POLICY_VERSIONING',
    description: 'Policy versions are explicit, non-empty, and validated.',
  },
  {
    id: 'F5-I009',
    name: 'TENANT_IDENTITY_MANDATORY',
    description: 'Merchant identity is mandatory and enforced on every policy lookup.',
  },
  {
    id: 'F5-I010',
    name: 'EXPERIMENT_VERSION_MANDATORY',
    description: 'Experiment version is mandatory and cannot be empty or whitespace.',
  },
  {
    id: 'F5-I011',
    name: 'DECISION_REASON_CONSISTENCY',
    description: 'Enforces strict consistency between decision and reason codes (blocks ALLOW_ACTION + CONFIG_HASH_MISMATCH).',
  },
  {
    id: 'F5-I012',
    name: 'EVIDENCE_SUPERSESSION_SAFETY',
    description: 'A policy superseded by conflicting F4 evidence cannot remain ACTIVE_ENFORCED; it transitions to INVALIDATED/EXPIRED.',
  },
  {
    id: 'F5-I013',
    name: 'AUTHORIZED_ACTION_SET_CARDINALITY',
    description: 'Authorized actions represent an immutable, canonically sorted, non-empty set of bounded action identifiers.',
  },
];

export const Governance: React.FC<GovernanceProps> = ({ merchantId = 'merchant_123' }) => {
  const [f4Report, setF4Report] = useState<F4Report | null>(null);
  const [authoritativeF5Decision, setAuthoritativeF5Decision] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Evidence Lookup state
  const [enforcementIdInput, setEnforcementIdInput] = useState<string>('');
  const [evidenceBundle, setEvidenceBundle] = useState<EnforcementEvidenceBundle | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState<boolean>(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

  // Kill Switch state
  const [killPolicyId, setKillPolicyId] = useState<string>('');
  const [killExperimentId, setKillExperimentId] = useState<string>('exp_recovery_v1');
  const [killExperimentVersion, setKillExperimentVersion] = useState<string>('1.0');
  const [killConfigHash, setKillConfigHash] = useState<string>('a'.repeat(64));
  const [killOperatorId, setKillOperatorId] = useState<string>('op_admin_safety');
  const [killReason, setKillReason] = useState<string>('Manual emergency safety stop triggered via F5 Governance console.');
  const [internalTokenInput, setInternalTokenInput] = useState<string>('');
  const [killing, setKilling] = useState<boolean>(false);
  const [killResult, setKillResult] = useState<PolicyKillResult | null>(null);
  const [killError, setKillError] = useState<string | null>(null);

  const loadGovernanceData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [reportRes, casesRes] = await Promise.all([
        getF4Report(merchantId).catch(() => null),
        listRecoveryCases({ merchantId, limit: 5 }).catch(() => ({ items: [], total: 0 })),
      ]);
      setF4Report(reportRes);

      let foundDecision: string | null = null;
      if (casesRes?.items && casesRes.items.length > 0) {
        for (const item of casesRes.items) {
          const attempts = await getCaseAttempts(item.case_id, merchantId).catch(() => []);
          const lastWithDecision = [...attempts].reverse().find((a) => a.enforcement_decision);
          if (lastWithDecision?.enforcement_decision) {
            foundDecision = lastWithDecision.enforcement_decision;
            break;
          }
        }
      }
      setAuthoritativeF5Decision(foundDecision);
    } catch (err: any) {
      console.error('Failed to load Governance data:', err);
      setError(err.message || 'Unable to connect to F5 Policy Safety API.');
    } finally {
      setLoading(false);
    }
  }, [merchantId]);

  useEffect(() => {
    loadGovernanceData();
  }, [loadGovernanceData]);

  const handleLookupEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enforcementIdInput.trim()) return;

    setEvidenceLoading(true);
    setEvidenceError(null);
    setEvidenceBundle(null);
    try {
      const bundle = await getEnforcementEvidence(
        enforcementIdInput.trim(),
        merchantId,
        internalTokenInput.trim() || undefined
      );
      setEvidenceBundle(bundle);
    } catch (err: any) {
      console.error('Evidence lookup failed:', err);
      setEvidenceError(err.message || `Enforcement audit log '${enforcementIdInput}' not found or access denied.`);
    } finally {
      setEvidenceLoading(false);
    }
  };

  const handleExecuteKillSwitch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!killPolicyId.trim()) {
      setKillError('Policy ID is required for emergency kill switch execution.');
      return;
    }

    if (killConfigHash.trim().length !== 64) {
      setKillError('Approved Configuration Hash must be exactly a 64-character hex string.');
      return;
    }

    setKilling(true);
    setKillError(null);
    setKillResult(null);

    const payload: KillPolicyPayload = {
      merchant_id: merchantId,
      experiment_id: killExperimentId.trim(),
      experiment_version: killExperimentVersion.trim(),
      approved_configuration_hash: killConfigHash.trim(),
      operator_id: killOperatorId.trim() || undefined,
      reason: killReason.trim() || undefined,
    };

    try {
      const res = await executePolicyKill(
        killPolicyId.trim(),
        payload,
        internalTokenInput.trim() || undefined
      );
      setKillResult(res);
    } catch (err: any) {
      console.error('Emergency Policy Kill Switch failed:', err);
      setKillError(err.message || 'Emergency Policy Kill Switch failed. Please check administrative token or scope match.');
    } finally {
      setKilling(false);
    }
  };

  if (loading) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto', padding: '1rem 0' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', marginBottom: '1rem' }}>
          F5 Policy Safety & Emergency Controls
        </h1>
        <DashboardSkeleton />
      </div>
    );
  }

  const rawJson = f4Report?.raw_report_json || {};
  const prov = rawJson.provenance || {};
  const configHash = prov.approved_configuration_hash || 'a'.repeat(64);

  // Authoritative F5 decision strictly comes from enforcement bundle or case attempts.
  // NEVER derived from f4Report.status.
  const effectiveF5Decision = evidenceBundle?.decision || authoritativeF5Decision || 'NOT_ESTABLISHED';

  const f5PolicyStatus = effectiveF5Decision !== 'NOT_ESTABLISHED' ? 'ACTIVE_ENFORCED' : 'NOT_ESTABLISHED';

  return (
    <div style={{ maxWidth: '1280px', margin: '0 auto', padding: '1rem 0', display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* Page Header */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', margin: 0, letterSpacing: '-0.02em' }}>
              F5 Policy Safety & Emergency Controls
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Authoritative real-time governance enforcement boundary, emergency policy kill switch, and evidence audit trace.
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
      </div>

      {error && <ErrorAlert message={error} onRetry={loadGovernanceData} />}

      {/* AI -> F5 -> DISPATCH -> OUTCOME Lineage Diagram */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
          System Authority & Lineage Boundary
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Strict separation between AI decision optimization, F5 safety governance enforcement, application action dispatch, and external payment outcome observation.
        </p>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '1rem',
          alignItems: 'stretch',
        }}>
          {/* Step 1: AI Recommendation */}
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem',
          }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Step 1</div>
            <div style={{ fontWeight: 700, color: '#38bdf8', fontSize: '0.95rem' }}>AI Recommendation</div>
            <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', margin: 0 }}>
              Generates statistical treatment proposal (e.g. DISPATCH_RETRY). <i>Non-authoritative.</i>
            </p>
          </div>

          {/* Arrow */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontWeight: 800 }}>
            ➔
          </div>

          {/* Step 2: Decision Proposal */}
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem',
          }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Step 2</div>
            <div style={{ fontWeight: 700, color: '#a855f7', fontSize: '0.95rem' }}>Decision Proposal</div>
            <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', margin: 0 }}>
              Binds candidate action with experiment identity and configuration hash.
            </p>
          </div>

          {/* Arrow */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontWeight: 800 }}>
            ➔
          </div>

          {/* Step 3: F5 Governance Decision */}
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px solid #10b981',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem',
          }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#10b981', textTransform: 'uppercase' }}>Step 3 • F5 Authority</div>
            <div style={{ fontWeight: 700, color: '#10b981', fontSize: '0.95rem' }}>F5 Governance</div>
            <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', margin: 0 }}>
              Evaluates ACTIVE_ENFORCED policy & F4 causal evidence. Issues <b>ALLOW</b> or <b>STOP</b>.
            </p>
          </div>

          {/* Arrow */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontWeight: 800 }}>
            ➔
          </div>

          {/* Step 4: Governed Dispatch */}
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem',
          }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Step 4</div>
            <div style={{ fontWeight: 700, color: '#f59e0b', fontSize: '0.95rem' }}>Governed Dispatch</div>
            <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', margin: 0 }}>
              Application executes authorized action. <i>(Dispatch ≠ Settlement)</i>.
            </p>
          </div>

          {/* Arrow */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontWeight: 800 }}>
            ➔
          </div>

          {/* Step 5: External Outcome Observation */}
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem',
          }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Step 5</div>
            <div style={{ fontWeight: 700, color: '#10b981', fontSize: '0.95rem' }}>Outcome Observed</div>
            <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', margin: 0 }}>
              Asynchronous payment outcome recorded from gateway webhook.
            </p>
          </div>
        </div>
      </div>

      {/* F5 Decision & Active Policy Panel */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
          <div>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', margin: 0 }}>
              Authoritative F5 Decision Policy Status
            </h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Current binding state and F4 evidence source for tenant <code style={{ color: 'var(--accent-teal)' }}>{merchantId}</code>.
            </p>
          </div>
          <div>
            <StatusBadge
              status={f5PolicyStatus}
              label={f5PolicyStatus}
            />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
          <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>F5 Enforcement Decision</div>
            <div style={{
              fontSize: '1.25rem',
              fontWeight: 800,
              marginTop: '0.5rem',
              color: effectiveF5Decision === 'ALLOW_ACTION' ? '#10b981' : (effectiveF5Decision === 'NOT_ESTABLISHED' ? 'var(--text-muted)' : '#f59e0b')
            }}>
              {effectiveF5Decision}
            </div>
            <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
              {effectiveF5Decision === 'ALLOW_ACTION' 
                ? 'Authorizes execution of Stage 2 treatment action.' 
                : (effectiveF5Decision === 'FALLBACK_TO_BASELINE' || effectiveF5Decision === 'FAIL_CLOSED'
                    ? 'Fails closed to baseline control (STOP).'
                    : 'No authoritative F5 enforcement record established for scope.')}
            </div>
          </div>

          <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>Approved Configuration Hash</div>
            <div style={{ fontSize: '0.8rem', fontFamily: 'monospace', color: 'var(--accent-teal)', marginTop: '0.5rem', wordBreak: 'break-all' }}>
              {configHash}
            </div>
            <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
              64-character SHA-256 configuration hash binding.
            </div>
          </div>

          <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>F4 Source Evidence ID</div>
            <div style={{ fontSize: '0.85rem', fontFamily: 'monospace', color: '#fff', marginTop: '0.5rem' }}>
              {f4Report?.report_id || 'NOT_ESTABLISHED'}
            </div>
            <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
              Authoritative causal estimand source reference.
            </div>
          </div>

          <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>Authorized Actions Set</div>
            <div style={{ fontSize: '0.85rem', fontFamily: 'monospace', color: '#38bdf8', marginTop: '0.5rem' }}>
              ['DISPATCH_RETRY', 'DISPATCH_RETRY_SMART']
            </div>
            <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
              Baseline Fallback Action: <b>STOP</b>
            </div>
          </div>
        </div>
      </div>

      {/* Emergency Policy Kill Switch Control Panel */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid #ef4444',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
          <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#ef4444', boxShadow: '0 0 10px #ef4444' }} />
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', margin: 0 }}>
            F5-5 Emergency Policy Safety Kill Switch
          </h2>
        </div>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Executes an immediate administrative kill switch on an active decision policy. Immediately transitions state to <code style={{ color: '#ef4444' }}>KILLED_SAFETY_STOP</code> under database row lock with <b>0ms fallback</b> to baseline control (<code style={{ color: '#f59e0b' }}>STOP</code>).
        </p>

        {killError && (
          <div style={{ marginBottom: '1rem' }}>
            <ErrorAlert message={killError} />
          </div>
        )}

        {killResult && (
          <div style={{
            background: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid #10b981',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            marginBottom: '1.25rem',
          }}>
            <div style={{ fontWeight: 700, color: '#10b981', fontSize: '0.95rem' }}>
              ✓ Emergency Kill Switch Executed Successfully {killResult.idempotent ? '(Idempotent Re-execution)' : ''}
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.5rem' }}>
              <div><b>Policy ID:</b> {killResult.policy_id}</div>
              <div><b>Previous Status:</b> {killResult.previous_status}</div>
              <div><b>New Status:</b> <span style={{ color: '#ef4444', fontWeight: 700 }}>{killResult.new_status}</span></div>
              <div><b>Effective At:</b> {new Date(killResult.kill_effective_at).toLocaleString()}</div>
            </div>
          </div>
        )}

        <form onSubmit={handleExecuteKillSwitch} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Policy ID *
              </label>
              <input
                type="text"
                value={killPolicyId}
                onChange={(e) => setKillPolicyId(e.target.value)}
                placeholder="e.g. pol_merchant_123_v1"
                required
                style={{
                  width: '100%',
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                  fontFamily: 'monospace',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Experiment ID
              </label>
              <input
                type="text"
                value={killExperimentId}
                onChange={(e) => setKillExperimentId(e.target.value)}
                required
                style={{
                  width: '100%',
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Experiment Version
              </label>
              <input
                type="text"
                value={killExperimentVersion}
                onChange={(e) => setKillExperimentVersion(e.target.value)}
                required
                style={{
                  width: '100%',
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Approved Config Hash (64-hex) *
              </label>
              <input
                type="text"
                value={killConfigHash}
                onChange={(e) => setKillConfigHash(e.target.value)}
                required
                maxLength={64}
                style={{
                  width: '100%',
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                  fontFamily: 'monospace',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Operator ID
              </label>
              <input
                type="text"
                value={killOperatorId}
                onChange={(e) => setKillOperatorId(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Internal Admin Token (`X-Internal-Token`)
              </label>
              <input
                type="password"
                value={internalTokenInput}
                onChange={(e) => setInternalTokenInput(e.target.value)}
                placeholder="Optional in dev; required if token set"
                style={{
                  width: '100%',
                  background: 'var(--bg-dark-700)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.6rem 0.8rem',
                  color: '#fff',
                  fontSize: '0.85rem',
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
              Kill Reason Description
            </label>
            <input
              type="text"
              value={killReason}
              onChange={(e) => setKillReason(e.target.value)}
              placeholder="Reason for emergency kill switch"
              style={{
                width: '100%',
                background: 'var(--bg-dark-700)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '0.6rem 0.8rem',
                color: '#fff',
                fontSize: '0.85rem',
              }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
            <button
              type="submit"
              disabled={killing}
              style={{
                background: killing ? '#991b1b' : '#dc2626',
                color: '#fff',
                border: 'none',
                borderRadius: 'var(--radius-md)',
                padding: '0.65rem 1.5rem',
                fontWeight: 700,
                fontSize: '0.875rem',
                cursor: killing ? 'not-allowed' : 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              {killing ? 'Executing Kill Switch...' : 'Execute Emergency Policy Kill Switch ➔'}
            </button>
          </div>
        </form>
      </div>

      {/* Forensic Enforcement Evidence Bundle Lookup */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
          Forensic Enforcement Evidence Bundle Lookup (F5-6)
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Reconstructs auditable forensic evidence tree traversal: <code style={{ color: 'var(--accent-teal)' }}>enforcement_id ➔ case_id ➔ proposal_id ➔ policy_id ➔ experiment_id ➔ configuration_hash ➔ source_f4_evidence_id</code>.
        </p>

        <form onSubmit={handleLookupEvidence} style={{ display: 'flex', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <input
            type="text"
            value={enforcementIdInput}
            onChange={(e) => setEnforcementIdInput(e.target.value)}
            placeholder="Enter Enforcement ID (e.g. enf_89a0b12f4d5e)"
            style={{
              flex: 1,
              minWidth: '260px',
              background: 'var(--bg-dark-700)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '0.65rem 0.85rem',
              color: '#fff',
              fontSize: '0.875rem',
              fontFamily: 'monospace',
            }}
          />
          <button
            type="submit"
            disabled={evidenceLoading}
            style={{
              background: 'var(--accent-primary)',
              color: '#fff',
              border: 'none',
              borderRadius: 'var(--radius-md)',
              padding: '0.65rem 1.25rem',
              fontWeight: 700,
              fontSize: '0.875rem',
              cursor: evidenceLoading ? 'not-allowed' : 'pointer',
            }}
          >
            {evidenceLoading ? 'Searching...' : 'Inspect Evidence Bundle'}
          </button>
        </form>

        {evidenceError && <ErrorAlert message={evidenceError} />}

        {evidenceBundle ? (
          <div style={{ background: 'var(--bg-dark-700)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ fontWeight: 700, color: '#fff', fontSize: '1rem' }}>
                Enforcement Audit Log: <span style={{ fontFamily: 'monospace', color: 'var(--accent-teal)' }}>{evidenceBundle.enforcement_id}</span>
              </div>
              <StatusBadge status={evidenceBundle.decision} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem', fontSize: '0.8rem' }}>
              <div><span style={{ color: 'var(--text-muted)' }}>Case ID:</span> <b style={{ color: '#fff' }}>{evidenceBundle.case_id}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Proposal ID:</span> <b style={{ color: '#fff' }}>{evidenceBundle.proposal_id || 'N/A'}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Reason Code:</span> <b style={{ color: '#38bdf8' }}>{evidenceBundle.reason_code}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Evaluated At:</span> <b style={{ color: '#fff' }}>{new Date(evidenceBundle.evaluated_at).toLocaleString()}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Proposed Action:</span> <b style={{ color: '#fff' }}>{evidenceBundle.stage2_proposed_action}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Executed Action:</span> <b style={{ color: '#10b981' }}>{evidenceBundle.executed_action}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Baseline Action:</span> <b style={{ color: '#f59e0b' }}>{evidenceBundle.baseline_action}</b></div>
              <div><span style={{ color: 'var(--text-muted)' }}>Policy Killed:</span> <b style={{ color: evidenceBundle.policy_killed ? '#ef4444' : '#10b981' }}>{evidenceBundle.policy_killed ? 'YES' : 'NO'}</b></div>
            </div>
          </div>
        ) : !evidenceLoading && (
          <div style={{
            background: 'var(--bg-dark-700)',
            border: '1px border-dashed var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1.25rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.85rem',
          }}>
            No enforcement evidence bundle currently loaded. Enter a valid <code style={{ color: 'var(--accent-teal)' }}>enforcement_id</code> above to inspect forensic lineage.
          </div>
        )}
      </div>

      {/* F5 Contract Invariants Inventory */}
      <div style={{
        background: 'var(--bg-dark-800)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
          Authoritative F5 Contract Invariants Inventory
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Formally enforced safety invariants preventing unauthorized recovery execution, un-governed AI dispatch, or tenant data bleeding.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '1rem' }}>
          {F5_INVARIANTS.map((inv) => (
            <div
              key={inv.id}
              style={{
                background: 'var(--bg-dark-700)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '1rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.4rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-teal)', fontFamily: 'monospace' }}>
                  {inv.id}
                </span>
                <span style={{
                  fontSize: '0.65rem',
                  fontWeight: 700,
                  background: 'rgba(16, 185, 129, 0.15)',
                  color: '#10b981',
                  padding: '0.2rem 0.5rem',
                  borderRadius: 'var(--radius-sm)',
                }}>
                  CONTRACT ENFORCED
                </span>
              </div>
              <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#fff' }}>{inv.name}</div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.4 }}>
                {inv.description}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Audit & Provenance Footer Note */}
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
          <b>Audit & Provenance Note:</b> F5 maintains an application-level append-only audit/evidence log (records in <code style={{ color: '#fff' }}>f5_policy_enforcement_logs</code> & <code style={{ color: '#fff' }}>f5_policy_kill_audits</code>).
        </div>
        <div>
          PostgreSQL 18.3 • <code style={{ color: 'var(--accent-teal)' }}>razorpay_pg_test</code>
        </div>
      </div>
    </div>
  );
};

export default Governance;

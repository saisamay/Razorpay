import React, { useEffect, useState, useCallback } from 'react';
import { getCaseEvaluationProjection } from '../services/evaluation';
import { getCaseDiagnosis, getCaseGenome } from '../services/cases';
import { getCaseAIReasoning } from '../services/ai';
import { getCaseAttempts } from '../services/stage3';
import { CaseEvaluationProjection } from '../types/evaluation';
import { CaseAIReasoningProjection } from '../types/ai';
import { RecoveryAttempt } from '../types/stage3';

import { FinancialOutcomeSection } from '../components/case/FinancialOutcomeSection';
import { DiagnosisSection } from '../components/case/DiagnosisSection';
import { GenomeSection } from '../components/case/GenomeSection';
import { AiCopilotPanel } from '../components/case/AiCopilotPanel';
import { DecisionProposalSection } from '../components/case/DecisionProposalSection';
import { AttemptsTimeline } from '../components/case/AttemptsTimeline';

import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { ErrorAlert } from '../components/common/ErrorAlert';

export interface CaseDetailProps {
  caseId: string;
  merchantId: string;
  onBackToCases: () => void;
}

export const CaseDetail: React.FC<CaseDetailProps> = ({ caseId, merchantId, onBackToCases }) => {
  // Main projection state
  const [projection, setProjection] = useState<CaseEvaluationProjection | null>(null);
  const [projLoading, setProjLoading] = useState<boolean>(true);
  const [projError, setProjError] = useState<{ status?: number; message: string } | null>(null);

  // Independent secondary states
  const [diagnosis, setDiagnosis] = useState<any | null>(null);
  const [diagLoading, setDiagLoading] = useState<boolean>(true);
  const [diagError, setDiagError] = useState<string | null>(null);

  const [genome, setGenome] = useState<any | null>(null);
  const [genomeLoading, setGenomeLoading] = useState<boolean>(true);

  const [aiReasoning, setAiReasoning] = useState<CaseAIReasoningProjection | null>(null);
  const [aiLoading, setAiLoading] = useState<boolean>(true);
  const [aiError, setAiError] = useState<string | null>(null);

  const [attempts, setAttempts] = useState<RecoveryAttempt[] | null>(null);
  const [attemptsLoading, setAttemptsLoading] = useState<boolean>(true);
  const [attemptsError, setAttemptsError] = useState<string | null>(null);

  const loadCaseData = useCallback(async () => {
    // Reset states
    setProjLoading(true);
    setProjError(null);
    setDiagLoading(true);
    setDiagError(null);
    setGenomeLoading(true);
    setAiLoading(true);
    setAiError(null);
    setAttemptsLoading(true);
    setAttemptsError(null);

    // 1. Fetch Main Projection
    getCaseEvaluationProjection(caseId, merchantId)
      .then((data) => {
        setProjection(data);
        setProjLoading(false);
      })
      .catch((err: any) => {
        setProjError({ status: err.status, message: err.message || 'Failed to load case projection' });
        setProjLoading(false);
      });

    // 2. Fetch Diagnosis
    getCaseDiagnosis(caseId, merchantId)
      .then((data) => {
        setDiagnosis(data);
        setDiagLoading(false);
      })
      .catch((err: any) => {
        setDiagError(err.message || 'Diagnosis record unavailable');
        setDiagLoading(false);
      });

    // 3. Fetch Genome
    getCaseGenome(caseId, merchantId)
      .then((data) => {
        setGenome(data);
        setGenomeLoading(false);
      })
      .catch(() => {
        setGenomeLoading(false);
      });

    // 4. Fetch AI Reasoning Copilot
    getCaseAIReasoning(caseId, merchantId)
      .then((data) => {
        setAiReasoning(data);
        setAiLoading(false);
      })
      .catch((err: any) => {
        setAiError(err.message || 'AI Copilot reasoning unavailable');
        setAiLoading(false);
      });

    // 5. Fetch Recovery Attempts
    getCaseAttempts(caseId, merchantId)
      .then((data) => {
        setAttempts(data);
        setAttemptsLoading(false);
      })
      .catch((err: any) => {
        setAttemptsError(err.message || 'Recovery attempts history unavailable');
        setAttemptsLoading(false);
      });
  }, [caseId, merchantId]);

  useEffect(() => {
    loadCaseData();
  }, [loadCaseData]);

  // Handle 404 Not Found or 403 Forbidden
  if (projError) {
    if (projError.status === 404) {
      return (
        <div style={{ maxWidth: '1000px', margin: '0 auto', paddingTop: '2rem' }}>
          <button
            onClick={onBackToCases}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent-blue)',
              fontWeight: 600,
              cursor: 'pointer',
              marginBottom: '1rem',
              fontSize: '0.9rem',
            }}
          >
            ← Back to Recovery Cases
          </button>
          <div
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-lg)',
              padding: '3rem 2rem',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>🔍</div>
            <h2 style={{ fontSize: '1.5rem', fontWeight: 800, color: '#fff', marginBottom: '0.5rem' }}>
              Recovery Case Not Found
            </h2>
            <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto 1.5rem auto', fontSize: '0.9rem' }}>
              The requested recovery case <code>{caseId}</code> does not exist in the database or is not available to merchant <code>{merchantId}</code>.
            </p>
            <button
              onClick={onBackToCases}
              style={{
                background: 'var(--accent-blue)',
                color: '#fff',
                border: 'none',
                padding: '0.6rem 1.25rem',
                borderRadius: 'var(--radius-md)',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Back to Cases List
            </button>
          </div>
        </div>
      );
    }

    if (projError.status === 403) {
      return (
        <div style={{ maxWidth: '1000px', margin: '0 auto', paddingTop: '2rem' }}>
          <button
            onClick={onBackToCases}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent-blue)',
              fontWeight: 600,
              cursor: 'pointer',
              marginBottom: '1rem',
              fontSize: '0.9rem',
            }}
          >
            ← Back to Recovery Cases
          </button>
          <div
            style={{
              background: 'rgba(239, 68, 68, 0.08)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: 'var(--radius-lg)',
              padding: '3rem 2rem',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>🛡️</div>
            <h2 style={{ fontSize: '1.5rem', fontWeight: 800, color: '#ef4444', marginBottom: '0.5rem' }}>
              Tenant Boundary Access Denied
            </h2>
            <p style={{ color: 'var(--text-main)', maxWidth: '480px', margin: '0 auto 1.5rem auto', fontSize: '0.9rem' }}>
              Authenticated merchant context <code>{merchantId}</code> is not authorized to read case <code>{caseId}</code> owned by another merchant.
            </p>
            <button
              onClick={onBackToCases}
              style={{
                background: 'var(--bg-dark-700)',
                color: '#fff',
                border: '1px solid var(--border-strong)',
                padding: '0.6rem 1.25rem',
                borderRadius: 'var(--radius-md)',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Return to Cases List
            </button>
          </div>
        </div>
      );
    }

    return (
      <div style={{ maxWidth: '1000px', margin: '0 auto', paddingTop: '2rem' }}>
        <button
          onClick={onBackToCases}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--accent-blue)',
            fontWeight: 600,
            cursor: 'pointer',
            marginBottom: '1rem',
            fontSize: '0.9rem',
          }}
        >
          ← Back to Recovery Cases
        </button>
        <ErrorAlert title="Unable to Load Case Detail" message={projError.message} onRetry={loadCaseData} />
      </div>
    );
  }

  // General Loading Skeleton for header
  if (projLoading) {
    return (
      <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
        <div style={{ marginBottom: '1.5rem' }}>
          <LoadingSkeleton height="32px" width="200px" />
          <div style={{ marginTop: '1rem' }}>
            <LoadingSkeleton height="80px" />
          </div>
        </div>
        <LoadingSkeleton height="200px" />
      </div>
    );
  }

  const rawAmount = typeof projection?.amount?.value === 'number' ? projection.amount.value : 0;
  const inrAmount = rawAmount > 1000 ? rawAmount / 100 : rawAmount; // Handle paise vs INR
  const stateStr = projection?.state?.value ? String(projection.state.value) : 'FAILED';
  const isEligible = projection?.recovery_eligible?.value === true;

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
      {/* Navigation & Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <button
          onClick={onBackToCases}
          style={{
            background: 'var(--bg-dark-800)',
            border: '1px solid var(--border-subtle)',
            color: 'var(--accent-blue)',
            padding: '0.4rem 0.85rem',
            borderRadius: 'var(--radius-md)',
            fontWeight: 600,
            fontSize: '0.85rem',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
          }}
        >
          ← Back to Recovery Cases
        </button>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Merchant:</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-main)', background: 'var(--bg-dark-800)', padding: '0.2rem 0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            {projection?.merchant_id || merchantId}
          </span>
        </div>
      </div>

      {/* Case Header Card */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          padding: '1.5rem',
          marginBottom: '1.5rem',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Recovery Case Overview
            </div>
            <h1 style={{ fontSize: '1.65rem', fontWeight: 800, color: '#fff', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
              {caseId}
            </h1>
          </div>

          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <StatusBadge status={stateStr} />
            <StatusBadge status={isEligible ? 'ELIGIBLE' : 'BLOCKED'} variant={isEligible ? 'green' : 'red'} />
          </div>
        </div>
      </div>

      {/* Section 1: Financial & Payment Context */}
      <FinancialOutcomeSection
        amount={inrAmount}
        currency={projection?.currency || 'INR'}
        state={stateStr}
        recoveryEligible={isEligible}
        eligibilityReason={projection?.compliance?.advice_code || (isEligible ? 'Compliant for retry' : 'Rule limits reached')}
        paymentId={projection?.payment_id || 'N/A'}
        orderId={projection?.order_id}
        paymentRail={projection?.payment_rail}
        stateVersion={projection?.state_version}
      />

      {/* Section 2: Failure Diagnosis */}
      <DiagnosisSection
        diagnosis={diagnosis || projection?.diagnosis}
        loading={diagLoading}
        error={diagError}
      />

      {/* Section 3: Failure DNA & Genome */}
      <GenomeSection
        genome={genome || projection?.genome}
        failureDna={projection?.failure_dna}
        loading={genomeLoading}
      />

      {/* Section 4: AI Recovery Reasoning Copilot Panel */}
      <AiCopilotPanel
        data={aiReasoning || projection?.genai_explanation as any}
        loading={aiLoading}
        error={aiError}
      />

      {/* Section 5: Stage 2 DecisionProposal & Action Matrix */}
      <DecisionProposalSection
        proposal={projection?.decision_proposal}
        actionCapabilityMatrix={projection?.action_capability_matrix}
        shadowEval={projection?.shadow_evaluation}
      />

      {/* Section 6: Stage 3 Recovery Attempt Execution Timeline */}
      <AttemptsTimeline
        attempts={attempts}
        stoppingReason={projection?.shadow_evaluation?.stopping_reason}
        loading={attemptsLoading}
        error={attemptsError}
      />
    </div>
  );
};

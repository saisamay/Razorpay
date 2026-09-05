import React, { useEffect, useState, useCallback } from 'react';
import { getF4Report } from '../services/evaluation';
import { fetchRevenueSummary } from '../services/revenue';
import { getExperiment } from '../services/experiments';
import { F4Report } from '../types/evaluation';
import { RevenueSummary } from '../types/revenue';
import { Experiment } from '../types/experiments';
import { KpiCard, formatINR } from '../components/common/KpiCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { DashboardSkeleton } from '../components/common/LoadingSkeleton';
import { ErrorAlert } from '../components/common/ErrorAlert';

export interface ExperimentsProps {
  merchantId: string;
}

export const Experiments: React.FC<ExperimentsProps> = ({ merchantId }) => {
  const [f4Report, setF4Report] = useState<F4Report | null>(null);
  const [revenueSummary, setRevenueSummary] = useState<RevenueSummary | null>(null);
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [reportRes, revRes] = await Promise.all([
        getF4Report(merchantId),
        fetchRevenueSummary(merchantId).catch(() => null),
      ]);
      setF4Report(reportRes);
      setRevenueSummary(revRes);

      if (reportRes && reportRes.experiment_id) {
        try {
          const expRes = await getExperiment(reportRes.experiment_id, reportRes.experiment_version || '1.0');
          setExperiment(expRes);
        } catch {
          setExperiment(null);
        }
      }
    } catch (err: any) {
      console.error('Failed to load Experiments / F4 report:', err);
      setError(err.message || 'Unable to fetch F4 report and experiment data.');
    } finally {
      setLoading(false);
    }
  }, [merchantId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ marginBottom: '1.5rem' }}>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff' }}>Experiments & F4 Causal Revenue</h1>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Loading F4 causal report and statistical validity data...</p>
        </div>
        <DashboardSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ marginBottom: '1.5rem' }}>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff' }}>Experiments & F4 Causal Revenue</h1>
        </div>
        <ErrorAlert title="F4 Report Service Error" message={error} onRetry={loadData} />
      </div>
    );
  }

  const isF4Available = f4Report && f4Report.status !== 'NOT_AVAILABLE';
  const hasIncremental = isF4Available && f4Report.incremental_recovered_revenue_paise != null;
  const hasCounterfactual = isF4Available && f4Report.counterfactual_control_revenue_paise != null;

  // Conversion helpers (paise to INR)
  const incrementalInr = hasIncremental ? (f4Report!.incremental_recovered_revenue_paise! / 100) : null;
  const counterfactualInr = hasCounterfactual ? (f4Report!.counterfactual_control_revenue_paise! / 100) : null;
  const pointEstimate = isF4Available ? f4Report?.point_estimate_paise_per_unit : null;

  const observedNetRecoveredInr = revenueSummary?.net_verified_recovered_inr ?? 0;
  const totalFailedVolumeInr = revenueSummary?.revenue_at_risk_inr ?? 0;
  const caseCount = revenueSummary?.case_count ?? 0;

  return (
    <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', letterSpacing: '-0.02em' }}>
              Experiments & F4 Causal Impact
            </h1>
            <StatusBadge
              status={isF4Available ? (f4Report?.status || 'VERIFIED') : 'NOT_AVAILABLE'}
              label={isF4Available ? `F4 ${f4Report?.status}` : 'NOT ESTABLISHED'}
            />
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            IPW/Hájek Causal Estimation, Counterfactual Evaluation, and Experiment Governance
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', background: 'var(--bg-dark-700)', padding: '0.4rem 0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            Merchant: <strong style={{ color: '#fff' }}>{merchantId}</strong>
          </span>
          <button
            onClick={loadData}
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
            ↻ Refresh Report
          </button>
        </div>
      </div>

      {/* Mandatory Section 17 & 36: Observed Recovery vs. F4 Causal Impact Comparison */}
      <section style={{ marginBottom: '2rem' }}>
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.5rem' }}>
          <div style={{ marginBottom: '1.25rem' }}>
            <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff' }}>
              Accounting Observed Recovery vs. F4 Causal Incremental Lift
            </h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Strict isolation of accounting settlements from counterfactual causal estimation
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.25rem', marginBottom: '1.25rem' }}>
            {/* Card 1: Observed Accounting Recovery */}
            <div style={{ background: 'rgba(59, 130, 246, 0.06)', border: '1px solid rgba(59, 130, 246, 0.25)', borderRadius: 'var(--radius-md)', padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#3b82f6' }}>
                  Observed Accounting Recovery
                </span>
                <StatusBadge status="OBSERVED" label="ACCOUNTING FACT" />
              </div>
              <div style={{ fontSize: '1.65rem', fontWeight: 800, color: '#3b82f6', fontFamily: 'var(--font-mono)', margin: '0.4rem 0' }}>
                {formatINR(observedNetRecoveredInr)}
              </div>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                Total payment recovery settlements verified across {caseCount} observed case{caseCount === 1 ? '' : 's'}. Total failed volume: {formatINR(totalFailedVolumeInr)}.
              </p>
            </div>

            {/* Card 2: F4 Causal Incremental Revenue */}
            <div style={{ background: hasIncremental ? 'rgba(16, 185, 129, 0.06)' : 'rgba(245, 158, 11, 0.06)', border: `1px solid ${hasIncremental ? 'rgba(16, 185, 129, 0.25)' : 'rgba(245, 158, 11, 0.25)'}`, borderRadius: 'var(--radius-md)', padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: hasIncremental ? '#10b981' : '#f59e0b' }}>
                  F4 Causal Incremental Revenue
                </span>
                <StatusBadge status={hasIncremental ? 'VERIFIED' : 'NOT_AVAILABLE'} label={hasIncremental ? 'F4 CAUSAL ESTIMATE' : 'NOT ESTABLISHED'} />
              </div>
              <div style={{ fontSize: '1.65rem', fontWeight: 800, color: hasIncremental ? '#10b981' : '#f59e0b', fontFamily: 'var(--font-mono)', margin: '0.4rem 0' }}>
                {hasIncremental ? formatINR(incrementalInr!) : 'Not Established'}
              </div>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                {hasIncremental
                  ? `Net counterfactual lift estimated via Hájek IPW propensity weighting against control arm.`
                  : (f4Report?.reason || 'Requires an active, pre-registered treatment vs. control experiment with F4 propensity weighting.')}
              </p>
            </div>
          </div>

          {/* Causal Notice Callout */}
          <div style={{ background: 'rgba(139, 92, 246, 0.08)', border: '1px solid rgba(139, 92, 246, 0.25)', borderRadius: 'var(--radius-sm)', padding: '0.85rem 1.1rem', fontSize: '0.825rem', color: '#c4b5fd', lineHeight: 1.5 }}>
            <strong>💡 CAUSAL IDENTIFICATION NOTICE:</strong> Observed accounting recovery represents total payment settlements. F4 causal incremental revenue calculates true net lift against a randomized control arm using IPW/Hájek estimation. The final 10-payment batch without a control arm yields observed accounting revenue, <em>NOT</em> causal incremental revenue.
          </div>
        </div>
      </section>

      {/* Causal Revenue Impact Metrics */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', marginBottom: '1rem' }}>
          Causal Revenue Estimand Metrics
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1.25rem' }}>
          <KpiCard
            title="Counterfactual Control Revenue"
            value={hasCounterfactual ? counterfactualInr : null}
            type="currency"
            isNotAvailable={!hasCounterfactual}
            notAvailableReason="F4 control arm evaluation required"
            subtext="Baseline revenue if no intervention applied"
            accentColor="#cbd5e1"
            badge="CONTROL BASELINE"
          />
          <KpiCard
            title="Observed Treatment Revenue"
            value={totalFailedVolumeInr > 0 ? totalFailedVolumeInr : null}
            type="currency"
            isNotAvailable={totalFailedVolumeInr === 0}
            notAvailableReason="No eligible treatment volume"
            subtext="Total eligible volume routed to treatment"
            accentColor="#3b82f6"
            badge="TREATMENT ARM"
          />
          <KpiCard
            title="Incremental Recovered Revenue"
            value={hasIncremental ? incrementalInr : null}
            type="currency"
            isNotAvailable={!hasIncremental}
            notAvailableReason="Pre-registered F4 report required"
            subtext="Causal lift above baseline control"
            accentColor="var(--accent-emerald)"
            badge="INCREMENTAL REVENUE"
          />
          <KpiCard
            title="Point Estimate (Paise/Unit)"
            value={pointEstimate != null ? `${pointEstimate.toFixed(2)} paise/unit` : null}
            type="text"
            isNotAvailable={pointEstimate == null}
            notAvailableReason="Estimand point estimate pending"
            subtext="Per-unit incremental revenue lift"
            accentColor="var(--accent-purple)"
            badge="POINT ESTIMATE"
          />
        </div>
      </section>

      {/* Statistical Validity & Governance Grid */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', marginBottom: '1rem' }}>
          Statistical Validity & Invariant Checks
        </h2>
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.5rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>

            <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '1rem' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Positivity Requirement
              </div>
              <div style={{ marginTop: '0.4rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <StatusBadge
                  status={f4Report?.positivity_status || 'NOT_AVAILABLE'}
                  label={f4Report?.positivity_status || 'NOT ESTABLISHED'}
                />
              </div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                Requires non-zero propensity allocation across all covariate strata.
              </p>
            </div>

            <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '1rem' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Standard Error
              </div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)', marginTop: '0.4rem' }}>
                {f4Report?.standard_error != null ? f4Report.standard_error.toFixed(4) : 'Not Established'}
              </div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                Propensity score weighted sample variance estimate.
              </p>
            </div>

            <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '1rem' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                95% Confidence Interval
              </div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)', marginTop: '0.4rem' }}>
                {f4Report?.confidence_interval_lower != null && f4Report?.confidence_interval_upper != null
                  ? `[${formatINR(f4Report.confidence_interval_lower / 100)}, ${formatINR(f4Report.confidence_interval_upper / 100)}]`
                  : 'Not Established'}
              </div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                Hájek IPW 95% confidence bounds.
              </p>
            </div>

            <div>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Estimand Target Population
              </div>
              <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', marginTop: '0.4rem' }}>
                {f4Report?.estimand_population || 'ALL_ELIGIBLE_CASES'}
              </div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                Target population boundary for causal inference.
              </p>
            </div>

            <div>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Allocation Proportion (p)
              </div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)', marginTop: '0.4rem' }}>
                {f4Report?.allocation_proportion_p != null
                  ? `${(f4Report.allocation_proportion_p * 100).toFixed(1)}% (${f4Report.allocation_proportion_p})`
                  : 'Not Established'}
              </div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                Randomized assignment probability ratio.
              </p>
            </div>

            <div>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Evaluation Timestamp
              </div>
              <div style={{ fontSize: '1.05rem', fontWeight: 600, color: '#fff', marginTop: '0.4rem' }}>
                {f4Report?.evaluated_at ? new Date(f4Report.evaluated_at).toLocaleString() : 'Not Established'}
              </div>
              <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                Authoritative timestamp of F4 evaluation report generation.
              </p>
            </div>

          </div>
        </div>
      </section>

      {/* Invalidation Reasons & Warnings Panel */}
      {f4Report?.invalidation_reasons && f4Report.invalidation_reasons.length > 0 && (
        <section style={{ marginBottom: '2rem' }}>
          <div style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 'var(--radius-md)', padding: '1.25rem' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#ef4444', marginBottom: '0.5rem' }}>
              ⚠️ F4 Report Invalidation Flags ({f4Report.invalidation_reasons.length})
            </h3>
            <ul style={{ margin: 0, paddingLeft: '1.25rem', color: 'var(--text-main)', fontSize: '0.875rem' }}>
              {f4Report.invalidation_reasons.map((reason, idx) => (
                <li key={idx} style={{ marginBottom: '0.25rem' }}>{reason}</li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {/* Experimental Population Breakdown */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', marginBottom: '1rem' }}>
          Experiment Population & Sample Counts
        </h2>
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.25rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>ELIGIBLE POPULATION</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#fff', fontFamily: 'var(--font-mono)', marginTop: '0.25rem' }}>
                {f4Report?.eligible_population_count ?? 'N/A'}
              </div>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>TREATMENT ARM SAMPLE</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#3b82f6', fontFamily: 'var(--font-mono)', marginTop: '0.25rem' }}>
                {f4Report?.observed_treatment_count ?? 'N/A'}
              </div>
            </div>
            <div style={{ background: 'var(--bg-dark-700)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>CONTROL ARM SAMPLE</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#cbd5e1', fontFamily: 'var(--font-mono)', marginTop: '0.25rem' }}>
                {f4Report?.observed_control_count ?? 'N/A'}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Experiment Governance & Design Details */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', marginBottom: '1rem' }}>
          Registered Experiment Governance & Design
        </h2>
        {experiment ? (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff' }}>{experiment.experiment_id}</h3>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Version: {experiment.experiment_version}</p>
              </div>
              <StatusBadge status={experiment.status} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', marginTop: '1rem' }}>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Allocation Ratio:</span>
                <div style={{ fontWeight: 600, color: '#fff' }}>{(experiment.allocation_ratio * 100).toFixed(1)}%</div>
              </div>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Approved Hash:</span>
                <div style={{ fontWeight: 600, color: 'var(--font-mono)', fontSize: '0.85rem' }}>{experiment.approved_configuration_hash || 'None'}</div>
              </div>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Approved By:</span>
                <div style={{ fontWeight: 600, color: '#fff' }}>{experiment.approved_by || 'Pending'}</div>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.5rem', textAlign: 'center' }}>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              No active experiment design is currently configured for merchant context <strong>{merchantId}</strong>.
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
              Experiment designs can be registered, frozen, approved, and activated via the Stage 2 Experiment Governance API (`POST /api/v2/experiments`).
            </p>
          </div>
        )}
      </section>
    </div>
  );
};

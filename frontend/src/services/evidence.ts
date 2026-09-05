import { getCaseEvaluationProjection, getF4Report } from './evaluation';
import { getCaseAttempts } from './stage3';
import { getEnforcementEvidence } from './f5';
import { CaseLineageSummary, EvidenceLineageNode } from '../types/evidence';
import { formatINR } from '../components/common/KpiCard';

export async function fetchFullCaseLineage(
  caseId: string,
  merchantId?: string
): Promise<CaseLineageSummary> {
  const [proj, attempts, f4Report] = await Promise.all([
    getCaseEvaluationProjection(caseId, merchantId).catch(() => null),
    getCaseAttempts(caseId, merchantId).catch(() => []),
    getF4Report(merchantId).catch(() => null),
  ]);

  if (!proj) {
    throw new Error(`RecoveryCase '${caseId}' not found or access denied for tenant.`);
  }

  const latestAttempt = attempts.length > 0 ? attempts[attempts.length - 1] : null;

  // Try fetching authoritative F5 enforcement evidence if an enforcement_id is linked
  let enforcementBundle = null;
  if (latestAttempt?.enforcement_id) {
    enforcementBundle = await getEnforcementEvidence(latestAttempt.enforcement_id, merchantId).catch(() => null);
  }

  const nodes: EvidenceLineageNode[] = [];

  // Node 1: Payment / Recovery Case
  nodes.push({
    step: 1,
    title: 'Payment / Recovery Case',
    subtitle: `Ingested payment failure record (${proj.payment_id})`,
    status: 'OBSERVED',
    id: proj.case_id,
    timestamp: proj.provenance?.stage1_state_version ? `State Version v${proj.provenance.stage1_state_version}` : undefined,
    details: {
      payment_id: proj.payment_id,
      order_id: proj.order_id || 'N/A',
      amount: typeof proj.amount?.value === 'number' ? formatINR(proj.amount.value) : 'N/A',
      currency: proj.currency,
      payment_rail: proj.payment_rail,
      state: proj.state?.value || 'INGESTED',
    },
    link: `/cases/${proj.case_id}`,
  });

  // Node 2: Failure Diagnosis
  nodes.push({
    step: 2,
    title: 'Failure Diagnosis',
    subtitle: proj.diagnosis ? `Class: ${proj.diagnosis.diagnosis_class || 'UNKNOWN'}` : 'Failure diagnosis record',
    status: proj.diagnosis ? 'AVAILABLE' : 'NOT_ESTABLISHED',
    id: proj.diagnosis?.diagnosis_id || null,
    details: proj.diagnosis ? {
      diagnosis_class: proj.diagnosis.diagnosis_class,
      confidence_score: proj.diagnosis.score,
      confidence_level: proj.diagnosis.confidence,
      engine_version: proj.diagnosis.engine_version,
      evidence_ids: proj.diagnosis.evidence_ids || [],
    } : null,
    link: `/cases/${proj.case_id}`,
  });

  // Node 3: Recovery Eligibility & Compliance
  nodes.push({
    step: 3,
    title: 'Recovery Eligibility & Compliance',
    subtitle: proj.compliance ? `Eligibility: ${proj.compliance.eligibility}` : 'Compliance evaluation',
    status: proj.compliance?.eligibility === 'ELIGIBLE' ? 'AVAILABLE' : 'NOT_ESTABLISHED',
    id: proj.compliance?.eligibility_id || null,
    details: proj.compliance ? {
      eligibility: proj.compliance.eligibility,
      attempts_remaining: proj.compliance.attempts_remaining,
      advice_code: proj.compliance.advice_code,
      required_delay_seconds: proj.compliance.required_delay_seconds,
      ruleset_version: proj.compliance.ruleset_version,
    } : null,
    link: `/cases/${proj.case_id}`,
  });

  // Node 4: Experiment / Randomization Assignment
  nodes.push({
    step: 4,
    title: 'Experiment & Randomization',
    subtitle: 'Treatment / Control cohort assignment link',
    status: proj.decision_proposal ? 'AVAILABLE' : 'NOT_ESTABLISHED',
    id: proj.decision_proposal?.experiment_id ? `${proj.decision_proposal.experiment_id}:v${proj.decision_proposal.experiment_version || '1.0'}` : null,
    details: proj.decision_proposal ? {
      experiment_id: proj.decision_proposal.experiment_id,
      experiment_version: proj.decision_proposal.experiment_version || '1.0',
      configuration_hash: proj.decision_proposal.configuration_hash || 'a'.repeat(64),
    } : null,
    link: '/experiments',
  });

  // Node 5: F4 Causal Revenue Evaluation (EVIDENCE ONLY - NOT F5 DECISION)
  nodes.push({
    step: 5,
    title: 'F4 Causal Revenue Evaluation',
    subtitle: f4Report?.status ? `Causal evidence status: ${f4Report.status}` : 'Causal estimand evidence',
    status: f4Report?.status === 'EFFICACY_RESULT_AVAILABLE' ? 'EVALUATED' : 'NOT_ESTABLISHED',
    id: f4Report?.report_id || null,
    timestamp: f4Report?.evaluated_at || undefined,
    details: f4Report ? {
      role: 'Causal Estimand Evidence (Consumed by F5 Governance)',
      status: f4Report.status,
      point_estimate: f4Report.point_estimate_paise_per_unit != null ? `${f4Report.point_estimate_paise_per_unit} paise/unit` : 'N/A',
      confidence_interval: (f4Report.confidence_interval_lower != null && f4Report.confidence_interval_upper != null)
        ? `[${f4Report.confidence_interval_lower}, ${f4Report.confidence_interval_upper}]`
        : 'N/A',
      eligible_population: f4Report.eligible_population_count,
      note: 'F4 status provides causal evidence. It is NOT the F5 governance decision authority.',
    } : null,
    link: '/experiments',
  });

  // Node 6: AI Reasoning & Proposal (NON-AUTHORITATIVE RECOMMENDATION)
  nodes.push({
    step: 6,
    title: 'AI Reasoning & Proposal',
    subtitle: proj.decision_proposal ? `Candidate recommendation: ${proj.decision_proposal.selected_action}` : 'AI candidate proposal',
    status: proj.decision_proposal ? 'AVAILABLE' : 'NOT_ESTABLISHED',
    id: proj.decision_proposal?.proposal_id || null,
    details: proj.decision_proposal ? {
      authority_level: 'Non-authoritative AI Recommendation (Requires F5 Governance)',
      selected_action: proj.decision_proposal.selected_action,
      expected_net_value: formatINR(proj.decision_proposal.expected_net_value_paise || 0),
      confidence_score: proj.decision_proposal.confidence_score,
      proposal_schema_version: proj.decision_proposal.proposal_schema_version,
    } : null,
    link: `/cases/${proj.case_id}`,
  });

  // Node 7: F5 Governance Decision (AUTHORITATIVE F5 ENFORCEMENT EVIDENCE ONLY)
  const f5Decision = enforcementBundle?.decision || latestAttempt?.enforcement_decision || null;
  const f5ReasonCode = enforcementBundle?.reason_code || null;
  const f5EnforcementId = enforcementBundle?.enforcement_id || latestAttempt?.enforcement_id || null;

  if (f5Decision) {
    nodes.push({
      step: 7,
      title: 'F5 Governance Decision',
      subtitle: `Authoritative F5 Decision: ${f5Decision}`,
      status: f5Decision === 'ALLOW_ACTION' ? 'ALLOW' : 'STOP',
      id: f5EnforcementId,
      timestamp: enforcementBundle?.evaluated_at || undefined,
      details: {
        governance_authority: 'F5 Decision Policy Safety Engine',
        decision: f5Decision,
        reason_code: f5ReasonCode || 'N/A',
        enforcement_id: f5EnforcementId,
        executed_action: enforcementBundle?.executed_action || (f5Decision === 'ALLOW_ACTION' ? (proj.decision_proposal?.selected_action || 'DISPATCH_RETRY') : 'STOP'),
        baseline_action: enforcementBundle?.baseline_action || 'STOP',
        policy_killed: enforcementBundle?.policy_killed || false,
      },
      link: '/governance',
    });
  } else {
    nodes.push({
      step: 7,
      title: 'F5 Governance Decision',
      subtitle: 'No authoritative F5 enforcement evidence record established for case',
      status: 'NOT_ESTABLISHED',
      details: {
        governance_authority: 'F5 Decision Policy Safety Engine',
        decision_status: 'NOT_ESTABLISHED',
        note: 'No F5 policy enforcement log record exists for this case ID in PostgreSQL.',
      },
      link: '/governance',
    });
  }

  // Node 8: Governed Dispatch Execution (APPLICATION-LEVEL ACTION EXECUTION)
  nodes.push({
    step: 8,
    title: 'Governed Dispatch / Action Execution',
    subtitle: latestAttempt ? `Attempt #${latestAttempt.attempt_number} (${latestAttempt.executed_action || latestAttempt.proposed_action})` : 'Governed action dispatch',
    status: latestAttempt ? 'EXECUTED' : 'NOT_ESTABLISHED',
    id: latestAttempt?.attempt_id || null,
    timestamp: latestAttempt?.started_at || undefined,
    details: latestAttempt ? {
      execution_level: 'Application-Level Governed Action Execution (Governed Dispatch ≠ Financial Settlement)',
      attempt_number: latestAttempt.attempt_number,
      proposed_action: latestAttempt.proposed_action,
      executed_action: latestAttempt.executed_action,
      attempt_status: latestAttempt.status,
      started_at: latestAttempt.started_at,
      completed_at: latestAttempt.completed_at || 'AWAITING_OUTCOME',
    } : {
      semantic_note: 'Governed Dispatch ≠ Financial Settlement',
    },
    link: '/operations',
  });

  // Node 9: External Asynchronous Outcome Observation
  nodes.push({
    step: 9,
    title: 'External Outcome Observation',
    subtitle: latestAttempt?.outcome_status ? `Status: ${latestAttempt.outcome_status}` : 'Webhook asynchronous outcome',
    status: latestAttempt?.outcome_status ? 'OBSERVED' : 'NOT_AVAILABLE',
    details: latestAttempt?.outcome_status ? {
      observation_source: 'External Gateway Webhook',
      outcome_status: latestAttempt.outcome_status,
      attempt_status: latestAttempt.status,
    } : {
      note: 'External payment outcome not yet observed via gateway webhook.',
    },
    link: '/operations',
  });

  // Node 10: Observed Revenue Outcome Accounting
  nodes.push({
    step: 10,
    title: 'Observed Revenue Outcome',
    subtitle: latestAttempt?.outcome_status === 'RECOVERED' ? 'Revenue Recovered' : 'Observed accounting status',
    status: latestAttempt?.outcome_status === 'RECOVERED' ? 'OBSERVED' : 'NOT_AVAILABLE',
    details: {
      accounting_source: 'PostgreSQL Raw Payment Events',
      recovered_amount: latestAttempt?.net_recovered_amount ? formatINR(latestAttempt.net_recovered_amount) : '₹0.00',
      settlement_disclaimer: 'Independent bank settlement reconciliation is NOT claimed.',
    },
  });

  return {
    case_id: proj.case_id,
    merchant_id: proj.merchant_id,
    payment_id: proj.payment_id,
    amount_inr: typeof proj.amount?.value === 'number' ? proj.amount.value / 100 : null,
    first_seen_at: proj.provenance?.first_seen_at || null,
    state: typeof proj.state?.value === 'string' ? proj.state.value : 'INGESTED',
    recovery_eligible: proj.recovery_eligible?.value === true,
    nodes,
  };
}

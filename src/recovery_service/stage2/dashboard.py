from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

dashboard_router = APIRouter(tags=["Stage 2 Primary Investigation Dashboard"])


INVESTIGATION_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Revenue Economics & Payment Recovery Investigation | Razorpay Intelligence</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-primary: #0a0d14;
      --bg-surface: #121824;
      --bg-card: #1a2234;
      --border-color: #2a364f;
      --text-primary: #f0f4fd;
      --text-secondary: #94a3b8;
      --accent-blue: #3b82f6;
      --accent-green: #10b981;
      --accent-amber: #f59e0b;
      --accent-red: #ef4444;
      --accent-purple: #8b5cf6;
      --glass-bg: rgba(26, 34, 52, 0.75);
      --glass-border: rgba(255, 255, 255, 0.08);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', sans-serif;
      background-color: var(--bg-primary);
      color: var(--text-primary);
      line-height: 1.5;
      padding: 2rem;
    }

    .container { max-width: 1280px; margin: 0 auto; }
    
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid var(--border-color);
      margin-bottom: 2rem;
    }

    h1 { font-size: 1.75rem; font-weight: 700; color: #fff; letter-spacing: -0.02em; }
    .subtitle { color: var(--text-secondary); font-size: 0.875rem; margin-top: 0.25rem; }

    .case-selector {
      display: flex;
      gap: 0.75rem;
      align-items: center;
    }

    input[type="text"] {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      color: #fff;
      padding: 0.5rem 1rem;
      border-radius: 0.375rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.875rem;
      width: 280px;
    }

    button {
      background: var(--accent-blue);
      color: #fff;
      border: none;
      padding: 0.5rem 1.25rem;
      border-radius: 0.375rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }
    button:hover { background: #2563eb; }

    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 1.5rem; }
    .col-12 { grid-column: span 12; }
    .col-8 { grid-column: span 8; }
    .col-6 { grid-column: span 6; }
    .col-4 { grid-column: span 4; }
    .col-2 { grid-column: span 2; }

    .card {
      background: var(--glass-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--glass-border);
      border-radius: 0.75rem;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }

    .card-title {
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: 1rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: #cbd5e1;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 0.5rem;
    }

    .badge {
      display: inline-block;
      padding: 0.2rem 0.6rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }

    .badge-observed { background: rgba(59, 130, 246, 0.2); color: var(--accent-blue); border: 1px solid rgba(59, 130, 246, 0.3); }
    .badge-predicted { background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); border: 1px solid rgba(139, 92, 246, 0.3); }
    .badge-verified { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-blocked { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge-shadow { background: rgba(245, 158, 11, 0.2); color: var(--accent-amber); border: 1px solid rgba(245, 158, 11, 0.3); }

    .data-row { display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
    .data-label { color: var(--text-secondary); font-size: 0.85rem; }
    .data-value { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 500; }

    .stat-card {
      background: rgba(26, 34, 52, 0.9);
      border: 1px solid var(--border-color);
      border-radius: 0.5rem;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .stat-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); font-weight: 600; margin-bottom: 0.5rem; }
    .stat-value { font-family: 'JetBrains Mono', monospace; font-size: 1.6rem; font-weight: 700; color: #fff; }
    .stat-subtext { font-size: 0.75rem; color: #64748b; margin-top: 0.4rem; }

    table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
    th, td { text-align: left; padding: 0.6rem; font-size: 0.85rem; border-bottom: 1px solid var(--border-color); }
    th { color: var(--text-secondary); font-weight: 500; }
    td { font-family: 'JetBrains Mono', monospace; }

    .ai-banner {
      background: linear-gradient(135deg, rgba(139, 92, 246, 0.15), rgba(59, 130, 246, 0.15));
      border: 1px solid rgba(139, 92, 246, 0.4);
      padding: 1rem;
      border-radius: 0.5rem;
      margin-top: 1rem;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Revenue Economics & Payment Recovery</h1>
        <div class="subtitle">Revenue-at-Risk Monitoring, Recovery Attribution & Governance Evidence | Track 03</div>
      </div>
      <div class="case-selector">
        <input type="text" id="caseIdInput" value="rc_shadow_demo_001" placeholder="Enter RecoveryCase ID">
        <button onclick="loadCaseData()">Investigate Case</button>
      </div>
    </header>

    <div id="content" class="grid">
      <!-- Loading State -->
      <div class="col-12 card" style="text-align: center; padding: 3rem;">
        <div style="font-size: 1.2rem; color: var(--text-secondary);">Loading Case Investigation & Revenue Data...</div>
      </div>
    </div>
  </div>

  <script>
    async function loadCaseData() {
      const caseId = document.getElementById('caseIdInput').value.trim();
      const contentDiv = document.getElementById('content');

      try {
        const [caseResp, revResp] = await Promise.all([
          fetch(`/api/v2/evaluation/cases/${caseId}`),
          fetch(`/api/v2/evaluation/revenue-summary`)
        ]);

        if (!caseResp.ok) {
          contentDiv.innerHTML = `
            <div class="col-12 card" style="border-color: var(--accent-red);">
              <div class="card-title" style="color: var(--accent-red);">Investigation Failed</div>
              <div style="padding: 1rem 0;">HTTP ${caseResp.status}: Unable to retrieve evaluation projection for case <code>${caseId}</code>.</div>
            </div>`;
          return;
        }

        const caseData = await caseResp.json();
        const revData = revResp.ok ? await revResp.json() : null;

        renderDashboard(caseData, revData);
      } catch (err) {
        contentDiv.innerHTML = `<div class="col-12 card" style="border-color: var(--accent-red);">Error: ${err.message}</div>`;
      }
    }

    function renderDashboard(d, rev) {
      const content = document.getElementById('content');
      
      const p0 = d.genome ? d.genome.p0_source : {};
      const p1 = d.genome ? d.genome.p1_source : {};
      const prop = d.decision_proposal || {};
      const shd = d.shadow_evaluation || {};
      const diag = d.diagnosis || {};

      const revRisk = rev ? rev.revenue_at_risk_inr : 0;
      const revEligible = rev ? rev.eligible_revenue_inr : 0;
      const revGross = rev ? rev.gross_recovered_inr : 0;
      const revNet = rev ? rev.net_verified_recovered_inr : 0;
      const revRate = rev ? (rev.recovery_rate * 100) : 0;
      const unrecovered = rev ? rev.unrecovered_revenue_inr : 0;

      content.innerHTML = `
        <!-- ======================================================== -->
        <!-- 1. REVENUE RECOVERY OVERVIEW (TRACK 03 PRIMARY SECTION) -->
        <!-- ======================================================== -->
        <div class="col-12 card" style="border-color: var(--accent-blue);">
          <div class="card-title" style="font-size: 1.1rem; color: #fff;">
            <span>1. Revenue Recovery Overview</span>
            <span class="badge badge-verified">REVENUE ECONOMICS LAYER</span>
          </div>
          <div class="grid" style="margin-top: 0.5rem;">
            <!-- Card 1: ₹ Revenue at Risk -->
            <div class="col-2 stat-card">
              <div class="stat-title">₹ Revenue at Risk</div>
              <div class="stat-value" style="color: var(--accent-amber);">₹${revRisk.toFixed(2)}</div>
              <div class="stat-subtext">Total failed volume</div>
            </div>

            <!-- Card 2: ₹ Eligible Revenue -->
            <div class="col-2 stat-card">
              <div class="stat-title">₹ Eligible Revenue</div>
              <div class="stat-value" style="color: var(--accent-blue);">₹${revEligible.toFixed(2)}</div>
              <div class="stat-subtext">Compliant volume</div>
            </div>

            <!-- Card 3: ₹ Gross Recovered -->
            <div class="col-2 stat-card">
              <div class="stat-title">₹ Gross Recovered</div>
              <div class="stat-value" style="color: #cbd5e1;">₹${revGross.toFixed(2)}</div>
              <div class="stat-subtext">Gross recovered total</div>
            </div>

            <!-- Card 4: ₹ Net Verified Recovered -->
            <div class="col-2 stat-card">
              <div class="stat-title">₹ Net Verified</div>
              <div class="stat-value" style="color: var(--accent-green);">₹${revNet.toFixed(2)}</div>
              <div class="stat-subtext">Stage 3 verified net</div>
            </div>

            <!-- Card 5: Recovery Rate -->
            <div class="col-2 stat-card">
              <div class="stat-title">Recovery Rate</div>
              <div class="stat-value" style="color: var(--accent-purple);">${revRate.toFixed(1)}%</div>
              <div class="stat-subtext">Net verified / Eligible</div>
            </div>

            <!-- Card 6: Incremental Recovery -->
            <div class="col-2 stat-card">
              <div class="stat-title">₹ Incremental</div>
              <div class="stat-value" style="font-size: 1.1rem; color: var(--text-secondary); padding-top: 0.4rem;">Not Established</div>
              <div class="stat-subtext">F4 parameter required</div>
            </div>
          </div>
        </div>

        <!-- ======================================================== -->
        <!-- 2. REVENUE BREAKDOWN & CASE-LEVEL TRACEABILITY -->
        <!-- ======================================================== -->
        <div class="col-6 card">
          <div class="card-title">
            <span>2. Revenue Breakdown</span>
            <span class="badge badge-observed">DETERMINISTIC AGGREGATION</span>
          </div>
          <table>
            <thead>
              <tr><th>Stage / Scope Metric</th><th>Monetary Value (₹)</th><th>% of Revenue at Risk</th></tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Revenue at Risk</strong></td>
                <td>₹${revRisk.toFixed(2)}</td>
                <td>100.0%</td>
              </tr>
              <tr>
                <td><strong>Eligible Revenue</strong></td>
                <td>₹${revEligible.toFixed(2)}</td>
                <td>${revRisk > 0 ? ((revEligible / revRisk) * 100).toFixed(1) : 0}%</td>
              </tr>
              <tr>
                <td><strong>Net Verified Recovered</strong></td>
                <td style="color: var(--accent-green); font-weight: 700;">₹${revNet.toFixed(2)}</td>
                <td>${revRisk > 0 ? ((revNet / revRisk) * 100).toFixed(1) : 0}%</td>
              </tr>
              <tr>
                <td><strong>Unrecovered Revenue</strong></td>
                <td style="color: var(--accent-red);">₹${unrecovered.toFixed(2)}</td>
                <td>${revRisk > 0 ? ((unrecovered / revRisk) * 100).toFixed(1) : 0}%</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Case-Level Traceability Table -->
        <div class="col-6 card">
          <div class="card-title">
            <span>Case-Level Revenue Traceability</span>
            <span class="badge badge-observed">${rev ? rev.cases_breakdown.length : 0} CASES</span>
          </div>
          <div style="max-height: 220px; overflow-y: auto;">
            <table>
              <thead>
                <tr><th>Case ID</th><th>Amount (₹)</th><th>Eligible</th><th>Outcome</th><th>Verified (₹)</th></tr>
              </thead>
              <tbody>
                ${(rev && rev.cases_breakdown.length > 0) ? rev.cases_breakdown.map(c => `
                  <tr style="${c.case_id === d.case_id ? 'background: rgba(59, 130, 246, 0.15); font-weight: bold;' : ''}">
                    <td>${c.case_id.substring(0, 16)}...</td>
                    <td>₹${c.amount_inr.toFixed(2)}</td>
                    <td><span class="badge ${c.recovery_eligible ? 'badge-verified' : 'badge-blocked'}">${c.recovery_eligible ? 'YES' : 'NO'}</span></td>
                    <td>${c.outcome_status}</td>
                    <td style="color: var(--accent-green);">₹${c.net_verified_recovered_inr.toFixed(2)}</td>
                  </tr>`).join('') : '<tr><td colspan="5" style="text-align:center; color:var(--text-secondary);">No cases found</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>

        <!-- ======================================================== -->
        <!-- PRESERVED TECHNICAL SECTIONS (BELOW REVENUE OVERVIEW)    -->
        <!-- ======================================================== -->

        <!-- Sec 3: Payment Metadata & Baseline -->
        <div class="col-6 card">
          <div class="card-title">
            <span>3. Payment Metadata</span>
            <span class="badge badge-observed">${d.state ? d.state.semantic_status : 'OBSERVED'}</span>
          </div>
          <div class="data-row"><span class="data-label">Case ID</span><span class="data-value">${d.case_id}</span></div>
          <div class="data-row"><span class="data-label">Payment ID</span><span class="data-value">${d.payment_id}</span></div>
          <div class="data-row"><span class="data-label">Order ID</span><span class="data-value">${d.order_id || 'N/A'}</span></div>
          <div class="data-row"><span class="data-label">Amount</span><span class="data-value">₹${(d.amount.value / 100).toFixed(2)} ${d.currency}</span></div>
          <div class="data-row"><span class="data-label">Payment Rail</span><span class="data-value">${d.payment_rail.toUpperCase()}</span></div>
          <div class="data-row"><span class="data-label">State Version</span><span class="data-value">v${d.state_version}</span></div>
        </div>

        <!-- Sec 13: Baseline & Execution Mode -->
        <div class="col-6 card">
          <div class="card-title">
            <span>Baseline & Shadow Mode</span>
            <span class="badge badge-shadow">PASSIVE_SHADOW</span>
          </div>
          <div class="data-row"><span class="data-label">Baseline Action (Control)</span><span class="data-value">${shd.baseline_action || 'STOP'}</span></div>
          <div class="data-row"><span class="data-label">Baseline Outcome</span><span class="data-value">${shd.baseline_outcome || 'FAILED'}</span></div>
          <div class="data-row"><span class="data-label">Stage 2 Proposed Action</span><span class="data-value" style="color: var(--accent-green);">${shd.stage2_proposed_action || 'N/A'}</span></div>
          <div class="data-row"><span class="data-label">Decision Delta</span><span class="data-value">${shd.decision_delta || 'NO_DELTA'}</span></div>
          <div class="data-row"><span class="data-label">Would Have Recovered</span><span class="data-value">₹${(shd.would_have_recovered_amount || 0).toFixed(2)}</span></div>
          <div class="data-row"><span class="data-label">Execution Authority</span><span class="data-value" style="color: var(--accent-amber);">PASSIVE (0 Actions Executed)</span></div>
        </div>

        <!-- Sec 4: Causal Diagnosis -->
        <div class="col-4 card">
          <div class="card-title">
            <span>4. Causal Diagnosis</span>
            <span class="badge badge-verified">DETERMINISTIC</span>
          </div>
          <div class="data-row"><span class="data-label">Diagnosis Class</span><span class="data-value" style="color: var(--accent-blue);">${diag.diagnosis_class || 'UNKNOWN'}</span></div>
          <div class="data-row"><span class="data-label">Confidence</span><span class="data-value">${((diag.confidence || 0) * 100).toFixed(0)}%</span></div>
          <div class="data-row"><span class="data-label">Engine Version</span><span class="data-value">v${diag.engine_version || '1.0'}</span></div>
          <div class="data-row"><span class="data-label">Score</span><span class="data-value">${diag.score || 0}</span></div>
        </div>

        <!-- Sec 5: Systemic Incident -->
        <div class="col-4 card">
          <div class="card-title">
            <span>5. Systemic Incident</span>
            <span class="badge badge-observed">${d.incident ? d.incident.status : 'NORMAL'}</span>
          </div>
          <div class="data-row"><span class="data-label">Incident ID</span><span class="data-value">${d.incident ? d.incident.incident_id : 'NO_INCIDENT'}</span></div>
          <div class="data-row"><span class="data-label">Systemic Confidence</span><span class="data-value">${d.incident ? (d.incident.confidence * 100).toFixed(0) : 0}%</span></div>
          <div class="data-row"><span class="data-label">Affected Case Count</span><span class="data-value">${d.incident ? d.incident.affected_case_count : 1}</span></div>
        </div>

        <!-- Sec 6: Compliance Gate -->
        <div class="col-4 card">
          <div class="card-title">
            <span>6. Compliance Gate</span>
            <span class="badge ${d.compliance && d.compliance.eligibility === 'ELIGIBLE' ? 'badge-verified' : 'badge-blocked'}">
              ${d.compliance ? d.compliance.eligibility : 'UNKNOWN'}
            </span>
          </div>
          <div class="data-row"><span class="data-label">Attempts Remaining</span><span class="data-value">${d.compliance ? d.compliance.attempts_remaining : 0}</span></div>
          <div class="data-row"><span class="data-label">Advice Code</span><span class="data-value">${d.compliance ? d.compliance.advice_code : 'NONE'}</span></div>
          <div class="data-row"><span class="data-label">Ruleset Version</span><span class="data-value">v${d.compliance ? d.compliance.ruleset_version : '1.0'}</span></div>
        </div>

        <!-- Sec 7: Action Capability Matrix Table -->
        <div class="col-6 card">
          <div class="card-title"><span>7. Action Capability Matrix</span></div>
          <table>
            <thead>
              <tr><th>Action</th><th>Capability</th><th>Compliance</th><th>Final Status</th></tr>
            </thead>
            <tbody>
              ${(d.action_capability_matrix || []).map(a => `
                <tr>
                  <td><strong>${a.action}</strong></td>
                  <td>${a.capability}</td>
                  <td>${a.compliance}</td>
                  <td><span class="badge ${a.status === 'ELIGIBLE' ? 'badge-verified' : 'badge-blocked'}">${a.status}</span></td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>

        <!-- Sec 8: Selected DecisionProposal -->
        <div class="col-6 card">
          <div class="card-title">
            <span>8. Selected DecisionProposal</span>
            <span class="badge badge-predicted">PROPOSED</span>
          </div>
          <div class="data-row"><span class="data-label">Selected Action</span><span class="data-value" style="color: var(--accent-purple); font-size: 1.1rem;">${prop.selected_action || 'STOP'}</span></div>
          <div class="data-row"><span class="data-label">Predicted P(Success)</span><span class="data-value">${((prop.predicted_success_probability || 0) * 100).toFixed(0)}%</span></div>
          <div class="data-row"><span class="data-label">Confidence Interval</span><span class="data-value">[${(prop.confidence_interval || [0,0]).map(n=> (n*100).toFixed(0)+'%').join(' - ')}]</span></div>
          <div class="data-row"><span class="data-label">Expected Net Value</span><span class="data-value" style="color: var(--accent-green);">₹${(prop.expected_net_value || 0).toFixed(2)}</span></div>
          <div class="data-row"><span class="data-label">Optimizer Version</span><span class="data-value">v${prop.optimizer_version || '1.0'}</span></div>
        </div>

        <!-- Sec 9: GenAI Non-Authoritative Explanation -->
        ${d.genai_explanation ? `
        <div class="col-12 card ai-banner">
          <div class="card-title" style="border-bottom: none; margin-bottom: 0.5rem;">
            <span>9. AI-Generated Decision Explanation</span>
            <span class="badge badge-shadow">NON-AUTHORITATIVE</span>
          </div>
          <div style="font-size: 0.95rem; line-height: 1.6; color: #e2e8f0;">
            "${d.genai_explanation.explanation}"
          </div>
          <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.5rem;">
            Context Allowlist: ${JSON.stringify(d.genai_explanation.sanitized_context)}
          </div>
        </div>` : ''}

        <!-- Sec 10: Decision Provenance & Version Audit -->
        <div class="col-12 card">
          <div class="card-title"><span>10. Decision Provenance & Version Audit</span></div>
          <div class="grid">
            <div class="col-4"><span class="data-label">Genome ID:</span> <span class="data-value">${p0.diagnosis_id ? 'genome_' + d.case_id : 'N/A'}</span></div>
            <div class="col-4"><span class="data-label">Proposal ID:</span> <span class="data-value">${prop.proposal_id || 'N/A'}</span></div>
            <div class="col-4"><span class="data-label">Fingerprint Hash:</span> <span class="data-value">${(p0.failure_dna_fingerprint || '').substring(0, 16)}...</span></div>
          </div>
        </div>
      `;
    }

    // Auto-load initial case
    window.addEventListener('DOMContentLoaded', loadCaseData);
  </script>
</body>
</html>
"""


@dashboard_router.get("/investigation", response_class=HTMLResponse)
@dashboard_router.get("/dashboard", response_class=HTMLResponse)
def get_investigation_ui() -> str:
    """Render Tier-1 Payment Recovery Investigation UI."""
    return INVESTIGATION_UI_HTML

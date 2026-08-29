from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

dashboard_router = APIRouter(tags=["Stage 2 Primary Investigation Dashboard"])


INVESTIGATION_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Payment Recovery Investigation | Razorpay Intelligence</title>
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
        <h1>Payment Recovery Investigation</h1>
        <div class="subtitle">Auditable, Compliance-Governed Post-Failure Recovery Intelligence | Read-Only Evaluation Interface</div>
      </div>
      <div class="case-selector">
        <input type="text" id="caseIdInput" value="rc_shadow_demo_001" placeholder="Enter RecoveryCase ID">
        <button onclick="loadCaseData()">Investigate Case</button>
      </div>
    </header>

    <div id="content" class="grid">
      <!-- Loading State -->
      <div class="col-12 card" style="text-align: center; padding: 3rem;">
        <div style="font-size: 1.2rem; color: var(--text-secondary);">Loading Case Investigation Data...</div>
      </div>
    </div>
  </div>

  <script>
    async function loadCaseData() {
      const caseId = document.getElementById('caseIdInput').value.trim();
      const contentDiv = document.getElementById('content');

      try {
        const response = await fetch(`/api/v2/evaluation/cases/${caseId}`);
        if (!response.ok) {
          contentDiv.innerHTML = `
            <div class="col-12 card" style="border-color: var(--accent-red);">
              <div class="card-title" style="color: var(--accent-red);">Investigation Failed</div>
              <div style="padding: 1rem 0;">HTTP ${response.status}: Unable to retrieve evaluation projection for case <code>${caseId}</code>.</div>
            </div>`;
          return;
        }

        const data = await response.json();
        renderDashboard(data);
      } catch (err) {
        contentDiv.innerHTML = `<div class="col-12 card" style="border-color: var(--accent-red);">Error: ${err.message}</div>`;
      }
    }

    function renderDashboard(d) {
      const content = document.getElementById('content');
      
      const p0 = d.genome ? d.genome.p0_source : {};
      const p1 = d.genome ? d.genome.p1_source : {};
      const prop = d.decision_proposal || {};
      const shd = d.shadow_evaluation || {};
      const diag = d.diagnosis || {};

      content.innerHTML = `
        <!-- Sec 1: Payment Metadata & Baseline -->
        <div class="col-6 card">
          <div class="card-title">
            <span>1. Payment Metadata</span>
            <span class="badge badge-observed">${d.state.semantic_status}</span>
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
            <span>13. Baseline & Shadow Mode</span>
            <span class="badge badge-shadow">PASSIVE_SHADOW</span>
          </div>
          <div class="data-row"><span class="data-label">Baseline Action (Control)</span><span class="data-value">${shd.baseline_action || 'STOP'}</span></div>
          <div class="data-row"><span class="data-label">Baseline Outcome</span><span class="data-value">${shd.baseline_outcome || 'FAILED'}</span></div>
          <div class="data-row"><span class="data-label">Stage 2 Proposed Action</span><span class="data-value" style="color: var(--accent-green);">${shd.stage2_proposed_action || 'N/A'}</span></div>
          <div class="data-row"><span class="data-label">Decision Delta</span><span class="data-value">${shd.decision_delta || 'NO_DELTA'}</span></div>
          <div class="data-row"><span class="data-label">Would Have Recovered</span><span class="data-value">₹${(shd.would_have_recovered_amount || 0).toFixed(2)}</span></div>
          <div class="data-row"><span class="data-label">Execution Authority</span><span class="data-value" style="color: var(--accent-amber);">PASSIVE (0 Actions Executed)</span></div>
        </div>

        <!-- Sec 3: Deterministic Diagnosis -->
        <div class="col-4 card">
          <div class="card-title">
            <span>3. Causal Diagnosis</span>
            <span class="badge badge-verified">DETERMINISTIC</span>
          </div>
          <div class="data-row"><span class="data-label">Diagnosis Class</span><span class="data-value" style="color: var(--accent-blue);">${diag.diagnosis_class || 'UNKNOWN'}</span></div>
          <div class="data-row"><span class="data-label">Confidence</span><span class="data-value">${((diag.confidence || 0) * 100).toFixed(0)}%</span></div>
          <div class="data-row"><span class="data-label">Engine Version</span><span class="data-value">v${diag.engine_version || '1.0'}</span></div>
          <div class="data-row"><span class="data-label">Score</span><span class="data-value">${diag.score || 0}</span></div>
        </div>

        <!-- Sec 5: Incident Intelligence -->
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

        <!-- Sec 8 & 9: Counterfactuals & Selected Proposal -->
        <div class="col-6 card">
          <div class="card-title">
            <span>8 & 9. Selected DecisionProposal</span>
            <span class="badge badge-predicted">PROPOSED</span>
          </div>
          <div class="data-row"><span class="data-label">Selected Action</span><span class="data-value" style="color: var(--accent-purple); font-size: 1.1rem;">${prop.selected_action || 'STOP'}</span></div>
          <div class="data-row"><span class="data-label">Predicted P(Success)</span><span class="data-value">${((prop.predicted_success_probability || 0) * 100).toFixed(0)}%</span></div>
          <div class="data-row"><span class="data-label">Confidence Interval</span><span class="data-value">[${(prop.confidence_interval || [0,0]).map(n=> (n*100).toFixed(0)+'%').join(' - ')}]</span></div>
          <div class="data-row"><span class="data-label">Expected Net Value</span><span class="data-value" style="color: var(--accent-green);">₹${(prop.expected_net_value || 0).toFixed(2)}</span></div>
          <div class="data-row"><span class="data-label">Optimizer Version</span><span class="data-value">v${prop.optimizer_version || '1.0'}</span></div>
        </div>

        <!-- Sec 12: GenAI Non-Authoritative Explanation -->
        ${d.genai_explanation ? `
        <div class="col-12 card ai-banner">
          <div class="card-title" style="border-bottom: none; margin-bottom: 0.5rem;">
            <span>12. AI-Generated Decision Explanation</span>
            <span class="badge badge-shadow">NON-AUTHORITATIVE</span>
          </div>
          <div style="font-size: 0.95rem; line-height: 1.6; color: #e2e8f0;">
            "${d.genai_explanation.explanation}"
          </div>
          <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.5rem;">
            Context Allowlist: ${JSON.stringify(d.genai_explanation.sanitized_context)}
          </div>
        </div>` : ''}

        <!-- Sec 11: Provenance & Audit -->
        <div class="col-12 card">
          <div class="card-title"><span>11. Decision Provenance & Version Audit</span></div>
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

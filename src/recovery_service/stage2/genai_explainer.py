from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .schemas import DecisionProposal, RecoveryGenome


PROHIBITED_PII_KEYS = {
    "email", "phone", "card_number", "pan", "address", "customer_name",
    "upi_id", "account_number", "raw_payload", "raw_evidence", "cvv"
}


def sanitize_genai_payload(genome: RecoveryGenome) -> dict[str, Any]:
    """Sanitize and allowlist PII-free fields for GenAI explanation context.

    Strictly enforces PDF Section 24 allowlist policy.
    """

    # Strictly allowlisted fields
    allowlisted = {
        "diagnosis_class": genome.p0_source.diagnosis_class,
        "rail": genome.p0_source.rail,
        "rail_subtype": genome.p0_source.rail_subtype,
        "time_window": genome.p0_source.failure_dna_features.get("time_window", "UNKNOWN"),
        "incident_status": genome.p1_source.incident_id != "NO_INCIDENT",
        "amount_bucket": genome.p0_source.failure_dna_features.get("amount_bucket", "UNKNOWN"),
    }

    # Verify no prohibited keys escaped
    for key in PROHIBITED_PII_KEYS:
        assert key not in allowlisted, f"Prohibited key {key} leaked into GenAI payload!"

    return allowlisted


def _call_openai_api(api_key: str, proposal: DecisionProposal, sanitized: dict[str, Any]) -> str | None:
    """Execute live OpenAI API call over sanitized context with timeout and graceful error handling."""

    prompt = (
        f"You are a post-failure recovery explanation assistant. Explain the following decision in 1-2 concise sentences for an auditor.\n"
        f"Selected Action: {proposal.selected_action}\n"
        f"Diagnosis Class: {sanitized['diagnosis_class']}\n"
        f"Rail: {sanitized['rail']}\n"
        f"Expected Net Value: {proposal.expected_net_value}\n"
        f"Incident Active: {sanitized['incident_status']}\n"
        f"Do NOT invent new payment data. Only explain the provided structured decision."
    )

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You provide auditable, non-authoritative post-failure payment recovery explanations."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 100,
        "temperature": 0.2,
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        # Fallback to local explanation generator on any API error or timeout
        return None


def generate_genai_explanation(
    proposal: DecisionProposal,
    genome: RecoveryGenome,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate human-readable decision explanation over structured DecisionProposal.

    Degrades gracefully if GenAI service is unavailable or OPENAI_API_KEY is not set.
    """
    effective_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
    sanitized = sanitize_genai_payload(genome)

    action = proposal.selected_action
    diag = sanitized["diagnosis_class"]
    net_val = proposal.expected_net_value

    explanation = None
    if effective_key:
        explanation = _call_openai_api(effective_key, proposal, sanitized)

    if not explanation:
        if action == "STOP":
            explanation = f"System selected STOP because diagnosis {diag} yields negative or non-profitable net recovery value."
        elif action == "RETRY_LATER":
            explanation = f"System scheduled retry later to avoid transient {diag} failure window and maximize net value."
        elif action == "ALTERNATE_RAIL":
            explanation = f"System selected alternate rail switching to bypass active provider degradation on {sanitized['rail']}."
        elif action == "PAYMENT_LINK":
            explanation = f"System selected customer payment link recovery to resolve {diag} with positive expected net value ₹{net_val:.2f}."
        elif action == "RE_AUTH":
            explanation = f"System selected re-authentication flow to clear {diag}."
        else:
            explanation = f"System selected action {action} based on structured evidence."

    return {
        "proposal_id": proposal.proposal_id,
        "case_id": proposal.case_id,
        "explanation": explanation,
        "sanitized_context": sanitized,
        "authoritative": False,  # Strictly non-authoritative explanation only
    }

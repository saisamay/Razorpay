"""F4 Invariant Registry (F4-I001 through F4-I031).

Provides compact machine-readable definitions for all Stage 2 Causal Evaluation invariants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class F4Invariant:
    """Machine-readable definition of an F4 Causal Evaluation invariant."""

    code: str
    name: str
    statement: str
    category: str  # METRIC, ESTIMATION, SAFETY, INTEGRITY, ACCOUNTING, LIFECYCLE


# Comprehensive registry of F4 invariants F4-I001 through F4-I031
F4_INVARIANTS: List[F4Invariant] = [
    F4Invariant(
        code="F4-I001",
        name="Primary Metric Immutability",
        statement="Primary metric is strictly VERIFIED_INCREMENTAL_RECOVERED_REVENUE and cannot be changed or overridden.",
        category="METRIC",
    ),
    F4Invariant(
        code="F4-I002",
        name="Allocation-Adjusted Estimation",
        statement="Point estimator uses sum(Y_T)/p - sum(Y_C)/(1-p) where p is pre-registered treatment allocation proportion.",
        category="ESTIMATION",
    ),
    F4Invariant(
        code="F4-I003",
        name="Mandatory Uncertainty",
        statement="Standard error, confidence interval, and cluster specification are mandatory for any primary efficacy result.",
        category="ESTIMATION",
    ),
    F4Invariant(
        code="F4-I004",
        name="Frozen Population",
        statement="Evaluation population is frozen at pre-registered allocation criteria; post-hoc exclusions are forbidden.",
        category="ACCOUNTING",
    ),
    F4Invariant(
        code="F4-I005",
        name="Explicit Compliance-Block Handling",
        statement="Quarantined or compliance-blocked units must be handled explicitly without outcome distortion.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I006",
        name="Outcome Semantic Preservation",
        statement="Semantic statuses (VERIFIED, OBSERVED, OUTCOME_PENDING, OUTCOME_UNKNOWN) must be preserved without implicit coercion.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I007",
        name="UNKNOWN != 0",
        statement="OUTCOME_UNKNOWN and OUTCOME_PENDING states must never be coerced to 0 or treated as observed zero outcome.",
        category="METRIC",
    ),
    F4Invariant(
        code="F4-I008",
        name="Verified-Only Primary Revenue",
        statement="Only verified outcomes contribute to the primary revenue calculation; unverified revenue is secondary.",
        category="METRIC",
    ),
    F4Invariant(
        code="F4-I009",
        name="Differential Attrition Monitoring",
        statement="CONTROL vs TREATMENT observation rates and gap must be monitored against an explicit configured threshold.",
        category="SAFETY",
    ),
    F4Invariant(
        code="F4-I010",
        name="Independent Safety Stopping",
        statement="Breaching the differential attrition threshold triggers independent safety stopping (SAFETY_STOPPED).",
        category="SAFETY",
    ),
    F4Invariant(
        code="F4-I011",
        name="No Efficacy Claim from Safety-Stopped Partial Data",
        statement="Safety-stopped evaluations cannot issue efficacy claims if the efficacy horizon is unreached.",
        category="SAFETY",
    ),
    F4Invariant(
        code="F4-I012",
        name="Fixed-Horizon Efficacy",
        statement="Efficacy evaluation is evaluated strictly at pre-registered evaluation horizon.",
        category="LIFECYCLE",
    ),
    F4Invariant(
        code="F4-I013",
        name="Invalidation Handling",
        statement="Experiment invalidation flags force EXPERIMENT_INVALIDATED status and prohibit efficacy claims.",
        category="LIFECYCLE",
    ),
    F4Invariant(
        code="F4-I014",
        name="Version Consistency",
        statement="Configuration hash, assignment version, and observation schemas must match expected version.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I015",
        name="No Cross-Version Pooling",
        statement="Observations across different experiment versions cannot be pooled into a single point estimate.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I016",
        name="Explicit Control-Arm Semantics",
        statement="Control arm baseline observation semantics must be strictly maintained.",
        category="ACCOUNTING",
    ),
    F4Invariant(
        code="F4-I017",
        name="Net Verified Recovery",
        statement="Revenue metrics reflect net verified value after deducting refunds/chargebacks within window.",
        category="METRIC",
    ),
    F4Invariant(
        code="F4-I018",
        name="Attribution Window",
        statement="Outcomes are strictly bounded by the pre-registered attribution window.",
        category="LIFECYCLE",
    ),
    F4Invariant(
        code="F4-I019",
        name="Read-Only Upstream Behavior",
        statement="F4 consumes upstream assignment, outcome, and design data read-only without side effects.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I020",
        name="Assignment-Unit Correlation",
        statement="Uncertainty calculations must account for clustering by assignment_unit_id and assignment_unit_type.",
        category="ESTIMATION",
    ),
    F4Invariant(
        code="F4-I021",
        name="Denominator Preservation",
        statement="Population accounting denominators must be strictly preserved across filtering.",
        category="ACCOUNTING",
    ),
    F4Invariant(
        code="F4-I022",
        name="Sourced Statistical Assumptions",
        statement="All statistical assumptions must be explicitly documented and sourced.",
        category="ESTIMATION",
    ),
    F4Invariant(
        code="F4-I023",
        name="Insufficient-Data Semantics",
        statement="INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM is returned when data threshold or horizon is unreached.",
        category="LIFECYCLE",
    ),
    F4Invariant(
        code="F4-I024",
        name="Tenant Isolation",
        statement="Evaluations are strictly isolated per tenant/merchant context.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I025",
        name="Primary-Metric Data-Loss Invalidation",
        statement="Data loss or missing primary metric observations invalidate efficacy calculation.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I026",
        name="Timestamp Integrity",
        statement="Temporal ordering of assignment, observation, and attribution strictly enforced.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I027",
        name="Configuration-Hash Integrity",
        statement="Configuration hash must strictly match frozen approved experiment configuration.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I028",
        name="Contamination Handling",
        statement="Cross-arm or cross-experiment contamination forces experiment invalidation.",
        category="SAFETY",
    ),
    F4Invariant(
        code="F4-I029",
        name="Outcome-Linkage Integrity",
        statement="Outcomes must be strictly linked to valid assignment records.",
        category="INTEGRITY",
    ),
    F4Invariant(
        code="F4-I030",
        name="Verified-Only Primary Result",
        statement="Primary efficacy result relies exclusively on verified recovery outcomes.",
        category="METRIC",
    ),
    F4Invariant(
        code="F4-I031",
        name="Secondary Metrics Structurally Subordinate",
        statement="Secondary metrics cannot override or substitute for primary evaluation results.",
        category="METRIC",
    ),
]

F4_INVARIANTS_REGISTRY: Dict[str, F4Invariant] = {
    inv.code: inv for inv in F4_INVARIANTS
}


def get_invariant(code: str) -> Optional[F4Invariant]:
    """Retrieve an F4 invariant by code (e.g. F4-I001)."""
    return F4_INVARIANTS_REGISTRY.get(code.upper())


def list_invariants(category: Optional[str] = None) -> List[F4Invariant]:
    """List all registered F4 invariants, optionally filtered by category."""
    if category is None:
        return list(F4_INVARIANTS)
    cat_upper = category.upper()
    return [inv for inv in F4_INVARIANTS if inv.category == cat_upper]

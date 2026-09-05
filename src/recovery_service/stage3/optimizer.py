from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..stage2.capability_matrix import ActionTypes, CAPABILITY_RULESET_VERSION
from ..stage2.f4.contracts import EvaluationStatus
from ..stage2.f5.contracts import (
    AuthorizedActionSet,
    DecisionPolicyAuthorization,
    EvidenceSupersessionStatus,
    PolicyBinding,
    PolicyStatus,
    SourceF4EvidenceReference,
)
from ..stage2.f5.repository import (
    get_active_policy_for_binding,
    get_policy_by_id,
    save_policy,
)
from ..stage2.models import DecisionPolicyRecord
from .models import Stage3OptimizationCandidate, Stage3PolicyPerformanceProjection
from .repository import (
    Stage3OptimizationCandidateRepository,
    Stage3PolicyPerformanceRepository,
)
from .schemas import CandidateStatus, OptimizationCandidateResult, ProjectionStatus

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def compute_candidate_id(
    merchant_id: str,
    source_projection_id: str,
    proposed_action: str,
    optimizer_version: str = "1.0",
) -> str:
    """Computes a deterministic, collision-proof canonical candidate ID (Option A).

    Uses true length-prefixed canonical encoding:
    len(merchant_id):merchant_id:len(source_projection_id):source_projection_id:len(proposed_action):proposed_action:len(optimizer_version):optimizer_version
    """
    fields = [merchant_id, source_projection_id, proposed_action, optimizer_version]
    parts = []
    for f in fields:
        if f is None:
            parts.append("-1:NULL")
        else:
            val = str(f)
            parts.append(f"{len(val.encode('utf-8'))}:{val}")

    canonical_bytes = ":".join(parts).encode("utf-8")
    return f"cand_{hashlib.sha256(canonical_bytes).hexdigest()[:32]}"


def compute_f5_policy_id(candidate_id: str) -> str:
    """Derives a stable, deterministic F5 policy ID for crash-consistent idempotency."""
    return f"pol_cand_{hashlib.sha256(candidate_id.encode('utf-8')).hexdigest()[:24]}"


def resolve_f4_evidence(
    session: Session,
    merchant_id: str,
    experiment_id: str | None,
    experiment_version: str | None,
    configuration_hash: str | None,
) -> dict[str, Any] | None:
    """Resolves applicable F4 evidence reference using the exact applicability predicate.

    Selects the latest evidence bundle by max generated_at timestamp.
    """
    if not experiment_id or not experiment_version or not configuration_hash:
        return None

    # Query active DecisionPolicyRecord or F4 evidence references for matching scope
    stmt = (
        select(DecisionPolicyRecord)
        .where(
            DecisionPolicyRecord.merchant_id == merchant_id,
            DecisionPolicyRecord.experiment_id == experiment_id,
            DecisionPolicyRecord.experiment_version == experiment_version,
            DecisionPolicyRecord.approved_configuration_hash == configuration_hash,
            DecisionPolicyRecord.source_f4_status == EvaluationStatus.EFFICACY_RESULT_AVAILABLE.value,
        )
        .order_by(DecisionPolicyRecord.created_at.desc())
    )

    records = list(session.scalars(stmt).all())
    if not records:
        return None

    # Filter records where supersession_status != SUPERSEDED_CONFLICT
    valid_records = [
        r for r in records if r.supersession_status != EvidenceSupersessionStatus.SUPERSEDED_CONFLICT.value
    ]
    if not valid_records:
        return None

    latest = valid_records[0]
    return {
        "source_f4_evidence_id": latest.source_f4_evidence_id,
        "source_f4_evaluated_at": latest.source_f4_evaluated_at,
        "source_f4_status": EvaluationStatus(latest.source_f4_status),
        "source_f4_configuration_hash": latest.source_f4_configuration_hash,
        "source_f4_point_estimate": latest.source_f4_point_estimate,
        "source_f4_confidence_interval_lower": latest.source_f4_confidence_interval_lower,
        "source_f4_confidence_interval_upper": latest.source_f4_confidence_interval_upper,
        "statistical_limitations": list(latest.statistical_limitations or []),
        "supersession_status": EvidenceSupersessionStatus(latest.supersession_status),
    }


def generate_optimization_candidate(
    session: Session,
    source_projection_id: str,
    *,
    projection_repository: Stage3PolicyPerformanceRepository = Stage3PolicyPerformanceRepository(),
    candidate_repository: Stage3OptimizationCandidateRepository = Stage3OptimizationCandidateRepository(),
    min_sample_size: int = 10,
    min_action_sample_size: int = 10,
    min_net_improvement_threshold: float = 10.0,
    max_allowed_rate_degradation: float = 0.0,
    max_projection_age_hours: int = 72,
    optimizer_version: str = "1.0",
) -> OptimizationCandidateResult:
    """Executes Stage 3-3 Strategy / Treatment Optimization Candidate Generation.

    Follows the 23-step deterministic algorithm approved in S3-3 PRE-IMPLEMENTATION VERIFICATION.
    Calculates per-observation net recovery value V(a) = total_net / N_a and evaluates candidates
    against the S3-3 operational baseline derived from S3-2 observed execution.
    """
    # 1. Projection Lookup & Tenant Validation
    projection = projection_repository.get_projection(session, source_projection_id)
    if projection is None:
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id="UNKNOWN",
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=None,
            objective_value=None,
            baseline_objective_value=None,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=None,
            expected_improvement_rate=None,
            sample_size=0,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="PROJECTION_NOT_FOUND",
            message=f"Stage3PolicyPerformanceProjection '{source_projection_id}' not found",
        )

    merchant_id = projection.merchant_id

    # 2. Projection Status Validation
    if projection.status != ProjectionStatus.ACTIVE_MONITORING.value:
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id=merchant_id,
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=None,
            objective_value=None,
            baseline_objective_value=None,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=None,
            expected_improvement_rate=None,
            sample_size=projection.sample_size,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="PROJECTION_STATUS_INELIGIBLE",
            message=f"Projection status '{projection.status}' is not eligible for optimization",
        )

    # 3. Freshness Validation
    now_utc = utc_now()
    window_end_utc = _utc(projection.window_end)
    age_hours = (now_utc - window_end_utc).total_seconds() / 3600.0
    if age_hours > max_projection_age_hours:
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id=merchant_id,
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=None,
            objective_value=None,
            baseline_objective_value=None,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=None,
            expected_improvement_rate=None,
            sample_size=projection.sample_size,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="STALE_PROJECTION",
            message=f"Projection age ({age_hours:.1f}h) exceeds maximum allowed ({max_projection_age_hours}h)",
        )

    # 4. Total Sample Gate
    if projection.sample_size < min_sample_size:
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id=merchant_id,
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=None,
            objective_value=None,
            baseline_objective_value=None,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=None,
            expected_improvement_rate=None,
            sample_size=projection.sample_size,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="INSUFFICIENT_TOTAL_SAMPLE",
            message=f"Projection sample size ({projection.sample_size}) is below threshold ({min_sample_size})",
        )

    # 5. Active Policy Resolution & Policy Snapshot Consistency
    active_policy = None
    if projection.policy_id:
        active_policy = get_policy_by_id(session, projection.policy_id)
        if active_policy is None or active_policy.status != PolicyStatus.ACTIVE_ENFORCED.value:
            return OptimizationCandidateResult(
                candidate_id=None,
                merchant_id=merchant_id,
                source_projection_id=source_projection_id,
                proposed_action=None,
                baseline_action=None,
                objective_value=None,
                baseline_objective_value=None,
                expected_improvement_value=None,
                observed_recovery_rate=None,
                baseline_recovery_rate=None,
                expected_improvement_rate=None,
                sample_size=projection.sample_size,
                source_f4_evidence_id=None,
                f5_policy_id=None,
                f5_policy_version=None,
                status="NO_CANDIDATE",
                reason_code="POLICY_NOT_ACTIVE_ENFORCED",
                message=f"Policy '{projection.policy_id}' is not in ACTIVE_ENFORCED state",
            )
    elif projection.experiment_id and projection.experiment_version and projection.configuration_hash:
        try:
            active_policy = get_active_policy_for_binding(
                session,
                merchant_id,
                projection.experiment_id,
                projection.experiment_version,
                projection.configuration_hash,
            )
        except ValueError:
            pass

    if active_policy is None:
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id=merchant_id,
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=None,
            objective_value=None,
            baseline_objective_value=None,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=None,
            expected_improvement_rate=None,
            sample_size=projection.sample_size,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="UNABLE_TO_RESOLVE_CURRENT_POLICY",
            message="No active ACTIVE_ENFORCED policy found for scope binding",
        )

    # Verify policy snapshot consistency
    if (
        (projection.policy_id and projection.policy_id != active_policy.policy_id)
        or (projection.policy_version and projection.policy_version != active_policy.policy_version)
        or (projection.configuration_hash and projection.configuration_hash != active_policy.approved_configuration_hash)
    ):
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id=merchant_id,
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=None,
            objective_value=None,
            baseline_objective_value=None,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=None,
            expected_improvement_rate=None,
            sample_size=projection.sample_size,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="POLICY_SNAPSHOT_MISMATCH",
            message="Projection policy snapshot identity does not match current active F5 policy identity",
        )

    authorized_actions_set = set(active_policy.authorized_actions or [])

    # 6. S3-3 Operational Baseline Resolution (a_baseline)
    breakdown = projection.strategy_breakdown_json or {}
    eligible_baseline_actions = [
        act for act, data in breakdown.items()
        if act in authorized_actions_set and data.get("sample_size", 0) >= min_action_sample_size
    ]

    if not eligible_baseline_actions:
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id=merchant_id,
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=None,
            objective_value=None,
            baseline_objective_value=None,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=None,
            expected_improvement_rate=None,
            sample_size=projection.sample_size,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="INSUFFICIENT_BASELINE_EVIDENCE",
            message=f"No authorized action satisfies action sample size threshold ({min_action_sample_size})",
        )

    # Select operational baseline as authorized action with max execution count
    a_baseline = max(eligible_baseline_actions, key=lambda act: breakdown[act].get("sample_size", 0))
    baseline_data = breakdown[a_baseline]
    baseline_n = baseline_data.get("sample_size", 0)
    baseline_net = baseline_data.get("total_net_recovered_amount", 0.0)
    v_baseline = baseline_net / baseline_n if baseline_n > 0 else 0.0
    rate_baseline = baseline_data.get("recovery_success_rate", 0.0) or baseline_data.get("success_rate", 0.0)

    # 7. Candidate Action Metric Calculation & Evaluation
    # Filter candidates: authorized in F5, action sample >= min_action_sample_size
    all_candidate_actions = [
        act for act, data in breakdown.items()
        if act in authorized_actions_set and data.get("sample_size", 0) >= min_action_sample_size and act != a_baseline
    ]

    evaluations: list[dict[str, Any]] = []

    for act in all_candidate_actions:
        data = breakdown[act]
        act_n = data.get("sample_size", 0)
        act_net = data.get("total_net_recovered_amount", 0.0)
        v_cand = act_net / act_n if act_n > 0 else 0.0
        rate_cand = data.get("recovery_success_rate", 0.0) or data.get("success_rate", 0.0)
        avg_lat = data.get("avg_recovery_latency_seconds") or 999999.0

        delta_v = v_cand - v_baseline
        delta_rate = rate_cand - rate_baseline

        # Apply Safety Constraint (success rate degradation check)
        if delta_rate < -max_allowed_rate_degradation:
            continue

        # Apply Net Improvement Threshold
        if delta_v <= min_net_improvement_threshold:
            continue

        evaluations.append({
            "action": act,
            "v_cand": v_cand,
            "rate_cand": rate_cand,
            "delta_v": delta_v,
            "delta_rate": delta_rate,
            "avg_lat": avg_lat,
            "sample_size": act_n,
        })

    if not evaluations:
        return OptimizationCandidateResult(
            candidate_id=None,
            merchant_id=merchant_id,
            source_projection_id=source_projection_id,
            proposed_action=None,
            baseline_action=a_baseline,
            objective_value=None,
            baseline_objective_value=v_baseline,
            expected_improvement_value=None,
            observed_recovery_rate=None,
            baseline_recovery_rate=rate_baseline,
            expected_improvement_rate=None,
            sample_size=projection.sample_size,
            source_f4_evidence_id=None,
            f5_policy_id=None,
            f5_policy_version=None,
            status="NO_CANDIDATE",
            reason_code="NO_IMPROVEMENT_EXCEEDS_THRESHOLD",
            message=f"No alternative action exceeds net recovery threshold ({min_net_improvement_threshold})",
        )

    # Multi-metric ranking: Maximize V(a), then rate(a), then minimize latency, then alphabetical ordering
    best = sorted(
        evaluations,
        key=lambda e: (e["v_cand"], e["rate_cand"], -e["avg_lat"], -ord(e["action"][0])),
        reverse=True,
    )[0]

    a_candidate = best["action"]
    v_cand = best["v_cand"]
    rate_cand = best["rate_cand"]
    delta_v = best["delta_v"]
    delta_rate = best["delta_rate"]
    cand_sample_size = best["sample_size"]

    # 8. F4 Evidence Resolution
    f4_info = resolve_f4_evidence(
        session,
        merchant_id,
        projection.experiment_id,
        projection.experiment_version,
        projection.configuration_hash,
    )

    initial_status = CandidateStatus.READY_FOR_F5 if f4_info is not None else CandidateStatus.WAITING_FOR_F4
    source_f4_id = f4_info["source_f4_evidence_id"] if f4_info is not None else None

    # 9. Compute Candidate ID & Atomic Upsert Persistence
    candidate_id = compute_candidate_id(merchant_id, source_projection_id, a_candidate, optimizer_version)

    candidate_model = Stage3OptimizationCandidate(
        candidate_id=candidate_id,
        merchant_id=merchant_id,
        source_projection_id=source_projection_id,
        policy_id=projection.policy_id or active_policy.policy_id,
        policy_version=projection.policy_version or active_policy.policy_version,
        experiment_id=projection.experiment_id,
        experiment_version=projection.experiment_version,
        configuration_hash=projection.configuration_hash,
        f5_policy_id=None,
        f5_policy_version=None,
        proposed_action=a_candidate,
        baseline_action=a_baseline,
        objective_value=v_cand,
        baseline_objective_value=v_baseline,
        expected_improvement_value=delta_v,
        observed_recovery_rate=rate_cand,
        baseline_recovery_rate=rate_baseline,
        expected_improvement_rate=delta_rate,
        sample_size=cand_sample_size,
        source_f4_evidence_id=source_f4_id,
        reason_code="NET_VALUE_OPTIMIZATION_SUCCESS",
        optimizer_version=optimizer_version,
        status=initial_status.value,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    persisted = candidate_repository.save_candidate(session, candidate_model)

    f5_policy_record = None
    if persisted.status in {CandidateStatus.READY_FOR_F5.value, CandidateStatus.WAITING_FOR_F5.value}:
        f5_policy_record = submit_candidate_to_f5(session, persisted.candidate_id, candidate_repository=candidate_repository)

    return OptimizationCandidateResult(
        candidate_id=persisted.candidate_id,
        merchant_id=merchant_id,
        source_projection_id=source_projection_id,
        proposed_action=a_candidate,
        baseline_action=a_baseline,
        objective_value=v_cand,
        baseline_objective_value=v_baseline,
        expected_improvement_value=delta_v,
        observed_recovery_rate=rate_cand,
        baseline_recovery_rate=rate_baseline,
        expected_improvement_rate=delta_rate,
        sample_size=cand_sample_size,
        source_f4_evidence_id=persisted.source_f4_evidence_id,
        f5_policy_id=persisted.f5_policy_id,
        f5_policy_version=persisted.f5_policy_version,
        status=CandidateStatus(persisted.status),
        reason_code=persisted.reason_code,
        message=f"Successfully generated optimization candidate '{persisted.candidate_id}' proposing '{a_candidate}'",
    )


def submit_candidate_to_f5(
    session: Session,
    candidate_id: str,
    *,
    candidate_repository: Stage3OptimizationCandidateRepository = Stage3OptimizationCandidateRepository(),
) -> DecisionPolicyRecord | None:
    """Submits a Stage 3 Optimization Candidate to F5 as a DRAFT Policy in a crash-consistent, idempotent manner."""
    candidate = candidate_repository.get_candidate(session, candidate_id)
    if candidate is None:
        return None

    if candidate.status in {CandidateStatus.ACCEPTED.value, CandidateStatus.REJECTED.value, CandidateStatus.EXPIRED.value}:
        return session.get(DecisionPolicyRecord, candidate.f5_policy_id) if candidate.f5_policy_id else None

    # Resolve F4 evidence
    f4_info = resolve_f4_evidence(
        session,
        candidate.merchant_id,
        candidate.experiment_id,
        candidate.experiment_version,
        candidate.configuration_hash,
    )

    if f4_info is None:
        candidate.status = CandidateStatus.WAITING_FOR_F4.value
        candidate.updated_at = utc_now()
        session.flush()
        return None

    # Update candidate source_f4_evidence_id
    candidate.source_f4_evidence_id = f4_info["source_f4_evidence_id"]

    # Compute stable F5 policy ID for crash consistency and candidate versioning
    f5_policy_id = compute_f5_policy_id(candidate_id)
    f5_policy_version = f"{candidate.policy_version or '1.0'}_draft"

    # Transition to SUBMITTED_TO_F5 during in-flight submission
    candidate.status = CandidateStatus.SUBMITTED_TO_F5.value
    candidate.updated_at = utc_now()
    session.flush()

    binding = PolicyBinding(
        merchant_id=candidate.merchant_id,
        experiment_id=candidate.experiment_id or "EXP_DEFAULT",
        experiment_version=candidate.experiment_version or "1.0",
        approved_configuration_hash=candidate.configuration_hash or "0" * 64,
        policy_version=f5_policy_version,
    )

    source_f4_ref = SourceF4EvidenceReference(
        source_f4_evidence_id=f4_info["source_f4_evidence_id"],
        source_f4_evaluated_at=f4_info["source_f4_evaluated_at"],
        source_f4_status=f4_info["source_f4_status"],
        source_f4_configuration_hash=f4_info["source_f4_configuration_hash"],
        source_f4_point_estimate=f4_info["source_f4_point_estimate"],
        source_f4_confidence_interval_lower=f4_info["source_f4_confidence_interval_lower"],
        source_f4_confidence_interval_upper=f4_info["source_f4_confidence_interval_upper"],
        statistical_limitations=f4_info["statistical_limitations"],
        supersession_status=f4_info["supersession_status"],
    )

    auth = DecisionPolicyAuthorization(
        policy_id=f5_policy_id,
        binding=binding,
        source_f4_reference=source_f4_ref,
        authorized_actions=AuthorizedActionSet(actions=(candidate.proposed_action,)),
        baseline_action=candidate.baseline_action or "STOP",
        status=PolicyStatus.DRAFT,
        created_at=utc_now(),
    )

    try:
        f5_record = save_policy(session, auth)
        candidate.f5_policy_id = f5_record.policy_id
        candidate.f5_policy_version = f5_record.policy_version
        candidate.status = CandidateStatus.ACCEPTED.value
        candidate.updated_at = utc_now()
        session.flush()
        return f5_record
    except ValueError as val_err:
        logger.warning(f"F5 validation rejected candidate submission '{candidate_id}': {val_err}")
        candidate.status = CandidateStatus.REJECTED.value
        candidate.updated_at = utc_now()
        session.flush()
        return None
    except Exception as exc:
        logger.error(f"F5 submission failed for candidate '{candidate_id}': {exc}")
        candidate.status = CandidateStatus.WAITING_FOR_F5.value
        candidate.updated_at = utc_now()
        session.flush()
        return None

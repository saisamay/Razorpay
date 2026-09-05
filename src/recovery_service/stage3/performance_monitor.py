from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Stage3OutcomeObservation, Stage3PolicyPerformanceProjection
from .repository import Stage3PolicyPerformanceRepository
from .schemas import (
    PolicyMonitoringScope,
    PolicyPerformanceProjectionResult,
    ProjectionStatus,
)

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def compute_projection_id(
    scope: PolicyMonitoringScope, window_start: datetime, window_end: datetime
) -> str:
    """Computes a deterministic, collision-proof canonical projection identity hash (S3-2).

    Uses injective length-prefixed canonical string encoding:
    [merchant_id, policy_id, policy_version, experiment_id, experiment_version, configuration_hash, window_start, window_end]
    """
    w_start_iso = _utc(window_start).isoformat()
    w_end_iso = _utc(window_end).isoformat()

    fields = [
        scope.merchant_id,
        scope.policy_id,
        scope.policy_version,
        scope.experiment_id,
        scope.experiment_version,
        scope.configuration_hash,
        w_start_iso,
        w_end_iso,
    ]

    parts = []
    for f in fields:
        if f is None:
            parts.append("-1:NULL")
        else:
            val = str(f)
            parts.append(f"{len(val.encode('utf-8'))}:{val}")

    canonical_bytes = ":".join(parts).encode("utf-8")
    return f"proj_{hashlib.sha256(canonical_bytes).hexdigest()[:32]}"


def generate_policy_performance_projection(
    session: Session,
    scope: PolicyMonitoringScope,
    window_start: datetime,
    window_end: datetime,
    *,
    repository: Stage3PolicyPerformanceRepository = Stage3PolicyPerformanceRepository(),
    persist_empty: bool = False,
    min_sample_size: int = 10,
) -> PolicyPerformanceProjectionResult:
    """Generates an aggregated operational Policy Performance Projection for a scope and time window (S3-2).

    Calculates:
    - Sample size (N)
    - Recovery success rate (S / N for outcome_status in {"RECOVERED", "PARTIALLY_RECOVERED"})
    - Total net verified recovered amount
    - Average recovery latency seconds (excluding NULLs)
    - Action-level strategy breakdown JSON
    - Sample-sufficiency & projection status classification
    """
    if not scope.merchant_id or not scope.merchant_id.strip():
        raise ValueError("merchant_id is mandatory for policy performance monitoring")

    w_start_utc = _utc(window_start)
    w_end_utc = _utc(window_end)

    if w_end_utc <= w_start_utc:
        raise ValueError(f"Invalid window: window_end ({w_end_utc}) must be strictly after window_start ({w_start_utc})")

    # Build SQL query over Stage3OutcomeObservation with explicit IS NULL vs equality scope matching
    stmt = (
        select(Stage3OutcomeObservation)
        .where(
            Stage3OutcomeObservation.merchant_id == scope.merchant_id,
            Stage3OutcomeObservation.observed_at >= w_start_utc,
            Stage3OutcomeObservation.observed_at < w_end_utc,
        )
    )

    if scope.policy_id is None:
        stmt = stmt.where(Stage3OutcomeObservation.policy_id.is_(None))
    else:
        stmt = stmt.where(Stage3OutcomeObservation.policy_id == scope.policy_id)

    if scope.policy_version is None:
        stmt = stmt.where(Stage3OutcomeObservation.policy_version.is_(None))
    else:
        stmt = stmt.where(Stage3OutcomeObservation.policy_version == scope.policy_version)

    if scope.experiment_id is None:
        stmt = stmt.where(Stage3OutcomeObservation.experiment_id.is_(None))
    else:
        stmt = stmt.where(Stage3OutcomeObservation.experiment_id == scope.experiment_id)

    if scope.experiment_version is None:
        stmt = stmt.where(Stage3OutcomeObservation.experiment_version.is_(None))
    else:
        stmt = stmt.where(Stage3OutcomeObservation.experiment_version == scope.experiment_version)

    observations = list(session.scalars(stmt).all())
    sample_size = len(observations)

    projection_id = compute_projection_id(scope, w_start_utc, w_end_utc)

    if sample_size == 0:
        result = PolicyPerformanceProjectionResult(
            projection_id=projection_id,
            scope=scope,
            window_start=w_start_utc,
            window_end=w_end_utc,
            sample_size=0,
            recovery_success_rate=None,
            total_net_recovered_amount=0.0,
            operational_failure_rate=None,
            avg_recovery_latency_seconds=None,
            strategy_breakdown={},
            status=ProjectionStatus.NO_DATA,
            message="No Stage3OutcomeObservation records matched the specified scope and window",
        )
        if persist_empty:
            model = Stage3PolicyPerformanceProjection(
                projection_id=projection_id,
                merchant_id=scope.merchant_id,
                policy_id=scope.policy_id,
                policy_version=scope.policy_version,
                experiment_id=scope.experiment_id,
                experiment_version=scope.experiment_version,
                configuration_hash=scope.configuration_hash,
                window_start=w_start_utc,
                window_end=w_end_utc,
                sample_size=0,
                recovery_success_rate=None,
                total_net_recovered_amount=0.0,
                operational_failure_rate=None,
                avg_recovery_latency_seconds=None,
                strategy_breakdown_json={},
                status=ProjectionStatus.NO_DATA.value,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            repository.save_projection(session, model)
        return result

    # Calculate metrics for sample_size > 0
    successful_obs = [o for o in observations if o.outcome_status in {"RECOVERED", "PARTIALLY_RECOVERED"}]
    success_count = len(successful_obs)
    recovery_success_rate = success_count / sample_size

    total_net_recovered_amount = float(sum(o.net_verified_recovered_amount for o in observations))
    operational_failure_rate: float | None = None

    valid_latencies = [o.recovery_latency_seconds for o in observations if o.recovery_latency_seconds is not None]
    avg_recovery_latency_seconds = (
        float(sum(valid_latencies) / len(valid_latencies)) if valid_latencies else None
    )

    # Strategy breakdown grouped by executed_action
    actions = {o.executed_action for o in observations}
    strategy_breakdown: dict[str, dict[str, Any]] = {}

    for action in sorted(actions):
        action_obs = [o for o in observations if o.executed_action == action]
        action_n = len(action_obs)
        action_s = len([o for o in action_obs if o.outcome_status in {"RECOVERED", "PARTIALLY_RECOVERED"}])
        action_success_rate = action_s / action_n if action_n > 0 else 0.0
        action_net = float(sum(o.net_verified_recovered_amount for o in action_obs))
        action_latencies = [o.recovery_latency_seconds for o in action_obs if o.recovery_latency_seconds is not None]
        action_avg_latency = float(sum(action_latencies) / len(action_latencies)) if action_latencies else None

        strategy_breakdown[action] = {
            "sample_size": action_n,
            "success_count": action_s,
            "success_rate": action_success_rate,
            "total_net_recovered_amount": action_net,
            "avg_recovery_latency_seconds": action_avg_latency,
        }

    status = (
        ProjectionStatus.INSUFFICIENT_DATA if sample_size < min_sample_size else ProjectionStatus.ACTIVE_MONITORING
    )

    projection_model = Stage3PolicyPerformanceProjection(
        projection_id=projection_id,
        merchant_id=scope.merchant_id,
        policy_id=scope.policy_id,
        policy_version=scope.policy_version,
        experiment_id=scope.experiment_id,
        experiment_version=scope.experiment_version,
        configuration_hash=scope.configuration_hash,
        window_start=w_start_utc,
        window_end=w_end_utc,
        sample_size=sample_size,
        recovery_success_rate=recovery_success_rate,
        total_net_recovered_amount=total_net_recovered_amount,
        operational_failure_rate=operational_failure_rate,
        avg_recovery_latency_seconds=avg_recovery_latency_seconds,
        strategy_breakdown_json=strategy_breakdown,
        status=status.value,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    repository.save_projection(session, projection_model)

    return PolicyPerformanceProjectionResult(
        projection_id=projection_id,
        scope=scope,
        window_start=w_start_utc,
        window_end=w_end_utc,
        sample_size=sample_size,
        recovery_success_rate=recovery_success_rate,
        total_net_recovered_amount=total_net_recovered_amount,
        operational_failure_rate=operational_failure_rate,
        avg_recovery_latency_seconds=avg_recovery_latency_seconds,
        strategy_breakdown=strategy_breakdown,
        status=status,
        message=f"Successfully generated PolicyPerformanceProjection for scope {scope.merchant_id}",
    )

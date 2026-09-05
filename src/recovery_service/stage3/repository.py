from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    Stage3OptimizationCandidate,
    Stage3OutcomeObservation,
    Stage3PolicyPerformanceProjection,
)

logger = logging.getLogger(__name__)


class Stage3OutcomeObservationRepository:
    """Repository layer for Stage3OutcomeObservation persistence and lookup."""

    @staticmethod
    def get_by_attribution_id(session: Session, attribution_id: str) -> Stage3OutcomeObservation | None:
        """Fetch a Stage3OutcomeObservation record by attribution_id primary key."""
        return session.get(Stage3OutcomeObservation, attribution_id)

    @staticmethod
    def exists_by_attribution_id(session: Session, attribution_id: str) -> bool:
        """Check if a Stage3OutcomeObservation record exists for attribution_id."""
        stmt = select(Stage3OutcomeObservation.attribution_id).where(
            Stage3OutcomeObservation.attribution_id == attribution_id
        )
        return session.scalars(stmt).first() is not None

    @staticmethod
    def insert(session: Session, observation: Stage3OutcomeObservation) -> Stage3OutcomeObservation:
        """Persist a new immutable Stage3OutcomeObservation record."""
        session.add(observation)
        session.flush()
        return observation

    @staticmethod
    def list_by_merchant(
        session: Session, merchant_id: str, limit: int = 100
    ) -> list[Stage3OutcomeObservation]:
        """List Stage3OutcomeObservation records scoped to merchant_id."""
        stmt = (
            select(Stage3OutcomeObservation)
            .where(Stage3OutcomeObservation.merchant_id == merchant_id)
            .order_by(Stage3OutcomeObservation.observed_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


class Stage3PolicyPerformanceRepository:
    """Repository layer for Stage3PolicyPerformanceProjection persistence, lookup, and upsert."""

    @staticmethod
    def get_projection(session: Session, projection_id: str) -> Stage3PolicyPerformanceProjection | None:
        """Fetch a Stage3PolicyPerformanceProjection by projection_id primary key."""
        return session.get(Stage3PolicyPerformanceProjection, projection_id)

    @staticmethod
    def save_projection(
        session: Session, projection: Stage3PolicyPerformanceProjection
    ) -> Stage3PolicyPerformanceProjection:
        """Atomically save or update a Stage3PolicyPerformanceProjection (upsert by projection_id)."""
        existing = session.get(Stage3PolicyPerformanceProjection, projection.projection_id, with_for_update=True)
        if existing is not None:
            existing.sample_size = projection.sample_size
            existing.recovery_success_rate = projection.recovery_success_rate
            existing.total_net_recovered_amount = projection.total_net_recovered_amount
            existing.operational_failure_rate = projection.operational_failure_rate
            existing.avg_recovery_latency_seconds = projection.avg_recovery_latency_seconds
            existing.strategy_breakdown_json = projection.strategy_breakdown_json
            existing.status = projection.status
            existing.updated_at = projection.updated_at
            session.flush()
            return existing

        try:
            with session.begin_nested():
                session.add(projection)
                session.flush()
            return projection
        except IntegrityError:
            # Fallback upsert for concurrent insertion on primary key / unique constraint
            existing = session.get(Stage3PolicyPerformanceProjection, projection.projection_id, with_for_update=True)
            if existing is not None:
                existing.sample_size = projection.sample_size
                existing.recovery_success_rate = projection.recovery_success_rate
                existing.total_net_recovered_amount = projection.total_net_recovered_amount
                existing.operational_failure_rate = projection.operational_failure_rate
                existing.avg_recovery_latency_seconds = projection.avg_recovery_latency_seconds
                existing.strategy_breakdown_json = projection.strategy_breakdown_json
                existing.status = projection.status
                existing.updated_at = projection.updated_at
                session.flush()
                return existing
            raise

    @staticmethod
    def list_projections_for_merchant(
        session: Session, merchant_id: str, limit: int = 100
    ) -> list[Stage3PolicyPerformanceProjection]:
        """List Stage3PolicyPerformanceProjection records scoped to merchant_id."""
        stmt = (
            select(Stage3PolicyPerformanceProjection)
            .where(Stage3PolicyPerformanceProjection.merchant_id == merchant_id)
            .order_by(Stage3PolicyPerformanceProjection.window_start.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


class Stage3OptimizationCandidateRepository:
    """Repository layer for Stage3OptimizationCandidate persistence, lookup, and atomic upsert."""

    @staticmethod
    def get_candidate(session: Session, candidate_id: str) -> Stage3OptimizationCandidate | None:
        """Fetch a Stage3OptimizationCandidate by candidate_id primary key."""
        return session.get(Stage3OptimizationCandidate, candidate_id)

    @staticmethod
    def find_candidate_by_scope_action(
        session: Session,
        merchant_id: str,
        source_projection_id: str,
        proposed_action: str,
        optimizer_version: str = "1.0",
    ) -> Stage3OptimizationCandidate | None:
        """Locates an existing Stage3OptimizationCandidate matching the unique candidate identity."""
        stmt = select(Stage3OptimizationCandidate).where(
            Stage3OptimizationCandidate.merchant_id == merchant_id,
            Stage3OptimizationCandidate.source_projection_id == source_projection_id,
            Stage3OptimizationCandidate.proposed_action == proposed_action,
            Stage3OptimizationCandidate.optimizer_version == optimizer_version,
        )
        return session.scalars(stmt).first()

    @staticmethod
    def save_candidate(
        session: Session, candidate: Stage3OptimizationCandidate
    ) -> Stage3OptimizationCandidate:
        """Atomically saves or updates a Stage3OptimizationCandidate (upsert with row locking)."""
        existing = session.get(Stage3OptimizationCandidate, candidate.candidate_id, with_for_update=True)
        if existing is not None:
            existing.source_f4_evidence_id = candidate.source_f4_evidence_id or existing.source_f4_evidence_id
            existing.f5_policy_id = candidate.f5_policy_id or existing.f5_policy_id
            existing.f5_policy_version = candidate.f5_policy_version or existing.f5_policy_version
            existing.status = candidate.status
            existing.updated_at = candidate.updated_at
            session.flush()
            return existing

        try:
            with session.begin_nested():
                session.add(candidate)
                session.flush()
            return candidate
        except IntegrityError:
            existing = session.get(Stage3OptimizationCandidate, candidate.candidate_id, with_for_update=True)
            if existing is not None:
                existing.source_f4_evidence_id = candidate.source_f4_evidence_id or existing.source_f4_evidence_id
                existing.f5_policy_id = candidate.f5_policy_id or existing.f5_policy_id
                existing.f5_policy_version = candidate.f5_policy_version or existing.f5_policy_version
                existing.status = candidate.status
                existing.updated_at = candidate.updated_at
                session.flush()
                return existing
            raise

    @staticmethod
    def list_candidates_for_merchant(
        session: Session, merchant_id: str, limit: int = 100
    ) -> list[Stage3OptimizationCandidate]:
        """List Stage3OptimizationCandidate records scoped to merchant_id."""
        stmt = (
            select(Stage3OptimizationCandidate)
            .where(Stage3OptimizationCandidate.merchant_id == merchant_id)
            .order_by(Stage3OptimizationCandidate.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    @staticmethod
    def list_pending_candidates(
        session: Session, status: str = "WAITING_FOR_F4", limit: int = 100
    ) -> list[Stage3OptimizationCandidate]:
        """List Stage3OptimizationCandidate records with a specific pending status."""
        stmt = (
            select(Stage3OptimizationCandidate)
            .where(Stage3OptimizationCandidate.status == status)
            .order_by(Stage3OptimizationCandidate.created_at.asc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

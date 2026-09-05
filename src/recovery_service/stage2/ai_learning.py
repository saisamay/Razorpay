from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CaseKnowledgeRecord, KnowledgeIngestionLogRecord
from .schemas import SanitizedAIContext
from ..stage3.models import Stage3OutcomeObservation

logger = logging.getLogger(__name__)

# Minimum thresholds for memory match evaluation
MIN_OBSERVATIONS_FOR_STRONG_MATCH = 5
STRONG_MATCH_CONFIDENCE_THRESHOLD = 0.40


@dataclass
class KnowledgeSnippet:
    knowledge_id: str
    merchant_id: str
    failure_fingerprint: str
    candidate_action: str
    total_observations: int
    successful_recoveries: int
    observed_success_rate: float
    confidence_score: float
    source_f4_is_causal: bool = False
    source_f4_evidence_id: str | None = None
    source_f4_status: str | None = None
    source_f4_point_estimate: float | None = None
    source_f4_confidence_interval: list[float] | None = None


@dataclass
class MemoryMatchResult:
    match_type: str  # "STRONG_MATCH", "WEAK_MATCH", "NOVEL_CASE", "CONFLICTING_EVIDENCE"
    explanation: str
    should_invoke_openai: bool
    knowledge_records: list[KnowledgeSnippet] = field(default_factory=list)
    top_candidate_action: str | None = None
    top_candidate_confidence: float = 0.0


def compute_confidence_score(
    total_observations: int,
    observed_success_rate: float,
    source_f4_is_causal: bool = False,
    source_f4_status: str | None = None,
) -> float:
    """Compute deterministic, sample-size-weighted knowledge confidence score."""
    if total_observations <= 0:
        return 0.0

    # Sample size weight: asymptotically approaches 1.0 as N grows (e.g. N=5 -> 0.625, N=10 -> 0.77)
    sample_weight = float(total_observations) / (float(total_observations) + 3.0)
    base_score = sample_weight * observed_success_rate

    # F4 Causal bonus: boost confidence if valid non-superseded causal evidence exists
    f4_multiplier = 1.25 if (source_f4_is_causal and source_f4_status == "EFFICACY_RESULT_AVAILABLE") else 1.0

    final_score = min(1.0, round(base_score * f4_multiplier, 4))
    return final_score


def match_case_memory(
    session: Session,
    context: SanitizedAIContext,
    failure_fingerprint: str | None = None,
) -> MemoryMatchResult:
    """Retrieve tenant-isolated memory records and evaluate match quality deterministically."""
    fp = failure_fingerprint or f"{context.rail}_{context.diagnosis_class.lower()}"

    # Strict Tenant Boundary Filtering: WHERE merchant_id = :merchant_id
    records = session.scalars(
        select(CaseKnowledgeRecord)
        .where(CaseKnowledgeRecord.merchant_id == context.merchant_id)
        .where(
            (CaseKnowledgeRecord.failure_fingerprint == fp)
            | (CaseKnowledgeRecord.diagnosis_class == context.diagnosis_class)
        )
        .order_by(CaseKnowledgeRecord.confidence_score.desc())
    ).all()

    if not records:
        return MemoryMatchResult(
            match_type="NOVEL_CASE",
            explanation="No prior validated recovery evidence found for this tenant and failure pattern.",
            should_invoke_openai=True,
            knowledge_records=[],
        )

    snippets = [
        KnowledgeSnippet(
            knowledge_id=r.knowledge_id,
            merchant_id=r.merchant_id,
            failure_fingerprint=r.failure_fingerprint,
            candidate_action=r.candidate_action,
            total_observations=r.total_observations,
            successful_recoveries=r.successful_recoveries,
            observed_success_rate=r.observed_success_rate,
            confidence_score=r.confidence_score,
            source_f4_is_causal=r.source_f4_is_causal,
            source_f4_evidence_id=r.source_f4_evidence_id,
            source_f4_status=r.source_f4_status,
            source_f4_point_estimate=r.source_f4_point_estimate,
            source_f4_confidence_interval=r.source_f4_confidence_interval,
        )
        for r in records
    ]

    # Check for conflicting evidence (multiple candidate actions with high observations but divergent success rates)
    if len(records) >= 2:
        top_two = records[:2]
        if top_two[0].total_observations >= 3 and top_two[1].total_observations >= 3:
            diff = abs(top_two[0].observed_success_rate - top_two[1].observed_success_rate)
            if diff > 0.35 and not top_two[0].source_f4_is_causal:
                return MemoryMatchResult(
                    match_type="CONFLICTING_EVIDENCE",
                    explanation=f"Prior outcomes conflict for candidates {top_two[0].candidate_action} ({top_two[0].observed_success_rate:.0%}) vs {top_two[1].candidate_action} ({top_two[1].observed_success_rate:.0%}).",
                    should_invoke_openai=True,
                    knowledge_records=snippets,
                )

    top_record = records[0]

    # Evaluate if top record qualifies as a STRONG_MATCH
    if (
        top_record.total_observations >= MIN_OBSERVATIONS_FOR_STRONG_MATCH
        and top_record.confidence_score >= STRONG_MATCH_CONFIDENCE_THRESHOLD
    ):
        # Also check if active incident requires fresh reasoning
        if context.incident_active:
            return MemoryMatchResult(
                match_type="WEAK_MATCH",
                explanation="Valid memory exists, but an active systemic incident requires fresh AI reasoning.",
                should_invoke_openai=True,
                knowledge_records=snippets,
                top_candidate_action=top_record.candidate_action,
                top_candidate_confidence=top_record.confidence_score,
            )

        return MemoryMatchResult(
            match_type="STRONG_MATCH",
            explanation=f"Strong validated match found ({top_record.total_observations} cases, {top_record.observed_success_rate:.0%} success). Reusing validated knowledge.",
            should_invoke_openai=False,
            knowledge_records=snippets,
            top_candidate_action=top_record.candidate_action,
            top_candidate_confidence=top_record.confidence_score,
        )

    return MemoryMatchResult(
        match_type="WEAK_MATCH",
        explanation=f"Prior evidence exists but sample count ({top_record.total_observations}) or confidence ({top_record.confidence_score:.2f}) is low.",
        should_invoke_openai=True,
        knowledge_records=snippets,
        top_candidate_action=top_record.candidate_action,
        top_candidate_confidence=top_record.confidence_score,
    )


def ingest_stage3_outcome(
    session: Session,
    obs: Stage3OutcomeObservation,
    failure_fingerprint: str | None = None,
    f4_evidence_id: str | None = None,
    f4_is_causal: bool = False,
    f4_point_estimate: float | None = None,
    f4_confidence_interval: list[float] | None = None,
) -> CaseKnowledgeRecord:
    """Ingest Stage3OutcomeObservation into tenant-isolated knowledge record with idempotency tracking."""

    # 1. Idempotency Check
    existing_log = session.scalars(
        select(KnowledgeIngestionLogRecord).where(
            KnowledgeIngestionLogRecord.attribution_id == obs.attribution_id
        )
    ).first()
    if existing_log:
        logger.info("Stage 3 outcome attribution %s already ingested into learning memory", obs.attribution_id)
        existing_rec = session.get(CaseKnowledgeRecord, existing_log.knowledge_id)
        if existing_rec:
            return existing_rec

    fp = failure_fingerprint or f"card_{obs.executed_action.lower()}"
    diag_class = "STAGE3_OBSERVED_CASE"

    # Find or create knowledge record for (merchant_id, failure_fingerprint, candidate_action)
    rec = session.scalars(
        select(CaseKnowledgeRecord)
        .where(CaseKnowledgeRecord.merchant_id == obs.merchant_id)
        .where(CaseKnowledgeRecord.failure_fingerprint == fp)
        .where(CaseKnowledgeRecord.candidate_action == obs.executed_action)
    ).first()

    now = datetime.now(timezone.utc)

    if rec is None:
        rec = CaseKnowledgeRecord(
            knowledge_id=f"knw_{uuid4().hex[:16]}",
            merchant_id=obs.merchant_id,
            failure_fingerprint=fp,
            diagnosis_class=diag_class,
            rail="card",
            candidate_action=obs.executed_action,
            experiment_id=obs.experiment_id,
            experiment_version=obs.experiment_version,
            source_f4_evidence_id=f4_evidence_id,
            source_f4_status="EFFICACY_RESULT_AVAILABLE" if f4_evidence_id else None,
            source_f4_is_causal=f4_is_causal,
            source_f4_point_estimate=f4_point_estimate,
            source_f4_confidence_interval=f4_confidence_interval,
            total_observations=0,
            successful_recoveries=0,
            total_net_recovered_amount=0.0,
            observed_success_rate=0.0,
            confidence_score=0.0,
            last_stage3_attribution_id=obs.attribution_id,
            created_at=now,
            updated_at=now,
        )
        session.add(rec)
        session.flush()

    # 2. Update outcome metrics deterministically
    is_success = obs.outcome_status in {"CAPTURED", "SUCCESS", "RECOVERED"} or obs.net_verified_recovered_amount > 0
    rec.total_observations += 1
    if is_success:
        rec.successful_recoveries += 1
        rec.total_net_recovered_amount += obs.net_verified_recovered_amount

    rec.observed_success_rate = round(float(rec.successful_recoveries) / float(rec.total_observations), 4)
    rec.confidence_score = compute_confidence_score(
        rec.total_observations,
        rec.observed_success_rate,
        source_f4_is_causal=rec.source_f4_is_causal,
        source_f4_status=rec.source_f4_status,
    )
    rec.last_stage3_attribution_id = obs.attribution_id
    rec.updated_at = now

    # 3. Write idempotency log
    log_rec = KnowledgeIngestionLogRecord(
        ingestion_id=f"ing_{uuid4().hex[:16]}",
        attribution_id=obs.attribution_id,
        case_id=obs.case_id,
        merchant_id=obs.merchant_id,
        knowledge_id=rec.knowledge_id,
        ingested_at=now,
    )
    session.add(log_rec)

    return rec

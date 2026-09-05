from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from recovery_service.database import build_session_factory, ensure_schema
from recovery_service.models import AuditLogEntry, RecoveryCase
from recovery_service.settings import Settings
from recovery_service.stage2.ai_learning import (
    CaseKnowledgeRecord,
    KnowledgeIngestionLogRecord,
    compute_confidence_score,
    ingest_stage3_outcome,
    match_case_memory,
)
from recovery_service.stage2.ai_reasoner import (
    assemble_sanitized_reasoning_context,
    generate_ai_reasoning,
)
from recovery_service.stage2.genai_explainer import PROHIBITED_PII_KEYS
from recovery_service.stage2.models import (
    DiagnosisRecord,
    EvidenceManifestRecord,
    FailureFingerprintRecord,
    IncidentClusterRecord,
    RecoveryEligibilityRecord,
)
from recovery_service.stage3.models import Stage3OutcomeObservation


def _setup_learning_db(tmp_path):
    db_path = tmp_path / "test_ai_learning.sqlite3"
    db_url = f"sqlite:///{db_path}"
    settings = Settings(
        database_url=db_url,
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test_secret",),
        environment="test",
        max_webhook_bytes=1048576,
    )
    factory = build_session_factory(settings)
    ensure_schema(factory)
    return factory


def _create_test_case(session, case_id: str = "rc_learn_1", merchant_id: str = "merc_learn_a"):
    now = datetime.now(timezone.utc)
    case = RecoveryCase(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id=f"ep_{case_id}",
        merchant_id=merchant_id,
        amount=500000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="ELIGIBLE",
    )
    session.add(case)

    diag = DiagnosisRecord(
        diagnosis_id=f"diag_{case_id}",
        case_id=case_id,
        stage1_state_version=1,
        payment_id=f"pay_{case_id}",
        merchant_id=merchant_id,
        diagnosis_class="ISSUER_DECLINE",
        score=0.85,
        confidence=0.90,
    )
    session.add(diag)

    fp = FailureFingerprintRecord(
        fingerprint_id=f"fp_rec_{case_id}",
        case_id=case_id,
        diagnosis_id=f"diag_{case_id}",
        stage1_state_version=1,
        payment_id=f"pay_{case_id}",
        merchant_id=merchant_id,
        fingerprint_hash="card_issuer_decline",
        dimensions={"rail": "card", "rail_subtype": "credit", "time_window": "PEAK", "amount_bucket": "1000_TO_5000_INR"},
        temporal_features={},
    )
    session.add(fp)

    el = RecoveryEligibilityRecord(
        eligibility_id=f"el_{case_id}",
        case_id=case_id,
        stage1_state_version=1,
        eligibility="ELIGIBLE",
    )
    session.add(el)

    ev = EvidenceManifestRecord(
        manifest_id=f"man_{case_id}",
        case_id=case_id,
        stage1_state_version=1,
        payment_id=f"pay_{case_id}",
        merchant_id=merchant_id,
        provenance_hash="hash_123",
        data={"items": []},
    )
    session.add(ev)
    session.commit()
    return case


# 1. Novel Case Test
def test_novel_case_invokes_openai(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_novel_1", "merc_novel")
        projection = generate_ai_reasoning(session, "rc_novel_1", "merc_novel", api_key="")

        assert projection.reasoning.learning_match_type == "NOVEL_CASE"
        assert projection.reasoning.authoritative is False


# 2. Strong Known Case Test (Avoids OpenAI call)
def test_strong_known_case_avoids_unnecessary_openai(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_strong_1", "merc_strong")

        # Seed strong memory (10 observations, 90% success)
        now = datetime.now(timezone.utc)
        knw = CaseKnowledgeRecord(
            knowledge_id="knw_strong_1",
            merchant_id="merc_strong",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            rail="card",
            candidate_action="RETRY_LATER",
            total_observations=10,
            successful_recoveries=9,
            observed_success_rate=0.90,
            confidence_score=compute_confidence_score(10, 0.90),
            created_at=now,
            updated_at=now,
        )
        session.add(knw)
        session.commit()

        projection = generate_ai_reasoning(session, "rc_strong_1", "merc_strong", api_key="")

        assert projection.reasoning.learning_match_type == "STRONG_MATCH"
        assert projection.reasoning.openai_invoked is False
        assert projection.reasoning.recommended_intervention == "RETRY_LATER"
        assert "knw_strong_1" in projection.reasoning.knowledge_ids_used
        assert projection.reasoning.authoritative is False


# 3. Weak Memory Invokes OpenAI Test
def test_weak_memory_invokes_openai(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_weak_1", "merc_weak")

        # Seed weak memory (only 2 observations)
        now = datetime.now(timezone.utc)
        knw = CaseKnowledgeRecord(
            knowledge_id="knw_weak_1",
            merchant_id="merc_weak",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            rail="card",
            candidate_action="ALTERNATE_RAIL",
            total_observations=2,
            successful_recoveries=1,
            observed_success_rate=0.50,
            confidence_score=compute_confidence_score(2, 0.50),
            created_at=now,
            updated_at=now,
        )
        session.add(knw)
        session.commit()

        projection = generate_ai_reasoning(session, "rc_weak_1", "merc_weak", api_key="")

        assert projection.reasoning.learning_match_type == "WEAK_MATCH"


# 4. Conflicting Evidence Test
def test_conflicting_evidence_invokes_openai(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_conflict_1", "merc_conflict")

        now = datetime.now(timezone.utc)
        k1 = CaseKnowledgeRecord(
            knowledge_id="knw_conf_1",
            merchant_id="merc_conflict",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            rail="card",
            candidate_action="RETRY_LATER",
            total_observations=10,
            successful_recoveries=9,
            observed_success_rate=0.90,
            confidence_score=0.75,
            created_at=now,
            updated_at=now,
        )
        k2 = CaseKnowledgeRecord(
            knowledge_id="knw_conf_2",
            merchant_id="merc_conflict",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            rail="card",
            candidate_action="ALTERNATE_RAIL",
            total_observations=10,
            successful_recoveries=2,
            observed_success_rate=0.20,
            confidence_score=0.70,
            created_at=now,
            updated_at=now,
        )
        session.add_all([k1, k2])
        session.commit()

        context = assemble_sanitized_reasoning_context(session, "rc_conflict_1", "merc_conflict")
        match_res = match_case_memory(session, context)

        assert match_res.match_type == "CONFLICTING_EVIDENCE"
        assert match_res.should_invoke_openai is True


# 5. Tenant Isolation Test
def test_tenant_isolation_prevents_cross_tenant_memory_access(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_tenant_a", "merc_a")

        now = datetime.now(timezone.utc)
        # Memory belongs ONLY to merc_b
        knw = CaseKnowledgeRecord(
            knowledge_id="knw_b_private",
            merchant_id="merc_b",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            rail="card",
            candidate_action="RETRY_LATER",
            total_observations=20,
            successful_recoveries=18,
            observed_success_rate=0.90,
            confidence_score=0.85,
            created_at=now,
            updated_at=now,
        )
        session.add(knw)
        session.commit()

        context = assemble_sanitized_reasoning_context(session, "rc_tenant_a", "merc_a")
        match_res = match_case_memory(session, context)

        # Merc A must NOT match Merc B's memory!
        assert match_res.match_type == "NOVEL_CASE"
        assert len(match_res.knowledge_records) == 0


# 6. PII Protection Test
def test_no_pii_in_memory_or_openai_context(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_pii_check", "merc_pii")
        context = assemble_sanitized_reasoning_context(session, "rc_pii_check", "merc_pii")

        context_json = context.model_dump_json()
        for prohibited in PROHIBITED_PII_KEYS:
            assert prohibited not in context_json.lower()


# 7. Memory Cannot Authorize Execution Test
def test_memory_cannot_authorize_execution(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_auth_check", "merc_auth")
        projection = generate_ai_reasoning(session, "rc_auth_check", "merc_auth", api_key="")

        assert projection.reasoning.authoritative is False


# 8. Stage 3 Outcome Updates Learning Test
def test_stage3_outcome_updates_learning(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        now = datetime.now(timezone.utc)
        obs = Stage3OutcomeObservation(
            attribution_id="attr_learn_100",
            case_id="case_s3_1",
            payment_id="pay_s3_1",
            proposal_id="prop_s3_1",
            merchant_id="merc_s3",
            executed_action="RETRY_LATER",
            outcome_status="CAPTURED",
            net_verified_recovered_amount=500.0,
            observed_at=now,
            finalized_at=now,
        )

        rec = ingest_stage3_outcome(session, obs, failure_fingerprint="card_issuer_decline")
        session.commit()

        assert rec.total_observations == 1
        assert rec.successful_recoveries == 1
        assert rec.observed_success_rate == 1.0
        assert rec.confidence_score > 0.0


# 9. Idempotent Stage 3 Outcome Ingestion Test
def test_idempotent_stage3_ingestion(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        now = datetime.now(timezone.utc)
        obs = Stage3OutcomeObservation(
            attribution_id="attr_idempotent_99",
            case_id="case_s3_dup",
            payment_id="pay_s3_dup",
            proposal_id="prop_s3_dup",
            merchant_id="merc_dup",
            executed_action="RETRY_LATER",
            outcome_status="CAPTURED",
            net_verified_recovered_amount=500.0,
            observed_at=now,
            finalized_at=now,
        )

        rec1 = ingest_stage3_outcome(session, obs, failure_fingerprint="card_issuer_decline")
        session.commit()

        # Ingest exact same outcome second time
        rec2 = ingest_stage3_outcome(session, obs, failure_fingerprint="card_issuer_decline")
        session.commit()

        assert rec1.total_observations == 1
        assert rec2.total_observations == 1  # Did NOT double-count!

        logs = session.scalars(
            select(KnowledgeIngestionLogRecord).where(
                KnowledgeIngestionLogRecord.attribution_id == "attr_idempotent_99"
            )
        ).all()
        assert len(logs) == 1


# 10. Audit Entry Captures Learning Details Test
def test_audit_entry_captures_learning_details(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_audit_learn", "merc_audit_l")
        generate_ai_reasoning(session, "rc_audit_learn", "merc_audit_l", api_key="")

        audit_rec = session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.payment_id == "rc_audit_learn")
        ).first()

        assert audit_rec is not None
        assert "learning_match_type" in audit_rec.details
        assert "openai_invoked" in audit_rec.details
        assert "knowledge_ids_used" in audit_rec.details
        assert audit_rec.details["authoritative"] is False


# 11. Active Incident Forces Fresh OpenAI Reasoning Test
def test_active_incident_forces_fresh_openai_reasoning(tmp_path):
    factory = _setup_learning_db(tmp_path)
    with factory() as session:
        _create_test_case(session, "rc_active_inc_1", "merc_inc")

        # Seed strong memory for fingerprint (10 observations, 90% success rate, confidence = 0.69 > 0.40)
        now = datetime.now(timezone.utc)
        knw = CaseKnowledgeRecord(
            knowledge_id="knw_inc_override_1",
            merchant_id="merc_inc",
            failure_fingerprint="card_issuer_decline",
            diagnosis_class="ISSUER_DECLINE",
            rail="card",
            candidate_action="RETRY_LATER",
            total_observations=10,
            successful_recoveries=9,
            observed_success_rate=0.90,
            confidence_score=compute_confidence_score(10, 0.90),
            created_at=now,
            updated_at=now,
        )
        session.add(knw)

        # Create active systemic incident record (status="CONFIRMED")
        inc = IncidentClusterRecord(
            incident_id="inc_active_cluster_1",
            dimensions={"rail": "card"},
            affected_case_count=25,
            status="CONFIRMED",
            started_at=now,
            last_seen_at=now,
            updated_at=now,
        )
        session.add(inc)
        session.commit()

        # Assemble production context and call match_case_memory
        context = assemble_sanitized_reasoning_context(session, "rc_active_inc_1", "merc_inc")
        assert context.incident_active is True

        match_res = match_case_memory(session, context)

        # Assert active incident overrides strong memory match, returning WEAK_MATCH and should_invoke_openai = True
        assert match_res.match_type == "WEAK_MATCH"
        assert match_res.should_invoke_openai is True
        assert "active systemic incident" in match_res.explanation.lower()


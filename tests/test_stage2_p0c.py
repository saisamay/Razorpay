from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import process_diagnosis
from recovery_service.stage2.diagnosis_engine import DiagnosisClasses, evaluate_diagnosis
from recovery_service.stage2.models import DiagnosisRecord, Stage2Case
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.schemas import RecoveryCaseContract


def _setup_db(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/p0c.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    return factory, settings


def _sample_contract(case_id: str = "rc_p0c_test", failure_details: dict | None = None) -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id="evt_fail_p0c",
        merchant_id="acc_p0c",
        order_id="order_p0c",
        amount=50000,
        currency="INR",
        state="FAILED",
        state_confidence=0.95,
        failure_evidence=failure_details or {"reason": "BAD_REQUEST_ERROR"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail_p0c"],
        stage1_state_version=1,
    )


def test_diagnosis_issuer_decline():
    contract = _sample_contract("rc_decline", {"reason": "CARD_DECLINED", "gateway": "HDFC"})
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.ISSUER_DECLINE
    assert diag.score >= 0.5


def test_diagnosis_transient_provider_timeout():
    contract = _sample_contract("rc_timeout", {"reason": "GATEWAY_TIMEOUT", "anomalies": ["timeout"]})
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.TRANSIENT_PROVIDER_TIMEOUT
    assert diag.score >= 0.5


def test_diagnosis_late_success_after_timeout_safety_precedence():
    """PDF Golden Example: Timeout + later valid authorization resolves to LATE_SUCCESS_AFTER_TIMEOUT.

    Simple timeout rule MUST NOT win merely because it executes first.
    """
    contract = _sample_contract("rc_late_success", {"reason": "GATEWAY_TIMEOUT", "anomalies": ["timeout", "late_authorization"]})
    t0 = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 27, 10, 0, 5, tzinfo=timezone.utc)
    events = [
        {"event_id": "evt_t", "event_type": "payment.failed", "occurred_at": t0},
        {"event_id": "evt_late", "event_type": "payment.authorized", "occurred_at": t1},
    ]
    manifest = normalize_evidence(contract, timeline_events=events)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.LATE_SUCCESS_AFTER_TIMEOUT
    assert diag.score > 0.90


def test_diagnosis_authentication_failure():
    contract = _sample_contract("rc_auth_fail", {"reason": "3DS_AUTH_FAILED", "failure_step": "payment_authentication"})
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.AUTHENTICATION_FAILURE
    assert diag.score >= 0.75


def test_diagnosis_duplicate_or_conflicting_attempt():
    contract = _sample_contract("rc_dup_attempt", {"anomalies": ["duplicate_attempt"], "contradictions": ["c1"]})
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.DUPLICATE_OR_CONFLICTING_ATTEMPT


def test_diagnosis_provider_degradation_suspected():
    contract = _sample_contract("rc_deg_suspected", {"anomalies": ["provider_degradation"], "gateway_degraded": True})
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.PROVIDER_DEGRADATION_SUSPECTED


def test_diagnosis_insufficient_evidence():
    """Contradiction penalty exceeding threshold forces INSUFFICIENT_EVIDENCE."""
    contract = _sample_contract("rc_insuff", {"contradictions": ["c1", "c2", "c3"]})
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.INSUFFICIENT_EVIDENCE
    assert diag.score == 0.0


def test_diagnosis_unknown():
    contract = _sample_contract("rc_unk", {"reason": "SOME_EXOTIC_UNMAPPED_REASON"})
    manifest = normalize_evidence(contract)
    diag = evaluate_diagnosis(manifest)
    assert diag.diagnosis_class == DiagnosisClasses.UNKNOWN


def test_diagnosis_pipeline_persistence_and_status_transition(tmp_path):
    factory, settings = _setup_db(tmp_path)
    contract = _sample_contract("rc_diag_persist", {"reason": "CARD_DECLINED"})

    with factory() as session:
        manifest, diag = process_diagnosis(session, contract, worker_id="stage2-worker-1")
        session.commit()
        assert diag.diagnosis_class == DiagnosisClasses.ISSUER_DECLINE

    with factory() as session:
        stage2_case = session.get(Stage2Case, ("rc_diag_persist", 1))
        assert stage2_case is not None
        assert stage2_case.status == "DIAGNOSED"

    with factory() as session:
        records = session.scalars(select(DiagnosisRecord).where(DiagnosisRecord.case_id == "rc_diag_persist")).all()
        assert len(records) == 1
        assert records[0].diagnosis_class == DiagnosisClasses.ISSUER_DECLINE
        assert records[0].engine_version == "1.0"

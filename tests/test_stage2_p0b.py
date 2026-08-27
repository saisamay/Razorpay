from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.models import RecoveryCase, utc_now
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import process_evidence_manifest, register_stage2_case
from recovery_service.stage2.models import EvidenceManifestRecord, Stage2Case
from recovery_service.stage2.normalizer import compute_provenance_hash, normalize_evidence
from recovery_service.stage2.schemas import EvidenceManifest, RecoveryCaseContract


def _setup_db(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/p0b.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    return factory, settings


def _sample_contract(case_id: str = "rc_p0b_test_1", state_version: int = 1) -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id=case_id,
        payment_id="pay_p0b_1",
        recovery_episode_id="evt_fail_p0b",
        merchant_id="acc_p0b",
        order_id="order_p0b",
        amount=75000,
        currency="INR",
        state="FAILED",
        state_confidence=0.98,
        failure_evidence={
            "reason": "BAD_REQUEST_ERROR",
            "failure_step": "payment_authentication",
            "gateway": "HDFC",
            "issuer": "ICICI",
        },
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail_p0b"],
        stage1_state_version=state_version,
    )


def test_evidence_normalizer_golden(tmp_path):
    contract = _sample_contract("rc_golden_1", state_version=1)
    t0 = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 27, 10, 0, 2, tzinfo=timezone.utc)
    events = [
        {"event_id": "evt_1", "event_type": "payment.failed", "occurred_at": t0},
        {"event_id": "evt_2", "event_type": "payment.authorized", "occurred_at": t1},
    ]

    manifest = normalize_evidence(contract, timeline_events=events)

    assert isinstance(manifest, EvidenceManifest)
    assert manifest.identity.case_id == "rc_golden_1"
    assert manifest.identity.payment_id == "pay_p0b_1"
    assert manifest.identity.merchant_id == "acc_p0b"
    assert manifest.identity.order_id == "order_p0b"

    assert manifest.state.state == "FAILED"
    assert manifest.state.stage1_state_version == 1
    assert manifest.state.state_confidence == 0.98

    assert manifest.failure.failure_code == "BAD_REQUEST_ERROR"
    assert manifest.failure.failure_step == "payment_authentication"
    assert manifest.failure.gateway == "HDFC"
    assert manifest.failure.issuer == "ICICI"

    assert manifest.features.amount_bucket == "50k-100k"
    assert manifest.features.currency == "INR"
    assert manifest.features.latency_bucket == "1s-5s"
    assert manifest.features.retry_count == 1

    assert manifest.provenance.normalizer_version == "1.0"
    assert len(manifest.provenance.provenance_hash) == 64


def test_evidence_normalizer_missing_fields_explicit():
    contract = RecoveryCaseContract(
        case_id="rc_missing_1",
        payment_id="pay_missing_1",
        recovery_episode_id="evt_missing",
        merchant_id=None,
        order_id=None,
        amount=None,
        currency=None,
        state="FAILED",
        state_confidence=0.9,
        failure_evidence={},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=[],
        stage1_state_version=1,
    )

    manifest = normalize_evidence(contract)

    # Missing values must be explicit NOT_AVAILABLE or UNKNOWN, never invented
    assert manifest.identity.merchant_id == "NOT_AVAILABLE"
    assert manifest.identity.order_id == "NOT_AVAILABLE"
    assert manifest.failure.failure_code == "UNKNOWN"
    assert manifest.failure.failure_step == "UNKNOWN"
    assert manifest.failure.gateway == "UNKNOWN"
    assert manifest.features.amount_bucket == "NOT_AVAILABLE"
    assert manifest.features.currency == "UNKNOWN"
    assert manifest.reconciliation.status == "NOT_AVAILABLE"


def test_evidence_normalizer_provenance_hash_determinism():
    contract_a = _sample_contract("rc_prov_1", state_version=1)
    contract_b = _sample_contract("rc_prov_1", state_version=1)
    contract_c = _sample_contract("rc_prov_1", state_version=2)

    hash_a = compute_provenance_hash(contract_a)
    hash_b = compute_provenance_hash(contract_b)
    hash_c = compute_provenance_hash(contract_c)

    assert hash_a == hash_b
    assert hash_a != hash_c


def test_process_evidence_manifest_persistence_and_status_transition(tmp_path):
    factory, settings = _setup_db(tmp_path)
    contract = _sample_contract("rc_pipe_1", state_version=1)

    with factory() as session:
        manifest = process_evidence_manifest(session, contract, worker_id="stage2-worker-1")
        session.commit()

        assert manifest.identity.case_id == "rc_pipe_1"

    # Verify Stage2Case status transitioned to EVIDENCE_READY
    with factory() as session:
        stage2_case = session.get(Stage2Case, ("rc_pipe_1", 1))
        assert stage2_case is not None
        assert stage2_case.status == "EVIDENCE_READY"

    # Verify EvidenceManifestRecord database row
    with factory() as session:
        records = session.scalars(select(EvidenceManifestRecord).where(EvidenceManifestRecord.case_id == "rc_pipe_1")).all()
        assert len(records) == 1
        assert records[0].normalizer_version == "1.0"
        assert records[0].data["identity"]["payment_id"] == "pay_p0b_1"

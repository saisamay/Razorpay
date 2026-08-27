from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import process_failure_fingerprint
from recovery_service.stage2.failure_dna import compute_failure_dna, compute_temporal_features
from recovery_service.stage2.models import FailureFingerprintRecord, Stage2Case
from recovery_service.stage2.normalizer import normalize_evidence
from recovery_service.stage2.schemas import FailureDNA, RecoveryCaseContract, TemporalFeatures


def _setup_db(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/p0e.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    return factory, settings


def _sample_contract(case_id: str = "rc_p0e_test", state_version: int = 1) -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id="evt_fail_p0e",
        merchant_id="acc_p0e",
        order_id="order_p0e",
        amount=85000,
        currency="INR",
        state="FAILED",
        state_confidence=0.97,
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
        source_event_ids=["evt_fail_p0e"],
        stage1_state_version=state_version,
    )


def test_failure_dna_determinism_and_hash_invariance():
    contract_a = _sample_contract("rc_fdna_1", state_version=1)
    contract_b = _sample_contract("rc_fdna_1", state_version=1)

    manifest_a = normalize_evidence(contract_a)
    manifest_b = normalize_evidence(contract_b)

    fdna_a = compute_failure_dna(manifest_a)
    fdna_b = compute_failure_dna(manifest_b)

    assert isinstance(fdna_a, FailureDNA)
    assert fdna_a.fingerprint_hash == fdna_b.fingerprint_hash
    assert len(fdna_a.fingerprint_hash) == 64
    assert fdna_a.version == "1.0"


def test_failure_dna_pii_redaction_and_bucketing():
    contract = _sample_contract("rc_fdna_pii", state_version=1)
    manifest = normalize_evidence(contract)
    fdna = compute_failure_dna(manifest)

    # Ensure no raw PII fields exist in FailureDNA schema
    dump = fdna.model_dump()
    assert "email" not in dump
    assert "card_number" not in dump
    assert "customer_name" not in dump

    # Check bounded bucketing
    assert fdna.amount_bucket == "50k-100k"
    assert fdna.currency == "INR"
    assert fdna.provider == "HDFC"
    assert fdna.issuer == "ICICI"
    assert fdna.auth_state in {"3DS_FAILED", "3DS_SUCCESS", "UNKNOWN"}


def test_temporal_features_occurrence_deltas():
    contract = _sample_contract("rc_temp_1", state_version=1)
    t0 = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 27, 12, 0, 6, tzinfo=timezone.utc)
    events = [
        {"event_id": "evt_1", "event_type": "payment.failed", "occurred_at": t0},
        {"event_id": "evt_2", "event_type": "payment.authorized", "occurred_at": t1},
    ]

    manifest = normalize_evidence(contract, timeline_events=events)
    temporal = compute_temporal_features(manifest)

    assert isinstance(temporal, TemporalFeatures)
    assert temporal.total_span_seconds == 6.0
    assert temporal.latency_regime == "ELEVATED"
    assert temporal.request_to_gateway_ms > 0


def test_failure_fingerprint_pipeline_persistence_and_status(tmp_path):
    factory, settings = _setup_db(tmp_path)
    contract = _sample_contract("rc_fp_pipe", state_version=1)

    with factory() as session:
        manifest, diag, fdna, temporal = process_failure_fingerprint(session, contract, worker_id="stage2-worker-1")
        session.commit()

        assert fdna.provider == "HDFC"

    # Verify Stage2Case status transitioned to FINGERPRINTED
    with factory() as session:
        stage2_case = session.get(Stage2Case, ("rc_fp_pipe", 1))
        assert stage2_case is not None
        assert stage2_case.status == "FINGERPRINTED"

    # Verify FailureFingerprintRecord database row
    with factory() as session:
        records = session.scalars(select(FailureFingerprintRecord).where(FailureFingerprintRecord.case_id == "rc_fp_pipe")).all()
        assert len(records) == 1
        assert records[0].version == "1.0"
        assert records[0].dimensions["provider"] == "HDFC"
        assert records[0].temporal_features["latency_regime"] in {"NORMAL", "ELEVATED", "CRITICAL"}

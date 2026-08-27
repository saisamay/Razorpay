from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.models import RecoveryCase, utc_now
from recovery_service.queue import EventQueue
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import Stage2ConsumerError, register_stage2_case
from recovery_service.stage2.models import Stage2Case
from recovery_service.stage2.schemas import RecoveryCaseContract
from recovery_service.worker import _sweep_cases


def _setup_db(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/p0a.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    return factory, settings


def _sample_contract(case_id: str = "rc_p0a_test_1", state_version: int = 1, eligible: bool = True) -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id=case_id,
        payment_id="pay_p0a_1",
        recovery_episode_id="evt_fail_p0a",
        merchant_id="acc_p0a",
        order_id="order_p0a",
        amount=50000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "payment_failed"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=eligible,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT" if eligible else "PAYMENT_ALREADY_CAPTURED",
        schema_version="1.5",
        source_event_ids=["evt_fail_p0a"],
        stage1_state_version=state_version,
    )


def test_stage2_handoff_outbox_sweep(tmp_path):
    factory, settings = _setup_db(tmp_path)
    now = utc_now()

    with factory() as session:
        case = RecoveryCase(
            case_id="rc_sweep_1",
            payment_id="pay_sweep_1",
            recovery_episode_id="evt_sweep_1",
            merchant_id="acc_sweep",
            order_id="order_sweep",
            amount=100000,
            currency="INR",
            state="FAILED",
            state_confidence=0.99,
            failure_evidence={"reason": "card_declined"},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
            schema_version="1.5",
            source_event_ids=["evt_sweep_1"],
            stage1_state_version=1,
        )
        session.add(case)
        session.commit()

    class DummyQueue:
        def __init__(self):
            self.published = []

        def publish_case(self, case_id: str):
            self.published.append(case_id)

    queue = DummyQueue()
    swept = _sweep_cases(factory, queue)
    assert "rc_sweep_1" in swept
    assert queue.published == ["rc_sweep_1"]


def test_stage2_case_validation_and_idempotent_registration(tmp_path):
    factory, settings = _setup_db(tmp_path)
    contract = _sample_contract("rc_reg_1", state_version=1)

    # 1. Register valid contract
    with factory() as session:
        res = register_stage2_case(session, contract, worker_id="stage2-worker-1")
        session.commit()
        assert res.status == "REGISTERED"
        assert res.duplicate is False
        assert res.is_current is True

    # 2. Duplicate registration attempt -> returns existing state idempotently
    with factory() as session:
        res_dup = register_stage2_case(session, contract, worker_id="stage2-worker-2")
        session.commit()
        assert res_dup.status == "REGISTERED"
        assert res_dup.duplicate is True
        assert res_dup.is_current is True

    # 3. Verify PostgreSQL database state
    with factory() as session:
        registered = session.scalars(select(Stage2Case).where(Stage2Case.case_id == "rc_reg_1")).all()
        assert len(registered) == 1
        assert registered[0].stage1_state_version == 1
        assert registered[0].status == "REGISTERED"
        assert registered[0].is_current is True


def test_stage2_100x_duplicate_delivery_idempotency(tmp_path):
    factory, settings = _setup_db(tmp_path)
    contract = _sample_contract("rc_dup_100", state_version=1)

    # Deliver same contract 100 times concurrently/sequentially
    for i in range(100):
        with factory() as session:
            register_stage2_case(session, contract, worker_id=f"worker-{i}")
            session.commit()

    with factory() as session:
        rows = session.scalars(select(Stage2Case).where(Stage2Case.case_id == "rc_dup_100")).all()
        assert len(rows) == 1
        assert rows[0].status == "REGISTERED"


def test_p0a_crash_window_recovery(tmp_path):
    """Simulate DB COMMIT -> Worker Crash (No Redis Publish) -> Restart -> Sweep -> Redis Publish -> Stage 2 Registration."""
    factory, settings = _setup_db(tmp_path)
    now = utc_now()

    # Step 1: DB COMMIT occurs in Stage 1
    with factory() as session:
        session.add(RecoveryCase(
            case_id="rc_crash_1", payment_id="pay_crash_1", recovery_episode_id="evt_crash",
            merchant_id="acc_crash", amount=5000, currency="INR", state="FAILED", state_confidence=1.0,
            failure_evidence={"reason": "timeout"}, first_seen_at=now, last_seen_at=now,
            recovery_eligible=True, eligibility_reason="DEFINITIVE_FAILED_PAYMENT", schema_version="1.5",
            source_event_ids=["evt_crash"], stage1_state_version=1,
        ))
        session.commit()

    # Step 2: Worker process crashes before Redis publication!
    # Step 3: Restart & durable PostgreSQL sweep runs
    published_events = []
    class MockQueue:
        def publish_case(self, case_id: str):
            published_events.append(case_id)

    swept = _sweep_cases(factory, MockQueue())
    assert "rc_crash_1" in swept
    assert published_events == ["rc_crash_1"]

    # Step 4: Stage 2 receives swept case and registers it
    contract = _sample_contract("rc_crash_1", state_version=1)
    with factory() as session:
        res = register_stage2_case(session, contract)
        session.commit()
        assert res.status == "REGISTERED"
        assert res.is_current is True


def test_p0a_version_race_stale_prevention(tmp_path):
    """Simulate v17 created -> v18 created (payment.captured revokes eligibility in DB) -> v17 arrives late.

    Expected: v17 is marked STALE_SUPERSEDED and is_current=False; v17 MUST NEVER overwrite v18 or be actionable.
    """
    factory, settings = _setup_db(tmp_path)
    now = utc_now()

    # PostgreSQL ground truth: Payment was captured at v18 (recovery_eligible=False)
    with factory() as session:
        session.add(RecoveryCase(
            case_id="rc_race_1", payment_id="pay_race_1", recovery_episode_id="evt_fail",
            merchant_id="acc_race", amount=12000, currency="INR", state="CAPTURED", state_confidence=1.0,
            failure_evidence={}, first_seen_at=now, last_seen_at=now,
            recovery_eligible=False, eligibility_reason="PAYMENT_ALREADY_CAPTURED", schema_version="1.5",
            source_event_ids=["evt_fail", "evt_cap"], stage1_state_version=18,
        ))
        session.commit()

    # Now v17 (old failure message) arrives late at Stage 2
    v17_contract = _sample_contract("rc_race_1", state_version=17, eligible=True)

    with factory() as session:
        res = register_stage2_case(session, v17_contract)
        session.commit()

        # v17 must be marked STALE_SUPERSEDED and NOT current
        assert res.status == "STALE_SUPERSEDED"
        assert res.is_current is False

    with factory() as session:
        rows = session.scalars(select(Stage2Case).where(Stage2Case.case_id == "rc_race_1")).all()
        assert len(rows) == 1
        assert rows[0].status == "STALE_SUPERSEDED"
        assert rows[0].is_current is False

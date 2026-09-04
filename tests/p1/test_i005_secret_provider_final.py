import os
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from recovery_service.models import RecoveryCase
from recovery_service.stage2.models import (
    Base,
    CaseAssignmentLinkRecord,
    ExperimentAssignmentRecord,
    Stage2Case,
)
from recovery_service.stage2.experiment import (
    create_experiment_design,
    freeze_experiment_design,
    mark_experiment_ready,
    approve_experiment_design,
    activate_experiment_running,
)
from recovery_service.stage2.assignment import assign_experiment_case
from recovery_service.stage2.consumer import process_p1_pipeline
from recovery_service.stage2.schemas import RecoveryCaseContract
import recovery_service.stage2.assignment as assignment_mod


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _setup_active_experiment(session, exp_id="exp_sec_final"):
    now = datetime.now(timezone.utc)
    start_past = now - timedelta(days=1)
    rec = create_experiment_design(session, exp_id, allocation_ratio=0.50, population_start_time=start_past)
    rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    rec.single_active_experiment_constraint = False
    session.commit()
    rec_frozen = freeze_experiment_design(session, exp_id, "1.0")
    session.commit()
    mark_experiment_ready(session, exp_id, "1.0")
    session.commit()
    approve_experiment_design(
        session, exp_id, "1.0", principal_id="admin_01", configuration_hash=rec_frozen.approved_configuration_hash
    )
    session.commit()
    activate_experiment_running(session, exp_id, "1.0")
    session.commit()
    return rec


def test_production_path_valid_secret(db_session, monkeypatch):
    exp = _setup_active_experiment(db_session, "exp_sec_val")
    monkeypatch.setenv("ASSIGNMENT_SECRET_SALT", "test_valid_secret_key_123")

    future_t = exp.population_start_time + timedelta(seconds=10)
    case_1 = RecoveryCase(
        case_id="rc_sec_val_01",
        payment_id="pay_sec_val_01",
        recovery_episode_id="ep_sec_val_01",
        merchant_id="merch_val",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_sec_val_01"},
        first_seen_at=future_t,
        last_seen_at=future_t,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_sec_val_01",
        stage1_state_version=1,
        payment_id="pay_sec_val_01",
        merchant_id="merch_val",
        status="RECEIVED",
        created_at=future_t,
        updated_at=future_t,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    contract = RecoveryCaseContract(
        case_id="rc_sec_val_01",
        payment_id="pay_sec_val_01",
        recovery_episode_id="ep_sec_val_01",
        merchant_id="merch_val",
        amount=1000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        first_seen_at=future_t.isoformat(),
        last_seen_at=future_t.isoformat(),
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
        failure_evidence={"customer_id": "cust_sec_val_01"},
    )

    hmac_calls = 0
    orig_hmac = assignment_mod.compute_hmac_assignment_bucket
    def hmac_spy(*args, **kwargs):
        nonlocal hmac_calls
        hmac_calls += 1
        return orig_hmac(*args, **kwargs)

    monkeypatch.setattr(assignment_mod, "compute_hmac_assignment_bucket", hmac_spy)

    process_p1_pipeline(db_session, contract)
    db_session.commit()

    assert hmac_calls == 1
    link = db_session.query(CaseAssignmentLinkRecord).filter_by(case_id="rc_sec_val_01").first()
    assert link is not None
    assert link.assignment_arm in {"CONTROL", "TREATMENT"}


def test_production_path_missing_secret(db_session, monkeypatch):
    exp = _setup_active_experiment(db_session, "exp_sec_mis")
    monkeypatch.delenv("ASSIGNMENT_SECRET_SALT", raising=False)
    monkeypatch.delenv("DEFAULT_ASSIGNMENT_SALT", raising=False)

    future_t = exp.population_start_time + timedelta(seconds=10)
    case_1 = RecoveryCase(
        case_id="rc_sec_mis_01",
        payment_id="pay_sec_mis_01",
        recovery_episode_id="ep_sec_mis_01",
        merchant_id="merch_mis",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_sec_mis_01"},
        first_seen_at=future_t,
        last_seen_at=future_t,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_sec_mis_01",
        stage1_state_version=1,
        payment_id="pay_sec_mis_01",
        merchant_id="merch_mis",
        status="RECEIVED",
        created_at=future_t,
        updated_at=future_t,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    contract = RecoveryCaseContract(
        case_id="rc_sec_mis_01",
        payment_id="pay_sec_mis_01",
        recovery_episode_id="ep_sec_mis_01",
        merchant_id="merch_mis",
        amount=1000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        first_seen_at=future_t.isoformat(),
        last_seen_at=future_t.isoformat(),
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
        failure_evidence={"customer_id": "cust_sec_mis_01"},
    )

    hmac_calls = 0
    orig_hmac = assignment_mod.compute_hmac_assignment_bucket
    def hmac_spy(*args, **kwargs):
        nonlocal hmac_calls
        hmac_calls += 1
        return orig_hmac(*args, **kwargs)

    monkeypatch.setattr(assignment_mod, "compute_hmac_assignment_bucket", hmac_spy)

    process_p1_pipeline(db_session, contract)
    db_session.commit()

    assert hmac_calls == 0
    link = db_session.query(CaseAssignmentLinkRecord).filter_by(case_id="rc_sec_mis_01").first()
    assert link is not None
    assert link.assignment_arm == "UNASSIGNED"
    assert link.assignment_status == "INFRASTRUCTURE_FAILURE"


def test_production_path_empty_secret(db_session, monkeypatch):
    exp = _setup_active_experiment(db_session, "exp_sec_emp")
    monkeypatch.setenv("ASSIGNMENT_SECRET_SALT", "")

    future_t = exp.population_start_time + timedelta(seconds=10)
    case_1 = RecoveryCase(
        case_id="rc_sec_emp_01",
        payment_id="pay_sec_emp_01",
        recovery_episode_id="ep_sec_emp_01",
        merchant_id="merch_emp",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_sec_emp_01"},
        first_seen_at=future_t,
        last_seen_at=future_t,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_sec_emp_01",
        stage1_state_version=1,
        payment_id="pay_sec_emp_01",
        merchant_id="merch_emp",
        status="RECEIVED",
        created_at=future_t,
        updated_at=future_t,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    contract = RecoveryCaseContract(
        case_id="rc_sec_emp_01",
        payment_id="pay_sec_emp_01",
        recovery_episode_id="ep_sec_emp_01",
        merchant_id="merch_emp",
        amount=1000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        first_seen_at=future_t.isoformat(),
        last_seen_at=future_t.isoformat(),
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
        failure_evidence={"customer_id": "cust_sec_emp_01"},
    )

    hmac_calls = 0
    orig_hmac = assignment_mod.compute_hmac_assignment_bucket
    def hmac_spy(*args, **kwargs):
        nonlocal hmac_calls
        hmac_calls += 1
        return orig_hmac(*args, **kwargs)

    monkeypatch.setattr(assignment_mod, "compute_hmac_assignment_bucket", hmac_spy)

    process_p1_pipeline(db_session, contract)
    db_session.commit()

    assert hmac_calls == 0
    link = db_session.query(CaseAssignmentLinkRecord).filter_by(case_id="rc_sec_emp_01").first()
    assert link is not None
    assert link.assignment_arm == "UNASSIGNED"
    assert link.assignment_status == "INFRASTRUCTURE_FAILURE"


def test_production_path_whitespace_secret(db_session, monkeypatch):
    exp = _setup_active_experiment(db_session, "exp_sec_ws")
    monkeypatch.setenv("ASSIGNMENT_SECRET_SALT", "   \t\n ")

    future_t = exp.population_start_time + timedelta(seconds=10)
    case_1 = RecoveryCase(
        case_id="rc_sec_ws_01",
        payment_id="pay_sec_ws_01",
        recovery_episode_id="ep_sec_ws_01",
        merchant_id="merch_ws",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_sec_ws_01"},
        first_seen_at=future_t,
        last_seen_at=future_t,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_sec_ws_01",
        stage1_state_version=1,
        payment_id="pay_sec_ws_01",
        merchant_id="merch_ws",
        status="RECEIVED",
        created_at=future_t,
        updated_at=future_t,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    contract = RecoveryCaseContract(
        case_id="rc_sec_ws_01",
        payment_id="pay_sec_ws_01",
        recovery_episode_id="ep_sec_ws_01",
        merchant_id="merch_ws",
        amount=1000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        first_seen_at=future_t.isoformat(),
        last_seen_at=future_t.isoformat(),
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
        failure_evidence={"customer_id": "cust_sec_ws_01"},
    )

    hmac_calls = 0
    orig_hmac = assignment_mod.compute_hmac_assignment_bucket
    def hmac_spy(*args, **kwargs):
        nonlocal hmac_calls
        hmac_calls += 1
        return orig_hmac(*args, **kwargs)

    monkeypatch.setattr(assignment_mod, "compute_hmac_assignment_bucket", hmac_spy)

    process_p1_pipeline(db_session, contract)
    db_session.commit()

    assert hmac_calls == 0
    link = db_session.query(CaseAssignmentLinkRecord).filter_by(case_id="rc_sec_ws_01").first()
    assert link is not None
    assert link.assignment_arm == "UNASSIGNED"
    assert link.assignment_status == "INFRASTRUCTURE_FAILURE"


def test_provider_exception_fails_closed(db_session, monkeypatch):
    exp = _setup_active_experiment(db_session, "exp_sec_exc")
    
    def failing_resolver():
        raise RuntimeError("Secret provider service unavailable")

    monkeypatch.setattr(assignment_mod, "resolve_production_secret_salt", failing_resolver)

    future_t = exp.population_start_time + timedelta(seconds=10)
    case_1 = RecoveryCase(
        case_id="rc_sec_exc_01",
        payment_id="pay_sec_exc_01",
        recovery_episode_id="ep_sec_exc_01",
        merchant_id="merch_exc",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_sec_exc_01"},
        first_seen_at=future_t,
        last_seen_at=future_t,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_sec_exc_01",
        stage1_state_version=1,
        payment_id="pay_sec_exc_01",
        merchant_id="merch_exc",
        status="RECEIVED",
        created_at=future_t,
        updated_at=future_t,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    contract = RecoveryCaseContract(
        case_id="rc_sec_exc_01",
        payment_id="pay_sec_exc_01",
        recovery_episode_id="ep_sec_exc_01",
        merchant_id="merch_exc",
        amount=1000,
        currency="INR",
        state="FAILED",
        state_confidence=1.0,
        first_seen_at=future_t.isoformat(),
        last_seen_at=future_t.isoformat(),
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
        failure_evidence={"customer_id": "cust_sec_exc_01"},
    )

    hmac_calls = 0
    orig_hmac = assignment_mod.compute_hmac_assignment_bucket
    def hmac_spy(*args, **kwargs):
        nonlocal hmac_calls
        hmac_calls += 1
        return orig_hmac(*args, **kwargs)

    monkeypatch.setattr(assignment_mod, "compute_hmac_assignment_bucket", hmac_spy)

    process_p1_pipeline(db_session, contract)
    db_session.commit()

    assert hmac_calls == 0
    link = db_session.query(CaseAssignmentLinkRecord).filter_by(case_id="rc_sec_exc_01").first()
    assert link is not None
    assert link.assignment_arm == "UNASSIGNED"
    assert link.assignment_status == "INFRASTRUCTURE_FAILURE"

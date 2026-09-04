import os
import math
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from recovery_service.models import RecoveryCase
from recovery_service.stage2.models import (
    Base,
    ExperimentDesignRecord,
    CaseAssignmentLinkRecord,
    Stage2Case,
)
from recovery_service.stage2.experiment import (
    create_experiment_design,
    freeze_experiment_design,
    mark_experiment_ready,
    approve_experiment_design,
    activate_experiment_running,
    ExperimentDesign,
)
from recovery_service.stage2.assignment import assign_experiment_case


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def test_empty_secret_fails_closed(db_session):
    now = datetime.now(timezone.utc)
    start_past = now - timedelta(days=1)

    exp_id = "exp_rem_salt_1"
    rec = create_experiment_design(db_session, exp_id, allocation_ratio=0.50, population_start_time=start_past)
    rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    rec.single_active_experiment_constraint = False
    db_session.commit()
    rec_frozen = freeze_experiment_design(db_session, exp_id, "1.0")
    db_session.commit()
    mark_experiment_ready(db_session, exp_id, "1.0")
    db_session.commit()
    approve_experiment_design(
        db_session, exp_id, "1.0", principal_id="admin_01", configuration_hash=rec_frozen.approved_configuration_hash
    )
    db_session.commit()
    activate_experiment_running(db_session, exp_id, "1.0")
    db_session.commit()

    case_1 = RecoveryCase(
        case_id="rc_rem_salt_01",
        payment_id="pay_rem_salt_01",
        recovery_episode_id="ep_rem_salt_01",
        merchant_id="merch_rem",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_rem_01"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_rem_salt_01",
        stage1_state_version=1,
        payment_id="pay_rem_salt_01",
        merchant_id="merch_rem",
        status="RECEIVED",
        created_at=now,
        updated_at=now,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    # Empty secret salt MUST fail closed (UNASSIGNED, INFRASTRUCTURE_FAILURE)
    res, link = assign_experiment_case(db_session, "rc_rem_salt_01", experiment_id=exp_id, secret_salt="")
    db_session.commit()

    assert link is not None
    assert link.assignment_arm == "UNASSIGNED"
    assert link.assignment_status == "INFRASTRUCTURE_FAILURE"
    assert link.assignment_arm not in {"CONTROL", "TREATMENT"}


def test_whitespace_secret_fails_closed(db_session):
    now = datetime.now(timezone.utc)
    start_past = now - timedelta(days=1)

    exp_id = "exp_rem_salt_2"
    rec = create_experiment_design(db_session, exp_id, allocation_ratio=0.50, population_start_time=start_past)
    rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    rec.single_active_experiment_constraint = False
    db_session.commit()
    rec_frozen = freeze_experiment_design(db_session, exp_id, "1.0")
    db_session.commit()
    mark_experiment_ready(db_session, exp_id, "1.0")
    db_session.commit()
    approve_experiment_design(
        db_session, exp_id, "1.0", principal_id="admin_01", configuration_hash=rec_frozen.approved_configuration_hash
    )
    db_session.commit()
    activate_experiment_running(db_session, exp_id, "1.0")
    db_session.commit()

    case_1 = RecoveryCase(
        case_id="rc_rem_salt_02",
        payment_id="pay_rem_salt_02",
        recovery_episode_id="ep_rem_salt_02",
        merchant_id="merch_rem",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_rem_02"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_rem_salt_02",
        stage1_state_version=1,
        payment_id="pay_rem_salt_02",
        merchant_id="merch_rem",
        status="RECEIVED",
        created_at=now,
        updated_at=now,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    # Whitespace-only secret salt MUST fail closed
    res, link = assign_experiment_case(db_session, "rc_rem_salt_02", experiment_id=exp_id, secret_salt="   \t\n ")
    db_session.commit()

    assert link is not None
    assert link.assignment_arm == "UNASSIGNED"
    assert link.assignment_status == "INFRASTRUCTURE_FAILURE"
    assert link.assignment_arm not in {"CONTROL", "TREATMENT"}


def test_valid_secret_assigns_normally(db_session):
    now = datetime.now(timezone.utc)
    start_past = now - timedelta(days=1)

    exp_id = "exp_rem_salt_3"
    rec = create_experiment_design(db_session, exp_id, allocation_ratio=0.50, population_start_time=start_past)
    rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    rec.single_active_experiment_constraint = False
    db_session.commit()
    rec_frozen = freeze_experiment_design(db_session, exp_id, "1.0")
    db_session.commit()
    mark_experiment_ready(db_session, exp_id, "1.0")
    db_session.commit()
    approve_experiment_design(
        db_session, exp_id, "1.0", principal_id="admin_01", configuration_hash=rec_frozen.approved_configuration_hash
    )
    db_session.commit()
    activate_experiment_running(db_session, exp_id, "1.0")
    db_session.commit()

    future_t = rec.population_start_time + timedelta(seconds=10)
    case_1 = RecoveryCase(
        case_id="rc_rem_salt_03",
        payment_id="pay_rem_salt_03",
        recovery_episode_id="ep_rem_salt_03",
        merchant_id="merch_rem",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "cust_rem_03"},
        first_seen_at=future_t,
        last_seen_at=future_t,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_1 = Stage2Case(
        case_id="rc_rem_salt_03",
        stage1_state_version=1,
        payment_id="pay_rem_salt_03",
        merchant_id="merch_rem",
        status="RECEIVED",
        created_at=future_t,
        updated_at=future_t,
    )
    db_session.add(s2_1)
    db_session.add(case_1)
    db_session.commit()

    res, link = assign_experiment_case(db_session, "rc_rem_salt_03", experiment_id=exp_id, secret_salt="valid_test_secret_salt_123")
    db_session.commit()

    assert link is not None
    assert link.assignment_arm in {"CONTROL", "TREATMENT"}


def test_negative_ratio_rejected(db_session):
    with pytest.raises(ValueError, match="Invalid allocation_ratio"):
        create_experiment_design(db_session, "exp_neg_ratio", allocation_ratio=-1.0)


def test_ratio_above_one_rejected(db_session):
    with pytest.raises(ValueError, match="Invalid allocation_ratio"):
        create_experiment_design(db_session, "exp_high_ratio", allocation_ratio=2.0)


def test_nan_ratio_rejected(db_session):
    with pytest.raises(ValueError, match="Invalid allocation_ratio"):
        create_experiment_design(db_session, "exp_nan_ratio", allocation_ratio=float("nan"))


def test_positive_infinity_ratio_rejected(db_session):
    with pytest.raises(ValueError, match="Invalid allocation_ratio"):
        create_experiment_design(db_session, "exp_inf_ratio", allocation_ratio=float("inf"))


def test_negative_infinity_ratio_rejected(db_session):
    with pytest.raises(ValueError, match="Invalid allocation_ratio"):
        create_experiment_design(db_session, "exp_neginf_ratio", allocation_ratio=float("-inf"))


def test_valid_ratios_accepted(db_session):
    now = datetime.now(timezone.utc)
    rec0 = create_experiment_design(db_session, "exp_ratio_0", allocation_ratio=0.0)
    rec1 = create_experiment_design(db_session, "exp_ratio_1", allocation_ratio=1.0)
    rec05 = create_experiment_design(db_session, "exp_ratio_05", allocation_ratio=0.5)

    assert rec0.allocation_ratio == 0.0
    assert rec1.allocation_ratio == 1.0
    assert rec05.allocation_ratio == 0.5

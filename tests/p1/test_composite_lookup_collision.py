import os
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from recovery_service.models import RecoveryCase
from recovery_service.stage2.models import (
    Base,
    ExperimentDesignRecord,
    IdentityBindingRecord,
    CaseAssignmentLinkRecord,
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


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    os.environ["DEFAULT_ASSIGNMENT_SALT"] = "test_salt_composite_lookup_v1"
    yield session
    session.close()


def test_composite_lookup_collision_regression(db_session):
    """Regression test proving colon-delimited boundary blending tuples map to distinct bindings."""
    exp_id = "exp_collision_test"
    rec = create_experiment_design(db_session, exp_id, allocation_ratio=0.50)
    rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    db_session.commit()
    rec_frozen = freeze_experiment_design(db_session, exp_id, "1.0")
    db_session.commit()
    mark_experiment_ready(db_session, exp_id, "1.0")
    db_session.commit()
    approve_experiment_design(
        db_session, exp_id, "1.0", principal_id="human_admin_01", configuration_hash=rec_frozen.approved_configuration_hash
    )
    db_session.commit()
    activate_experiment_running(db_session, exp_id, "1.0")
    db_session.commit()

    now = datetime.now(timezone.utc)

    # Tuple A: merchant_id="m1", identity_type="CUSTOM_TYPE", customer_id="user:123"
    case_A = RecoveryCase(
        case_id="rc_comp_A",
        payment_id="pay_comp_A",
        recovery_episode_id="ep_comp_A",
        merchant_id="m1",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "user:123"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_case_A = Stage2Case(
        case_id="rc_comp_A",
        stage1_state_version=1,
        payment_id="pay_comp_A",
        merchant_id="m1",
        status="RECEIVED",
        created_at=now,
        updated_at=now,
    )
    db_session.add(s2_case_A)
    db_session.add(case_A)
    db_session.commit()

    asgn_A, link_A = assign_experiment_case(db_session, "rc_comp_A", experiment_id=exp_id)
    db_session.commit()
    assert link_A is not None

    binding_A = db_session.get(IdentityBindingRecord, link_A.binding_id)
    assert binding_A.merchant_id == "m1"
    assert binding_A.resolved_identity_source_key == "m1:user:123"

    # Tuple B: merchant_id="m1:CUSTOM_TYPE", identity_type="user", customer_id="123"
    case_B = RecoveryCase(
        case_id="rc_comp_B",
        payment_id="pay_comp_B",
        recovery_episode_id="ep_comp_B",
        merchant_id="m1:CUSTOM_TYPE",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": "123"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2_case_B = Stage2Case(
        case_id="rc_comp_B",
        stage1_state_version=1,
        payment_id="pay_comp_B",
        merchant_id="m1:CUSTOM_TYPE",
        status="RECEIVED",
        created_at=now,
        updated_at=now,
    )
    db_session.add(s2_case_B)
    db_session.add(case_B)
    db_session.commit()

    asgn_B, link_B = assign_experiment_case(db_session, "rc_comp_B", experiment_id=exp_id)
    db_session.commit()
    assert link_B is not None

    binding_B = db_session.get(IdentityBindingRecord, link_B.binding_id)
    assert binding_B.merchant_id == "m1:CUSTOM_TYPE"
    assert binding_B.resolved_identity_source_key == "m1:CUSTOM_TYPE:123"

    # CRITICAL INVARIANT: Binding A and Binding B MUST be completely distinct!
    assert binding_A.binding_id != binding_B.binding_id
    assert db_session.query(IdentityBindingRecord).count() == 2


def test_boundary_colon_variations(db_session):
    """Test boundary variations containing single colons, double colons, and empty segments."""
    exp_id = "exp_boundary_test"
    rec = create_experiment_design(db_session, exp_id, allocation_ratio=0.50)
    rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    db_session.commit()
    rec_frozen = freeze_experiment_design(db_session, exp_id, "1.0")
    db_session.commit()
    mark_experiment_ready(db_session, exp_id, "1.0")
    db_session.commit()
    approve_experiment_design(
        db_session, exp_id, "1.0", principal_id="human_admin_01", configuration_hash=rec_frozen.approved_configuration_hash
    )
    db_session.commit()
    activate_experiment_running(db_session, exp_id, "1.0")
    db_session.commit()

    now = datetime.now(timezone.utc)
    cases_data = [
        ("rc_var_1", "merch:a", "cust::1"),
        ("rc_var_2", "merch::a", "cust:1"),
        ("rc_var_3", "merch", "a:cust::1"),
    ]

    binding_ids = set()
    for case_id, merchant, customer in cases_data:
        case = RecoveryCase(
            case_id=case_id,
            payment_id=f"pay_{case_id}",
            recovery_episode_id=f"ep_{case_id}",
            merchant_id=merchant,
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={"customer_id": customer},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="FAILED_PAYMENT",
            schema_version="1.0",
            stage1_state_version=1,
        )
        s2_case = Stage2Case(
            case_id=case_id,
            stage1_state_version=1,
            payment_id=f"pay_{case_id}",
            merchant_id=merchant,
            status="RECEIVED",
            created_at=now,
            updated_at=now,
        )
        db_session.add(s2_case)
        db_session.add(case)
        db_session.commit()

        asgn, link = assign_experiment_case(db_session, case_id, experiment_id=exp_id)
        db_session.commit()
        binding_ids.add(link.binding_id)

    assert len(binding_ids) == 3
    assert db_session.query(IdentityBindingRecord).count() == 3

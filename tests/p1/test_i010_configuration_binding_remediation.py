import os
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
    compute_configuration_hash,
    experiment_design_from_record,
)
from recovery_service.stage2.assignment import assign_experiment_case
import recovery_service.stage2.assignment as assignment_mod


@pytest.fixture
def db_session():
    os.environ["ASSIGNMENT_SECRET_SALT"] = "test_i010_remediation_salt_v1"
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _setup_running_experiment(session, exp_id="exp_i010_remediation", version="1.0"):
    now = datetime.now(timezone.utc)
    start_past = now - timedelta(days=1)
    rec = create_experiment_design(session, exp_id, experiment_version=version, allocation_ratio=0.50, population_start_time=start_past)
    rec.assignment_identity_strategy = "MERCHANT_SCOPED_CUSTOMER_STABLE"
    rec.single_active_experiment_constraint = False
    session.commit()

    rec_frozen = freeze_experiment_design(session, exp_id, version)
    session.commit()
    approved_hash = rec_frozen.approved_configuration_hash

    mark_experiment_ready(session, exp_id, version)
    session.commit()
    approve_experiment_design(session, exp_id, version, principal_id="admin_01", configuration_hash=approved_hash)
    session.commit()
    activate_experiment_running(session, exp_id, version)
    session.commit()
    return rec


def _add_case(session, case_id, cust_id="cust_101"):
    now = datetime.now(timezone.utc)
    c = RecoveryCase(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id=f"ep_{case_id}",
        merchant_id="merch_remediation",
        state="FAILED",
        state_confidence=1.0,
        failure_evidence={"customer_id": cust_id},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="FAILED_PAYMENT",
        schema_version="1.0",
        stage1_state_version=1,
    )
    s2 = Stage2Case(
        case_id=case_id,
        stage1_state_version=1,
        payment_id=f"pay_{case_id}",
        merchant_id="merch_remediation",
        status="RECEIVED",
        created_at=now,
        updated_at=now,
    )
    session.add(s2)
    session.add(c)
    session.commit()
    return c


def test_i010_mutation_fails_closed_and_suppresses_hmac(db_session, monkeypatch):
    rec = _setup_running_experiment(db_session, "exp_i010_mut")
    _add_case(db_session, "rc_i010_base")

    # Instrument HMAC calls
    hmac_calls = 0
    orig_hmac = assignment_mod.compute_hmac_assignment_bucket

    def tracking_hmac(*args, **kwargs):
        nonlocal hmac_calls
        hmac_calls += 1
        return orig_hmac(*args, **kwargs)

    monkeypatch.setattr(assignment_mod, "compute_hmac_assignment_bucket", tracking_hmac)

    # 1. Baseline Case Assignment
    res1, link1 = assign_experiment_case(db_session, "rc_i010_base", experiment_id="exp_i010_mut")
    db_session.commit()
    assert link1.assignment_arm in {"CONTROL", "TREATMENT"}
    assert hmac_calls == 1

    # Reset counter
    hmac_calls = 0

    # 2. Mutate allocation_ratio directly in DB
    rec.allocation_ratio = 1.00
    db_session.commit()

    # 3. New Case Assignment under Mutated Configuration
    _add_case(db_session, "rc_i010_mutated")
    res2, link2 = assign_experiment_case(db_session, "rc_i010_mutated", experiment_id="exp_i010_mut")
    db_session.commit()

    # Verify FAIL CLOSED behavior
    assert link2.assignment_arm == "UNASSIGNED"
    assert link2.assignment_status == "UNASSIGNED_STALE_CONFIGURATION"
    assert hmac_calls == 0  # Zero HMAC calls executed!


def test_i010_all_21_field_mutations(db_session):
    now = datetime.now(timezone.utc)
    mutations = [
        ("control_arm_definition", "MUTATED_CONTROL"),
        ("treatment_arm_definition", "MUTATED_TREATMENT"),
        ("primary_metric", "MUTATED_METRIC"),
        ("secondary_metrics", ["mutated_metric"]),
        ("population_definition", "MUTATED_POPULATION"),
        ("population_start_time", now - timedelta(days=10)),
        ("population_end_time", now + timedelta(days=30)),
        ("assignment_identity_strategy", "MERCHANT_SCOPED_PAYMENT_STABLE"),
        ("assignment_salt_version", "v2_mutated"),
        ("allocation_ratio", 0.99),
        ("baseline_assumption_source", "MUTATED_SOURCE"),
        ("baseline_recovery_rate", "0.50"),
        ("minimum_detectable_effect", "0.10"),
        ("required_sample_size", "10000"),
        ("significance_level", 0.01),
        ("statistical_power", 0.95),
        ("attribution_window_hours", 144),
        ("efficacy_stopping_rule", "MUTATED_RULE"),
        ("safety_stopping_rules", {"max_compliance_violations": 99}),
    ]

    for idx, (field_name, mutated_val) in enumerate(mutations, 1):
        exp_id = f"exp_i010_field_{idx}"
        rec = _setup_running_experiment(db_session, exp_id)

        # Mutate single field directly
        setattr(rec, field_name, mutated_val)
        db_session.commit()

        cid = f"rc_i010_f_{idx}"
        _add_case(db_session, cid)

        res, link = assign_experiment_case(db_session, cid, experiment_id=exp_id)
        db_session.commit()

        assert link.assignment_arm == "UNASSIGNED", f"Field '{field_name}' mutation failed to result in UNASSIGNED arm"
        assert link.assignment_status == "UNASSIGNED_STALE_CONFIGURATION", f"Field '{field_name}' mutation failed to fail closed"


def test_i010_missing_and_corrupt_approved_hash(db_session):
    # 1. Missing Approved Hash
    rec1 = _setup_running_experiment(db_session, "exp_i010_null_hash")
    rec1.approved_configuration_hash = None
    db_session.commit()

    _add_case(db_session, "rc_i010_null")
    res1, link1 = assign_experiment_case(db_session, "rc_i010_null", experiment_id="exp_i010_null_hash")
    assert link1.assignment_arm == "UNASSIGNED"
    assert link1.assignment_status == "UNASSIGNED_STALE_CONFIGURATION"

    # 2. Corrupt Approved Hash
    rec2 = _setup_running_experiment(db_session, "exp_i010_bad_hash")
    rec2.approved_configuration_hash = "corrupt_hash_12345678901234567890123456789012"
    db_session.commit()

    _add_case(db_session, "rc_i010_corrupt")
    res2, link2 = assign_experiment_case(db_session, "rc_i010_corrupt", experiment_id="exp_i010_bad_hash")
    assert link2.assignment_arm == "UNASSIGNED"
    assert link2.assignment_status == "UNASSIGNED_STALE_CONFIGURATION"


def test_i010_hash_substitution_attack(db_session):
    rec_a = _setup_running_experiment(db_session, "exp_i010_sub_a")
    rec_b = _setup_running_experiment(db_session, "exp_i010_sub_b")

    hash_a = rec_a.approved_configuration_hash
    hash_b = rec_b.approved_configuration_hash

    # Substitute hash_b onto exp_a
    rec_a.approved_configuration_hash = hash_b
    db_session.commit()

    _add_case(db_session, "rc_i010_sub_test")
    res, link = assign_experiment_case(db_session, "rc_i010_sub_test", experiment_id="exp_i010_sub_a")
    assert link.assignment_arm == "UNASSIGNED"
    assert link.assignment_status == "UNASSIGNED_STALE_CONFIGURATION"


def test_i010_existing_link_immutability_preserved(db_session):
    rec = _setup_running_experiment(db_session, "exp_i010_i003")
    _add_case(db_session, "rc_i010_existing")

    # 1. Assign baseline case
    res1, link1 = assign_experiment_case(db_session, "rc_i010_existing", experiment_id="exp_i010_i003")
    db_session.commit()
    orig_arm = link1.assignment_arm
    assert orig_arm in {"CONTROL", "TREATMENT"}

    # 2. Mutate configuration
    rec.allocation_ratio = 0.99
    db_session.commit()

    # 3. Replay existing case -> I-003 immutability returns committed link unchanged
    res_replay, link_replay = assign_experiment_case(db_session, "rc_i010_existing", experiment_id="exp_i010_i003")
    assert link_replay.assignment_arm == orig_arm
    assert link_replay.assignment_status == link1.assignment_status

    # 4. New case -> I-010 fails closed
    _add_case(db_session, "rc_i010_new_case")
    res_new, link_new = assign_experiment_case(db_session, "rc_i010_new_case", experiment_id="exp_i010_i003")
    assert link_new.assignment_arm == "UNASSIGNED"
    assert link_new.assignment_status == "UNASSIGNED_STALE_CONFIGURATION"

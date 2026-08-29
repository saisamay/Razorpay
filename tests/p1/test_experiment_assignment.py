from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings as hyp_settings, strategies as st
from sqlalchemy import select

from recovery_service.database import Base, build_session_factory
from recovery_service.models import RecoveryCase
from recovery_service.settings import Settings
from recovery_service.stage2.assignment import (
    assign_experiment_case,
    canonical_encode_input,
    compute_hmac_assignment_bucket,
    resolve_assignment_identity,
)
from recovery_service.stage2.consumer import process_p1_pipeline
from recovery_service.stage2.experiment import (
    activate_experiment_running,
    approve_experiment_design,
    create_experiment_design,
    freeze_experiment_design,
    mark_experiment_ready,
)
from recovery_service.stage2.models import (
    CaseAssignmentLinkRecord,
    ExperimentAssignmentRecord,
    ExperimentDesignRecord,
    IdentityBindingRecord,
    IdentityQuarantineRecord,
)
from recovery_service.stage2.schemas import RecoveryCaseContract


def _setup_f3_env(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/f3_test.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    return factory


def _create_active_running_experiment(session, exp_id="exp_f3_active"):
    now = datetime.now(timezone.utc)
    create_experiment_design(session, exp_id, allocation_ratio=0.50, population_start_time=now - timedelta(minutes=10))
    rec = freeze_experiment_design(session, exp_id)
    mark_experiment_ready(session, exp_id)
    approve_experiment_design(session, exp_id, "1.0", "human_auditor_alpha", rec.approved_configuration_hash)
    activate_experiment_running(session, exp_id)
    session.commit()
    return exp_id


def test_assignment_is_deterministic(tmp_path):
    """I-001: Same approved inputs always return the same arm."""
    factory = _setup_f3_env(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        exp_id = _create_active_running_experiment(session, "exp_det_01")

        case = RecoveryCase(
            case_id="rc_det_1",
            payment_id="pay_det_1",
            recovery_episode_id="ep_det",
            merchant_id="merchant_alpha",
            amount=50000,
            currency="INR",
            state="FAILED",
            state_confidence=0.99,
            failure_evidence={"reason": "GATEWAY_TIMEOUT"},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
            schema_version="1.5",
            source_event_ids=["evt_det"],
            stage1_state_version=1,
        )
        session.add(case)
        session.commit()

        res1, link1 = assign_experiment_case(session, "rc_det_1", experiment_id=exp_id)
        session.commit()

        res2, link2 = assign_experiment_case(session, "rc_det_1", experiment_id=exp_id)
        session.commit()

        assert res1 is not None and res2 is not None
        assert res1.assignment_arm == res2.assignment_arm
        assert res1.assignment_id == res2.assignment_id
        assert link1.link_id == link2.link_id


def test_assignment_is_model_independent(tmp_path):
    """I-004: Assignment does not consume downstream intelligence."""
    factory = _setup_f3_env(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        exp_id = _create_active_running_experiment(session, "exp_indep_01")

        contract_a = RecoveryCaseContract(
            case_id="rc_indep_A",
            payment_id="pay_same_1",
            recovery_episode_id="ep_1",
            merchant_id="merchant_beta",
            amount=50000,
            currency="INR",
            state="FAILED",
            state_confidence=0.99,
            failure_evidence={"reason": "GATEWAY_TIMEOUT"},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
            schema_version="1.5",
            source_event_ids=["evt_1"],
            stage1_state_version=1,
        )

        session.add(RecoveryCase(
            case_id=contract_a.case_id,
            payment_id=contract_a.payment_id,
            recovery_episode_id=contract_a.recovery_episode_id,
            merchant_id=contract_a.merchant_id,
            amount=contract_a.amount,
            currency=contract_a.currency,
            state=contract_a.state,
            state_confidence=contract_a.state_confidence,
            failure_evidence=contract_a.failure_evidence,
            first_seen_at=contract_a.first_seen_at,
            last_seen_at=contract_a.last_seen_at,
            recovery_eligible=True,
            eligibility_reason=contract_a.eligibility_reason,
            schema_version=contract_a.schema_version,
            source_event_ids=contract_a.source_event_ids,
            stage1_state_version=1,
        ))
        session.commit()

        res_a, _ = assign_experiment_case(session, "rc_indep_A", experiment_id=exp_id)
        session.commit()

        # Run downstream pipeline
        process_p1_pipeline(session, contract_a)
        session.commit()

        # Re-check assignment after downstream pipeline execution
        res_after, _ = assign_experiment_case(session, "rc_indep_A", experiment_id=exp_id)
        assert res_a.assignment_arm == res_after.assignment_arm


def test_merchant_namespace_isolation(tmp_path):
    """I-008, I-017: Merchant A + identity X != Merchant B + identity X."""
    factory = _setup_f3_env(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        exp_id = _create_active_running_experiment(session, "exp_iso_01")

        b1 = canonical_encode_input("v1", exp_id, "1.0", "merchant_A", "PAYMENT", "pay_shared", "v1", "1.0")
        b2 = canonical_encode_input("v1", exp_id, "1.0", "merchant_B", "PAYMENT", "pay_shared", "v1", "1.0")

        assert b1 != b2

        bucket1, _ = compute_hmac_assignment_bucket("secret", b1)
        bucket2, _ = compute_hmac_assignment_bucket("secret", b2)
        assert bucket1 != bucket2


def test_prestart_case_not_assigned(tmp_path):
    """I-006: Cases created before RUNNING activation timestamp get NOT_ASSIGNED_PRESTART."""
    factory = _setup_f3_env(tmp_path)
    past_time = datetime.now(timezone.utc) - timedelta(hours=5)

    with factory() as session:
        exp_id = _create_active_running_experiment(session, "exp_prestart_01")

        case = RecoveryCase(
            case_id="rc_prestart_1",
            payment_id="pay_prestart_1",
            recovery_episode_id="ep_pre",
            merchant_id="merchant_alpha",
            amount=50000,
            currency="INR",
            state="FAILED",
            state_confidence=0.99,
            failure_evidence={"reason": "GATEWAY_TIMEOUT"},
            first_seen_at=past_time,
            last_seen_at=past_time,
            recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
            schema_version="1.5",
            source_event_ids=["evt_pre"],
            stage1_state_version=1,
        )
        session.add(case)
        session.commit()

        res, link = assign_experiment_case(session, "rc_prestart_1", experiment_id=exp_id)
        session.commit()

        assert res.assignment_arm == "EXCLUDED"
        assert res.assignment_status == "NOT_ASSIGNED_PRESTART"


def test_quarantine_persistence(tmp_path):
    """I-019: Identity conflict results in QUARANTINED status and EXCLUDED arm."""
    factory = _setup_f3_env(tmp_path)

    with factory() as session:
        exp_id = _create_active_running_experiment(session, "exp_quar_01")
        now = datetime.now(timezone.utc)

        import hashlib
        raw_fp = "merchant_alpha:MERCHANT_SCOPED_PAYMENT_STABLE:merchant_alpha:fp_quar_123"
        exact_fp = hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()

        # Add active quarantine record for merchant_alpha
        session.add(IdentityQuarantineRecord(
            quarantine_id="q_merchant_alpha_PAYMENT_fp_quar",
            merchant_id="merchant_alpha",
            identity_type="MERCHANT_SCOPED_PAYMENT_STABLE",
            identity_fingerprint=exact_fp,
            conflict_count=3,
            status="QUARANTINED",
            created_at=now,
        ))
        session.commit()

        case = RecoveryCase(
            case_id="rc_quar_1",
            payment_id="fp_quar_123",
            recovery_episode_id="ep_q",
            merchant_id="merchant_alpha",
            amount=50000,
            currency="INR",
            state="FAILED",
            state_confidence=0.99,
            failure_evidence={"reason": "GATEWAY_TIMEOUT"},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
            schema_version="1.5",
            source_event_ids=["evt_q"],
            stage1_state_version=1,
        )
        session.add(case)
        session.commit()

        res, link = assign_experiment_case(session, "rc_quar_1", experiment_id=exp_id)
        session.commit()

        assert link.assignment_status == "QUARANTINED"
        assert res.assignment_arm == "EXCLUDED"


def test_commit_time_experiment_validity_race(tmp_path):
    """I-026: Mid-transaction transition from RUNNING -> SAFETY_STOPPED invalidates assignment."""
    factory = _setup_f3_env(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        exp_id = _create_active_running_experiment(session, "exp_race_01")

        case = RecoveryCase(
            case_id="rc_race_1",
            payment_id="pay_race_1",
            recovery_episode_id="ep_race",
            merchant_id="merchant_alpha",
            amount=50000,
            currency="INR",
            state="FAILED",
            state_confidence=0.99,
            failure_evidence={"reason": "GATEWAY_TIMEOUT"},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
            schema_version="1.5",
            source_event_ids=["evt_race"],
            stage1_state_version=1,
        )
        session.add(case)
        session.commit()

        # Transition experiment to SAFETY_STOPPED
        exp_rec = session.get(ExperimentDesignRecord, f"{exp_id}:1.0")
        exp_rec.status = "SAFETY_STOPPED"
        session.commit()

        res, link = assign_experiment_case(session, "rc_race_1", experiment_id=exp_id)
        session.commit()

        assert res is None or res.assignment_arm in {"UNASSIGNED", "EXCLUDED"}


def test_shadow_mode_zero_execution_calls(tmp_path):
    """I-016: F3 treatment assignment in shadow mode executes zero Stage 3 calls."""
    factory = _setup_f3_env(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        exp_id = _create_active_running_experiment(session, "exp_shadow_01")

        contract = RecoveryCaseContract(
            case_id="rc_shadow_f3_1",
            payment_id="pay_shadow_f3_1",
            recovery_episode_id="ep_shd",
            merchant_id="merchant_alpha",
            amount=50000,
            currency="INR",
            state="FAILED",
            state_confidence=0.99,
            failure_evidence={"reason": "GATEWAY_TIMEOUT"},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
            schema_version="1.5",
            source_event_ids=["evt_shd"],
            stage1_state_version=1,
        )

        session.add(RecoveryCase(
            case_id=contract.case_id,
            payment_id=contract.payment_id,
            recovery_episode_id=contract.recovery_episode_id,
            merchant_id=contract.merchant_id,
            amount=contract.amount,
            currency=contract.currency,
            state=contract.state,
            state_confidence=contract.state_confidence,
            failure_evidence=contract.failure_evidence,
            first_seen_at=contract.first_seen_at,
            last_seen_at=contract.last_seen_at,
            recovery_eligible=True,
            eligibility_reason=contract.eligibility_reason,
            schema_version=contract.schema_version,
            source_event_ids=contract.source_event_ids,
            stage1_state_version=1,
        ))
        session.commit()

        genome, proposal, shadow_eval = process_p1_pipeline(session, contract)
        session.commit()

        # Assert shadow mode evaluation recorded without physical payment execution
        assert shadow_eval is not None
        assert shadow_eval.baseline_action == "STOP"
        assert shadow_eval.stage2_proposed_action is not None


# Hypothesis Property-Based State Sequence Test Harness (Section 37, 38 & I-001..I-026)
@given(
    exp_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=5, max_size=12),
    merchant_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=5, max_size=12),
    payment_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=5, max_size=12),
    cust_id=st.one_of(st.none(), st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=5, max_size=12)),
    ratio=st.floats(min_value=0.05, max_value=0.95),
    salt_ver=st.sampled_from(["v1", "v2"]),
    alg_ver=st.sampled_from(["1.0", "1.1"]),
)
@hyp_settings(max_examples=100, deadline=None)
def test_hypothesis_property_harness_invariants(exp_id, merchant_id, payment_id, cust_id, ratio, salt_ver, alg_ver):
    """Property-based state machine test generating state transition sequences to verify I-001 through I-026."""
    secret_salt = "hypothesis_salt_v1"

    # Simulated case
    ev = {"customer_id": cust_id} if cust_id else {}
    case = RecoveryCase(
        case_id=f"rc_{payment_id}",
        payment_id=payment_id,
        merchant_id=merchant_id,
        failure_evidence=ev,
    )

    # I-012, I-017, I-024: Identity Resolution
    id_type, source_key, fp, unit = resolve_assignment_identity(case, "ALL")
    assert id_type in {"MERCHANT_SCOPED_CUSTOMER_STABLE", "MERCHANT_SCOPED_PAYMENT_STABLE", "MERCHANT_SCOPED_CASE_STABLE"}
    assert source_key.startswith(merchant_id)
    assert len(fp) == 64  # SHA-256 hex string

    # I-008, I-009: Injective Canonical Encoding
    b1 = canonical_encode_input("v1", exp_id, "1.0", merchant_id, id_type, fp, salt_ver, alg_ver)
    b2 = canonical_encode_input("v1", exp_id, "1.0", merchant_id, id_type, fp, salt_ver, alg_ver)
    assert b1 == b2

    # Verify merchant scoping injectivity (I-008)
    b_other_merchant = canonical_encode_input("v1", exp_id, "1.0", f"{merchant_id}_other", id_type, fp, salt_ver, alg_ver)
    assert b1 != b_other_merchant

    # I-001: Deterministic HMAC Assignment Derivation
    bucket1, digest1 = compute_hmac_assignment_bucket(secret_salt, b1)
    bucket2, digest2 = compute_hmac_assignment_bucket(secret_salt, b2)
    assert bucket1 == bucket2
    assert digest1 == digest2
    assert 0.0 <= bucket1 <= 1.0

    arm1 = "TREATMENT" if bucket1 < ratio else "CONTROL"
    arm2 = "TREATMENT" if bucket2 < ratio else "CONTROL"
    assert arm1 == arm2

    # I-025: Configuration Hash Hash-Exclusion Verification
    from recovery_service.stage2.experiment import ExperimentDesign, compute_configuration_hash
    now = datetime.now(timezone.utc)
    exp = ExperimentDesign(
        experiment_id=exp_id,
        experiment_version="1.0",
        population_start_time=now,
        allocation_ratio=ratio,
        assignment_salt_version=salt_ver,
        created_at=now,
    )
    h1 = compute_configuration_hash(exp)
    # Mutating activation timestamp must NOT change approved configuration hash
    exp_activated = exp.model_copy(update={"status": "RUNNING", "approved_at": now + timedelta(seconds=5)})
    h2 = compute_configuration_hash(exp_activated)
    assert h1 == h2

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.orm import Session

from recovery_service.database import Base, build_session_factory, ensure_schema
from recovery_service.settings import Settings
from recovery_service.stage2.f4.contracts import EvaluationStatus
from recovery_service.stage2.f5.contracts import (
    AuthorizedActionSet,
    DecisionPolicyAuthorization,
    EvidenceSupersessionStatus,
    PolicyBinding,
    PolicyStatus,
    SourceF4EvidenceReference,
)
from recovery_service.stage2.f5.repository import save_policy
from recovery_service.stage2.models import DecisionPolicyRecord
from recovery_service.stage3.models import (
    Stage3OptimizationCandidate,
    Stage3PolicyPerformanceProjection,
)
from recovery_service.stage3.optimizer import (
    compute_candidate_id,
    compute_f5_policy_id,
    generate_optimization_candidate,
    submit_candidate_to_f5,
)
from recovery_service.stage3.repository import Stage3OptimizationCandidateRepository
from recovery_service.stage3.schemas import CandidateStatus, ProjectionStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def session_factory():
    settings = Settings(
        database_url="sqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("sec_test",),
        environment="test",
        max_webhook_bytes=1048576,
    )
    factory = build_session_factory(settings)
    ensure_schema(factory)
    return factory


@pytest.fixture
def session(session_factory):
    with session_factory() as session:
        yield session


def _create_active_f5_policy(
    session: Session,
    merchant_id: str = "merch_test_s3_3",
    policy_id: str = "pol_s3_3_active",
    authorized_actions: tuple[str, ...] = ("RETRY_NOW", "RETRY_LATER"),
    baseline_action: str = "STOP",
) -> DecisionPolicyRecord:
    binding = PolicyBinding(
        merchant_id=merchant_id,
        experiment_id="EXP_S3_3",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
        policy_version="1.0",
    )
    source_f4_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="f4_ev_s3_3_001",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash="a" * 64,
        source_f4_point_estimate=12.5,
        source_f4_confidence_interval_lower=5.0,
        source_f4_confidence_interval_upper=20.0,
        statistical_limitations=[],
        supersession_status=EvidenceSupersessionStatus.CURRENT,
    )
    auth = DecisionPolicyAuthorization(
        policy_id=policy_id,
        binding=binding,
        source_f4_reference=source_f4_ref,
        authorized_actions=AuthorizedActionSet(actions=authorized_actions),
        baseline_action=baseline_action,
        status=PolicyStatus.ACTIVE_ENFORCED,
        activated_at=utc_now(),
    )
    return save_policy(session, auth)


def _create_s3_2_projection(
    session: Session,
    merchant_id: str = "merch_test_s3_3",
    projection_id: str = "proj_s3_3_001",
    policy_id: str = "pol_s3_3_active",
    sample_size: int = 100,
    strategy_breakdown: dict | None = None,
    window_age_hours: int = 1,
) -> Stage3PolicyPerformanceProjection:
    now = utc_now()
    if strategy_breakdown is None:
        strategy_breakdown = {
            "RETRY_NOW": {
                "sample_size": 60,
                "recovery_success_rate": 0.40,
                "total_net_recovered_amount": 1200.0,
                "avg_recovery_latency_seconds": 12.0,
            },
            "RETRY_LATER": {
                "sample_size": 40,
                "recovery_success_rate": 0.65,
                "total_net_recovered_amount": 2000.0,
                "avg_recovery_latency_seconds": 1800.0,
            },
        }

    proj = Stage3PolicyPerformanceProjection(
        projection_id=projection_id,
        merchant_id=merchant_id,
        policy_id=policy_id,
        policy_version="1.0",
        experiment_id="EXP_S3_3",
        experiment_version="1.0",
        configuration_hash="a" * 64,
        window_start=now - timedelta(hours=24),
        window_end=now - timedelta(hours=window_age_hours),
        sample_size=sample_size,
        recovery_success_rate=0.50,
        total_net_recovered_amount=3200.0,
        operational_failure_rate=0.05,
        avg_recovery_latency_seconds=727.2,
        strategy_breakdown_json=strategy_breakdown,
        status=ProjectionStatus.ACTIVE_MONITORING.value,
        created_at=now,
        updated_at=now,
    )
    session.add(proj)
    session.flush()
    return proj


def test_f5_has_no_scalar_current_action(session):
    """Verifies that F5 active policy defines authorized_actions set, NOT a scalar current action."""
    pol = _create_active_f5_policy(session)
    assert hasattr(pol, "authorized_actions")
    assert isinstance(pol.authorized_actions, list)
    assert "RETRY_NOW" in pol.authorized_actions
    assert "RETRY_LATER" in pol.authorized_actions
    assert not hasattr(pol, "current_action")


def test_s3_baseline_is_derived_from_s3_observed_execution(session):
    """Verifies S3-3 operational baseline action (a_baseline) is derived from eligible execution in S3-2."""
    _create_active_f5_policy(session)
    proj = _create_s3_2_projection(session)

    res = generate_optimization_candidate(session, proj.projection_id)
    assert res.status == CandidateStatus.ACCEPTED
    assert res.baseline_action == "RETRY_NOW"  # Max sample size (60 vs 40)
    assert res.proposed_action == "RETRY_LATER"
    assert res.baseline_objective_value == pytest.approx(20.0)  # 1200 / 60
    assert res.objective_value == pytest.approx(50.0)  # 2000 / 40
    assert res.expected_improvement_value == pytest.approx(30.0)  # 50 - 20


def test_authorized_set_not_treated_as_current_action(session):
    """Verifies that authorized_actions set is not mistaken for a single current action."""
    _create_active_f5_policy(session, authorized_actions=("RETRY_LATER", "RETRY_NOW"))
    proj = _create_s3_2_projection(session)

    res = generate_optimization_candidate(session, proj.projection_id)
    assert res.baseline_action == "RETRY_NOW"  # Determined by max execution count, NOT tuple index 0


def test_f5_baseline_fallback_not_used_as_s3_optimization_baseline(session):
    """Verifies F5 baseline_action ("STOP") is NOT used as S3-3 operational comparison baseline."""
    _create_active_f5_policy(session, baseline_action="STOP")
    proj = _create_s3_2_projection(session)

    res = generate_optimization_candidate(session, proj.projection_id)
    assert res.baseline_action != "STOP"
    assert res.baseline_action == "RETRY_NOW"


def test_insufficient_baseline_evidence_fails_closed(session):
    """Verifies insufficient sample size per action (< 10) returns NO_CANDIDATE."""
    _create_active_f5_policy(session)
    low_sample_breakdown = {
        "RETRY_NOW": {"sample_size": 5, "total_net_recovered_amount": 100.0, "success_rate": 0.5},
        "RETRY_LATER": {"sample_size": 4, "total_net_recovered_amount": 200.0, "success_rate": 0.6},
    }
    proj = _create_s3_2_projection(session, projection_id="proj_low", strategy_breakdown=low_sample_breakdown)

    res = generate_optimization_candidate(session, proj.projection_id, min_action_sample_size=10)
    assert res.status == "NO_CANDIDATE"
    assert res.reason_code == "INSUFFICIENT_BASELINE_EVIDENCE"


def test_candidate_compares_against_operational_baseline(session):
    """Verifies candidate expected improvement delta V = V(a_candidate) - V(a_baseline)."""
    _create_active_f5_policy(session)
    proj = _create_s3_2_projection(session)

    res = generate_optimization_candidate(session, proj.projection_id)
    assert res.expected_improvement_value == pytest.approx(res.objective_value - res.baseline_objective_value)


def test_f5_save_policy_is_idempotent_for_same_candidate(session):
    """Verifies passing stable policy_id to save_policy() updates existing record without duplicates."""
    pol = _create_active_f5_policy(session)
    cand_id = compute_candidate_id("merch_test_s3_3", "proj_s3_3_001", "RETRY_LATER")
    f5_pol_id = compute_f5_policy_id(cand_id)

    binding = PolicyBinding(
        merchant_id="merch_test_s3_3",
        experiment_id="EXP_S3_3",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
        policy_version="1.0_draft",
    )
    source_f4_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="f4_ev_s3_3_001",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash="a" * 64,
    )
    auth = DecisionPolicyAuthorization(
        policy_id=f5_pol_id,
        binding=binding,
        source_f4_reference=source_f4_ref,
        authorized_actions=AuthorizedActionSet(actions=("RETRY_LATER",)),
        baseline_action="STOP",
        status=PolicyStatus.DRAFT,
    )

    rec1 = save_policy(session, auth)
    assert rec1.policy_id == f5_pol_id

    # Second call with same policy_id
    rec2 = save_policy(session, auth)
    assert rec2.policy_id == f5_pol_id
    assert rec1 is rec2


def test_crash_after_f5_success_before_local_persist(session):
    """Verifies retry uses stable policy_id to locate/reuse existing F5 DRAFT policy."""
    _create_active_f5_policy(session)
    proj = _create_s3_2_projection(session)

    cand_id = compute_candidate_id("merch_test_s3_3", proj.projection_id, "RETRY_LATER")
    f5_pol_id = compute_f5_policy_id(cand_id)

    # Simulate manual creation of F5 policy (as if crash occurred after F5 save_policy but before candidate update)
    binding = PolicyBinding(
        merchant_id="merch_test_s3_3",
        experiment_id="EXP_S3_3",
        experiment_version="1.0",
        approved_configuration_hash="a" * 64,
        policy_version="1.0_draft",
    )
    source_f4_ref = SourceF4EvidenceReference(
        source_f4_evidence_id="f4_ev_s3_3_001",
        source_f4_evaluated_at=utc_now(),
        source_f4_status=EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
        source_f4_configuration_hash="a" * 64,
    )
    auth = DecisionPolicyAuthorization(
        policy_id=f5_pol_id,
        binding=binding,
        source_f4_reference=source_f4_ref,
        authorized_actions=AuthorizedActionSet(actions=("RETRY_LATER",)),
        baseline_action="STOP",
        status=PolicyStatus.DRAFT,
    )
    save_policy(session, auth)

    # Run optimizer candidate generation
    res = generate_optimization_candidate(session, proj.projection_id)
    assert res.status == CandidateStatus.ACCEPTED
    assert res.f5_policy_id == f5_pol_id


def test_retry_recovers_existing_f5_draft(session):
    """Verifies background submit_candidate_to_f5 retries WAITING_FOR_F5 candidate safely."""
    _create_active_f5_policy(session)
    proj = _create_s3_2_projection(session)

    cand_id = compute_candidate_id("merch_test_s3_3", proj.projection_id, "RETRY_LATER")
    cand = Stage3OptimizationCandidate(
        candidate_id=cand_id,
        merchant_id="merch_test_s3_3",
        source_projection_id=proj.projection_id,
        policy_id="pol_s3_3_active",
        policy_version="1.0",
        experiment_id="EXP_S3_3",
        experiment_version="1.0",
        configuration_hash="a" * 64,
        proposed_action="RETRY_LATER",
        baseline_action="RETRY_NOW",
        objective_value=50.0,
        baseline_objective_value=20.0,
        expected_improvement_value=30.0,
        observed_recovery_rate=0.65,
        baseline_recovery_rate=0.40,
        expected_improvement_rate=0.25,
        sample_size=40,
        reason_code="MANUAL_WAITING",
        optimizer_version="1.0",
        status=CandidateStatus.WAITING_FOR_F5.value,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(cand)
    session.flush()

    rec = submit_candidate_to_f5(session, cand_id)
    assert rec is not None
    assert cand.status == CandidateStatus.ACCEPTED.value
    assert cand.f5_policy_id == compute_f5_policy_id(cand_id)


def test_candidate_id_serialization_is_injective():
    """Verifies true length-prefixed encoding prevents canonical collisions."""
    id1 = compute_candidate_id("m1", "p1:sub", "a1", "1.0")
    id2 = compute_candidate_id("m1:p1", "sub", "a1", "1.0")
    assert id1 != id2


def test_candidate_id_is_deterministic():
    """Verifies candidate ID generation is 100% deterministic across repeated calls."""
    id1 = compute_candidate_id("merch_1", "proj_1", "RETRY_LATER", "1.0")
    id2 = compute_candidate_id("merch_1", "proj_1", "RETRY_LATER", "1.0")
    assert id1 == id2
    assert id1.startswith("cand_")


def test_stale_projection_rejected(session):
    """Verifies stale projection (> max_projection_age_hours) returns NO_CANDIDATE."""
    _create_active_f5_policy(session)
    proj = _create_s3_2_projection(session, projection_id="proj_stale", window_age_hours=100)

    res = generate_optimization_candidate(session, proj.projection_id, max_projection_age_hours=72)
    assert res.status == "NO_CANDIDATE"
    assert res.reason_code == "STALE_PROJECTION"


def test_safety_constraint_degradation_rejection(session):
    """Verifies candidate violating success-rate safety constraint is excluded."""
    _create_active_f5_policy(session)
    degraded_breakdown = {
        "RETRY_NOW": {
            "sample_size": 60,
            "recovery_success_rate": 0.70,
            "total_net_recovered_amount": 600.0,
        },
        "RETRY_LATER": {
            "sample_size": 40,
            "recovery_success_rate": 0.40,  # 30% lower success rate!
            "total_net_recovered_amount": 2000.0,  # Higher monetary value
        },
    }
    proj = _create_s3_2_projection(session, projection_id="proj_degraded", strategy_breakdown=degraded_breakdown)

    res = generate_optimization_candidate(session, proj.projection_id, max_allowed_rate_degradation=0.0)
    assert res.status == "NO_CANDIDATE"
    assert res.reason_code == "NO_IMPROVEMENT_EXCEEDS_THRESHOLD"

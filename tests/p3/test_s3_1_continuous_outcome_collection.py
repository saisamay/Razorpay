from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from recovery_service.database import Base, ensure_schema
from recovery_service.models import RecoveryCase
from recovery_service.stage2.models import (
    DecisionProposalRecord,
    OutcomeAttributionRecord,
    PolicyEnforcementLogRecord,
    Stage2Case,
)
from recovery_service.stage3.collector import collect_outcome, sweep_unobserved_attributions
from recovery_service.stage3.models import Stage3OutcomeObservation
from recovery_service.stage3.repository import Stage3OutcomeObservationRepository
from recovery_service.stage3.schemas import OutcomeCollectionStatus
from recovery_service.worker import _sweep_stage3_observations


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ensure_schema(factory)
    return factory


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    with session_factory() as session:
        yield session


def _seed_sample_attribution_tree(
    session: Session,
    attribution_id: str = "attr_test_001",
    case_id: str = "case_test_001",
    payment_id: str = "pay_test_001",
    proposal_id: str = "prop_test_001",
    merchant_id: str = "merch_acme_corp",
    enforcement_id: str | None = None,
    policy_id: str = "pol_test_001",
    policy_version: str = "1.0",
    experiment_id: str = "exp_test_001",
    experiment_version: str = "1.0",
    finalized: bool = True,
    proposal_time: datetime | None = None,
    recovery_time: datetime | None = None,
    net_amount: float = 950.0,
    gross_amount: float = 1000.0,
    executed_action: str = "RETRY_IMMEDIATE",
    decision: str = "ALLOW_ACTION",
    outcome_status: str = "RECOVERED",
    case_status: str = "DISPATCHED",
) -> OutcomeAttributionRecord:
    now = datetime.now(timezone.utc)
    p_time = proposal_time or (now - timedelta(hours=2))
    r_time = recovery_time if recovery_time is not None else (p_time + timedelta(minutes=15))
    enf_id = enforcement_id or f"enf_{attribution_id}"

    rec_case = RecoveryCase(
        case_id=case_id,
        payment_id=payment_id,
        recovery_episode_id="ep_001",
        merchant_id=merchant_id,
        amount=100000,
        currency="INR",
        state="RECOVERED",
        state_confidence=1.0,
        failure_evidence={},
        first_seen_at=p_time - timedelta(hours=1),
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="ELIGIBLE",
    )
    session.add(rec_case)

    s2_case = Stage2Case(
        case_id=case_id,
        stage1_state_version=1,
        payment_id=payment_id,
        merchant_id=merchant_id,
        status=case_status,
        is_current=True,
    )
    session.add(s2_case)

    prop = DecisionProposalRecord(
        proposal_id=proposal_id,
        case_id=case_id,
        genome_id="gen_001",
        stage1_state_version=1,
        selected_action=executed_action,
        predicted_success_probability=0.85,
        expected_net_value=950.0,
        data={},
        created_at=p_time,
    )
    session.add(prop)

    enf_log = PolicyEnforcementLogRecord(
        enforcement_id=enf_id,
        proposal_id=proposal_id,
        case_id=case_id,
        merchant_id=merchant_id,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        configuration_hash="cfg_hash_001",
        policy_id=policy_id,
        policy_version=policy_version,
        source_f4_evidence_id="ev_f4_001",
        stage2_proposed_action=executed_action,
        executed_action=executed_action,
        baseline_action="STOP",
        decision=decision,
        reason_code="POLICY_ENFORCED_EFFICACIOUS",
        evaluated_at=p_time,
    )
    session.add(enf_log)

    attr = OutcomeAttributionRecord(
        attribution_id=attribution_id,
        case_id=case_id,
        payment_id=payment_id,
        experiment_id=experiment_id,
        proposal_id=proposal_id,
        proposal_timestamp=p_time,
        attribution_window_start=p_time,
        attribution_window_end=p_time + timedelta(hours=72),
        first_recovery_event_at=r_time,
        gross_recovered_amount=gross_amount,
        refund_amount_within_window=0.0,
        reversal_amount_within_window=0.0,
        net_verified_recovered_amount=net_amount,
        outcome_status=outcome_status if finalized else "OUTCOME_PENDING",
        verification_status="VERIFIED" if finalized else "PENDING",
        created_at=now,
        finalized_at=now if finalized else None,
    )
    session.add(attr)
    session.flush()
    return attr


# Test 1 — Happy path and 4 distinct source concepts preservation
def test_happy_path_and_distinct_source_fields_preservation(session: Session) -> None:
    attr = _seed_sample_attribution_tree(
        session,
        executed_action="RETRY_SCHEDULED",
        decision="ALLOW_ACTION",
        outcome_status="RECOVERED",
        case_status="DISPATCHED",
    )
    session.commit()

    res = collect_outcome(session, attr.attribution_id)
    session.commit()

    assert res.status == OutcomeCollectionStatus.COLLECTED
    assert res.attribution_id == attr.attribution_id
    assert res.merchant_id == "merch_acme_corp"

    obs = session.get(Stage3OutcomeObservation, attr.attribution_id)
    assert obs is not None

    # Verify 4 separate source fields
    assert obs.executed_action == "RETRY_SCHEDULED"
    assert obs.enforcement_decision == "ALLOW_ACTION"
    assert obs.outcome_status == "RECOVERED"
    assert obs.case_status == "DISPATCHED"

    # Verify NO execution_status column exists on Stage3OutcomeObservation model
    assert not hasattr(obs, "execution_status")

    # Verify other required identity and metric fields
    assert obs.attribution_id == attr.attribution_id
    assert obs.case_id == "case_test_001"
    assert obs.payment_id == "pay_test_001"
    assert obs.proposal_id == "prop_test_001"
    assert obs.enforcement_id == "enf_attr_test_001"
    assert obs.merchant_id == "merch_acme_corp"
    assert obs.policy_id == "pol_test_001"
    assert obs.policy_version == "1.0"
    assert obs.experiment_id == "exp_test_001"
    assert obs.experiment_version == "1.0"
    assert obs.gross_recovered_amount == 1000.0
    assert obs.net_verified_recovered_amount == 950.0
    assert obs.recovery_latency_seconds == pytest.approx(900.0)
    assert obs.finalized_at is not None


# Test 2 — Duplicate collection idempotency
def test_duplicate_collection_idempotency(session: Session) -> None:
    attr = _seed_sample_attribution_tree(session)
    session.commit()

    res1 = collect_outcome(session, attr.attribution_id)
    session.commit()
    assert res1.status == OutcomeCollectionStatus.COLLECTED

    res2 = collect_outcome(session, attr.attribution_id)
    assert res2.status == OutcomeCollectionStatus.ALREADY_COLLECTED

    count = session.query(Stage3OutcomeObservation).filter_by(attribution_id=attr.attribution_id).count()
    assert count == 1


# Test 3 — Concurrent collection safety
def test_concurrent_collection(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        attr = _seed_sample_attribution_tree(session)
        session.commit()
        attr_id = attr.attribution_id

    with session_factory() as s1:
        res1 = collect_outcome(s1, attr_id)
        s1.commit()

    with session_factory() as s2:
        res2 = collect_outcome(s2, attr_id)
        s2.commit()

    assert res1.status == OutcomeCollectionStatus.COLLECTED
    assert res2.status == OutcomeCollectionStatus.ALREADY_COLLECTED

    with session_factory() as s3:
        observations = s3.query(Stage3OutcomeObservation).filter_by(attribution_id=attr_id).all()
        assert len(observations) == 1


# Test 4 — Missing attribution
def test_missing_attribution_returns_not_found(session: Session) -> None:
    res = collect_outcome(session, "attr_non_existent")
    assert res.status == OutcomeCollectionStatus.NOT_FOUND


# Test 5 — Unfinalized attribution
def test_unfinalized_attribution_returns_not_ready(session: Session) -> None:
    attr = _seed_sample_attribution_tree(session, finalized=False)
    session.commit()

    res = collect_outcome(session, attr.attribution_id)
    assert res.status == OutcomeCollectionStatus.NOT_READY

    obs = session.get(Stage3OutcomeObservation, attr.attribution_id)
    assert obs is None


# Test 6 — Tenant mismatch validation
def test_tenant_mismatch_validation(session: Session) -> None:
    attr = _seed_sample_attribution_tree(session, merchant_id="merch_acme_corp")
    session.commit()

    res_mismatch = collect_outcome(session, attr.attribution_id, merchant_id="merch_other_corp")
    assert res_mismatch.status == OutcomeCollectionStatus.TENANT_MISMATCH

    res_match = collect_outcome(session, attr.attribution_id, merchant_id="merch_acme_corp")
    assert res_match.status == OutcomeCollectionStatus.COLLECTED


# Test 7 — Financial value preservation
def test_financial_value_preservation(session: Session) -> None:
    attr = _seed_sample_attribution_tree(session, gross_amount=5000.0, net_amount=4850.75)
    session.commit()

    res = collect_outcome(session, attr.attribution_id)
    assert res.status == OutcomeCollectionStatus.COLLECTED

    obs = session.get(Stage3OutcomeObservation, attr.attribution_id)
    assert obs.gross_recovered_amount == 5000.0
    assert obs.net_verified_recovered_amount == 4850.75


# Test 8 — Recovery latency derivation
def test_recovery_latency_derivation(session: Session) -> None:
    p_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    r_time = datetime(2026, 9, 1, 10, 45, 0, tzinfo=timezone.utc)
    attr = _seed_sample_attribution_tree(session, proposal_time=p_time, recovery_time=r_time)
    session.commit()

    res = collect_outcome(session, attr.attribution_id)
    assert res.status == OutcomeCollectionStatus.COLLECTED

    obs = session.get(Stage3OutcomeObservation, attr.attribution_id)
    assert obs.recovery_latency_seconds == pytest.approx(2700.0)


# Test 9 — Invalid timestamp ordering
def test_invalid_timestamp_ordering_returns_validation_failed(session: Session) -> None:
    p_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    r_time = datetime(2026, 9, 1, 9, 30, 0, tzinfo=timezone.utc)
    attr = _seed_sample_attribution_tree(session, proposal_time=p_time, recovery_time=r_time)
    session.commit()

    res = collect_outcome(session, attr.attribution_id)
    assert res.status == OutcomeCollectionStatus.VALIDATION_FAILED

    obs = session.get(Stage3OutcomeObservation, attr.attribution_id)
    assert obs is None


# Test 10 — Database failure handling
def test_database_failure_handling(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    attr = _seed_sample_attribution_tree(session)
    session.commit()

    def mock_insert(*args, **kwargs):
        raise RuntimeError("Simulated DB connection drop")

    monkeypatch.setattr(Stage3OutcomeObservationRepository, "insert", mock_insert)

    res = collect_outcome(session, attr.attribution_id)
    assert res.status == OutcomeCollectionStatus.FAILURE


# Test 11 — Source linkage
def test_source_linkage_propagation(session: Session) -> None:
    attr = _seed_sample_attribution_tree(
        session,
        attribution_id="attr_link_100",
        case_id="case_link_100",
        payment_id="pay_link_100",
        proposal_id="prop_link_100",
        enforcement_id="enf_link_100",
    )
    session.commit()

    res = collect_outcome(session, "attr_link_100")
    assert res.status == OutcomeCollectionStatus.COLLECTED

    obs = session.get(Stage3OutcomeObservation, "attr_link_100")
    assert obs.attribution_id == "attr_link_100"
    assert obs.case_id == "case_link_100"
    assert obs.payment_id == "pay_link_100"
    assert obs.proposal_id == "prop_link_100"
    assert obs.enforcement_id == "enf_link_100"


# Test 12 — Tenant isolation
def test_tenant_isolation(session: Session) -> None:
    _seed_sample_attribution_tree(session, attribution_id="attr_m1", case_id="case_m1", payment_id="p1", proposal_id="pr1", merchant_id="merchant_alpha")
    _seed_sample_attribution_tree(session, attribution_id="attr_m2", case_id="case_m2", payment_id="p2", proposal_id="pr2", merchant_id="merchant_beta")
    session.commit()

    collect_outcome(session, "attr_m1")
    collect_outcome(session, "attr_m2")
    session.commit()

    repo = Stage3OutcomeObservationRepository()
    alpha_obs = repo.list_by_merchant(session, "merchant_alpha")
    beta_obs = repo.list_by_merchant(session, "merchant_beta")

    assert len(alpha_obs) == 1
    assert alpha_obs[0].attribution_id == "attr_m1"
    assert len(beta_obs) == 1
    assert beta_obs[0].attribution_id == "attr_m2"


# Test 13 — Worker sweep integration
def test_worker_sweep_integration(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_sample_attribution_tree(session, attribution_id="attr_s1", case_id="c1", payment_id="p1", proposal_id="pr1")
        _seed_sample_attribution_tree(session, attribution_id="attr_s2", case_id="c2", payment_id="p2", proposal_id="pr2")
        session.commit()

    _sweep_stage3_observations(session_factory)

    with session_factory() as session:
        count = session.query(Stage3OutcomeObservation).count()
        assert count == 2

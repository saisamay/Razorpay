from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from recovery_service.database import Base, ensure_schema
from recovery_service.stage2.models import DecisionPolicyRecord
from recovery_service.stage3.models import Stage3OutcomeObservation, Stage3PolicyPerformanceProjection
from recovery_service.stage3.performance_monitor import generate_policy_performance_projection
from recovery_service.stage3.repository import Stage3PolicyPerformanceRepository
from recovery_service.stage3.schemas import PolicyMonitoringScope, ProjectionStatus


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


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _seed_observation(
    session: Session,
    attribution_id: str,
    merchant_id: str = "merch_acme_corp",
    policy_id: str | None = "pol_alpha",
    policy_version: str | None = "1.0",
    experiment_id: str | None = "exp_001",
    experiment_version: str | None = "1.0",
    executed_action: str = "RETRY_IMMEDIATE",
    enforcement_decision: str | None = "ALLOW_ACTION",
    outcome_status: str = "RECOVERED",
    net_amount: float = 1000.0,
    latency: float | None = 60.0,
    observed_at: datetime | None = None,
) -> Stage3OutcomeObservation:
    now = observed_at or datetime.now(timezone.utc)
    obs = Stage3OutcomeObservation(
        attribution_id=attribution_id,
        case_id=f"case_{attribution_id}",
        payment_id=f"pay_{attribution_id}",
        proposal_id=f"prop_{attribution_id}",
        enforcement_id=f"enf_{attribution_id}",
        merchant_id=merchant_id,
        policy_id=policy_id,
        policy_version=policy_version,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        gross_recovered_amount=net_amount,
        net_verified_recovered_amount=net_amount,
        executed_action=executed_action,
        enforcement_decision=enforcement_decision,
        outcome_status=outcome_status,
        case_status="DISPATCHED",
        recovery_latency_seconds=latency,
        observed_at=now,
        finalized_at=now,
    )
    session.add(obs)
    session.flush()
    return obs


# Test 1 — Basic projection metrics
def test_basic_projection_metrics(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    w_start = now - timedelta(hours=2)
    w_end = now + timedelta(hours=2)

    _seed_observation(session, "a1", outcome_status="RECOVERED", net_amount=1000.0, latency=40.0, observed_at=now)
    _seed_observation(session, "a2", outcome_status="RECOVERED", net_amount=1500.0, latency=60.0, observed_at=now)
    _seed_observation(session, "a3", outcome_status="NO_RECOVERY", net_amount=0.0, latency=None, observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, w_start, w_end, min_sample_size=1)

    assert res.sample_size == 3
    assert res.recovery_success_rate == pytest.approx(2 / 3)
    assert res.total_net_recovered_amount == 2500.0
    assert res.avg_recovery_latency_seconds == pytest.approx(50.0)  # (40 + 60) / 2
    assert res.status == ProjectionStatus.ACTIVE_MONITORING


# Test 2 — Success rate formula
def test_success_rate_formula(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "s1", outcome_status="RECOVERED", observed_at=now)
    _seed_observation(session, "s2", outcome_status="PARTIALLY_RECOVERED", observed_at=now)
    _seed_observation(session, "s3", outcome_status="NO_RECOVERY", observed_at=now)
    _seed_observation(session, "s4", outcome_status="RECOVERED_THEN_REFUNDED", observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res.sample_size == 4
    # RECOVERED + PARTIALLY_RECOVERED = 2 successful out of 4
    assert res.recovery_success_rate == 0.5


# Test 3 — Total net recovery sum
def test_total_net_recovery_sum(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "f1", net_amount=123.45, observed_at=now)
    _seed_observation(session, "f2", net_amount=678.90, observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res.total_net_recovered_amount == pytest.approx(802.35)


# Test 4 — Average latency calculation
def test_average_latency_calculation(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "l1", latency=10.0, observed_at=now)
    _seed_observation(session, "l2", latency=20.0, observed_at=now)
    _seed_observation(session, "l3", latency=30.0, observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res.avg_recovery_latency_seconds == pytest.approx(20.0)


# Test 5 — Missing latency exclusion from denominator
def test_missing_latency_exclusion_from_denominator(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "ml1", latency=10.0, observed_at=now)
    _seed_observation(session, "ml2", latency=20.0, observed_at=now)
    _seed_observation(session, "ml3", latency=None, observed_at=now)  # Missing!
    _seed_observation(session, "ml4", latency=30.0, observed_at=now)
    _seed_observation(session, "ml5", latency=None, observed_at=now)  # Missing!
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    # Valid latencies are [10, 20, 30] -> mean = 20.0 (NOT 60 / 5 = 12)
    assert res.avg_recovery_latency_seconds == pytest.approx(20.0)


# Test 6 — Operational failure rate null semantics
def test_operational_failure_rate_null_semantics(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "of1", enforcement_decision="FAIL_CLOSED", observed_at=now)
    _seed_observation(session, "of2", enforcement_decision="ALLOW_ACTION", observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res.operational_failure_rate is None


# Test 7 — Zero sample NO_DATA handling
def test_zero_sample_no_data_handling(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1))

    assert res.sample_size == 0
    assert res.recovery_success_rate is None
    assert res.total_net_recovered_amount == 0.0
    assert res.avg_recovery_latency_seconds is None
    assert res.status == ProjectionStatus.NO_DATA


# Test 8 — Time window boundaries (inclusive start, exclusive end)
def test_time_window_boundaries(session: Session) -> None:
    w_start = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    w_end = datetime(2026, 9, 1, 11, 0, 0, tzinfo=timezone.utc)

    _seed_observation(session, "b_in_start", observed_at=w_start)  # 10:00:00 -> INCLUDED
    _seed_observation(session, "b_in_mid", observed_at=datetime(2026, 9, 1, 10, 30, 0, tzinfo=timezone.utc))  # INCLUDED
    _seed_observation(session, "b_out_end", observed_at=w_end)  # 11:00:00 -> EXCLUDED (belongs to next window)
    _seed_observation(session, "b_out_before", observed_at=w_start - timedelta(seconds=1))  # EXCLUDED
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, w_start, w_end, min_sample_size=1)

    assert res.sample_size == 2


# Test 9 — Tenant isolation boundary
def test_tenant_isolation_boundary(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "t_alpha", merchant_id="merchant_alpha", observed_at=now)
    _seed_observation(session, "t_beta", merchant_id="merchant_beta", observed_at=now)
    session.commit()

    scope_alpha = PolicyMonitoringScope(merchant_id="merchant_alpha", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res_alpha = generate_policy_performance_projection(session, scope_alpha, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res_alpha.sample_size == 1
    assert res_alpha.scope.merchant_id == "merchant_alpha"


# Test 10 — Policy version isolation
def test_policy_version_isolation(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "v1_obs", policy_version="1.0", observed_at=now)
    _seed_observation(session, "v2_obs", policy_version="2.0", observed_at=now)
    session.commit()

    scope_v1 = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res_v1 = generate_policy_performance_projection(session, scope_v1, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res_v1.sample_size == 1


# Test 11 — Experiment version isolation
def test_experiment_version_isolation(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "ev1", experiment_version="1.0", observed_at=now)
    _seed_observation(session, "ev2", experiment_version="2.0", observed_at=now)
    session.commit()

    scope_e1 = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res_e1 = generate_policy_performance_projection(session, scope_e1, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res_e1.sample_size == 1


# Test 12 — Configuration hash scope isolation
def test_configuration_hash_scope_isolation(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "c1", observed_at=now)
    session.commit()

    scope_cfg_a = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0", configuration_hash="cfg_hash_A")
    res_cfg_a = generate_policy_performance_projection(session, scope_cfg_a, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res_cfg_a.sample_size == 1
    assert res_cfg_a.scope.configuration_hash == "cfg_hash_A"


# Test 13 — Out of order observation window membership
def test_out_of_order_observation_window_membership(session: Session) -> None:
    w_start = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    w_end = datetime(2026, 9, 1, 11, 0, 0, tzinfo=timezone.utc)

    # Insert observation B (10:05) before observation A (10:01)
    _seed_observation(session, "oo_b", observed_at=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc))
    _seed_observation(session, "oo_a", observed_at=datetime(2026, 9, 1, 10, 1, 0, tzinfo=timezone.utc))
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, w_start, w_end, min_sample_size=1)

    assert res.sample_size == 2


# Test 14 — Late observation window membership
def test_late_observation_window_membership(session: Session) -> None:
    w1_start = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    w1_end = datetime(2026, 9, 1, 11, 0, 0, tzinfo=timezone.utc)

    # Observation with observed_at at 10:15
    _seed_observation(session, "late_1", observed_at=datetime(2026, 9, 1, 10, 15, 0, tzinfo=timezone.utc))
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res1 = generate_policy_performance_projection(session, scope, w1_start, w1_end, min_sample_size=1)

    assert res1.sample_size == 1


# Test 15 — Projection recomputation reproducibility
def test_projection_recomputation_reproducibility(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "rep1", net_amount=1000.0, observed_at=now)
    _seed_observation(session, "rep2", net_amount=2000.0, observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res1 = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)
    res2 = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res1.projection_id == res2.projection_id
    assert res1.total_net_recovered_amount == res2.total_net_recovered_amount == 3000.0
    assert res1.sample_size == res2.sample_size == 2


# Test 16 — Concurrent projection upsert safety
def test_concurrent_projection_upsert_safety(session_factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    with session_factory() as session:
        _seed_observation(session, "conc1", observed_at=now)
        session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    w_start = now - timedelta(hours=1)
    w_end = now + timedelta(hours=1)

    with session_factory() as s1:
        generate_policy_performance_projection(s1, scope, w_start, w_end, min_sample_size=1)
        s1.commit()

    with session_factory() as s2:
        generate_policy_performance_projection(s2, scope, w_start, w_end, min_sample_size=1)
        s2.commit()

    with session_factory() as s3:
        projections = s3.query(Stage3PolicyPerformanceProjection).all()
        assert len(projections) == 1


# Test 17 — Strategy breakdown action sums
def test_strategy_breakdown_action_sums(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "sb1", executed_action="RETRY_IMMEDIATE", outcome_status="RECOVERED", net_amount=1000.0, observed_at=now)
    _seed_observation(session, "sb2", executed_action="RETRY_IMMEDIATE", outcome_status="NO_RECOVERY", net_amount=0.0, observed_at=now)
    _seed_observation(session, "sb3", executed_action="STOP", outcome_status="NO_RECOVERY", net_amount=0.0, observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res.sample_size == 3
    breakdown = res.strategy_breakdown
    assert "RETRY_IMMEDIATE" in breakdown
    assert "STOP" in breakdown

    assert breakdown["RETRY_IMMEDIATE"]["sample_size"] == 2
    assert breakdown["RETRY_IMMEDIATE"]["success_count"] == 1
    assert breakdown["RETRY_IMMEDIATE"]["success_rate"] == 0.5

    assert breakdown["STOP"]["sample_size"] == 1
    assert breakdown["STOP"]["success_count"] == 0
    assert breakdown["STOP"]["success_rate"] == 0.0

    # Total sample size equals sum of action sample sizes
    assert sum(b["sample_size"] for b in breakdown.values()) == res.sample_size


# Test 18 — No causal effect or treatment calculations
def test_no_causal_effect_or_treatment_calculations(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_observation(session, "no_causal_1", observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    # Verify no treatment effect, p-value, or ATE fields exist on the result
    assert not hasattr(res, "treatment_effect")
    assert not hasattr(res, "p_value")
    assert not hasattr(res, "confidence_interval")


# Test 19 — No F5 policy state mutation
def test_no_f5_policy_state_mutation(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    pol_rec = DecisionPolicyRecord(
        policy_id="pol_alpha",
        policy_version="1.0",
        merchant_id="merch_acme_corp",
        experiment_id="exp_001",
        experiment_version="1.0",
        approved_configuration_hash="cfg_hash_001",
        source_f4_evidence_id="ev_001",
        source_f4_evaluated_at=now,
        source_f4_status="EFFICACIOUS",
        source_f4_configuration_hash="cfg_hash_001",
        authorized_actions=["RETRY_IMMEDIATE"],
        baseline_action="STOP",
        status="ACTIVE_ENFORCED",
    )
    session.add(pol_rec)
    _seed_observation(session, "f5_mut_1", policy_id="pol_alpha", observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_alpha", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)
    session.commit()

    # F5 policy record status MUST remain ACTIVE_ENFORCED
    reloaded_pol = session.get(DecisionPolicyRecord, "pol_alpha")
    assert reloaded_pol.status == "ACTIVE_ENFORCED"


# Test 20 — Historical policy measurement without active F5
def test_historical_policy_measurement_without_active_f5(session: Session) -> None:
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Seed observation for a historical policy that has NO record in f5_decision_policies table
    _seed_observation(session, "hist_1", policy_id="pol_historical_999", observed_at=now)
    session.commit()

    scope = PolicyMonitoringScope(merchant_id="merch_acme_corp", policy_id="pol_historical_999", policy_version="1.0", experiment_id="exp_001", experiment_version="1.0")
    res = generate_policy_performance_projection(session, scope, now - timedelta(hours=1), now + timedelta(hours=1), min_sample_size=1)

    assert res.sample_size == 1
    assert res.scope.policy_id == "pol_historical_999"
    assert res.status == ProjectionStatus.ACTIVE_MONITORING

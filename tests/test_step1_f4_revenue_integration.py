from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from recovery_service.database import build_session_factory, ensure_schema
from recovery_service.models import PaymentState, RecoveryCase
from recovery_service.revenue_economics import compute_revenue_summary, RevenueSummary
from recovery_service.settings import Settings
from recovery_service.stage2.f4.contracts import (
    ClusteredUncertaintyMetric,
    DifferentialAttrition,
    EstimandPopulation,
    EvaluationStatus,
    F4EvaluationReport,
    F4PrimaryResult,
    F4Provenance,
    F4SecondaryMetrics,
    PopulationAccounting,
)
from recovery_service.stage2.f4.repository import save_f4_report, get_latest_f4_report
from recovery_service.stage3.models import Stage3OutcomeObservation


def _setup_db(tmp_path, db_name="test_step1_f4.db"):
    db_path = tmp_path / db_name
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test_secret",),
        environment="test",
        max_webhook_bytes=1048576,
    )
    factory = build_session_factory(settings)
    ensure_schema(factory)
    return factory


def _build_valid_f4_report(
    *,
    merchant_id: str = "merc_f4_test",
    p: float = 0.50,
    control_recoveries: int = 5,
    point_est: float = 500.0,
    counterfactual_control_subunits: int = 95000,
    status: EvaluationStatus = EvaluationStatus.EFFICACY_RESULT_AVAILABLE,
    invalidation_reasons: list[str] | None = None,
    experiment_id: str = "exp_v1",
    experiment_version: str = "1.0",
) -> F4EvaluationReport:
    now = datetime.now(timezone.utc)
    uncertainty = ClusteredUncertaintyMetric(
        standard_error=10.0,
        confidence_interval_lower=point_est - 19.6,
        confidence_interval_upper=point_est + 19.6,
        confidence_level=0.95,
        clustering_unit_type="MERCHANT",
        clustering_unit_count=1,
    )
    if 0.0 < p < 1.0:
        primary = F4PrimaryResult(
            primary_metric_name="VERIFIED_INCREMENTAL_RECOVERED_REVENUE",
            point_estimate=point_est,
            point_estimator_symbol="IPW_ALLOCATION_ADJUSTED_TOTAL",
            allocation_proportion_p=p,
            estimand_population=EstimandPopulation.PRE_REGISTERED_ELIGIBLE,
            eligible_population_count=10,
            observed_population_count=10,
            uncertainty=uncertainty,
        )
    else:
        primary = None

    secondary = F4SecondaryMetrics(
        conversion_rate_control=0.50,
        conversion_rate_treatment=0.80,
        recovery_count_control=control_recoveries,
        recovery_count_treatment=8,
        counterfactual_control_revenue_subunits=counterfactual_control_subunits,
    )
    attrition = DifferentialAttrition(
        control_observation_rate=1.0,
        treatment_observation_rate=1.0,
        attrition_gap=0.0,
        configured_threshold=0.05,
    )
    accounting = PopulationAccounting(
        total_assigned_control=5,
        total_assigned_treatment=5,
        observed_control=5,
        observed_treatment=5,
        pending_control=0,
        pending_treatment=0,
        unknown_control=0,
        unknown_treatment=0,
        differential_attrition=attrition,
    )
    provenance = F4Provenance(
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        merchant_id=merchant_id,
        approved_configuration_hash="a" * 64,
        assignment_algorithm_version="1.0",
        f4_schema_version="1.0",
        evaluated_at=now,
    )
    return F4EvaluationReport(
        status=status,
        primary_result=primary,
        secondary_metrics=secondary,
        accounting=accounting,
        differential_attrition=attrition,
        provenance=provenance,
        invalidation_reasons=invalidation_reasons or [],
    )


def _seed_test_cases_and_outcomes(factory, merchant_id: str = "merc_f4_test"):
    now = datetime.now(timezone.utc)
    with factory() as session:
        # Create 10 cases of ₹100 (10,000 paise each) -> Total = ₹1,000.00
        for i in range(1, 11):
            cid = f"case_{merchant_id}_{i}"
            pid = f"pay_{merchant_id}_{i}"
            case = RecoveryCase(
                case_id=cid,
                payment_id=pid,
                recovery_episode_id=f"ep_{merchant_id}_{i}",
                merchant_id=merchant_id,
                amount=10000,  # ₹100.00 in paise
                currency="INR",
                state="PAYMENT_FAILED",
                state_confidence=1.0,
                failure_evidence={"error_code": "card_issuer_decline", "rail": "card"},
                first_seen_at=now,
                last_seen_at=now,
                recovery_eligible=True,
                eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
                schema_version="1.5",
                source_event_ids=[f"evt_{merchant_id}_{i}"],
                stage1_state_version=1,
            )
            session.add(case)

            # 10 cases recovered out of 10 -> Total Net Recovered = ₹1,000.00
            obs = Stage3OutcomeObservation(
                attribution_id=f"attr_{merchant_id}_{i}",
                case_id=cid,
                payment_id=pid,
                proposal_id=f"prop_{merchant_id}_{i}",
                merchant_id=merchant_id,
                executed_action="RETRY_NOW",
                outcome_status="RECOVERED",
                gross_recovered_amount=100.0,
                net_verified_recovered_amount=100.0,
                observed_at=now,
                finalized_at=now,
            )
            session.add(obs)
        session.commit()


# Test A — Valid F4 Evidence
def test_step1_valid_f4_evidence(tmp_path):
    factory = _setup_db(tmp_path, "test_a.db")
    merchant_id = "merc_valid_f4"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    f4_report = _build_valid_f4_report(
        merchant_id=merchant_id,
        p=0.50,
        control_recoveries=5,
        point_est=500.0,  # 500 paise/case * 10 cases = 5000 paise = ₹50.00 incremental
        counterfactual_control_subunits=95000,  # ₹950.00 control counterfactual
    )

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id, f4_report=f4_report)

        assert summary.incremental_recovery.status == "AVAILABLE"
        assert summary.incremental_recovery.value == 50.0
        assert summary.baseline_recovery.status == "AVAILABLE"
        assert summary.baseline_recovery.value == 950.0


# Test B — No Control Arm (p = 1.0)
def test_step1_no_control_arm(tmp_path):
    factory = _setup_db(tmp_path, "test_b.db")
    merchant_id = "merc_no_ctrl"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    f4_report = _build_valid_f4_report(
        merchant_id=merchant_id,
        p=1.0,  # No control arm!
        control_recoveries=0,
    )

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id, f4_report=f4_report)

        assert summary.baseline_recovery.status == "NOT_AVAILABLE"
        assert summary.incremental_recovery.status == "NOT_AVAILABLE"


# Test C — Zero Control Observations
def test_step1_zero_control_observations(tmp_path):
    factory = _setup_db(tmp_path, "test_c.db")
    merchant_id = "merc_zero_ctrl"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    f4_report = _build_valid_f4_report(
        merchant_id=merchant_id,
        p=0.50,
        control_recoveries=0,  # 0 control recoveries
    )

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id, f4_report=f4_report)

        assert summary.baseline_recovery.status == "NOT_AVAILABLE"
        assert summary.incremental_recovery.status == "NOT_AVAILABLE"


# Test D — Invalid F4 Status
def test_step1_invalid_f4_status(tmp_path):
    factory = _setup_db(tmp_path, "test_d.db")
    merchant_id = "merc_invalid_status"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    f4_report = _build_valid_f4_report(
        merchant_id=merchant_id,
        status=EvaluationStatus.INSUFFICIENT_DATA_FOR_EFFICACY_CLAIM,
    )

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id, f4_report=f4_report)

        assert summary.baseline_recovery.status == "NOT_AVAILABLE"
        assert summary.incremental_recovery.status == "NOT_AVAILABLE"


# Test E — Invalid Positivity
def test_step1_invalid_positivity(tmp_path):
    factory = _setup_db(tmp_path, "test_e.db")
    merchant_id = "merc_invalid_positivity"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    f4_report = _build_valid_f4_report(
        merchant_id=merchant_id,
        invalidation_reasons=["INVALID_POSITIVITY_DETECTED"],
    )

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id, f4_report=f4_report)

        assert summary.baseline_recovery.status == "NOT_AVAILABLE"
        assert summary.incremental_recovery.status == "NOT_AVAILABLE"


# Test F — Existing Observed Revenue Regression
def test_step1_existing_observed_revenue_regression(tmp_path):
    factory = _setup_db(tmp_path, "test_f.db")
    merchant_id = "merc_regression"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id)

        assert summary.case_count == 10
        assert summary.recovered_case_count == 10
        assert summary.revenue_at_risk_inr == 1000.0
        assert summary.eligible_revenue_inr == 1000.0
        assert summary.gross_recovered_inr == 1000.0
        assert summary.net_verified_recovered_inr == 1000.0
        assert summary.unrecovered_revenue_inr == 0.0
        assert summary.recovery_rate == 1.0


# Test G — No Causal Overclaim
def test_step1_no_causal_overclaim(tmp_path):
    factory = _setup_db(tmp_path, "test_g.db")
    merchant_id = "merc_overclaim"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id)

        assert summary.net_verified_recovered_inr == 1000.0
        assert summary.baseline_recovery.status == "NOT_AVAILABLE"
        assert summary.incremental_recovery.status == "NOT_AVAILABLE"


# Test H — Database Persistence & Application Restart Safety
def test_step1_db_persistence_restart_safety(tmp_path):
    factory = _setup_db(tmp_path, "test_h.db")
    merchant_id = "merc_db_persist"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    f4_report = _build_valid_f4_report(
        merchant_id=merchant_id,
        p=0.50,
        control_recoveries=5,
        point_est=500.0,
        counterfactual_control_subunits=80000,  # ₹800.00
    )

    # 1. Save to DB
    with factory() as session:
        save_f4_report(session, f4_report)
        session.commit()

    # 2. Simulate process restart by querying compute_revenue_summary WITHOUT passing in-memory f4_report!
    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id)

        assert summary.baseline_recovery.status == "AVAILABLE"
        assert summary.baseline_recovery.value == 800.0
        assert summary.incremental_recovery.status == "AVAILABLE"
        assert summary.incremental_recovery.value == 50.0


# Test I — Tenant Isolation in Database
def test_step1_tenant_isolation_db(tmp_path):
    factory = _setup_db(tmp_path, "test_i.db")
    merchant_a = "merc_tenant_a"
    merchant_b = "merc_tenant_b"
    _seed_test_cases_and_outcomes(factory, merchant_a)
    _seed_test_cases_and_outcomes(factory, merchant_b)

    report_a = _build_valid_f4_report(merchant_id=merchant_a, point_est=500.0, counterfactual_control_subunits=70000)
    with factory() as session:
        save_f4_report(session, report_a)
        session.commit()

    # Query for Merchant B (who has NO F4 report in DB)
    with factory() as session:
        summary_b = compute_revenue_summary(session, merchant_id=merchant_b)

        assert summary_b.baseline_recovery.status == "NOT_AVAILABLE"
        assert summary_b.incremental_recovery.status == "NOT_AVAILABLE"

    # Query for Merchant A
    with factory() as session:
        summary_a = compute_revenue_summary(session, merchant_id=merchant_a)

        assert summary_a.baseline_recovery.status == "AVAILABLE"
        assert summary_a.baseline_recovery.value == 700.0


# Test J — Prevention of Invalid Negative Baseline Formula
def test_step1_negative_baseline_prevention(tmp_path):
    factory = _setup_db(tmp_path, "test_j.db")
    merchant_id = "merc_neg_base"
    _seed_test_cases_and_outcomes(factory, merchant_id)

    # Suppose net_verified_recovered_inr is ₹1,000, but incremental_inr is ₹1,500.
    # The old invalid formula would produce 1000 - 1500 = -500 (Negative ₹500).
    # The new authoritative baseline directly uses counterfactual_control_subunits = 20000 (₹200.00).
    f4_report = _build_valid_f4_report(
        merchant_id=merchant_id,
        point_est=15000.0,  # 15,000 paise * 10 = 150,000 paise = ₹1,500
        counterfactual_control_subunits=20000,  # ₹200.00
    )

    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id=merchant_id, f4_report=f4_report)

        assert summary.baseline_recovery.status == "AVAILABLE"
        assert summary.baseline_recovery.value == 200.0  # ₹200.00, NOT -₹500.00!
        assert summary.incremental_recovery.value == 1500.0

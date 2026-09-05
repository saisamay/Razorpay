from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from recovery_service.database import build_session_factory, ensure_schema
from recovery_service.main import app
from recovery_service.models import RecoveryCase
from recovery_service.revenue_economics import compute_revenue_summary, RevenueSummary
from recovery_service.settings import Settings
from recovery_service.stage3.models import Stage3OutcomeObservation


def _setup_db(tmp_path):
    db_path = tmp_path / "test_revenue.sqlite3"
    db_url = f"sqlite:///{db_path}"
    settings = Settings(
        database_url=db_url,
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test_secret",),
        environment="test",
        max_webhook_bytes=1048576,
    )
    factory = build_session_factory(settings)
    ensure_schema(factory)
    app.state.sessions = factory
    return factory


def test_revenue_summary_empty_dataset(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        summary = compute_revenue_summary(session, merchant_id="merc_empty")
        assert summary.merchant_id == "merc_empty"
        assert summary.case_count == 0
        assert summary.revenue_at_risk_paise == 0
        assert summary.revenue_at_risk_inr == 0.0
        assert summary.eligible_revenue_inr == 0.0
        assert summary.gross_recovered_inr == 0.0
        assert summary.net_verified_recovered_inr == 0.0
        assert summary.recovery_rate is None  # Undefined denominator returns None, not 0.0
        assert summary.baseline_recovery.status == "NOT_AVAILABLE"
        assert summary.incremental_recovery.status == "NOT_AVAILABLE"
        assert len(summary.cases_breakdown) == 0


def test_revenue_at_risk_and_eligibility(tmp_path):
    factory = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        # Case 1: Eligible, ₹1,000 (100,000 paise)
        c1 = RecoveryCase(
            case_id="rc_rev_001",
            payment_id="pay_001",
            recovery_episode_id="ep_001",
            merchant_id="merc_test_a",
            amount=100000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
            source_event_ids=["evt_1"],
        )
        # Case 2: Ineligible, ₹500 (50,000 paise)
        c2 = RecoveryCase(
            case_id="rc_rev_002",
            payment_id="pay_002",
            recovery_episode_id="ep_002",
            merchant_id="merc_test_a",
            amount=50000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=False,
            eligibility_reason="MAX_ATTEMPTS_EXCEEDED",
            source_event_ids=["evt_2"],
        )
        session.add_all([c1, c2])
        session.commit()

        summary = compute_revenue_summary(session, merchant_id="merc_test_a")
        assert summary.case_count == 2
        assert summary.revenue_at_risk_paise == 150000
        assert summary.revenue_at_risk_inr == 1500.0
        assert summary.eligible_revenue_paise == 100000
        assert summary.eligible_revenue_inr == 1000.0
        assert summary.unrecovered_revenue_inr == 1000.0
        # No outcomes yet, recovery rate = 0.0 / 1000.0 = 0.0
        assert summary.recovery_rate == 0.0


def test_recovered_revenue_and_recovery_rate(tmp_path):
    factory = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        # Eligible case ₹2,000
        c1 = RecoveryCase(
            case_id="rc_rev_101",
            payment_id="pay_101",
            recovery_episode_id="ep_101",
            merchant_id="merc_test_b",
            amount=200000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
            source_event_ids=["evt_101"],
        )
        # Stage 3 Outcome: Net verified ₹1,500
        obs1 = Stage3OutcomeObservation(
            attribution_id="attr_101",
            case_id="rc_rev_101",
            payment_id="pay_101",
            proposal_id="prop_101",
            merchant_id="merc_test_b",
            gross_recovered_amount=2000.0,
            net_verified_recovered_amount=1500.0,
            executed_action="ALTERNATE_RAIL",
            outcome_status="RECOVERED",
            finalized_at=now,
        )
        session.add_all([c1, obs1])
        session.commit()

        summary = compute_revenue_summary(session, merchant_id="merc_test_b")
        assert summary.case_count == 1
        assert summary.recovered_case_count == 1
        assert summary.revenue_at_risk_inr == 2000.0
        assert summary.eligible_revenue_inr == 2000.0
        assert summary.gross_recovered_inr == 2000.0
        assert summary.net_verified_recovered_inr == 1500.0
        assert summary.unrecovered_revenue_inr == 500.0
        # Recovery Rate = 1500 / 2000 = 0.75 (75%)
        assert summary.recovery_rate == pytest.approx(0.75)


def test_outcome_uniqueness_double_counting_protection(tmp_path):
    """Area B Test: Verify multiple Stage3 outcome observations for the same case do NOT double count."""
    factory = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(hours=1)

    with factory() as session:
        c1 = RecoveryCase(
            case_id="rc_dup_001",
            payment_id="pay_dup_001",
            recovery_episode_id="ep_dup_1",
            merchant_id="merc_dup",
            amount=100000,  # ₹1,000
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        # Observation 1 (earlier attempt): ₹0
        obs_early = Stage3OutcomeObservation(
            attribution_id="attr_dup_1",
            case_id="rc_dup_001",
            payment_id="pay_dup_001",
            proposal_id="prop_dup_1",
            merchant_id="merc_dup",
            gross_recovered_amount=0.0,
            net_verified_recovered_amount=0.0,
            executed_action="RETRY_NOW",
            outcome_status="FAILED",
            observed_at=earlier,
            finalized_at=earlier,
        )
        # Observation 2 (latest finalized attempt): ₹1,000
        obs_latest = Stage3OutcomeObservation(
            attribution_id="attr_dup_2",
            case_id="rc_dup_001",
            payment_id="pay_dup_001",
            proposal_id="prop_dup_2",
            merchant_id="merc_dup",
            gross_recovered_amount=1000.0,
            net_verified_recovered_amount=1000.0,
            executed_action="ALTERNATE_RAIL",
            outcome_status="RECOVERED",
            observed_at=now,
            finalized_at=now,
        )
        session.add_all([c1, obs_early, obs_latest])
        session.commit()

        summary = compute_revenue_summary(session, merchant_id="merc_dup")
        # Must count exactly 1 case and 1 authoritative outcome (₹1,000), not ₹0 + ₹1,000 double count
        assert summary.case_count == 1
        assert summary.recovered_case_count == 1
        assert summary.gross_recovered_inr == 1000.0
        assert summary.net_verified_recovered_inr == 1000.0


def test_merchant_isolation(tmp_path):
    """Area C Test: Merchant A cannot access Merchant B metrics."""
    factory = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        c1 = RecoveryCase(
            case_id="rc_m_a",
            payment_id="pay_m_a",
            recovery_episode_id="ep_a",
            merchant_id="merchant_A",
            amount=100000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        c2 = RecoveryCase(
            case_id="rc_m_b",
            payment_id="pay_m_b",
            recovery_episode_id="ep_b",
            merchant_id="merchant_B",
            amount=500000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        session.add_all([c1, c2])
        session.commit()

        summary_a = compute_revenue_summary(session, merchant_id="merchant_A")
        assert summary_a.case_count == 1
        assert summary_a.revenue_at_risk_inr == 1000.0

        summary_b = compute_revenue_summary(session, merchant_id="merchant_B")
        assert summary_b.case_count == 1
        assert summary_b.revenue_at_risk_inr == 5000.0


def test_tenant_header_mismatch_returns_403(tmp_path):
    """Area C Test: API endpoint raises HTTP 403 Forbidden when authenticated tenant header conflicts with query param."""
    _setup_db(tmp_path)
    client = TestClient(app)

    # Header says merchant_A, query param asks for merchant_B -> HTTP 403 Forbidden
    response = client.get(
        "/api/v2/evaluation/revenue-summary?merchant_id=merchant_B",
        headers={"X-Merchant-Id": "merchant_A"},
    )
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


def test_window_aggregation_filtering(tmp_path):
    """Area D Test: Verify cases inside vs outside window boundaries."""
    factory = _setup_db(tmp_path)
    t0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)  # Inside
    t2 = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)  # Outside

    with factory() as session:
        c_inside = RecoveryCase(
            case_id="rc_win_inside",
            payment_id="pay_win_in",
            recovery_episode_id="ep_win_in",
            merchant_id="merc_win",
            amount=100000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=t1,
            last_seen_at=t1,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        c_outside = RecoveryCase(
            case_id="rc_win_outside",
            payment_id="pay_win_out",
            recovery_episode_id="ep_win_out",
            merchant_id="merc_win",
            amount=500000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=t2,
            last_seen_at=t2,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        session.add_all([c_inside, c_outside])
        session.commit()

        # Window: 2026-09-01 to 2026-09-03
        summary = compute_revenue_summary(
            session,
            merchant_id="merc_win",
            window_start=t0,
            window_end=datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc),
        )
        assert summary.case_count == 1
        assert summary.cases_breakdown[0].case_id == "rc_win_inside"
        assert summary.revenue_at_risk_inr == 1000.0


def test_baseline_and_incremental_metrics_never_fabricated(tmp_path):
    factory = _setup_db(tmp_path)
    with factory() as session:
        summary = compute_revenue_summary(session)
        assert summary.baseline_recovery.status == "NOT_AVAILABLE"
        assert "baseline" in summary.baseline_recovery.reason.lower()
        assert summary.incremental_recovery.status == "NOT_AVAILABLE"
        assert "incremental" in summary.incremental_recovery.reason.lower()
        assert summary.incremental_recovery.value is None


def test_revenue_api_endpoint(tmp_path):
    _setup_db(tmp_path)
    client = TestClient(app)

    response = client.get("/api/v2/evaluation/revenue-summary")
    assert response.status_code == 200
    data = response.json()
    assert "revenue_at_risk_inr" in data
    assert "net_verified_recovered_inr" in data
    assert "recovery_rate" in data
    assert data["baseline_recovery"]["status"] == "NOT_AVAILABLE"
    assert data["incremental_recovery"]["status"] == "NOT_AVAILABLE"


def test_window_boundary_half_open_interval(tmp_path):
    """Area B Test: Explicitly verify three boundaries for half-open interval [window_start, window_end).

    - case timestamp < window_start  -> excluded
    - case timestamp == window_start -> included
    - case timestamp == window_end   -> excluded
    """
    factory = _setup_db(tmp_path)
    w_start = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
    w_end = datetime(2026, 9, 3, 0, 0, 0, tzinfo=timezone.utc)

    with factory() as session:
        # 1. timestamp < window_start (Excluded)
        c_before = RecoveryCase(
            case_id="rc_b_before",
            payment_id="pay_b_before",
            recovery_episode_id="ep_b_before",
            merchant_id="merc_bound",
            amount=100,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=w_start - timedelta(seconds=1),
            last_seen_at=w_start - timedelta(seconds=1),
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        # 2. timestamp == window_start (Included)
        c_exact_start = RecoveryCase(
            case_id="rc_b_start",
            payment_id="pay_b_start",
            recovery_episode_id="ep_b_start",
            merchant_id="merc_bound",
            amount=200,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=w_start,
            last_seen_at=w_start,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        # 3. timestamp == window_end (Excluded)
        c_exact_end = RecoveryCase(
            case_id="rc_b_end",
            payment_id="pay_b_end",
            recovery_episode_id="ep_b_end",
            merchant_id="merc_bound",
            amount=400,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=w_end,
            last_seen_at=w_end,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )

        session.add_all([c_before, c_exact_start, c_exact_end])
        session.commit()

        summary = compute_revenue_summary(
            session,
            merchant_id="merc_bound",
            window_start=w_start,
            window_end=w_end,
        )

        assert summary.case_count == 1
        assert len(summary.cases_breakdown) == 1
        assert summary.cases_breakdown[0].case_id == "rc_b_start"
        assert summary.revenue_at_risk_paise == 200
        assert summary.revenue_at_risk_inr == 2.0


def test_integer_minor_unit_monetary_precision(tmp_path):
    """Area C Test: Verify integer minor-unit paise aggregation and conversion to INR at boundary."""
    factory = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)

    with factory() as session:
        # Cases with precise paise amounts: 101, 202, 303 paise
        c1 = RecoveryCase(
            case_id="rc_p_1",
            payment_id="pay_p_1",
            recovery_episode_id="ep_p_1",
            merchant_id="merc_paise",
            amount=101,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        c2 = RecoveryCase(
            case_id="rc_p_2",
            payment_id="pay_p_2",
            recovery_episode_id="ep_p_2",
            merchant_id="merc_paise",
            amount=202,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        c3 = RecoveryCase(
            case_id="rc_p_3",
            payment_id="pay_p_3",
            recovery_episode_id="ep_p_3",
            merchant_id="merc_paise",
            amount=303,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="ELIGIBLE",
        )
        session.add_all([c1, c2, c3])
        session.commit()

        summary = compute_revenue_summary(session, merchant_id="merc_paise")
        assert summary.revenue_at_risk_paise == 606
        assert summary.revenue_at_risk_inr == 6.06
        assert summary.eligible_revenue_paise == 606
        assert summary.eligible_revenue_inr == 6.06
        assert summary.unrecovered_revenue_inr == 6.06


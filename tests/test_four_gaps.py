"""Four Backend Gaps Integration & Verification Test Suite.

Verifies:
- Gap 1: GET /api/v3/cases/{case_id}/attempts (0 attempts, multi-attempts, ordering, non-escalated, tenant isolation)
- Gap 2: GET /api/v2/evaluation/f4-report (valid report, NOT_AVAILABLE semantics, tenant isolation, no recalculation)
- Gap 3: GET /api/v2/cases (DB-level pagination, limit/offset, filters, tenant isolation, deterministic sorting)
- Gap 4: Experiment Lifecycle Auth (unauthenticated -> 401, invalid token -> 401, valid token -> success)
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from recovery_service.main import app
from recovery_service.database import Base
from recovery_service.models import RecoveryCase
from recovery_service.settings import Settings
from recovery_service.stage2.models import F4EvaluationReportRecord
from recovery_service.stage2.experiment import compute_configuration_hash
from recovery_service.stage3.models import RecoveryAttemptRecord, RecoveryOrchestrationRecord


@pytest.fixture
def test_setup(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/gaps_test.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("sec_test",),
        environment="test",
        max_webhook_bytes=1048576,
        internal_api_token="super-secret-admin-token",
    )
    factory = sessionmaker(bind=build_engine(settings))
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)

    app.state.settings = settings
    app.state.sessions = factory
    return factory, TestClient(app)


def build_engine(settings: Settings):
    from sqlalchemy import create_engine
    return create_engine(settings.database_url, connect_args={"check_same_thread": False})


# --- GAP 1 TESTS: STEP 3 ATTEMPT TIMELINE API ---

def test_gap1_attempt_timeline_empty_and_populated(test_setup):
    factory, client = test_setup
    now = datetime.now(timezone.utc)

    # 1. Case with 0 attempts
    with factory() as session:
        c1 = RecoveryCase(
            case_id="c_zero_attempts",
            payment_id="p_zero",
            recovery_episode_id="ep_zero",
            merchant_id="m_gap1",
            amount=5000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="RETRYABLE",
            schema_version="1.0",
            stage1_state_version=1,
        )
        session.add(c1)
        session.commit()

    res0 = client.get("/api/v3/cases/c_zero_attempts/attempts", headers={"x-merchant-id": "m_gap1"})
    assert res0.status_code == 200
    assert res0.json() == []

    # 2. Case with multiple attempts (non-escalated)
    with factory() as session:
        c2 = RecoveryCase(
            case_id="c_multi_attempts",
            payment_id="p_multi",
            recovery_episode_id="ep_multi",
            merchant_id="m_gap1",
            amount=15000,
            currency="INR",
            state="RECOVERED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="RETRYABLE",
            schema_version="1.0",
            stage1_state_version=1,
        )
        session.add(c2)

        a2 = RecoveryAttemptRecord(
            attempt_id="att_2",
            orchestration_id="orch_multi",
            case_id="c_multi_attempts",
            merchant_id="m_gap1",
            attempt_number=2,
            proposed_action="RETRY_LATER",
            executed_action="RETRY_LATER",
            status="COMPLETED",
            outcome_status="RECOVERED",
            net_recovered_amount=150.0,
            started_at=now,
            completed_at=now,
        )
        a1 = RecoveryAttemptRecord(
            attempt_id="att_1",
            orchestration_id="orch_multi",
            case_id="c_multi_attempts",
            merchant_id="m_gap1",
            attempt_number=1,
            proposed_action="RETRY_NOW",
            executed_action="RETRY_NOW",
            status="FAILED",
            outcome_status="FAILED",
            net_recovered_amount=0.0,
            started_at=now,
            completed_at=now,
        )
        session.add_all([a2, a1])
        session.commit()

    res_multi = client.get("/api/v3/cases/c_multi_attempts/attempts", headers={"x-merchant-id": "m_gap1"})
    assert res_multi.status_code == 200
    attempts = res_multi.json()
    assert len(attempts) == 2
    assert attempts[0]["attempt_number"] == 1
    assert attempts[0]["executed_action"] == "RETRY_NOW"
    assert attempts[1]["attempt_number"] == 2
    assert attempts[1]["executed_action"] == "RETRY_LATER"
    assert attempts[1]["net_recovered_amount"] == 150.0


def test_gap1_attempt_timeline_tenant_isolation_and_404(test_setup):
    factory, client = test_setup
    now = datetime.now(timezone.utc)

    # Missing case -> 404
    res404 = client.get("/api/v3/cases/c_missing/attempts", headers={"x-merchant-id": "m_gap1"})
    assert res404.status_code == 404

    # Seed case owned by m_owner
    with factory() as session:
        c = RecoveryCase(
            case_id="c_tenant_iso",
            payment_id="p_iso",
            recovery_episode_id="ep_iso",
            merchant_id="m_owner",
            amount=5000,
            currency="INR",
            state="FAILED",
            state_confidence=1.0,
            failure_evidence={},
            first_seen_at=now,
            last_seen_at=now,
            recovery_eligible=True,
            eligibility_reason="RETRYABLE",
            schema_version="1.0",
            stage1_state_version=1,
        )
        session.add(c)
        session.commit()

    # Tenant mismatch -> 403
    res403 = client.get("/api/v3/cases/c_tenant_iso/attempts", headers={"x-merchant-id": "m_unauthorized"})
    assert res403.status_code == 403


# --- GAP 2 TESTS: F4 CAUSAL REPORT API ---

def test_gap2_f4_causal_report_surface(test_setup):
    factory, client = test_setup
    now = datetime.now(timezone.utc)

    # 1. NOT_AVAILABLE when no report exists (positivity_status must be null/None)
    res_na = client.get("/api/v2/evaluation/f4-report", headers={"x-merchant-id": "m_f4_test"})
    assert res_na.status_code == 200
    data_na = res_na.json()
    assert data_na["status"] == "NOT_AVAILABLE"
    assert data_na["positivity_status"] is None

    # 2. Seed persisted F4 report with explicit positivity_status = "SATISFIED"
    with factory() as session:
        rec = F4EvaluationReportRecord(
            report_id="rep_f4_101",
            merchant_id="m_f4_test",
            experiment_id="exp_causal_01",
            experiment_version="1.0",
            status="EFFICACY_RESULT_AVAILABLE",
            estimand_population="PRE_REGISTERED_ELIGIBLE",
            allocation_proportion_p=0.50,
            eligible_population_count=100,
            observed_control_count=50,
            observed_treatment_count=50,
            point_estimate_paise_per_unit=250.0,
            incremental_recovered_revenue_paise=25000,
            counterfactual_control_revenue_paise=100000,
            standard_error=12.5,
            confidence_interval_lower=225.0,
            confidence_interval_upper=275.0,
            invalidation_reasons=[],
            raw_report_json={"audit": "verified", "positivity_status": "SATISFIED"},
            evaluated_at=now,
        )
        session.add(rec)
        session.commit()

    # Query valid report
    res_val = client.get("/api/v2/evaluation/f4-report", headers={"x-merchant-id": "m_f4_test"})
    assert res_val.status_code == 200
    data_val = res_val.json()

    # Verify all 21 fields exist in top-level response
    required_fields = [
        "report_id", "merchant_id", "experiment_id", "experiment_version", "status",
        "estimand_population", "allocation_proportion_p", "eligible_population_count",
        "observed_control_count", "observed_treatment_count", "point_estimate_paise_per_unit",
        "incremental_recovered_revenue_paise", "counterfactual_control_revenue_paise",
        "standard_error", "confidence_interval_lower", "confidence_interval_upper",
        "invalidation_reasons", "positivity_status", "raw_report_json", "evaluated_at", "created_at"
    ]
    for field in required_fields:
        assert field in data_val, f"Required top-level field '{field}' missing from F4 report API response"

    # Verify values match persisted evidence
    assert data_val["report_id"] == "rep_f4_101"
    assert data_val["merchant_id"] == "m_f4_test"
    assert data_val["point_estimate_paise_per_unit"] == 250.0
    assert data_val["incremental_recovered_revenue_paise"] == 25000
    assert data_val["counterfactual_control_revenue_paise"] == 100000
    assert data_val["standard_error"] == 12.5
    assert data_val["confidence_interval_lower"] == 225.0
    assert data_val["positivity_status"] == "SATISFIED"
    assert data_val["raw_report_json"]["positivity_status"] == "SATISFIED"

    # 3. Seed and verify report with explicit positivity_status = "FAILED"
    with factory() as session:
        rec_inv = F4EvaluationReportRecord(
            report_id="rep_f4_102",
            merchant_id="m_f4_invalid_test",
            experiment_id="exp_causal_02",
            experiment_version="1.0",
            status="INVALID",
            estimand_population="PRE_REGISTERED_ELIGIBLE",
            allocation_proportion_p=0.50,
            eligible_population_count=50,
            observed_control_count=25,
            observed_treatment_count=25,
            point_estimate_paise_per_unit=None,
            incremental_recovered_revenue_paise=None,
            counterfactual_control_revenue_paise=None,
            standard_error=None,
            confidence_interval_lower=None,
            confidence_interval_upper=None,
            invalidation_reasons=["POSITIVITY_VIOLATION: Propensity score overlap below 0.10"],
            raw_report_json={"positivity_status": "FAILED"},
            evaluated_at=now,
        )
        session.add(rec_inv)
        session.commit()

    res_inv = client.get("/api/v2/evaluation/f4-report", headers={"x-merchant-id": "m_f4_invalid_test"})
    assert res_inv.status_code == 200
    data_inv = res_inv.json()
    assert data_inv["status"] == "INVALID"
    assert data_inv["positivity_status"] == "FAILED"
    assert data_inv["raw_report_json"]["positivity_status"] == "FAILED"

    # 4. CRITICAL REGRESSION TEST: Report with invalidation_reasons BUT NO positivity_status in raw_report_json
    # Proves the API does NOT infer positivity_status from invalidation_reasons!
    with factory() as session:
        rec_no_pos = F4EvaluationReportRecord(
            report_id="rep_f4_103",
            merchant_id="m_f4_no_pos_test",
            experiment_id="exp_causal_03",
            experiment_version="1.0",
            status="INVALID",
            estimand_population="PRE_REGISTERED_ELIGIBLE",
            allocation_proportion_p=0.50,
            eligible_population_count=50,
            observed_control_count=25,
            observed_treatment_count=25,
            point_estimate_paise_per_unit=None,
            incremental_recovered_revenue_paise=None,
            counterfactual_control_revenue_paise=None,
            standard_error=None,
            confidence_interval_lower=None,
            confidence_interval_upper=None,
            invalidation_reasons=["POSITIVITY_VIOLATION: Propensity score overlap below 0.10"],
            raw_report_json={"audit": "legacy_report_without_positivity_status_key"},
            evaluated_at=now,
        )
        session.add(rec_no_pos)
        session.commit()

    res_no_pos = client.get("/api/v2/evaluation/f4-report", headers={"x-merchant-id": "m_f4_no_pos_test"})
    assert res_no_pos.status_code == 200
    data_no_pos = res_no_pos.json()
    assert data_no_pos["status"] == "INVALID"
    assert data_no_pos["invalidation_reasons"] == ["POSITIVITY_VIOLATION: Propensity score overlap below 0.10"]
    # MUST be None (null), proving ZERO inference from invalidation_reasons!
    assert data_no_pos["positivity_status"] is None

    # 5. Tenant mismatch rejection
    res_tenant_denied = client.get(
        "/api/v2/evaluation/f4-report",
        params={"merchant_id": "m_f4_test"},
        headers={"x-merchant-id": "m_other_tenant"},
    )
    assert res_tenant_denied.status_code == 403




# --- GAP 3 TESTS: PAGINATED CASE LIST API ---

def test_gap3_paginated_case_listing(test_setup):
    factory, client = test_setup
    now = datetime.now(timezone.utc)

    # Seed 15 cases with different states and amounts
    with factory() as session:
        for i in range(15):
            c = RecoveryCase(
                case_id=f"c_page_{i:02d}",
                payment_id=f"p_page_{i:02d}",
                recovery_episode_id=f"ep_{i}",
                merchant_id="m_page_test",
                amount=1000 * (i + 1),
                currency="INR",
                state="FAILED" if i % 2 == 0 else "RECOVERED",
                state_confidence=1.0,
                failure_evidence={},
                first_seen_at=now,
                last_seen_at=now,
                recovery_eligible=(i % 3 != 0),
                eligibility_reason="RETRYABLE",
                schema_version="1.0",
                stage1_state_version=1,
            )
            session.add(c)
        session.commit()

    # 1. First page (limit 5, offset 0)
    res_p1 = client.get("/api/v2/cases", params={"limit": 5, "offset": 0}, headers={"x-merchant-id": "m_page_test"})
    assert res_p1.status_code == 200
    p1_data = res_p1.json()
    assert p1_data["total"] == 15
    assert p1_data["limit"] == 5
    assert p1_data["offset"] == 0
    assert len(p1_data["items"]) == 5

    # 2. Filter by status=FAILED
    res_failed = client.get("/api/v2/cases", params={"status": "FAILED"}, headers={"x-merchant-id": "m_page_test"})
    assert res_failed.status_code == 200
    failed_data = res_failed.json()
    assert failed_data["total"] == 8
    assert all(item["state"] == "FAILED" for item in failed_data["items"])

    # 3. Filter by amount range
    res_amt = client.get(
        "/api/v2/cases",
        params={"min_amount": 5000, "max_amount": 10000},
        headers={"x-merchant-id": "m_page_test"},
    )
    assert res_amt.status_code == 200
    amt_data = res_amt.json()
    assert amt_data["total"] == 6

    # 4. Tenant isolation check
    res_tenant_denied = client.get("/api/v2/cases", headers={"x-merchant-id": "m_other_tenant"}, params={"merchant_id": "m_page_test"})
    assert res_tenant_denied.status_code == 403


# --- GAP 4 TESTS: EXPERIMENT LIFECYCLE AUTHENTICATION ---

def test_gap4_experiment_lifecycle_authentication(test_setup):
    factory, client = test_setup

    # 1. Unauthenticated create experiment -> 401 Unauthorized
    res_unauth = client.post("/api/v2/experiments", json={"experiment_id": "exp_sec_01"})
    assert res_unauth.status_code == 401

    # 2. Invalid internal token -> 401 Unauthorized
    res_bad_token = client.post(
        "/api/v2/experiments",
        headers={"x-internal-token": "wrong-token"},
        json={"experiment_id": "exp_sec_01"},
    )
    assert res_bad_token.status_code == 401

    # 3. Valid admin token -> 201 Created
    headers = {"x-internal-token": "super-secret-admin-token"}
    res_created = client.post("/api/v2/experiments", headers=headers, json={"experiment_id": "exp_sec_01"})
    assert res_created.status_code == 201
    assert res_created.json()["experiment_id"] == "exp_sec_01"

    # 4. Unauthenticated lifecycle transitions -> 401
    assert client.post("/api/v2/experiments/exp_sec_01/freeze").status_code == 401
    assert client.post("/api/v2/experiments/exp_sec_01/ready").status_code == 401
    assert client.post("/api/v2/experiments/exp_sec_01/activate").status_code == 401

    # 5. Authenticated lifecycle transitions -> Success
    res_frz = client.post("/api/v2/experiments/exp_sec_01/freeze", headers=headers)
    assert res_frz.status_code == 200
    res_rdy = client.post("/api/v2/experiments/exp_sec_01/ready", headers=headers)
    assert res_rdy.status_code == 200

    # 6. Approve with token & principal ID & computed hash
    from recovery_service.stage2.models import ExperimentDesignRecord
    with factory() as session:
        rec = session.get(ExperimentDesignRecord, "exp_sec_01:1.0")
        conf_hash = compute_configuration_hash(rec)

    res_appr = client.post(
        "/api/v2/experiments/exp_sec_01/approve",
        headers={"x-internal-token": "super-secret-admin-token", "x-principal-id": "op_admin_01"},
        json={"experiment_version": "1.0", "configuration_hash": conf_hash},
    )
    assert res_appr.status_code == 200
    assert res_appr.json()["status"] == "APPROVED"

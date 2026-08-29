from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from recovery_service.database import Base, build_session_factory
from recovery_service.main import app
from recovery_service.settings import Settings
from recovery_service.stage2.experiment import (
    activate_experiment_running,
    approve_experiment_design,
    compute_configuration_hash,
    create_experiment_design,
    freeze_experiment_design,
    mark_experiment_ready,
    reject_experiment_design,
)
from recovery_service.stage2.models import ExperimentApprovalRecord, ExperimentDesignRecord


def _setup_app(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/exp_test.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)

    app.state.settings = settings
    app.state.sessions = factory
    return factory, TestClient(app)


def test_experiment_design_defaults_and_hashing(tmp_path):
    factory, _ = _setup_app(tmp_path)
    with factory() as session:
        rec = create_experiment_design(session, "exp_default_01", allocation_ratio=0.50)
        session.commit()

        assert rec.experiment_id == "exp_default_01"
        assert rec.control_arm_definition == "PASSIVE_NO_ACTION"
        assert rec.primary_metric == "VERIFIED_INCREMENTAL_RECOVERED_REVENUE"
        assert rec.baseline_recovery_rate == "UNAVAILABLE"
        assert rec.minimum_detectable_effect == "UNAVAILABLE"
        assert rec.status == "DRAFT"

        rec_frozen = freeze_experiment_design(session, "exp_default_01")
        session.commit()

        assert rec_frozen.status == "FROZEN"
        assert rec_frozen.approved_configuration_hash is not None
        assert len(rec_frozen.approved_configuration_hash) == 64


def test_experiment_lifecycle_and_human_approval_gate(tmp_path):
    factory, _ = _setup_app(tmp_path)
    with factory() as session:
        # Create DRAFT -> FROZEN -> READY
        rec = create_experiment_design(session, "exp_gate_01")
        session.commit()

        rec_frozen = freeze_experiment_design(session, "exp_gate_01")
        session.commit()
        conf_hash = rec_frozen.approved_configuration_hash

        mark_experiment_ready(session, "exp_gate_01")
        session.commit()

        # Bot / Automated Principal Attempt -> FAILS
        with pytest.raises(ValueError, match="Unauthorized principal"):
            approve_experiment_design(session, "exp_gate_01", "1.0", "bot_automated_worker", conf_hash)

        # Hash Mismatch -> FAILS
        with pytest.raises(ValueError, match="Configuration hash mismatch"):
            approve_experiment_design(session, "exp_gate_01", "1.0", "human_auditor_alpha", "invalid_hash_000")

        # Valid Authorized Human Approval -> SUCCEEDS
        rec_approved = approve_experiment_design(session, "exp_gate_01", "1.0", "human_auditor_alpha", conf_hash)
        session.commit()

        assert rec_approved.status == "APPROVED"
        assert rec_approved.approved_by == "human_auditor_alpha"

        # Activate -> RUNNING
        rec_running = activate_experiment_running(session, "exp_gate_01")
        session.commit()

        assert rec_running.status == "RUNNING"
        # Verify population_start_time bound to RUNNING activation timestamp (v4.1 Sec 11)
        assert rec_running.population_start_time is not None


def test_experiment_rejection_path(tmp_path):
    factory, _ = _setup_app(tmp_path)
    with factory() as session:
        create_experiment_design(session, "exp_reject_01")
        freeze_experiment_design(session, "exp_reject_01")
        mark_experiment_ready(session, "exp_reject_01")
        session.commit()

        rec_rejected = reject_experiment_design(
            session, "exp_reject_01", "1.0", "human_auditor_beta", "Baseline data insufficient for risk tolerance"
        )
        session.commit()

        assert rec_rejected.status == "REJECTED"
        assert rec_rejected.rejected_by == "human_auditor_beta"
        assert "insufficient" in rec_rejected.rejection_reason

        # Rejected experiment cannot transition to RUNNING
        with pytest.raises(ValueError, match="must be APPROVED"):
            activate_experiment_running(session, "exp_reject_01")


def test_single_active_experiment_constraint(tmp_path):
    factory, _ = _setup_app(tmp_path)
    with factory() as session:
        # 1. Activate first experiment
        create_experiment_design(session, "exp_active_A")
        freeze_experiment_design(session, "exp_active_A")
        mark_experiment_ready(session, "exp_active_A")
        h_a = session.get(ExperimentDesignRecord, "exp_active_A:1.0").approved_configuration_hash
        approve_experiment_design(session, "exp_active_A", "1.0", "human_auditor_alpha", h_a)
        activate_experiment_running(session, "exp_active_A")
        session.commit()

        # 2. Try to activate second concurrent experiment for same population scope -> FAILS
        create_experiment_design(session, "exp_active_B")
        freeze_experiment_design(session, "exp_active_B")
        mark_experiment_ready(session, "exp_active_B")
        h_b = session.get(ExperimentDesignRecord, "exp_active_B:1.0").approved_configuration_hash
        approve_experiment_design(session, "exp_active_B", "1.0", "human_auditor_alpha", h_b)
        session.commit()

        with pytest.raises(ValueError, match="Single active experiment constraint violated"):
            activate_experiment_running(session, "exp_active_B")


def test_experiment_governance_api_endpoints(tmp_path):
    _, client = _setup_app(tmp_path)

    # 1. Create DRAFT
    resp = client.post("/api/v2/experiments", json={"experiment_id": "exp_api_01", "allocation_ratio": 0.50})
    assert resp.status_code == 201
    data = resp.json()
    assert data["experiment_id"] == "exp_api_01"
    assert data["status"] == "DRAFT"

    # 2. Freeze
    resp = client.post("/api/v2/experiments/exp_api_01/freeze")
    assert resp.status_code == 200
    conf_hash = resp.json()["approved_configuration_hash"]
    assert conf_hash is not None

    # 3. Ready
    resp = client.post("/api/v2/experiments/exp_api_01/ready")
    assert resp.status_code == 200

    # 4. Approve without header -> 401 Unauthorized
    resp = client.post("/api/v2/experiments/exp_api_01/approve", json={"configuration_hash": conf_hash})
    assert resp.status_code == 401

    # 5. Approve with human header -> 200 OK
    resp = client.post(
        "/api/v2/experiments/exp_api_01/approve",
        json={"configuration_hash": conf_hash},
        headers={"x-principal-id": "human_reviewer_99"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"

    # 6. Activate
    resp = client.post("/api/v2/experiments/exp_api_01/activate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "RUNNING"

    # 7. Audit History
    resp = client.get("/api/v2/experiments/exp_api_01/history")
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) >= 1
    assert history[0]["decision"] == "APPROVED"
    assert history[0]["principal_id"] == "human_reviewer_99"

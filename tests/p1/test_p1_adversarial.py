from datetime import datetime, timezone

import pytest

from recovery_service.database import Base, build_session_factory
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import process_p1_pipeline
from recovery_service.stage2.genai_explainer import generate_genai_explanation, sanitize_genai_payload
from recovery_service.stage2.models import Stage2Case
from recovery_service.stage2.schemas import RecoveryCaseContract


def _setup_db(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/p1_adv.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    return factory, settings


def _sample_contract(case_id: str = "rc_p1_adv_1") -> RecoveryCaseContract:
    now = datetime.now(timezone.utc)
    return RecoveryCaseContract(
        case_id=case_id,
        payment_id=f"pay_{case_id}",
        recovery_episode_id="evt_fail",
        merchant_id="acc_adv",
        amount=60000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "BAD_REQUEST_ERROR", "gateway": "HDFC"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail"],
        stage1_state_version=1,
    )


def test_p1_pipeline_end_to_end_execution(tmp_path):
    factory, settings = _setup_db(tmp_path)
    contract = _sample_contract("rc_e2e_p1")

    with factory() as session:
        genome, proposal, shadow = process_p1_pipeline(session, contract, worker_id="p1-worker-1")
        session.commit()

        assert genome.case_id == "rc_e2e_p1"
        assert proposal.selected_action in proposal.candidate_actions
        assert shadow.stage2_proposed_action == proposal.selected_action

    with factory() as session:
        stage2_case = session.get(Stage2Case, ("rc_e2e_p1", 1))
        assert stage2_case is not None
        assert stage2_case.status == "PUBLISHED"


def test_genai_explainer_pii_redaction_and_safety(tmp_path):
    factory, settings = _setup_db(tmp_path)
    contract = _sample_contract("rc_genai_safety")

    with factory() as session:
        genome, proposal, shadow = process_p1_pipeline(session, contract)
        session.commit()

        sanitized = sanitize_genai_payload(genome)
        explanation_res = generate_genai_explanation(proposal, genome)

        assert "email" not in sanitized
        assert "card_number" not in sanitized
        assert explanation_res["authoritative"] is False
        assert proposal.proposal_id in explanation_res["proposal_id"]

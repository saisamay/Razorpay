from datetime import datetime, timezone

from recovery_service.database import Base, build_session_factory
from recovery_service.models import PaymentState, RawEvent, RecoveryCase
from recovery_service.settings import Settings
from recovery_service.stage2.attribution import evaluate_outcome_attribution
from recovery_service.stage2.consumer import process_p1_pipeline
from recovery_service.stage2.schemas import OutcomeAttribution, RecoveryCaseContract


def _setup_db(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/f1_attr.sqlite3",
        redis_url="redis://localhost:6379/0",
        webhook_secrets=("test-secret",),
        environment="test",
        max_webhook_bytes=4096,
    )
    factory = build_session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    return factory, settings


def test_outcome_attribution_no_recovery(tmp_path):
    factory, settings = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_attr_no_rec",
        payment_id="pay_attr_1",
        recovery_episode_id="evt_fail",
        merchant_id="acc_attr",
        amount=100000,
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "CARD_DECLINED"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail"],
        stage1_state_version=1,
    )

    with factory() as session:
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

        process_p1_pipeline(session, contract)
        session.commit()

        attribution = evaluate_outcome_attribution(session, "rc_attr_no_rec")
        session.commit()

        assert isinstance(attribution, OutcomeAttribution)
        assert attribution.case_id == "rc_attr_no_rec"
        assert attribution.net_verified_recovered_amount == 0.0
        assert attribution.outcome_status in {"NO_RECOVERY", "OUTCOME_PENDING"}


def test_outcome_attribution_partial_recovery_and_refund(tmp_path):
    factory, settings = _setup_db(tmp_path)
    now = datetime.now(timezone.utc)
    contract = RecoveryCaseContract(
        case_id="rc_attr_partial",
        payment_id="pay_attr_2",
        recovery_episode_id="evt_fail",
        merchant_id="acc_attr",
        amount=150000,  # ₹1500.00
        currency="INR",
        state="FAILED",
        state_confidence=0.99,
        failure_evidence={"reason": "GATEWAY_TIMEOUT"},
        first_seen_at=now,
        last_seen_at=now,
        recovery_eligible=True,
        eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
        schema_version="1.5",
        source_event_ids=["evt_fail"],
        stage1_state_version=1,
    )

    with factory() as session:
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
        
        # Add capture event ₹1000.00 (partial recovery)
        session.add(RawEvent(
            id="evt_cap_1",
            source="razorpay",
            source_event_id="evt_cap_1",
            event_type="payment.captured",
            environment="test",
            raw_payload={},
            normalized_payload={"amount": 100000},
            payment_id="pay_attr_2",
            occurred_at=now,
            received_at=now,
            processing_status="PROCESSED",
        ))
        session.commit()

        process_p1_pipeline(session, contract)
        session.commit()

        attribution = evaluate_outcome_attribution(session, "rc_attr_partial")
        session.commit()

        # PDF Section 13 Explicit Rule: ₹1500 recoverable, ₹1000 captured -> gross ₹1000, status PARTIALLY_RECOVERED!
        assert attribution.gross_recovered_amount == 1000.0
        assert attribution.net_verified_recovered_amount == 1000.0
        assert attribution.outcome_status == "PARTIALLY_RECOVERED"

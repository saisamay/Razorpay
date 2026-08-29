#!/usr/bin/env python3
"""Stage 2 P1 Full Shadow Mode Pipeline Runner.

Executes Stage 2 P1 recovery intelligence pipeline in full Shadow Mode over
eligible RecoveryCase records without modifying Stage 3 or executing payment actions.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from recovery_service.database import Base, build_session_factory
from recovery_service.models import RecoveryCase
from recovery_service.settings import Settings
from recovery_service.stage2.consumer import process_p1_pipeline
from recovery_service.stage2.genai_explainer import generate_genai_explanation
from recovery_service.stage2.models import DecisionProposalRecord, RecoveryGenomeRecord, ShadowEvaluationRecord, Stage2Case
from recovery_service.stage2.schemas import RecoveryCaseContract


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shadow_runner")


def run_shadow_mode_sweep():
    settings = Settings.from_environment()
    factory = build_session_factory(settings)

    logger.info("Initializing database schema for Stage 2 P1 Shadow Pipeline...")
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)

    with factory() as session:
        # Load eligible RecoveryCases
        cases = session.scalars(
            select(RecoveryCase)
            .where(RecoveryCase.recovery_eligible.is_(True))
            .order_by(RecoveryCase.first_seen_at.desc())
        ).all()

        logger.info("Found %d eligible RecoveryCases for Shadow Mode evaluation.", len(cases))

        if not cases:
            # Seed a sample RecoveryCase for demonstration if database has no cases
            now = datetime.now(timezone.utc)
            sample = RecoveryCase(
                case_id="rc_shadow_demo_001",
                payment_id="pay_demo_1001",
                recovery_episode_id="evt_fail_1001",
                merchant_id="merchant_demo_1",
                order_id="order_1001",
                amount=75000,
                currency="INR",
                state="FAILED",
                state_confidence=0.98,
                failure_evidence={
                    "reason": "GATEWAY_TIMEOUT",
                    "failure_step": "payment_execution",
                    "gateway": "HDFC",
                    "issuer": "SBI",
                },
                first_seen_at=now,
                last_seen_at=now,
                recovery_eligible=True,
                eligibility_reason="DEFINITIVE_FAILED_PAYMENT",
                schema_version="1.5",
                source_event_ids=["evt_fail_1001"],
                stage1_state_version=1,
            )
            session.add(sample)
            session.commit()
            cases = [sample]
            logger.info("Seeded demonstration RecoveryCase: %s", sample.case_id)

        processed_count = 0
        for case in cases:
            contract = RecoveryCaseContract(
                case_id=case.case_id,
                payment_id=case.payment_id,
                recovery_episode_id=case.recovery_episode_id,
                merchant_id=case.merchant_id,
                order_id=case.order_id,
                amount=case.amount,
                currency=case.currency,
                state=case.state,
                state_confidence=case.state_confidence,
                failure_evidence=case.failure_evidence,
                first_seen_at=case.first_seen_at,
                last_seen_at=case.last_seen_at,
                recovery_eligible=case.recovery_eligible,
                eligibility_reason=case.eligibility_reason,
                schema_version=case.schema_version,
                source_event_ids=case.source_event_ids,
                stage1_state_version=case.stage1_state_version,
            )

            # Execute full P1 pipeline in Shadow Mode
            genome, proposal, shadow = process_p1_pipeline(
                session, contract, worker_id="shadow-mode-runner-1"
            )
            session.commit()
            processed_count += 1

            # Generate non-authoritative explanation if GenAI API key is present
            explanation_res = generate_genai_explanation(proposal, genome)

            logger.info("==================================================================")
            logger.info("Case ID: %s | State Version: %d", case.case_id, case.stage1_state_version)
            logger.info("Baseline Action (Control): %s | Baseline Outcome: %s", shadow.baseline_action, shadow.baseline_outcome)
            logger.info("Stage 2 Proposed Action (Treatment): %s", proposal.selected_action)
            logger.info("Predicted P(Success): %.2f | CI: %s", proposal.predicted_success_probability, proposal.confidence_interval)
            logger.info("Expected Net Value: ₹%.2f", proposal.expected_net_value)
            logger.info("Would Have Recovered: ₹%.2f", shadow.would_have_recovered_amount)
            logger.info("GenAI Non-Authoritative Explanation: %s", explanation_res["explanation"])
            logger.info("Stage 2 Decision Execution Status: PASSIVE_SHADOW (0 actions executed)")

        logger.info("==================================================================")
        logger.info("Successfully processed %d cases in Full Shadow Mode.", processed_count)


if __name__ == "__main__":
    run_shadow_mode_sweep()

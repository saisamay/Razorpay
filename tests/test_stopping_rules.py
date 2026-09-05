from datetime import datetime, timedelta, timezone

from recovery_service.stage3.stopping import evaluate_stopping_rules




def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_stopping_rule_escalation_lockout():
    res = evaluate_stopping_rules(
        episode_status="ESCALATED",
        current_attempt_number=1,
        escalation_active=True,
    )
    assert res.should_stop is True
    assert res.reason_code == "ESCALATION_LOCKOUT"
    assert res.target_status == "ESCALATED"


def test_stopping_rule_already_terminal():
    res_stopped = evaluate_stopping_rules(
        episode_status="STOPPED",
        current_attempt_number=1,
    )
    assert res_stopped.should_stop is True
    assert res_stopped.reason_code == "EPISODE_ALREADY_STOPPED"
    assert res_stopped.target_status == "STOPPED"

    res_recovered = evaluate_stopping_rules(
        episode_status="RECOVERED",
        current_attempt_number=1,
    )
    assert res_recovered.should_stop is True
    assert res_recovered.reason_code == "EPISODE_ALREADY_RECOVERED"
    assert res_recovered.target_status == "RECOVERED"


def test_stopping_rule_payment_recovered():
    for status in ["RECOVERED", "PARTIALLY_RECOVERED", "SUCCESS"]:
        res = evaluate_stopping_rules(
            episode_status="AWAITING_OUTCOME",
            current_attempt_number=1,
            latest_outcome_status=status,
        )
        assert res.should_stop is True
        assert res.reason_code == "PAYMENT_RECOVERED"
        assert res.target_status == "RECOVERED"


def test_stopping_rule_permanent_failure_compliance():
    res = evaluate_stopping_rules(
        episode_status="IN_PROGRESS",
        current_attempt_number=1,
        compliance_advice_code="HARD_DECLINE_DO_NOT_RETRY",
    )
    assert res.should_stop is True
    assert res.reason_code == "PERMANENT_FAILURE"
    assert res.target_status == "STOPPED"


def test_stopping_rule_permanent_failure_outcome():
    res = evaluate_stopping_rules(
        episode_status="AWAITING_OUTCOME",
        current_attempt_number=1,
        latest_outcome_status="PERMANENT_FAILURE",
    )
    assert res.should_stop is True
    assert res.reason_code == "PERMANENT_FAILURE"
    assert res.target_status == "STOPPED"


def test_stopping_rule_max_attempts_reached():
    res = evaluate_stopping_rules(
        episode_status="IN_PROGRESS",
        current_attempt_number=3,
        max_attempts=3,
    )
    assert res.should_stop is True
    assert res.reason_code == "MAX_ATTEMPTS_REACHED"
    assert res.target_status == "STOPPED"


def test_stopping_rule_recovery_window_expired():
    now = utc_now()
    first_failure = now - timedelta(hours=73)
    res = evaluate_stopping_rules(
        episode_status="IN_PROGRESS",
        current_attempt_number=1,
        first_failure_at=first_failure,
        current_time=now,
        recovery_window_hours=72.0,
    )
    assert res.should_stop is True
    assert res.reason_code == "RECOVERY_WINDOW_EXPIRED"
    assert res.target_status == "STOPPED"


def test_stopping_rule_non_positive_expected_net_value():
    res = evaluate_stopping_rules(
        episode_status="IN_PROGRESS",
        current_attempt_number=1,
        expected_net_value=0.0,
    )
    assert res.should_stop is True
    assert res.reason_code == "NON_POSITIVE_EXPECTED_NET_VALUE"
    assert res.target_status == "STOPPED"


def test_stopping_rule_f5_governance_denial():
    for decision in ["DENY_ACTION", "FALLBACK_TO_BASELINE", "FAIL_CLOSED"]:
        res = evaluate_stopping_rules(
            episode_status="IN_PROGRESS",
            current_attempt_number=1,
            f5_enforcement_decision=decision,
        )
        assert res.should_stop is True
        assert res.reason_code == "F5_GOVERNANCE_DENIAL"
        assert res.target_status == "STOPPED"


def test_stopping_rule_active_systemic_incident():
    res = evaluate_stopping_rules(
        episode_status="IN_PROGRESS",
        current_attempt_number=1,
        incident_active=True,
    )
    assert res.should_stop is True
    assert res.reason_code == "ACTIVE_SYSTEMIC_INCIDENT"
    assert res.target_status == "ESCALATED"


def test_stopping_rule_continue_attempt():
    now = utc_now()
    first_failure = now - timedelta(hours=10)
    res = evaluate_stopping_rules(
        episode_status="PENDING",
        current_attempt_number=1,
        max_attempts=3,
        first_failure_at=first_failure,
        current_time=now,
        expected_net_value=150.0,
        recovery_eligible=True,
    )
    assert res.should_stop is False
    assert res.reason_code == "CONTINUE_ATTEMPT"
    assert res.target_status == "IN_PROGRESS"

from datetime import datetime, timezone

from recovery_service.stage2.evaluation import ValueSemantics, build_metric_value


def test_evaluation_value_semantics():
    m1 = build_metric_value(50000, ValueSemantics.OBSERVED, "CURRENCY_INR", "RecoveryCase", "1.5")
    assert m1.value == 50000
    assert m1.semantic_status == ValueSemantics.OBSERVED
    assert m1.unit == "CURRENCY_INR"

    m2 = build_metric_value(0.65, ValueSemantics.PREDICTED, "PERCENTAGE", "DecisionProposal", "1.0")
    assert m2.semantic_status == ValueSemantics.PREDICTED
    assert m2.unit == "PERCENTAGE"


def test_unknown_semantics_preserved():
    m_unknown = build_metric_value("UNKNOWN", ValueSemantics.UNKNOWN, "TEXT", "IncidentCluster", "1.0")
    assert m_unknown.value == "UNKNOWN"
    assert m_unknown.semantic_status == ValueSemantics.UNKNOWN

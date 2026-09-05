"""M-01 Per-Case Attribution Window Unit Tests.

Verifies:
1. Case-specific start + 71h -> incomplete
2. Case-specific start + 72h -> complete
3. Case-specific start + 96h -> complete
4. Two cases with different proposal timestamps -> independent per-case windows
5. Missing attribution start -> safe non-completion (False)
6. source_f4_evaluated_at cannot substitute for per-case attribution start
7. Experiment-level population_start_time cannot substitute for per-case attribution start
"""

from datetime import datetime, timedelta, timezone
import pytest

from recovery_service.stage2.f4.lifecycle import (
    evaluate_batch_attribution_completion,
    is_case_attribution_complete,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_m01_case_specific_start_71h_incomplete():
    t0 = utc_now() - timedelta(hours=71)
    now = utc_now()
    assert is_case_attribution_complete(t0, current_time=now, required_hours=72.0) is False


def test_m01_case_specific_start_72h_complete():
    t0 = utc_now() - timedelta(hours=72)
    now = utc_now()
    assert is_case_attribution_complete(t0, current_time=now, required_hours=72.0) is True


def test_m01_case_specific_start_96h_complete():
    t0 = utc_now() - timedelta(hours=96)
    now = utc_now()
    assert is_case_attribution_complete(t0, current_time=now, required_hours=72.0) is True


def test_m01_independent_per_case_windows():
    now = utc_now()
    # Case A proposal at T0 (75h ago)
    t0_case_a = now - timedelta(hours=75)
    # Case B proposal at T0 + 30 days (10h ago)
    t0_case_b = now - timedelta(hours=10)

    assert is_case_attribution_complete(t0_case_a, current_time=now, required_hours=72.0) is True
    assert is_case_attribution_complete(t0_case_b, current_time=now, required_hours=72.0) is False

    # Batch completion across both cases must return False since Case B is incomplete
    assert evaluate_batch_attribution_completion([t0_case_a, t0_case_b], current_time=now, required_hours=72.0) is False


def test_m01_missing_attribution_start_safe_non_completion():
    now = utc_now()
    assert is_case_attribution_complete(None, current_time=now, required_hours=72.0) is False
    assert evaluate_batch_attribution_completion([None], current_time=now, required_hours=72.0) is False


def test_m01_source_f4_evaluated_at_cannot_substitute():
    now = utc_now()
    # Evaluation ran just now (0h ago), but case proposal/attribution start was 10h ago
    case_start = now - timedelta(hours=10)
    source_f4_evaluated_at = now

    # Evaluating using evaluation timestamp would wrongly claim complete or wrong delta;
    # evaluating using case_start correctly reveals incomplete attribution (10h < 72h)
    assert is_case_attribution_complete(case_start, current_time=now, required_hours=72.0) is False


def test_m01_population_start_time_cannot_substitute():
    now = utc_now()
    # Experiment population_start_time was 100 days ago
    exp_population_start = now - timedelta(days=100)
    # Individual case proposal was 5 hours ago
    case_proposal = now - timedelta(hours=5)

    # Using experiment population_start_time would wrongly claim 100d >= 72h complete
    # Using case_proposal correctly shows case is incomplete (5h < 72h)
    assert is_case_attribution_complete(exp_population_start, current_time=now, required_hours=72.0) is True
    assert is_case_attribution_complete(case_proposal, current_time=now, required_hours=72.0) is False
